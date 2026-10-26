/// 日付指定取り込み（メルヘン）の部品。PC版 `recent_days`・`with_target_date`
/// （database/browser_import.py）と同じ規則。P’s CUBEは `pscube_auto.dart`。
library;

import 'models.dart' show normalizeMachineName;

/// 取り込み日として選べる営業日（新しい順）。[today] は営業日の今日
/// （`todayIso()`：日本時間の午前3時までは前日）。
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
/// もう変わらないので、そこで頭打ち。PC版 `stale_capture_cutoff`（core.py）と同じ。閉店後の基準なので、
/// 営業日の切り替え（3時、2026-10-26）とは別に2時のまま（3時にすると23時〜0時に取った分を取り直しに行く）。
/// 取り込みを開き直しただけで、少し前（今夜）に取った分まで取り直さないよう、3時間の余裕を持たせる（昼と夜のような差だけを取り直す。2026-10-05、開き直した後に手動の「次へ」が済んだ機種の表へ向かった不具合）。営業が終わった日は、その日の23時より後に取った分を最終とみなす。
const staleMargin = Duration(hours: 3);

int? staleCaptureCutoff(String? day, DateTime? since) {
  if (day == null || since == null) return null;
  final dayEnd = DateTime.parse('${day}T00:00:00+09:00')
      .add(const Duration(days: 1, hours: 2))
      .millisecondsSinceEpoch;
  final start = since.millisecondsSinceEpoch;
  return (start < dayEnd ? start : dayEnd) - staleMargin.inMilliseconds;
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

/// 機種一覧の1機種について、次にすること（PC版の `next_unimported_machine` と同じ判定）。
///
/// 'graphs'：表は保存済みでグラフが残る、'table'：未取込・一覧の台数が増えた・前に取った表のまま
/// （[stale]）、null：済み。機種一覧はこれを一覧の並び（選んだ向き）の順に1回だけ見て、最初に
/// null でない機種へ進む（2026-10-06）。以前は「グラフが残る機種」を一覧のどこにあっても先に
/// 選んでいたため、下から始めても、上に取りかけの機種があると、下の機種の次にいきなり上へ飛んだ。
String? machineNextStep(
  Map<String, int>? status, {
  required int? listedCount,
  required bool stale,
}) {
  if (status != null && status['done'] != status['total'] && !stale) {
    return 'graphs';
  }
  if (status == null ||
      stale ||
      (listedCount != null && listedCount > (status['total'] ?? 0))) {
    return 'table';
  }
  return null;
}

/// サイトが機種の表の代わりに「該当する台情報が見つかりませんでした」を出した機種は、その日は
/// 飛ばして次の機種へ進む（2026-10-11、長町南の10/10のSハイパーラッシュ）。その判定は表の読み取り
/// （web_import_page.dart の `_extractTableScript` の no_racks、PC版 `NO_RACKS_PATTERN` と同じ文）。
///
/// 台情報が無かった機種を覚えるときの鍵（店舗・日・機種。機種名は正規化して空白を除く）。
/// PC版の `(store, day, machine_key(machine))` と同じ。
String noRacksKey(String store, String day, String machine) =>
    '$store|$day|${normalizeMachineName(machine).replaceAll(RegExp(r'\s+'), '')}';

/// 台情報が無い機種を飛ばすときの案内。PC版 `no_racks_notice` と同じ文。
String noRacksNotice(String day, String machine) =>
    '${int.parse(day.substring(5, 7))}/${int.parse(day.substring(8, 10))}の$machineは、'
    'サイトに台情報がありません（該当する台情報が見つかりませんでした）。'
    'この日は飛ばして、次の機種へ進みます。';

/// その日の機種一覧（サイト自身のページ）。グラフが済んだあと・台情報が無い機種を
/// 飛ばしたあとに戻り、ここから次の機種を探す。PC版 `machine_list_url` と同じ形（済ませた
/// 機種の印は、Android版は画面の状態 `_afterMachine` で持つ）。
String meruhenMachineListUrl(String store, String day) =>
    'https://meruhenworld.pt.teramoba2.com/$store/rack_info_kt/?kind_code=21'
    '#database_next_machine=1&database_day=${Uri.encodeComponent(day)}';
