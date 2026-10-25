import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

import 'models.dart' show timestampWithOffset;
import 'pscube_viewer_data.dart';
import 'capture_health.dart';

/// 時差つきの時刻文字列を比べられる数（ミリ秒）に。読めなければ null。
int? _instant(Object? text) =>
    text is String ? DateTime.tryParse(text)?.millisecondsSinceEpoch : null;

/// [day] の記録がこれより古い「サイトの更新時刻」なら取り直す（昼に取った数値を夜の分として残さない）。
/// [freshSince]：今回の取り込みで最初に保存したページのサイトの更新時刻。その日の営業が終わった後
/// （翌日の午前2時以降）の数値はもう変わらないので、そこで頭打ち。PC版 `stale_cutoff` と同じ。
/// 取り込みを開き直しただけで、少し前（今夜）に取った分まで取り直さないよう、3時間の余裕を持たせる（昼と夜のような差だけを取り直す。2026-10-05、開き直した後に手動の「次へ」が済んだ機種の表へ向かった不具合）。営業が終わった日は、その日の23時より後に取った分を最終とみなす。
const pscubeStaleMargin = Duration(hours: 3);

int? pscubeStaleCutoff(String? day, String? freshSince) {
  final since = _instant(freshSince);
  if (since == null || day == null) return null;
  final dayEnd = DateTime.parse('${day}T00:00:00+09:00')
      .add(const Duration(days: 1, hours: 2))
      .millisecondsSinceEpoch;
  return (since < dayEnd ? since : dayEnd) - pscubeStaleMargin.inMilliseconds;
}

/// 同じページか。一覧のページではサイトがスクロール位置を#以降へ書き込むので、#以降は比べない。
/// 台別ページの#以降は履歴の日付なので、完全に一致させる。機種名（日本語）は%の形と元の文字の
/// 形のどちらでも返ってきうるので、%を戻して比べる（PC版の `same_page` と同じ規則）。
bool pscubeSamePage(Uri first, Uri second) {
  String key(Uri uri) {
    final text =
        (uri.path.endsWith('nc-v06-001.php') ? uri : uri.removeFragment())
            .toString();
    try {
      return Uri.decodeFull(text);
    } catch (_) {
      return text;
    }
  }

  return key(first) == key(second);
}

/// 取り込み日を指定しているとき、機種の全台一覧をその日の日付タブで開くURL。サイトは全台一覧の状態
/// （表示件数;位置;選んだ日付;…）を#以降に持ち、開いたときにその日付のタブを選ぶ（2026-10-06 実サイトで
/// 確認）。#以降が無いと「本日」のタブになり、営業中は数値が動き続けるため、その日を取り込めなかった。
/// PC版 `table_url_for_day` と同じ。
String pscubeTableUrlForDay(String url, String? day) {
  final uri = Uri.parse(url);
  if (day == null || !uri.path.endsWith('nc-v05-011.php')) return url;
  return uri
      .replace(fragment: '0;0;${day.replaceAll('-', '')};0;cd_dai;1;0;0')
      .toString();
}

/// 同じ機種の全台一覧の住所か（#以降は比べない）。機種名の%は、保存した一覧のリンクでは二重
/// （`%25E9…`）、WebViewの住所では一重や元の文字のことがあるので、戻しきってから比べる
/// （2026-10-19。PC版 `same_machine_url` と同じ）。
bool pscubeSameMachineUrl(String first, String second) {
  String plain(String value) {
    for (var i = 0; i < 4; i++) {
      final String decoded;
      try {
        decoded = Uri.decodeComponent(value);
      } catch (_) {
        return value;
      }
      if (decoded == value) break;
      value = decoded;
    }
    return value;
  }

  String key(String raw) {
    final uri = Uri.parse(raw);
    final query = <String>[
      for (final part in uri.query.split('&'))
        if (part.isNotEmpty)
          [
            for (final piece in part.split('='))
              plain(piece.replaceAll('+', ' ')),
          ].join('='),
    ]..sort();
    return jsonEncode([uri.path, query]);
  }

  try {
    return key(first) == key(second);
  } catch (_) {
    return false;
  }
}

/// 取り込み日の日付タブがサイトに無かった機種と日（新台・入れ替え）。その日の未取得に数えない。
const pscubeAbsentDaysKey = 'absent_table_days';

/// 全台一覧の日付タブ（[days]）に、取り込み日（[day]）のタブが無く、飛ばしてよい形か（PC版 `day_tab_absent` と
/// 同じ規則）。タブが読めない・空のときや、取り込み日がタブより新しい（早朝でまだ出ていない）ときは false。
/// 自動取り込みの「日付違いでも読み取りへ進めるか」と、保存側の `_skipAbsentDay` の両方で使う（2026-10-22）。
bool pscubeDayTabAbsent(String? day, Object? days) {
  if (day == null ||
      days is! List ||
      days.isEmpty ||
      days.any(
        (d) => d is! String || !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(d),
      )) {
    return false;
  }
  final tabs = days.cast<String>().toList()..sort();
  return !tabs.contains(day) && day.compareTo(tabs.last) < 0;
}

/// 過去の日の全台一覧で、その日の数値もリンクも無かった台（増台した台）。台数の確認と未取得の数え方に足す。
const pscubeAbsentRacksKey = 'absent_table_racks';

/// P's CUBE records live apart from the Meruhen database and its store codes.
class PscubeStore {
  PscubeStore._(this.db);
  final Database db;
  Future<void> _pending = Future<void>.value();

  Future<T> _serial<T>(Future<T> Function() action) {
    final result = _pending.then((_) => action());
    _pending = result.then<void>((_) {}, onError: (Object _, StackTrace _) {});
    return result;
  }

  static const root =
      'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/';
  static const index = '${root}cgi-bin/nc-v03-001.php?cd_ps=2';

  static Future<PscubeStore> open({
    String? path,
    DatabaseFactory? factory,
  }) async {
    final db = await (factory ?? databaseFactory).openDatabase(
      path ?? '${await getDatabasesPath()}/pscube.sqlite3',
      options: OpenDatabaseOptions(
        version: 1,
        onCreate: (db, _) async {
          await db.execute(
            'CREATE TABLE machines (key TEXT PRIMARY KEY, payload TEXT NOT NULL)',
          );
          await db.execute(
            'CREATE TABLE records (key TEXT PRIMARY KEY, payload TEXT NOT NULL)',
          );
          await db.execute('CREATE TABLE rack_captures (key TEXT PRIMARY KEY)');
          await db.execute(
            'CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
          );
        },
      ),
    );
    return PscubeStore._(db);
  }

  Future<void> close() => _serial(db.close);

  /// Read only the known count for this exact machine/rate URL; do not guess.
  Future<int?> installationCount(String? currentUrl) => _serial(() async {
    final current = Uri.tryParse(currentUrl ?? '');
    if (current == null || !current.path.endsWith('nc-v05-011.php')) {
      return null;
    }
    _site(currentUrl, 'nc-v05-011.php');
    String queryIdentity(Uri uri) {
      final query = uri.queryParametersAll;
      final keys = query.keys.toList()..sort();
      return jsonEncode([
        for (final key in keys) [key, query[key]],
      ]);
    }

    final query = queryIdentity(current);
    final counts = <int>{};
    for (final row in await db.query('machines', columns: ['payload'])) {
      final machine = _asMap(jsonDecode(row['payload'] as String));
      // アナスロだけにある補完機種はP’s CUBEの機種URLを持たない（_machine と同じ扱い）。台数確認へ
      // 混ぜない。住所の検査で止めると、補完機種を取り込んだ端末ではどの全台一覧も「対象のP’s CUBE
      // ページではありません」で保存できなかった（2026-10-20）。PC版 installation_count と同じ。
      if (machine['source_site'] == 'anaslo' && machine['url'] == null) {
        continue;
      }
      final stored = _site(machine['url'] as String?, 'nc-v05-011.php');
      if (queryIdentity(stored) == query) {
        final count = machine['expected_count'];
        if (count is int && count >= 1 && count <= 5000) counts.add(count);
      }
    }
    return counts.length == 1 ? counts.single : null;
  });

