import 'models.dart';
import 'scoring.dart';
import 'viewer_data.dart';

/// 段階B2（VIEWER_DAY_STORE.md、2026-11-18）：日・機種一覧に出す台の点数（表示用の採点 v12、
/// `scoreRecord(..., sameDayForNew: true)`）を、日別キャッシュの「その日と前30暦日」だけから計算し、
/// 今の計算（全記録から）と1台ずつ比べる。
///
/// 採点が全記録から使うのは、同じ店・同じ機種の、評価日の30日前〜前日（新台は同じ日）の記録だけ
/// （`scoring.dart` の `comparisonPool`・`newMachinePeers`）。日別キャッシュを古い日から1日ずつ [addDay] に
/// 渡すと、その日と前30暦日の記録だけを窓として持ち、対象の日 [targets] の台をその窓で採点する。
///
/// 全日の全台を毎回比べると、今の計算（全記録から）の側が台数のほぼ2乗の手間になり、108日・約7.9万台で
/// デスクトップでも200秒を超えた（2026-11-18 測定）。そのため1回の更新で比べるのは数日分だけにし
/// （[pickScoreDays]）、更新のたびに対象の日を回して全日を一巡する。さらに今の計算の側も、本体の記録から
/// 同じ「その日と前30日」を切り出して採点する（全記録で採点しても同じ点数になることは、[fullCurrent] を
/// true にした試験で全日について確かめる。`test/day_score_check_test.dart`）。照合が確かめるのは、
/// 日別キャッシュの窓と本体の窓から同じ点数が出ること（読み先を替えても値が変わらないこと）。
class DayScoreCheck {
  DayScoreCheck(
    this.records,
    Iterable<String> targets, {
    this.store,
    this.fullCurrent = false,
  }) : targets = {...targets} {
    final from = this.from;
    final last = this.targets.isEmpty ? null : (this.targets.toList()..sort()).last;
    if (from == null || last == null) return;
    for (final r in records) {
      if ((store == null || r.store == store) &&
          r.day.compareTo(from) >= 0 &&
          r.day.compareTo(last) <= 0) {
        (_oldByDay[r.day] ??= []).add(r);
      }
    }
  }

  /// 照合する店（null なら全部）。1回の更新で1店だけにすると、窓（31日分の記録）が約半分になる。
  /// 180日の合成データで、2店まとめた窓は更新1回のメモリの境界を上げた（2026-11-18 測定）。
  final String? store;

  /// true なら、今の計算の側を全記録 [records] で採点する（試験用。全日・全台では重い）。
  final bool fullCurrent;

  /// 今の計算に使う全記録（表示中の `ViewerData.records`）。
  final List<SlotRecord> records;

  /// 照合する日。
  final Set<String> targets;
  final Map<String, List<SlotRecord>> _oldByDay = {};
  final Set<String> _seenDays = {};
  List<SlotRecord> _window = const [];
  int compared = 0, mismatched = 0;
  final List<Map<String, String>> examples = [];

  /// 窓を作るために最初に読む日（対象のいちばん古い日の30日前）。対象が無ければ null。
  String? get from {
    if (targets.isEmpty) return null;
    final first = (targets.toList()..sort()).first;
    return _minus30(first);
  }

  void _miss(SlotRecord r, String old, String next) {
    mismatched++;
    if (examples.length < 3) {
      examples.add({
        'store': r.store,
        'day': r.day,
        'machine': r.machine,
        'rack': '${r.rack}',
        'old': old,
        'next': next,
      });
    }
  }

