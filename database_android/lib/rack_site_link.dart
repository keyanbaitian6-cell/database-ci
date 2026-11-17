import 'models.dart';

/// 台番号を押したときに開く、データサイトのその台の対象日のページ（閲覧ページの狙い台一覧。
/// 2026-11-17 利用者「狙い台一覧からはピーステはサイトセブン、メルヘンは取得元のデータサイトへその台番へ
/// 飛べるようにして。共有カレンダーの翌日候補と同じだね」）。
///
/// 規則は共有カレンダーの `share_viewer/daily_learning.mjs` の `dailyRackUrl` と同じ（変えるときは両方）。
/// - メルヘン（長町南・幸町）：台のグラフ（取り込みと同じ standgraph?rack_no=&target_date=）。
/// - P-STATION：サイトセブンの台の「出玉詳細」（D4000.do?pmc=&mdc=&dtdd=&dn=。2026-11-15 利用者
///   「P-STATIONのリンクはP'SCUBEではなくサイトセブンにしてほしい」）。機種の番号（mdc）は、その台の
///   いちばん新しいサイトセブンの記録の出典URLから引く。何日前（dtdd）は日本時間3時切り替えの営業日から数え、
///   対象日が今日より先なら今日の分（0）。サイトが見せる8日分（0〜7日前）より古い日、機種の番号が分からない台、
///   ほかの店はリンクにしない。
/// 押したときだけ開く（先読みしない。サイトへのアクセスは増えない）。サイトの確認画面は利用者が押す。
const _meruhen = 'https://meruhenworld.pt.teramoba2.com/';
const _site777Halls = {'pscube:c740601:20': '04034001'};
const site777VisibleDays = 8;

/// 形だけでなく実在する日か（2026-13-01 などを弾く）。
DateTime? _realDay(String day) {
  if (!RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(day)) return null;
  final parsed = DateTime.tryParse('${day}T00:00:00Z');
  if (parsed == null) return null;
  final back =
      '${parsed.year.toString().padLeft(4, '0')}-${parsed.month.toString().padLeft(2, '0')}-${parsed.day.toString().padLeft(2, '0')}';
  return back == day ? parsed : null;
}

/// サイトセブンの今の営業日（日本時間3時切り替え。PCの business_day と同じ）。
String site777Today(DateTime now) => now
    .toUtc()
    .add(const Duration(hours: 9 - 3))
    .toIso8601String()
    .substring(0, 10);

/// 台のページのURL。リンクにしない台は null。[models] は台番号→サイトセブンの機種の番号。
String? rackSiteUrl(
  String store,
  int rack,
  String day,
  DateTime now, {
  Map<int, String> models = const {},
}) {
  final target = _realDay(day);
  if (rack < 1 || target == null) return null;
  if (store == 'nagamachiminami' || store == 'saiwaichou') {
    return '$_meruhen$store/standgraph/?rack_no=$rack&target_date=$day';
  }
  final hall = _site777Halls[store];
  final model = models[rack];
  if (hall == null || model == null || !RegExp(r'^\d{1,10}$').hasMatch(model)) {
    return null;
  }
  final today = DateTime.parse('${site777Today(now)}T00:00:00Z');
  final days = (today.difference(target).inHours / 24).round();
  final back = days < 0 ? 0 : days;
  if (back >= site777VisibleDays) return null;
  return 'https://m.site777.jp/f/D4000.do?pmc=$hall&mdc=$model&dtdd=$back&dn=$rack';
}

/// サイトセブンの記録の出典URL（大当り一覧 D3300）の機種の番号。サイトセブン以外・形が違うときは null。
String? site777ModelCode(SlotRecord record) {
  if (record.extra['source_site'] != 'site777') return null;
  final url = Uri.tryParse(record.extra['source_url']?.toString() ?? '');
  final mdc = url?.queryParameters['mdc'] ?? '';
  return url != null &&
          url.scheme == 'https' &&
          url.host == 'm.site777.jp' &&
          RegExp(r'^\d{1,10}$').hasMatch(mdc)
      ? mdc
      : null;
}

/// 台番号→機種の番号。同じ台は、いちばん新しい日のサイトセブンの記録を使う（入れ替えた台は新しい機種）。
Map<int, String> rackModelCodes(Iterable<SlotRecord> records, String store) {
  final latest = <int, (String, String)>{};
  for (final r in records) {
    if (r.store != store) continue;
    final code = site777ModelCode(r);
    if (code == null) continue;
    final seen = latest[r.rack];
    if (seen == null || r.day.compareTo(seen.$1) > 0) {
      latest[r.rack] = (r.day, code);
    }
  }
  return {for (final e in latest.entries) e.key: e.value.$2};
}
