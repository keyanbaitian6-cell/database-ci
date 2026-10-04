/// 日付指定取り込み（メルヘン）の部品。PC版 `recent_days`・`with_target_date`
/// （database/browser_import.py）と同じ規則。P’s CUBEは `pscube_auto.dart`。
library;

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
