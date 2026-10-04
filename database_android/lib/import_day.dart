/// 日付指定取り込み（メルヘン）の部品。PC版 `recent_days`・`with_target_date`
/// （database/browser_import.py）と同じ規則。P’s CUBEは `pscube_auto.dart`。
library;

import 'models.dart' show normalizeMachineName;

/// 取り込み日として選べる営業日（新しい順）。[today] は営業日の今日
/// （`todayIso()`：日本時間の午前2時までは前日）。
List<String> recentImportDays(String today, [int count = 7]) {
  final latest = DateTime.parse('${today}T00:00:00Z');
  return [
    for (var i = 0; i < count; i++)
      latest.subtract(Duration(days: i)).toIso8601String().substring(0, 10),
  ];
}

/// 機種の表のURLに取り込み日（`target_date`）を付ける。サイトが日付を選んだときに
/// 自分で付ける形で、すでにある `target_date` は置き換える。機種名の符号化は
/// 変えない（文字列のまま付け足す）。
String withTargetDate(String url, String day) {
  final hash = url.indexOf('#');
  final base = hash < 0 ? url : url.substring(0, hash);
  final fragment = hash < 0 ? '' : url.substring(hash);
  final existing = RegExp(r'([?&])target_date=[^&]*');
  final changed = existing.hasMatch(base)
      ? base.replaceFirstMapped(
          existing,
          (match) => '${match.group(1)}target_date=$day',
        )
      : '$base${base.contains('?') ? '&' : '?'}target_date=$day';
  return '$changed$fragment';
}

/// 取り込み日を指定しているとき、表示中の日が違えば理由を返す（保存しない）。
String? targetDayMismatch(String? target, String? shown) {
  if (target == null || shown == null || shown == target) return null;
  return '取り込み日は$targetですが、表示中は$shownです。日付を$targetに合わせてください。保存しませんでした。';
}

/// [day] の機種の表を、これより前に取ったきりなら取り直す（昼に取った数値を夜の分として残さない）。
/// [since]：今回の取り込みを始めた時刻。その日の営業が終わった後（翌日の午前2時以降）の数値は
/// もう変わらないので、そこで頭打ち。PC版 `stale_capture_cutoff`（core.py）と同じ。
int? staleCaptureCutoff(String? day, DateTime? since) {
  if (day == null || since == null) return null;
  final dayEnd = DateTime.parse('${day}T00:00:00+09:00')
      .add(const Duration(days: 1, hours: 2))
      .millisecondsSinceEpoch;
  final start = since.millisecondsSinceEpoch;
  return start < dayEnd ? start : dayEnd;
}

/// 機種一覧で次に探す順。[names] は一覧の並び（向きを反映済み）。
///
/// 手動で取り込んでいるとき、いま済ませた機種 [after] があれば、一覧の上から探し直さず
/// その機種の次から探す。先に見つからなければ、取りこぼしを探して最初から見直す
/// （この2回目だけ案内の頭に付ける文を返す）。[after] が無い・一覧に無いときは、
/// 最初から1回だけ探す。PC版の `next_unimported_machine`（browser_import.py）と同じ規則。
List<(List<int>, String)> machineSearchPasses(
  List<String> names,
  String? after,
) {
  String squash(String? value) =>
      normalizeMachineName(value ?? '').replaceAll(RegExp(r'\s+'), '');
  final every = [for (var i = 0; i < names.length; i++) i];
  final key = squash(after);
  final index = key.isEmpty
      ? -1
      : [for (final n in names) squash(n)].indexOf(key);
  if (index < 0) return [(every, '')];
  return [(every.sublist(index + 1), ''), (every, '最後まで来たので、一覧の最初から残りを探しました。')];
}