  /// 当たりが1回もない台（BB・RB・AT/ARTがすべて0、0回転を含む）。全台一覧の数値は保存するが、
  /// 台別7日分（グラフ）は取りに行かない（メルヘンv12を AT/ART も含めて引き継ぐ。利用者の指定、
  /// 2026-10-01）。PC版 `no_hits` と同じ。
  /// 沖ドキ（「沖ドキ」「オキドキ」、半角も）は取り込みの対象外。メルヘンと同じ約束（2026-09-29、
  /// P’s CUBEへの反映は2026-10-01）。回る対象にせず、表・グラフも保存しない。
  static const excludedMachineWords = ['沖ドキ', '沖ﾄﾞｷ', 'オキドキ', 'ｵｷﾄﾞｷ'];

  static bool isExcludedMachine(String? name) =>
      excludedMachineWords.any((word) => (name ?? '').contains(word));

  static bool noHits(Map<String, dynamic> r) =>
      (r['bb'] as int) + (r['rb'] as int) + (r['at_art'] as int) == 0;

  static String _key(Map<String, dynamic> row, {bool record = false}) =>
      jsonEncode([
        row['store'],
        row['rate'],
        row['machine'],
        if (record) ...[row['rack'], row['day']],
      ]);

  static Uri _site(String? value, String file) {
    final uri = Uri.tryParse(value ?? '');
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host != 'www.pscube.jp' ||
        uri.userInfo.isNotEmpty ||
        uri.hasPort ||
        uri.path != '/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/$file') {
      throw const FormatException('対象のP’s CUBEページではありません。');
    }
    return uri;
  }

  static void _base(Map<String, dynamic> row) {
    if (row['store'] != 'c740601' ||
        row['rate'] is! String ||
        !RegExp(r'^\d+(?:\.\d+)?$').hasMatch(row['rate']) ||
        row['machine'] is! String ||
        (row['machine'] as String).trim().isEmpty ||
        (row['machine'] as String).length > 200) {
      throw const FormatException('店舗・貸玉・機種名が一致しません。');
    }
  }

  static void _machine(Map<String, dynamic> row) {
    _base(row);
    final external = row['source_site'] == 'anaslo' && row['url'] == null;
    final uri = external
        ? null
        : _site(row['url'] as String?, 'nc-v05-011.php');
    if (!external &&
        (uri!.queryParameters['bai'] != row['rate'] ||
            (uri.queryParameters.containsKey('cd_ps') &&
                uri.queryParameters['cd_ps'] != '2'))) {
      throw const FormatException('機種リンクが一致しません。');
    }
    final count = row['expected_count'];
    if (count != null && (count is! int || count < 1 || count > 5000)) {
      throw const FormatException('設置台数が不正です。');
    }
    if (row['machine_type'] != null &&
        !['normal', 'other'].contains(row['machine_type'])) {
      throw const FormatException('機種タイプが不正です。');
    }
  }

  static void _record(Map<String, dynamic> row) {
    _base(row);
    final rack = row['rack'];
    final day = row['day'];
    if (rack is! int ||
        rack < 1 ||
        day is! String ||
        !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(day) ||
        DateTime.tryParse(day)?.toIso8601String().substring(0, 10) != day) {
      throw const FormatException('台番号・営業日が不正です。');
    }
    final external = row['source_site'] == 'anaslo';
    if (external) validateAnasloRecord(row);
    final uri = external
        ? null
        : _site(row['detail_url'] as String?, 'nc-v06-001.php');
    if (!external &&
        (uri!.queryParameters['cd_dai'] != '$rack' ||
            uri.fragment != day.replaceAll('-', ''))) {
      throw const FormatException('台番号・営業日とリンクが一致しません。');
    }
    for (final field
        in external
            ? ['bb', 'rb', 'at_art', 'games']
            : ['bb', 'rb', 'at_art', 'games', 'my']) {
      final value = row[field];
      if (value is! int || value < 0) throw FormatException('$field の数値が不正です。');
    }
    if (row['net_medals'] != null &&
        (row['net_medals'] is! int ||
            (row['net_medals'] as int).abs() > 1000000)) {
      throw const FormatException('差枚の数値が不正です。');
    }
    if (row['net_capture'] != null) {
      row['net_capture'] = validateNetCapture(row['net_capture'], record: row);
    }
    final graph = row['graph'];
    if (graph != null) {
      if (graph is! Map ||
          !['overview', 'daily'].contains(graph['kind']) ||
          graph['zero_y'] is! num ||
          !(graph['zero_y'] as num).isFinite ||
          graph['points'] is! List) {
        throw const FormatException('グラフが不正です。');
      }
      final points = graph['points'] as List;
      if (points.length < 2 || points.length > 50000) {
        throw const FormatException('グラフが不正です。');
      }
      for (var i = 0; i < points.length; i++) {
        final point = points[i];
        if (point is! List ||
            point.length != 2 ||
            point.any((v) => v is! num || !v.isFinite || v.abs() > 1e7) ||
            (i > 0 && (point[0] as num) < (points[i - 1][0] as num))) {
          throw const FormatException('グラフの座標が不正です。');
        }
      }
    }
    if (row['observed_at'] != null &&
        (row['observed_at'] is! String ||
            DateTime.tryParse(row['observed_at']) == null)) {
      throw const FormatException('更新時刻が不正です。');
    }
  }

  static Map<String, dynamic> _asMap(dynamic item) {
    if (item is! Map<String, dynamic>) {
      throw const FormatException('読み取り結果が不正です。');
    }
    return item;
  }

  Future<Map<String, dynamic>?> _get(String table, String key) async {
    final rows = await db.query(
      table,
      columns: ['payload'],
      where: 'key=?',
      whereArgs: [key],
    );
    return rows.isEmpty
        ? null
        : _asMap(jsonDecode(rows.first['payload'] as String));
  }

  Future<String?> _day() async {
    final rows = await db.query(
      'state',
      columns: ['value'],
      where: 'key=?',
      whereArgs: ['last_day'],
    );
    return rows.isEmpty ? null : rows.first['value'] as String;
  }

  /// [expectedDay]：取り込み日を指定しているときの日付。表示中の日付と違うページは保存しない。
  /// [direction]：`top`＝機種を一覧の上から、`bottom`＝下から次の機種を選ぶ。
  /// [manual]：手動の取り込み。次のページは、一覧の最初から探し直さず、いま保存したページの次から探す。
  /// [freshSince]：{日付: 今回の取り込みで最初に保存したページのサイトの更新時刻}。これより古い数値の機種は
  /// 全台一覧から取り直す（数値が変わった台だけ台別ページも）。このページで分かった分をここに足す
  /// （呼び出し側が持ち続けて、次の保存でも渡す）。
  Future<
    ({int saved, int remaining, String kind, String? nextUrl, String? skipped})
  >
  importPage(
    String raw,
    String? currentUrl, {
    String? expectedDay,
    String direction = 'top',
    bool manual = false,
    Map<String, String>? freshSince,
  }) => _serial(
    () => _importPage(
      raw,
      currentUrl,
      expectedDay,
      direction,
      manual,
      freshSince ?? <String, String>{},
    ),
  );

  Future<
    ({int saved, int remaining, String kind, String? nextUrl, String? skipped})
  >
  _importPage(
    String raw,
    String? currentUrl,
    String? expectedDay,
    String direction,
    bool manual,
    Map<String, String> freshSince,
  ) async {
    if (direction != 'top' && direction != 'bottom') {
      throw const FormatException('取り込みの向きが不正です。');
    }
    final data = _asMap(jsonDecode(raw));
    final skipped = await _skipAbsentDay(
      data,
      currentUrl,
      expectedDay,
      direction,
      manual,
      freshSince,
    );
    if (skipped != null) return skipped;
    if (data['error'] != null) throw FormatException('${data['error']}');
    if (data['format'] != 'pscube-viewer' ||
        data['version'] != 1 ||
        data['machines'] is! List ||
        data['records'] is! List) {
      throw const FormatException('P’s CUBEの取り込み形式ではありません。');
    }
    final current = Uri.tryParse(currentUrl ?? '');
    final reported = Uri.tryParse(data['source_url']?.toString() ?? '');
    if (current == null ||
        reported == null ||
        !pscubeSamePage(current, reported)) {
      throw const FormatException('表示中のURLと読み取り結果が一致しません。');
    }
    final indexPage = current.path.endsWith('nc-v03-001.php');
    final tablePage = current.path.endsWith('nc-v05-011.php');
    final rackPage = current.path.endsWith('nc-v06-001.php');
    _site(
      currentUrl,
      indexPage
          ? 'nc-v03-001.php'
          : tablePage
          ? 'nc-v05-011.php'
          : 'nc-v06-001.php',
    );
    if (!indexPage && !tablePage && !rackPage) {
      throw const FormatException('取り込み対象の画面ではありません。');
    }
    var machines = (data['machines'] as List).map(_asMap).toList();
    final records = (data['records'] as List).map(_asMap).toList();
    if (machines.length > 10000 || records.length > 5000 || machines.isEmpty) {
      throw const FormatException('機種・台の件数が不正です。');
    }
    for (final machine in machines) {
      _machine(machine);
    }
    for (final record in records) {
      _record(record);
    }
    if (machines.map((m) => _key(m)).toSet().length != machines.length ||
        records.map((r) => _key(r, record: true)).toSet().length !=
            records.length) {
      throw const FormatException('機種・台が重複しています。');
    }
    if (indexPage &&
        (current.queryParameters['cd_ps'] != '2' || records.isNotEmpty)) {
      throw const FormatException('スロット機種一覧ではありません。');
    }
    if (indexPage) {
      machines = [
        for (final machine in machines)
          if (!isExcludedMachine(machine['machine'] as String?)) machine,
      ];
    } else if (isExcludedMachine(machines.first['machine'] as String?)) {
      throw FormatException(
        '${machines.first['machine']}は取り込みの対象外です（沖ドキ）。保存しませんでした。',
      );
    }
    String? day;
    var missingRacks = <int>[];
    if (tablePage) {
      if ((current.queryParameters.containsKey('cd_ps') &&
              current.queryParameters['cd_ps'] != '2') ||
          machines.length != 1 ||
          records.isEmpty ||
          records.any((r) => _key(r) != _key(machines.single))) {
        throw const FormatException('全台一覧が揃っていません。');
      }
      day = records.first['day'] as String;
      if (records.any((r) => r['day'] != day)) {
        throw const FormatException('営業日が一致しません。');
      }
      missingRacks = _missingRacksOf(data, records, day);
      final known = await _get('machines', _key(machines.single));
      final shown = records.length + missingRacks.length;
      if (known == null ||
          known['expected_count'] == null ||
          shown != known['expected_count']) {
        throw FormatException(
          '全台を表示してください。表示 $shown 台、設置 ${known?['expected_count'] ?? '?'} 台。',
        );
      }
    }
    if (rackPage) {
      if (machines.length != 1 ||
          records.isEmpty ||
          records.length > 7 ||
          current.fragment.length != 8) {
        throw const FormatException('台別7日分が揃っていません。');
      }
      day =
          '${current.fragment.substring(0, 4)}-${current.fragment.substring(4, 6)}-${current.fragment.substring(6)}';
      final today = records.where((r) => r['day'] == day).toList();
      if (today.length != 1 ||
          await _get('records', _key(today.single, record: true)) == null ||
          records.any(
            (r) =>
                _key(r) != _key(today.single) ||
                r['rack'] != today.single['rack'],
          )) {
        throw const FormatException('先にこの台の全台一覧を取り込んでください。');
      }
      if (current.queryParameters['cd_dai'] != '${today.single['rack']}' ||
          _key(machines.single) != _key(today.single)) {
        throw const FormatException('表示中の台番号・機種と一致しません。');
      }
      // 台別ページの7列はサイトの「本日」（history_latest_day）から並び、選んだ日より新しい列は
      // 読み取りで除いてある（2026-10-06）。その日が無い古い読み取り結果は、選んだ日を1列目とみなす。
      final selected = DateTime.parse('${day}T00:00:00Z');
      final latestText = data['history_latest_day'];
      final latest = latestText == null
          ? selected
          : latestText is String &&
                RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(latestText)
          ? DateTime.tryParse('${latestText}T00:00:00Z')
          : null;
      if (latest == null ||
          latest.isBefore(selected) ||
          latest.difference(selected).inDays > 6) {
        throw const FormatException('台別7日分の日付を確認できません。');
      }
      final expected = {
        for (var i = 0; i < 7; i++)
          if (!latest.subtract(Duration(days: i)).isAfter(selected))
            latest
                .subtract(Duration(days: i))
                .toIso8601String()
                .substring(0, 10),
      };
      // 共通JSが新台の「全空欄かつグラフ無し」の過去列を明示している場合だけ省略可。
      final missing = data['missing_history_days'] ?? <dynamic>[];
      final present = records.map((r) => r['day']).toSet();
      if (missing is! List ||
          missing.length > 6 ||
          missing.any((d) => d is! String || !expected.contains(d)) ||
          missing.toSet().length != missing.length ||
          missing.contains(day) ||
          missing.any(present.contains) ||
          {...present, ...missing}.length != expected.length ||
          present.any((d) => !expected.contains(d))) {
        throw const FormatException('連続した7日分の履歴ではありません。');
      }
    }
    if (expectedDay != null && (tablePage || rackPage) && day != expectedDay) {
      final where = tablePage ? '全台一覧の日付タブを' : 'このページを';
      throw FormatException(
        '取り込み日は$expectedDayですが、表示中は$dayです。$where$expectedDayに合わせてください。保存しませんでした。',
      );
    }
    day ??= await _day();
    // Read old values before the transaction. sqflite queues ordinary Database
    // calls while a transaction is active, so querying db inside it deadlocks.
    final oldMachines = <String, Map<String, dynamic>?>{};
    final oldRecords = <String, Map<String, dynamic>?>{};
    for (final machine in machines) {
      final key = _key(machine);
      oldMachines[key] = await _get('machines', key);
    }
    for (final record in records) {
      final key = _key(record, record: true);
      oldRecords[key] = await _get('records', key);
    }
    final oldAbsentRacks = await _absentRacks();
    final oldAbsentDays = tablePage ? await _absentDays() : const <String>{};
    await db.transaction((txn) async {
      for (final machine in machines) {
        final key = _key(machine);
        final previous = oldMachines[key];
        final saved = {
          ...machine,
          'expected_count':
              machine['expected_count'] ?? previous?['expected_count'],
          'machine_type': machine['machine_type'] ?? previous?['machine_type'],
        };
        await txn.insert('machines', {
          'key': key,
          'payload': jsonEncode(saved),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
      for (final record in records) {
        final key = _key(record, record: true);
        final previous = oldRecords[key];
        final saved = _merge(previous, record);
        if (previous != null &&
            [
              'bb',
              'rb',
              'at_art',
              'games',
              'my',
            ].any((f) => previous[f] != saved[f])) {
          await txn.delete('rack_captures', where: 'key=?', whereArgs: [key]);
        }
        await txn.insert('records', {
          'key': key,
          'payload': jsonEncode(saved),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
      if (day != null) {
        await txn.insert('state', {
          'key': 'last_day',
          'value': day,
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
      if (tablePage) {
        // その日に無かった台（増台した台）を覚える。全部そろった一覧を取り直したら消す。
        final place = jsonEncode([_key(machines.single), day]);
        final absent = {...oldAbsentRacks}..remove(place);
        if (missingRacks.isNotEmpty) absent[place] = missingRacks;
        await txn.insert('state', {
          'key': pscubeAbsentRacksKey,
          'value': jsonEncode([
            for (final e
                in (absent.entries.toList()
                  ..sort((a, b) => a.key.compareTo(b.key))))
              [...jsonDecode(e.key) as List, e.value],
          ]),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
        // この機種・日の全台一覧を保存できた＝その日のタブはある。「タブなし」の印を外し、未取得に戻す
        // （以前は外さず、あとで取れても機種ごと除外され続けた。2026-10-22、PC版と同じ）。ほかの機種・日の印は残す。
        // 読むのはトランザクションの前（上の oldAbsentDays）。ここで db へ問い合わせると待ち合いで止まる。
        if (oldAbsentDays.contains(place)) {
          await txn.insert('state', {
            'key': pscubeAbsentDaysKey,
            'value': jsonEncode([
              for (final e
                  in (oldAbsentDays.toSet()..remove(place)).toList()..sort())
                jsonDecode(e),
            ]),
          }, conflictAlgorithm: ConflictAlgorithm.replace);
        }
      }
      if (indexPage) {
        await txn.insert('state', {
          'key': 'active_machine_keys',
          'value': jsonEncode(machines.map(_key).toList()),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
      if (rackPage) {
        final current = records.singleWhere((r) => r['day'] == day);
        await txn.insert('rack_captures', {
          'key': _key(current, record: true),
        }, conflictAlgorithm: ConflictAlgorithm.ignore);
      }
    });
    if (records.any((r) => r['net_capture'] != null)) await _trimProbes();
    if ((tablePage || rackPage) &&
        day != null &&
        !freshSince.containsKey(day)) {
      String? newest;
      for (final r in records) {
        final time = r['observed_at'];
        if (r['day'] != day || _instant(time) == null) continue;
        if (newest == null || _instant(time)! > _instant(newest)!) {
          newest = time as String;
        }
      }
      if (newest != null) freshSince[day] = newest;
    }
    // 取り込み日を指定しているときは、一覧から最初の機種ではなく、その日の未取得の先頭へ進む。
    // ただし、その日の基準の時刻がまだ無い（今回まだ1ページも保存していない）ときは、決めた向きの
    // 最初の機種を開く（開いた機種の全台一覧で基準が分かる）。
    final next =
        indexPage &&
            (expectedDay == null || !freshSince.containsKey(expectedDay))
        ? (
            url:
                (direction == 'bottom' ? machines.last : machines.first)['url']
                    as String?,
            remaining: machines.length,
          )
        : await _nextTarget(
            expectedDay ?? day,
            direction,
            !manual
                ? null
                : tablePage
                ? (_key(machines.single), null)
                : rackPage
                ? (
                    _key(machines.single),
                    records.singleWhere((r) => r['day'] == day)['rack'] as int,
                  )
                : null,
            freshSince[expectedDay ?? day],
          );
    return (
      saved: records.length,
      remaining: next.remaining,
      kind: indexPage
          ? '機種一覧'
          : tablePage
          ? (missingRacks.isEmpty
                ? '全台一覧'
                : '全台一覧（${missingRacks.join('・')}番台はこの日の数値なし）')
          : records.length < 7
          ? '台別履歴（${records.length}日分）'
          : '台別7日分',
      nextUrl: next.url == null
          ? null
          : pscubeTableUrlForDay(next.url!, expectedDay),
      skipped: null,
    );
  }

  /// その日に無かった台（{jsonEncode([機種のキー, 日付]): [台番号]}）。増台した台は、過去の日の全台一覧に
  /// 数値もリンクも無く並ぶ（PC版 `_absent_racks` と同じ）。
  Future<Map<String, List<int>>> _absentRacks() async {
    final rows = await db.query(
      'state',
      columns: ['value'],
      where: 'key=?',
      whereArgs: [pscubeAbsentRacksKey],
    );
    try {
      return rows.isEmpty
          ? <String, List<int>>{}
          : {
              for (final e in jsonDecode(rows.first['value'] as String) as List)
                jsonEncode([e[0], e[1]]): (e[2] as List).cast<int>(),
            };
    } catch (_) {
      return <String, List<int>>{};
    }
  }

  /// 全台一覧の「その日に数値もリンクも無い台」（共通JSの missing_racks）を確かめて返す。今動いている日（日付タブの
  /// 最新）では受け付けない。数値のある台が1台も無いページは共通JSが止める（読み込み途中かもしれない。2026-10-19、
  /// PC版 `_missing_racks_of` と同じ）。
  static List<int> _missingRacksOf(
    Map<String, dynamic> data,
    List<Map<String, dynamic>> records,
    String day,
  ) {
    final missing = data['missing_racks'];
    if (missing == null || (missing is List && missing.isEmpty)) return [];
    final racks = records.map((r) => r['rack']).toSet();
    if (missing is! List ||
        missing.any((r) => r is! int || r < 1 || racks.contains(r)) ||
        missing.toSet().length != missing.length) {
      throw const FormatException('数値の無い台の情報が不正です。');
    }
    final list = missing.cast<int>().toList()..sort();
    final days = data['available_days'];
    if (days is! List ||
        days.isEmpty ||
        days.any((d) => d is! String) ||
        day.compareTo(
              days.cast<String>().reduce((a, b) => a.compareTo(b) > 0 ? a : b),
            ) >=
            0) {
      throw FormatException(
        '${list.join('・')}番台に数値と台別ページへのリンクがありません。数値が表示されてから保存してください。',
      );
    }
    return list;
  }

  Future<Set<String>> _absentDays() async {
    final rows = await db.query(
      'state',
      columns: ['value'],
      where: 'key=?',
      whereArgs: [pscubeAbsentDaysKey],
    );
    try {
      return rows.isEmpty
          ? <String>{}
          : {
              for (final e in jsonDecode(rows.first['value'] as String) as List)
                jsonEncode(e),
            };
    } catch (_) {
      return <String>{};
    }
  }

  /// 取り込み日を指定して開いた全台一覧に、その日の日付タブが無ければ、その機種のその日を「サイトに記録なし」
  /// として覚え、保存せずに次へ進む。入れ替えで入った新台はその日からのタブしか無く、前日を指定するとサイトは
  /// 最新のタブを選ぶ。以前は未取得の先頭に残り続け、取り込みが先へ進まなかった（2026-10-19。PC版
  /// `_skip_absent_day` と同じ）。飛ばすのは、指定日がタブの範囲より前か、範囲の中で抜けている日だけ。
  /// タブより新しい日（その日のタブがまだ出ていない早朝など）は飛ばさない。
  Future<
    ({int saved, int remaining, String kind, String? nextUrl, String? skipped})?
  >
  _skipAbsentDay(
    Map<String, dynamic> data,
    String? currentUrl,
    String? expectedDay,
    String direction,
    bool manual,
    Map<String, String> freshSince,
  ) async {
    final days = data['available_days'];
    final current = Uri.tryParse(currentUrl ?? '');
    if (expectedDay == null ||
        current == null ||
        !current.path.endsWith('nc-v05-011.php') ||
        !pscubeDayTabAbsent(expectedDay, days)) {
      return null;
    }
    final tabs = (days as List).cast<String>().toList()..sort();
    _site(currentUrl, 'nc-v05-011.php');
    final reported = Uri.tryParse(data['source_url']?.toString() ?? '');
    if (reported == null || !pscubeSamePage(current, reported)) {
      throw const FormatException('表示中のURLと読み取り結果が一致しません。');
    }
    Map<String, dynamic>? machine;
    for (final row in await db.query('machines', columns: ['payload'])) {
      final m = _asMap(jsonDecode(row['payload'] as String));
      final url = m['url'];
      if (url is String && pscubeSameMachineUrl(url, currentUrl!)) {
        machine = m;
        break;
      }
    }
    String label(String d) =>
        '${int.parse(d.substring(5, 7))}/${int.parse(d.substring(8))}';
    final shown = tabs.map(label).join('・');
    if (machine == null) {
      throw FormatException(
        '取り込み日$expectedDayの日付タブがこの機種にありません（タブ：$shown）。'
        '先に設置機種一覧を取り込んでください。保存しませんでした。',
      );
    }
    final key = _key(machine);
    final absent = {
      ...await _absentDays(),
      jsonEncode([key, expectedDay]),
    };
    await db.insert('state', {
      'key': pscubeAbsentDaysKey,
      'value': jsonEncode([
        for (final e in absent.toList()..sort()) jsonDecode(e),
      ]),
    }, conflictAlgorithm: ConflictAlgorithm.replace);
    final next = await _nextTarget(
      expectedDay,
      direction,
      manual ? (key, null) : null,
      freshSince[expectedDay],
    );
    return (
      saved: 0,
      remaining: next.remaining,
      kind: '全台一覧',
      nextUrl: next.url == null
          ? null
          : pscubeTableUrlForDay(next.url!, expectedDay),
      skipped:
          '${machine['machine']}は${label(expectedDay)}の日付タブがサイトにありません'
          '（タブ：$shown。新台・入れ替えの可能性）。保存せずに飛ばしました',
    );
  }

  static Map<String, dynamic> _merge(
    Map<String, dynamic>? old,
    Map<String, dynamic> fresh,
  ) {
    if (old == null) return fresh;
    if (fresh['source_site'] == 'anaslo') return old;
    if (old['source_site'] == 'anaslo') return fresh;
    final same = [
      'bb',
      'rb',
      'at_art',
      'games',
      'my',
    ].every((f) => old[f] == fresh[f]);
    final oldTime = DateTime.tryParse('${old['observed_at'] ?? ''}');
    final newTime = DateTime.tryParse('${fresh['observed_at'] ?? ''}');
    final older = oldTime != null && newTime != null
        ? newTime.isBefore(oldTime)
        : (fresh['games'] as int) < (old['games'] as int);
    if (older && !same) return old;
    final chosen = older ? old : fresh;
    final other = older ? fresh : old;
    final net = chosen['net_medals'] ?? other['net_medals'];
    if (!same) return chosen;
    final graph = chosen['graph'];
    final alternate = other['graph'];
    final capture = mergeNetCapture(chosen, other, same);
    return {
      ...chosen,
      if (capture != null) 'net_capture': capture,
      if (net != null) 'net_medals': net,
      'graph': graph is Map && graph['kind'] == 'daily'
          ? graph
          : alternate is Map && alternate['kind'] == 'daily'
          ? alternate
          : graph ?? alternate,
    };
  }

  Future<({String? url, int remaining})> nextTarget([
    String? day,
    String direction = 'top',
    (String, int?)? after,
    String? freshSince,
  ]) => _serial(() => _nextTarget(day, direction, after, freshSince));

  /// [after]：手動の取り込みで、いま保存したページ（機種のキー、台番号。全台一覧ならnull）。
  /// 一覧の最初から探し直さず、そのページの次（機種の並びの順、機種の中は台番号の小さい順）から
  /// 探し、最後まで行って残りが無いときだけ最初へ回る。
  /// [freshSince]：今回の取り込みの基準の時刻（[pscubeStaleCutoff]）。全台一覧が揃っていても、数値が
  /// それより古い機種は全台一覧から取り直す（以前は昼に一度取った機種を夜も「済み」として飛ばしていた）。
  Future<({String? url, int remaining})> _nextTarget([
    String? day,
    String direction = 'top',
    (String, int?)? after,
    String? freshSince,
  ]) async {
    day ??= await _day();
    var machines = (await db.query(
      'machines',
      columns: ['payload'],
      orderBy: 'rowid',
    )).map((r) => _asMap(jsonDecode(r['payload'] as String))).toList();
    final activeRows = await db.query(
      'state',
      columns: ['value'],
      where: 'key=?',
      whereArgs: ['active_machine_keys'],
    );
    if (activeRows.isNotEmpty) {
      final active = (jsonDecode(activeRows.first['value'] as String) as List)
          .cast<String>();
      final byKey = {for (final machine in machines) _key(machine): machine};
      machines = [
        for (final key in active)
          if (byKey[key] != null) byKey[key]!,
      ];
    }
    machines = [
      for (final machine in machines)
        if (machine['url'] != null &&
            !isExcludedMachine(machine['machine'] as String?))
          machine,
    ];
    if (direction == 'bottom') machines = machines.reversed.toList();
    if (machines.isEmpty) return (url: index, remaining: 0);
    if (day == null) {
      return (url: machines.first['url'] as String, remaining: machines.length);
    }
    final records = (await db.query(
      'records',
      columns: ['payload'],
    )).map((r) => _asMap(jsonDecode(r['payload'] as String))).toList();
    final captured = (await db.query(
      'rack_captures',
      columns: ['key'],
    )).map((r) => r['key'] as String).toSet();
    // (機種の並び順, 台番号（全台一覧は-1）, URL)
    final pending = <(int, int, String)>[];
    final cutoff = pscubeStaleCutoff(day, freshSince);
    final absent = await _absentDays();
    final absentRacks = await _absentRacks();
    for (final (index, machine) in machines.indexed) {
      // その日の日付タブがサイトに無かった機種（新台・入れ替え）は、その日の未取得に数えない。
      if (absent.contains(jsonEncode([_key(machine), day]))) continue;
      final rows =
          records
              .where((r) => _key(r) == _key(machine) && r['day'] == day)
              .toList()
            ..sort((a, b) => (a['rack'] as int).compareTo(b['rack'] as int));
      // 一番古い数値で判断する（台別ページは1台ずつしか新しくならない）。時刻の分からない台は使わない。
      final times = [
        for (final r in rows)
          if (_instant(r['observed_at']) case final time?) time,
      ];
      final oldest = times.isEmpty
          ? null
          : times.reduce((a, b) => a < b ? a : b);
      final racks = rows.map((r) => r['rack']).toSet();
      final missing =
          (absentRacks[jsonEncode([_key(machine), day])] ?? const []).where(
            (r) => !racks.contains(r),
          );
      if (rows.length + missing.length != machine['expected_count'] ||
          (cutoff != null && oldest != null && oldest < cutoff)) {
        pending.add((index, -1, machine['url'] as String));
      } else {
        pending.addAll(
          rows
              .where(
                (r) =>
                    r['detail_url'] != null &&
                    !captured.contains(_key(r, record: true)) &&
                    !noHits(r),
              )
              .map((r) => (index, r['rack'] as int, r['detail_url'] as String)),
        );
      }
    }
    var ordered = pending;
    final position = after == null
        ? -1
        : machines.indexWhere((m) => _key(m) == after.$1);
    if (after != null && position >= 0 && pending.isNotEmpty) {
      // 全台一覧を保存した機種は、その機種の台から（-2は全台一覧より前）。台別ページなら、その台の次から。
      final here = after.$2 ?? -2;
      bool later((int, int, String) e) =>
          e.$1 > position || (e.$1 == position && e.$2 > here);
      ordered = [...pending.where(later), ...pending.where((e) => !later(e))];
    }
    return (
      url: ordered.isEmpty ? null : ordered.first.$3,
      remaining: ordered.length,
    );
  }

  /// 共有フォルダに置くバックアップの名前。例 pscube-backup-android-20261001-120000.json
  /// （メルヘンの database-backup-* と重ならない。半角英数字だけ）。
  static String backupFileName(DateTime now) {
    String two(int v) => v.toString().padLeft(2, '0');
    return 'pscube-backup-android-${now.year}${two(now.month)}${two(now.day)}'
        '-${two(now.hour)}${two(now.minute)}${two(now.second)}.json';
  }

  /// 全期間のバックアップ（仕様：database/PSCUBE_SYNC.md）。[path] を省くと
  /// 書類フォルダへ [backupFileName] の名前で書き、前に書いた自分のバックアップを消す。
  Future<void> _trimProbes() async {
    final rows = await db.query(
      'records',
      columns: ['key', 'payload'],
      where: 'payload LIKE ?',
      whereArgs: ['%"probe":%'],
    );
    final records = rows
        .map((r) => _asMap(jsonDecode(r['payload'] as String)))
        .toList();
    final before = records.map((r) => jsonEncode(r['net_capture'])).toList();
    trimNetProbes(records);
    final batch = db.batch();
    for (var i = 0; i < records.length; i++) {
      if (jsonEncode(records[i]['net_capture']) != before[i]) {
        batch.update(
          'records',
          {'payload': jsonEncode(records[i])},
          where: 'key=?',
          whereArgs: [rows[i]['key']],
        );
      }
    }
    await batch.commit(noResult: true);
  }

  Future<List<Map<String, dynamic>>> healthRecords(String? day) =>
      _serial(() async {
        final selected = day ?? await _dayIn(db);
        final rows = await db.query(
          'records',
          columns: ['payload'],
          where: selected == null ? null : 'key LIKE ?',
          whereArgs: selected == null ? null : ['%,"$selected"]'],
        );
        return rows
            .map((r) => _asMap(jsonDecode(r['payload'] as String)))
            .toList();
      });

  Future<Map<String, dynamic>?> syncStatus() =>
      _serial(() => _syncStatusIn(db));

  Future<Map<String, dynamic>?> _syncStatusIn(DatabaseExecutor executor) async {
    final rows = await executor.query(
      'state',
      columns: ['value'],
      where: 'key=?',
      whereArgs: ['sync_status'],
    );
    return rows.isEmpty
        ? null
        : validateSyncStatus(jsonDecode(rows.first['value'] as String));
  }

  Future<File> exportViewer({String? path, DateTime? now}) =>
      _serial(() => _exportViewer(path, now ?? DateTime.now()));

  Future<File> _exportViewer(String? path, DateTime now) async {
    final machines = (await db.query(
      'machines',
      columns: ['payload'],
      orderBy: 'rowid',
    )).map((r) => jsonDecode(r['payload'] as String)).toList();
    final records = (await db.query(
      'records',
      columns: ['payload'],
      orderBy: 'rowid',
    )).map((r) => _asMap(jsonDecode(r['payload'] as String))).toList();
    final captures = (await db.query(
      'rack_captures',
      columns: ['key'],
      orderBy: 'rowid',
    )).map((r) => r['key'] as String).toList();
    trimNetProbes(records, now: now);
    final events = await _dateEventsIn(db);
    final status = mergeSyncStatuses(
      await _syncStatusIn(db),
      makeSyncWrite('android', timestampWithOffset(now), records),
    );
    final folder = path == null
        ? Directory((await getApplicationDocumentsDirectory()).path)
        : null;
    final file = File(path ?? '${folder!.path}/${backupFileName(now)}');
    final temp = File('${file.path}.tmp');
    await temp.writeAsString(
      jsonEncode({
        'format': 'pscube-viewer',
        'version': 1,
        'kind': 'backup',
        'source': 'android',
        'exported_at': timestampWithOffset(now),
        if (status != null) 'sync_status': status,
        'machines': machines,
        'records': records,
        'rack_captures': captures,
        if (events.isNotEmpty)
          'date_events': [for (final e in events) e.toJson()],
      }),
      flush: true,
    );
    final saved = await temp.rename(file.path);
    if (status != null)
      await db.insert('state', {
        'key': 'sync_status',
        'value': jsonEncode(status),
      }, conflictAlgorithm: ConflictAlgorithm.replace);
    if (folder != null) {
      await for (final old in folder.list()) {
        final name = old.uri.pathSegments.last;
        if (old is File &&
            old.path != saved.path &&
            RegExp(r'^pscube-backup-android-\d{8}-\d{6}\.json$')
                .hasMatch(name)) {
          try {
            await old.delete();
          } on FileSystemException {
            // 消せなくても書き出しは成功している。
          }
        }
      }
    }
    return saved;
  }

  /// 日付ごとのイベント名（消した印を含む）。state の date_events に JSON で持つ
  /// （表を増やさない。PC版 `PscubeStore.date_events` と同じ形）。
  Future<List<PscubeDateEvent>> dateEvents() =>
      _serial(() => _dateEventsIn(db));

  Future<List<PscubeDateEvent>> _dateEventsIn(DatabaseExecutor executor) async {
    final rows = await executor.query(
      'state',
      columns: ['value'],
      where: 'key=?',
      whereArgs: ['date_events'],
    );
    if (rows.isEmpty) return const [];
    return pscubeDateEvents({
      'date_events': jsonDecode(rows.first['value'] as String),
    });
  }

  /// [day] のイベント名を付ける・変える・消す（null・空はイベントなし）。記録のある店舗・貸玉
  /// それぞれに同じ名前を入れる（閲覧ページは店舗・貸玉ごとに持つ）。PC版 `set_date_event` と同じ。
  Future<void> setDateEvent(String day, String? name, {DateTime? now}) =>
      _serial(() async {
        if (DateTime.tryParse('${day}T00:00:00Z') == null) {
          throw const FormatException('日付が不正です。');
        }
        final cleaned = cleanPscubeEventName(name);
        final scopes = <(String, String)>{
          for (final row in await db.query('machines', columns: ['payload']))
            () {
              final m = _asMap(jsonDecode(row['payload'] as String));
              return (m['store'] as String, m['rate'] as String);
            }(),
        };
        if (scopes.isEmpty) {
          throw const FormatException('先にP’s CUBEの記録を取り込んでください。');
        }
        final events = {
          for (final e in await _dateEventsIn(db)) e.event.key: e,
        };
        final at = (now ?? DateTime.now()).toUtc();
        for (final (store, rate) in scopes) {
          final key = 'pscube:$store:$rate|$day';
          final previous = events[key];
          var time = at;
          if (previous != null) {
            final after = DateTime.parse(previous.updatedAt)
                .toUtc()
                .add(const Duration(milliseconds: 1));
            if (after.isAfter(time)) time = after;
          }
          events[key] = PscubeDateEvent(
            store: store,
            rate: rate,
            day: day,
            name: cleaned,
            updatedAt: time.toIso8601String(),
          );
        }
        await db.insert('state', {
          'key': 'date_events',
          'value': jsonEncode([for (final e in events.values) e.toJson()]),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      });

  /// イベントカレンダー（2026-10-08）：[days]（先の日も可）に同じ名前を付ける・消す。記録のある
  /// 店舗・貸玉それぞれに入れる。名前の変わらない日は時刻を変えず、何も無い日の「イベントなし」で
  /// 消した印を作らない（PC版 `set_date_event_days` と同じ）。
  Future<void> setDateEventDays(
    List<String> days,
    String? name, {
    DateTime? now,
  }) => _serial(() async {
    if (days.isEmpty ||
        days.length > 62 ||
        days.any((d) => DateTime.tryParse('${d}T00:00:00Z') == null)) {
      throw const FormatException('日付が不正です。');
    }
    final cleaned = cleanPscubeEventName(name);
    final scopes = <(String, String)>{
      for (final row in await db.query('machines', columns: ['payload']))
        () {
          final m = _asMap(jsonDecode(row['payload'] as String));
          return (m['store'] as String, m['rate'] as String);
        }(),
    };
    if (scopes.isEmpty) {
      throw const FormatException('先にP’s CUBEの記録を取り込んでください。');
    }
    final events = {for (final e in await _dateEventsIn(db)) e.event.key: e};
    final at = (now ?? DateTime.now()).toUtc();
    var changed = false;
    for (final day in days) {
      for (final (store, rate) in scopes) {
        final key = 'pscube:$store:$rate|$day';
        final previous = events[key];
        if (previous == null ? cleaned == null : previous.name == cleaned) {
          continue;
        }
        var time = at;
        if (previous != null) {
          final after = DateTime.parse(previous.updatedAt)
              .toUtc()
              .add(const Duration(milliseconds: 1));
          if (after.isAfter(time)) time = after;
        }
        events[key] = PscubeDateEvent(
          store: store,
          rate: rate,
          day: day,
          name: cleaned,
          updatedAt: time.toIso8601String(),
        );
        changed = true;
      }
    }
    if (!changed) return;
    await db.insert('state', {
      'key': 'date_events',
      'value': jsonEncode([for (final e in events.values) e.toJson()]),
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  });

  /// イベントカレンダーに出す記録とイベント（閲覧ページと同じ `pscube-viewer` の形。ファイルには書かない）。
  Future<Map<String, Object?>> calendarData() => _serial(() async {
    final machines = (await db.query(
      'machines',
      columns: ['payload'],
      orderBy: 'rowid',
    )).map((r) => jsonDecode(r['payload'] as String)).toList();
    final records = (await db.query(
      'records',
      columns: ['payload'],
      orderBy: 'rowid',
    )).map((r) => jsonDecode(r['payload'] as String)).toList();
    final events = await _dateEventsIn(db);
    return {
      'format': 'pscube-viewer',
      'version': 1,
      'machines': machines,
      'records': records,
      if (events.isNotEmpty)
        'date_events': [for (final e in events) e.toJson()],
    };
  });

  /// [day] のイベント名（どれかの貸玉に付いていれば、その名前）。
  Future<String?> dateEventFor(String day) async {
    for (final e in await dateEvents()) {
      if (e.day == day && e.name != null) return e.name;
    }
    return null;
  }

  /// 今までに付けたイベント名（新しく使った順、重複なし）。入力欄のプルダウンに使う。
  Future<List<String>> dateEventNames() async {
    final latest = <String, DateTime>{};
    for (final e in await dateEvents()) {
      final name = e.name;
      if (name == null) continue;
      final time = DateTime.parse(e.updatedAt);
      if (latest[name] == null || time.isAfter(latest[name]!)) {
        latest[name] = time;
      }
    }
    return (latest.entries.toList()..sort((a, b) {
          final byTime = b.value.compareTo(a.value);
          return byTime != 0 ? byTime : a.key.compareTo(b.key);
        }))
        .map((e) => e.key)
        .toList();
  }

  /// 最後にバックアップを書き出した時刻（共有を完了したときだけ [markBackedUp] で残す）。
  Future<DateTime?> lastBackupAt() => _serial(() async {
    final rows = await db.query(
      'state',
      columns: ['value'],
      where: 'key=?',
      whereArgs: ['last_backup_at'],
    );
    return rows.isEmpty
        ? null
        : DateTime.tryParse(rows.first['value'] as String);
  });

  /// 最後に全台一覧を保存した日（取り込み中の日）。
  Future<String?> lastDay() => _serial(() => _dayIn(db));

  /// その日の記録だけのバックアップ（Apps Scriptへ送る当日分、2026-10-26、database/PSCUBE_SYNC.md）。
  /// 形は [exportViewer] の書き出しと同じで、記録・取り込み済みの印はその日の分、機種はその記録の機種だけ。
  /// PC版は普通のバックアップとして読む。その日の記録が無ければ null。
  Future<Map<String, Object?>?> dayBackup(String day, {DateTime? now}) =>
      _serial(() async {
        final records = [
          for (final r in await db.query(
            'records',
            columns: ['payload'],
            where: 'key LIKE ?',
            whereArgs: ['%,"$day"]'],
            orderBy: 'rowid',
          ))
            _asMap(jsonDecode(r['payload'] as String)),
        ].where((r) => r['day'] == day).toList();
        if (records.isEmpty) return null;
        final recordKeys = {for (final r in records) _key(r, record: true)};
        final machineKeys = {for (final r in records) _key(r)};
        final machines = [
          for (final m in await db.query(
            'machines',
            columns: ['key', 'payload'],
            orderBy: 'rowid',
          ))
            if (machineKeys.contains(m['key']))
              jsonDecode(m['payload'] as String),
        ];
        final captures = [
          for (final c in await db.query(
            'rack_captures',
            columns: ['key'],
            orderBy: 'rowid',
          ))
            if (recordKeys.contains(c['key'])) c['key'] as String,
        ];
        final at = now ?? DateTime.now();
        trimNetProbes(records, now: at);
        return {
          'format': 'pscube-viewer',
          'version': 1,
          'kind': 'backup',
          'source': 'android',
          'exported_at': timestampWithOffset(at),
          'machines': machines,
          'records': records,
          'rack_captures': captures,
        };
      });

  /// 当日分の自動送信の設定（{url, key, enabled}）と、最後の送信の結果（{day, at, ok, message}）。
  /// 端末の中だけに持つ（バックアップには入れない。合言葉を他の端末のファイルへ出さない）。
  Future<Map<String, dynamic>?> dayUploadSetting() =>
      _serial(() => _stateJson('day_upload'));

  Future<void> setDayUploadSetting(Map<String, Object?>? value) => _serial(
    () => value == null
        ? db.delete('state', where: 'key=?', whereArgs: ['day_upload'])
        : db.insert('state', {
            'key': 'day_upload',
            'value': jsonEncode(value),
          }, conflictAlgorithm: ConflictAlgorithm.replace),
  );

  Future<Map<String, dynamic>?> lastDayUpload() =>
      _serial(() => _stateJson('day_upload_last'));

  Future<void> markDayUpload(Map<String, Object?> value) => _serial(
    () => db.insert('state', {
      'key': 'day_upload_last',
      'value': jsonEncode(value),
    }, conflictAlgorithm: ConflictAlgorithm.replace),
  );

  Future<Map<String, dynamic>?> _stateJson(String key) async {
    final rows = await db.query(
      'state',
      columns: ['value'],
      where: 'key=?',
      whereArgs: [key],
    );
    if (rows.isEmpty) return null;
    try {
      final value = jsonDecode(rows.first['value'] as String);
      return value is Map ? value.cast<String, dynamic>() : null;
    } on FormatException {
      return null;
    }
  }

  Future<void> markBackedUp([DateTime? at]) => _serial(
    () => db.insert('state', {
      'key': 'last_backup_at',
      'value': timestampWithOffset(at ?? DateTime.now()),
    }, conflictAlgorithm: ConflictAlgorithm.replace),
  );

  /// 他の端末のバックアップ（PC・ブラウザ）を統合する。消す操作はない。
  ///
  /// 台ごとの統合は取り込みと同じ [_merge]（古い数値で新しい数値を上書きしない）。
  /// 軽い閲覧用ファイル（kind=viewer）と形式の不正は、1件も保存せずに止める。
  Future<({int added, int updated, int unchanged, int keptLocal, int machines})>
  importBackup(String text) => _serial(() => _importBackup(text));

  Future<({int added, int updated, int unchanged, int keptLocal, int machines})>
  _importBackup(String text) async {
    final Object? decoded;
    try {
      decoded = jsonDecode(text);
    } on FormatException {
      throw const FormatException('P’s CUBEのバックアップではありません。');
    }
    if (decoded is! Map<String, dynamic> ||
        decoded['format'] != 'pscube-viewer' ||
        decoded['version'] != 1 ||
        decoded['machines'] is! List ||
        decoded['records'] is! List) {
      throw const FormatException('P’s CUBEのバックアップではありません。');
    }
    if (decoded['kind'] == 'viewer') {
      throw const FormatException('閲覧用の軽いファイルはバックアップではないため、読み込めません。');
    }
    final machines = [
      for (final item in decoded['machines'] as List) _asMap(item),
    ];
    final records = [
      for (final item in decoded['records'] as List) _asMap(item),
    ];
    if (machines.length > 10000 || records.length > 200000) {
      throw const FormatException('バックアップの件数が多すぎます。');
    }
    machines.forEach(_machine);
    records.forEach(_record);
    final machineKeys = machines.map(_key).toSet();
    final recordKeys = records.map((r) => _key(r, record: true)).toList();
    if (machineKeys.length != machines.length ||
        recordKeys.toSet().length != recordKeys.length) {
      throw const FormatException('同じ機種・台が重複しています。');
    }
    if (records.any((r) => !machineKeys.contains(_key(r)))) {
      throw const FormatException('台に対応する機種情報がありません。');
    }
    final Set<String> wanted;
    if (decoded.containsKey('rack_captures')) {
      final marks = decoded['rack_captures'];
      if (marks is! List ||
          marks.any((k) => k is! String) ||
          !recordKeys.toSet().containsAll(marks.cast<String>())) {
        throw const FormatException('取り込み済みの印が不正です。');
      }
      wanted = marks.cast<String>().toSet();
    } else {
      // 印の無い古い書き出し：台別7日分のグラフがある日は取り込み済みとみなす。
      wanted = {
        for (final r in records)
          if (r['graph'] is Map && (r['graph'] as Map)['kind'] == 'daily')
            _key(r, record: true),
      };
    }
    final incomingEvents = pscubeDateEvents(decoded);
    final status = mergeSyncStatuses(
      await _syncStatusIn(db),
      mergeSyncStatuses(
        decoded['sync_status'],
        makeSyncWrite(
          decoded['source'] as String?,
          decoded['exported_at'] as String?,
          records,
        ),
      ),
    );
    final fillMissing = decoded['import_mode'] == 'fill_missing';
    // sqflite はトランザクション中の通常の問い合わせを待たせるので、先に全部読む。
    final storedEvents = await _dateEventsIn(db);
    final mergedEvents = mergePscubeDateEvents(storedEvents, incomingEvents);
    final storedJson = {for (final e in storedEvents) jsonEncode(e.toJson())};
    final changedEvents = mergedEvents
        .where((e) => !storedJson.contains(jsonEncode(e.toJson())))
        .length;
    final oldMachines = {
      for (final row in await db.query('machines'))
        row['key'] as String: _asMap(jsonDecode(row['payload'] as String)),
    };
    final oldRecords = {
      for (final row in await db.query('records'))
        row['key'] as String: _asMap(jsonDecode(row['payload'] as String)),
    };
    const numbers = ['bb', 'rb', 'at_art', 'games', 'my'];
    String rackDayKey(Map<String, dynamic> r) =>
        jsonEncode([r['store'], r['rate'], r['rack'], r['day']]);
    final occupied = oldRecords.values.map(rackDayKey).toSet();
    var added = 0, updated = 0, unchanged = 0, keptLocal = 0;
    await db.transaction((txn) async {
      final batch = txn.batch();
      for (final machine in machines) {
        final key = _key(machine);
        final previous = oldMachines[key];
        if (previous != null &&
            (fillMissing || machine['source_site'] == 'anaslo')) {
          continue;
        }
        batch.insert('machines', {
          'key': key,
          'payload': jsonEncode({
            ...machine,
            'expected_count':
                machine['expected_count'] ?? previous?['expected_count'],
            'machine_type':
                previous?['machine_type'] ?? machine['machine_type'],
          }),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
      for (final record in records) {
        final key = _key(record, record: true);
        if (record['source_site'] == 'anaslo' &&
            occupied.contains(rackDayKey(record))) {
          keptLocal++;
          unchanged++;
          continue;
        }
        occupied.add(rackDayKey(record));
        final previous = oldRecords[key];
        final saved = _merge(previous, record);
        final numbersChanged =
            previous != null && numbers.any((f) => previous[f] != saved[f]);
        if (previous == null) {
          added++;
        } else if (numbersChanged ||
            jsonEncode(saved) != jsonEncode(previous)) {
          updated++;
        } else {
          unchanged++;
        }
        if (previous != null &&
            identical(saved, previous) &&
            numbers.any((f) => previous[f] != record[f])) {
          keptLocal++;
        }
        if (numbersChanged) {
          batch.delete('rack_captures', where: 'key=?', whereArgs: [key]);
        }
        batch.insert('records', {
          'key': key,
          'payload': jsonEncode(saved),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
        if (wanted.contains(key) &&
            numbers.every((f) => saved[f] == record[f])) {
          batch.insert('rack_captures', {
            'key': key,
          }, conflictAlgorithm: ConflictAlgorithm.ignore);
        }
      }
      if (records.isNotEmpty && await _dayIn(txn) == null) {
        final latest = records
            .map((r) => r['day'] as String)
            .reduce((a, b) => a.compareTo(b) >= 0 ? a : b);
        batch.insert('state', {
          'key': 'last_day',
          'value': latest,
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
      if (status != null)
        batch.insert('state', {
          'key': 'sync_status',
          'value': jsonEncode(status),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      if (changedEvents > 0) {
        batch.insert('state', {
          'key': 'date_events',
          'value': jsonEncode([for (final e in mergedEvents) e.toJson()]),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
      await batch.commit(noResult: true);
    });
    if (records.any((r) => r['net_capture'] != null)) await _trimProbes();
    return (
      added: added,
      updated: updated,
      unchanged: unchanged,
      keptLocal: keptLocal,
      machines: machines.length,
    );
  }

  Future<String?> _dayIn(DatabaseExecutor executor) async {
    final rows = await executor.query(
      'state',
      columns: ['value'],
      where: 'key=?',
      whereArgs: ['last_day'],
    );
    return rows.isEmpty ? null : rows.first['value'] as String;
  }
}
