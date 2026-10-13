import 'data_checks.dart';
import 'models.dart';
import 'scoring.dart';

/// 翌日候補（仮）の記録。
///
/// 候補は保存済みの記録から毎回計算し直すので、後から取り込んだ台や取り込み
/// 直しで、過去のある時点に画面に出ていた候補とは変わってしまう。それでは
/// 「予測した時点で分かっていたことだけで当たったか」を検証できないため、
/// 取り込みのたびに、その機種・日付の候補を時刻付きで残しておく。
/// 採点・候補の選び方・画面には一切影響しない。
class CandidateSnapshot {
  const CandidateSnapshot({
    required this.store,
    required this.day,
    required this.machine,
    required this.takenAt,
    required this.total,
    required this.eligible,
    required this.candidates,
    this.method,
  });

  final String store;
  final String day;
  final String machine;

  /// 記録した時刻（ISO 8601、UTCとの時差付き）。
  final String takenAt;

  /// その時点の、その機種・日付の台数と、過去傾向を計算できた台数。
  final int total;
  final int eligible;

  /// 候補に入った台。候補が出なかった（4台未満など）ときは空。
  final List<({int rack, double index, int days})> candidates;

  /// 計算方式の版（[nextDayMethodVersion]）。この項目ができる前の記録は null
  /// （版が分からないので、新しい版の成績とは無条件に合わせない）。
  final String? method;

  String get groupKey => '$store|$day|$machine';

  /// 時刻を除いた中身。同じ中身なら記録し直さない（版が変われば記録し直す）。
  String get signature =>
      '${method ?? ''}|$total|$eligible|${candidates.map((c) => '${c.rack}:${c.index}:${c.days}').join(',')}';

  Map<String, dynamic> toJson() => {
    'store': store,
    'day': day,
    'machine': machine,
    'taken_at': takenAt,
    if (method != null) 'method': method,
    'total': total,
    'eligible': eligible,
    'candidates': [
      for (final c in candidates)
        {'rack': c.rack, 'index': c.index, 'days': c.days},
    ],
  };

  static CandidateSnapshot? tryFromJson(Object? raw) {
    if (raw is! Map) return null;
    try {
      final store = raw['store'];
      final day = raw['day'];
      final machine = raw['machine'];
      final takenAt = raw['taken_at'];
      if (store is! String ||
          !storeNames.containsKey(store) ||
          day is! String ||
          !isValidRecordDay(day) ||
          machine is! String ||
          machine.trim().isEmpty ||
          takenAt is! String ||
          DateTime.tryParse(takenAt) == null) {
        return null;
      }
      final method = raw['method'];
      return CandidateSnapshot(
        store: store,
        day: day,
        machine: normalizeMachineName(machine),
        takenAt: takenAt,
        method: method is String && method.isNotEmpty ? method : null,
        total: (raw['total'] as num).toInt(),
        eligible: (raw['eligible'] as num).toInt(),
        candidates: [
          for (final c in raw['candidates'] as List)
            (
              rack: ((c as Map)['rack'] as num).toInt(),
              index: (c['index'] as num).toDouble(),
              days: (c['days'] as num).toInt(),
            ),
        ],
      );
    } on Object {
      return null;
    }
  }
}

/// [store]・[day]・[machine] の、[all] から見た今の翌日候補。
/// 結果画面と同じ [provisionalNextDayCandidates] をそのまま使う。[machine] が
/// [varietyGroupName] なら、その日その店のバラエティ（1〜3台の機種）の候補
/// （[varietyNextDayCandidates]）。台番号はその日その店で1台ずつなので、
/// 候補は台番号だけで分かる。
CandidateSnapshot candidateSnapshot({
  required String store,
  required String day,
  required String machine,
  required List<SlotRecord> all,
  required DateTime now,
}) {
  final ({int total, int eligible, List<ProvisionalCandidate> candidates})
  result;
  if (machine == varietyGroupName) {
    final dayRows = [
      for (final r in all)
        if (r.store == store && r.day == day) r,
    ];
    final variety = varietyMachines(dayRows);
    result = varietyNextDayCandidates([
      for (final r in dayRows)
        if (variety.contains(r.machine)) r,
    ], all);
  } else {
    final history = machineHistory(all, store, machine);
    final rows = [
      for (final r in history)
        if (r.day == day) r,
    ];
    result = provisionalNextDayCandidates(rows, history);
  }
  return CandidateSnapshot(
    store: store,
    day: day,
    machine: machine,
    takenAt: timestampWithOffset(now),
    method: candidateMethodVersion(store, machine),
    total: result.total,
    eligible: result.eligible,
    candidates: [
      for (final c in result.candidates)
        (rack: c.record.rack, index: c.index, days: c.days),
    ],
  );
}