  /// 日別キャッシュの1日分の記録（古い日から順に渡す）。
  void addDay(Iterable<Object?> rows) {
    final today = [
      for (final r in ViewerData.recordsOfRows(rows))
        if (store == null || r.store == store) r,
    ];
    if (today.isEmpty) return;
    final day = today.first.day;
    final first = _minus30(day);
    // 採点の索引（scoring.dart の _byMachine）は一覧そのものに紐づくので、日ごとに新しい一覧を作る。
    _window = [
      for (final r in _window)
        if (r.day.compareTo(first) >= 0) r,
      ...today,
    ];
    if (!targets.contains(day)) return;
    _seenDays.add(day);
    final old = {
      for (final r in _oldByDay[day] ?? const <SlotRecord>[]) r.key: r,
    };
    // 今の計算の側：本体の記録から、同じ「その日と前30日」を切り出す（fullCurrent なら全記録）。
    final current = fullCurrent
        ? records
        : [
            for (final e in _oldByDay.entries)
              if (e.key.compareTo(first) >= 0 && e.key.compareTo(day) <= 0)
                ...e.value,
          ];
    for (final r in today) {
      final next = scoreRecord(r, _window, sameDayForNew: true);
      final before = old.remove(r.key);
      if (before == null) {
        _miss(r, '台無し', scoreText(next));
        continue;
      }
      compared++;
      final was = scoreRecord(before, current, sameDayForNew: true);
      if (scoreText(was) != scoreText(next)) {
        _miss(r, scoreText(was), scoreText(next));
      }
    }
    for (final r in old.values) {
      _miss(r, scoreText(scoreRecord(r, current, sameDayForNew: true)), '台無し');
    }
  }

  /// 照合の結果。日別キャッシュに無かった対象の日の台も、一致しない台として数える。
  Map<String, Object?> finish() {
    for (final day in targets) {
      if (_seenDays.contains(day)) continue;
      for (final r in _oldByDay[day] ?? const <SlotRecord>[]) {
        _miss(r, '本体にあり', '台無し');
      }
    }
    return {
      'status': mismatched == 0 ? 'match' : 'mismatch',
      'store': ?store,
      'targets': (targets.toList()..sort()),
      'racks': compared,
      'mismatched': mismatched,
      'examples': examples,
    };
  }
}

String _minus30(String day) => DateTime.parse(day)
    .subtract(const Duration(days: 30))
    .toIso8601String()
    .substring(0, 10);

/// 1回の照合で比べる日：いちばん新しい日を [recent] 日と、それより前の日を、前回の最後に比べた日 [after] より
/// 古い日から順に [rotating] 日（いちばん古い日まで行ったら、新しい側へ戻る）。戻り値の `next`（最後に選んだ日）を
/// 次の [after] として覚えておくと、日が増えても全日を一巡する。
///
/// 2026-11-22（Codexの点検 #11・Gemini H-7）：以前は新しい順の並びの「位置」を覚えていたので、新しい日が先頭に
/// 入るたびに同じ位置が1日ずれ、1日1回ほどの更新では同じ過去の日ばかり選んで一巡しなかった。日付で覚える。
({List<String> targets, String? next}) pickScoreDays(
  Iterable<String> days,
  String? after, {
  int recent = 1,
  int rotating = 3,
}) {
  final sorted = days.toSet().toList()..sort((a, b) => b.compareTo(a));
  final latest = sorted.take(recent).toList();
  final rest = sorted.skip(recent).toList();
  if (rest.isEmpty) return (targets: latest, next: null);
  // 前回の日より古い最初の日から。覚えた日が無い・いちばん古い日まで済んでいるときは、いちばん新しい側から。
  var start = after == null ? 0 : rest.indexWhere((d) => d.compareTo(after) < 0);
  if (start < 0) start = 0;
  final picked = <String>[
    for (var i = 0; i < rotating && i < rest.length; i++)
      rest[(start + i) % rest.length],
  ];
  return (targets: [...latest, ...picked], next: picked.last);
}

String _n(double? v) => v == null ? '-' : v.toStringAsFixed(6);

/// 採点結果の全項目を1つの文字にする（比べる・例に出す）。
String scoreText(ScoreResult s) =>
    '合計${_n(s.total)}・回転${_n(s.games)}・持玉${_n(s.maxHold)}・当たり${_n(s.hits)}'
    '・プラス${_n(s.positive)}・維持${_n(s.retention)}・比較${s.referenceCount}台${s.referenceDays}日'
    '・持玉比較${s.holdReferenceCount}・網羅${s.coverage}・欠${_n(s.missingLow)}/${_n(s.missingHigh)}'
    '・${s.provisional ? '仮' : '確'}・${s.reasons.join('／')}';