/// 保存した [saved] の影響を受ける機種・日付の候補のうち、最後の記録から
/// 中身が変わったものだけを返す。
///
/// 候補はその日までの記録だけで決まるので、保存した日と、同じ店舗・機種で
/// それより後の日（30日以内）だけを計算し直す。[latest] は機種・日付ごとの
/// 最後の記録。その日にバラエティ（1〜3台）の機種は、機種ではなくその日その
/// 店のバラエティ（[varietyGroupName]）を計算し直す。台数が変わって機種が
/// バラエティに入った・出た場合に備え、影響する日のバラエティは毎回計算し
/// 直す（中身が変わらなければ記録しない）。
List<CandidateSnapshot> changedCandidateSnapshots({
  required Iterable<SlotRecord> saved,
  required List<SlotRecord> all,
  required Map<String, CandidateSnapshot> latest,
  required DateTime now,
}) {
  // 1回の保存は同じ機種・日付の台がまとまって来るので、先に重複を除く。
  final savedGroups = {for (final s in saved) (s.store, s.machine, s.day)};
  final affected = <(String, String, String)>{};
  for (final (store, machine, day) in savedGroups) {
    // 削除で台が1台も残らなくても「候補なし」として残せるよう、保存した
    // 機種・日付そのものは必ず計算し直す。
    affected.add((store, day, machine));
    final last = DateTime.parse(day)
        .add(const Duration(days: 30))
        .toIso8601String()
        .substring(0, 10);
    for (final r in all) {
      if (r.store == store &&
          r.machine == machine &&
          r.day.compareTo(day) >= 0 &&
          r.day.compareTo(last) <= 0) {
        affected.add((r.store, r.day, r.machine));
      }
    }
  }
  // 店舗・日付ごとの機種の台数（バラエティかどうかの判定）。
  final counts = <String, int>{};
  final storeDays = {for (final (store, day, _) in affected) '$store|$day'};
  for (final r in all) {
    if (storeDays.contains('${r.store}|${r.day}')) {
      final key = '${r.store}|${r.day}|${r.machine}';
      counts[key] = (counts[key] ?? 0) + 1;
    }
  }
  bool hasVariety(String store, String day) => counts.entries.any(
    (e) =>
        e.key.startsWith('$store|$day|') &&
        e.value <= varietyMaxRacksFor(store),
  );
  final targets = <String, (String, String, String)>{};
  for (final (store, day, machine) in affected) {
    final key = '$store|$day|$machine';
    final racks = counts[key] ?? 0;
    // 1〜3台の機種の候補はバラエティで出す。機種ごとの記録は、以前に候補が
    // 出ていた（4台以上だった）ときだけ「候補なし」に更新する。
    final wasListed = latest[key]?.candidates.isNotEmpty ?? false;
    if (racks == 0 || racks > varietyMaxRacksFor(store) || wasListed) {
      targets[key] = (store, day, machine);
    }
    final varietyKey = '$store|$day|$varietyGroupName';
    if (hasVariety(store, day) || latest.containsKey(varietyKey)) {
      targets[varietyKey] = (store, day, varietyGroupName);
    }
  }
  final changed = <CandidateSnapshot>[];
  for (final entry in targets.entries) {
    final (store, day, machine) = entry.value;
    final snapshot = candidateSnapshot(
      store: store,
      day: day,
      machine: machine,
      all: all,
      now: now,
    );
    if (latest[entry.key]?.signature != snapshot.signature) {
      changed.add(snapshot);
    }
  }
  return changed;
}

/// 機種・日付ごとに、記録時刻がいちばん新しいもの。
Map<String, CandidateSnapshot> latestCandidateSnapshots(
  Iterable<CandidateSnapshot> snapshots,
) {
  final latest = <String, CandidateSnapshot>{};
  for (final s in snapshots) {
    final current = latest[s.groupKey];
    if (current == null ||
        earliestTimestamp(current.takenAt, s.takenAt) == current.takenAt) {
      latest[s.groupKey] = s;
    }
  }
  return latest;
}
