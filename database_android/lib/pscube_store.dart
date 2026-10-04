import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

import 'models.dart' show timestampWithOffset;

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
    final uri = _site(row['url'] as String?, 'nc-v05-011.php');
    if (uri.queryParameters['bai'] != row['rate'] ||
        (uri.queryParameters.containsKey('cd_ps') &&
            uri.queryParameters['cd_ps'] != '2')) {
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
    final uri = _site(row['detail_url'] as String?, 'nc-v06-001.php');
    if (uri.queryParameters['cd_dai'] != '$rack' ||
        uri.fragment != day.replaceAll('-', '')) {
      throw const FormatException('台番号・営業日とリンクが一致しません。');
    }
    for (final field in ['bb', 'rb', 'at_art', 'games', 'my']) {
      final value = row[field];
      if (value is! int || value < 0) throw FormatException('$field の数値が不正です。');
    }
    if (row['net_medals'] != null &&
        (row['net_medals'] is! int ||
            (row['net_medals'] as int).abs() > 1000000)) {
      throw const FormatException('差枚の数値が不正です。');
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
  Future<({int saved, int remaining, String kind, String? nextUrl})> importPage(
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

  Future<({int saved, int remaining, String kind, String? nextUrl})>
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
    if (data['error'] != null) throw FormatException('${data['error']}');
    if (data['format'] != 'pscube-viewer' ||
        data['version'] != 1 ||
        data['machines'] is! List ||
        data['records'] is! List) {
      throw const FormatException('P’s CUBEの取り込み形式ではありません。');
    }
    final current = Uri.tryParse(currentUrl ?? '');
    final reported = Uri.tryParse(data['source_url']?.toString() ?? '');
    if (current == null || reported == null || current != reported) {
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
    if (tablePage) {
      if ((current.queryParameters.containsKey('cd_ps') &&
              current.queryParameters['cd_ps'] != '2') ||
          machines.length != 1 ||
          records.isEmpty ||
          records.any((r) => _key(r) != _key(machines.single))) {
        throw const FormatException('全台一覧が揃っていません。');
      }
      final known = await _get('machines', _key(machines.single));
      if (known == null ||
          known['expected_count'] == null ||
          records.length != known['expected_count']) {
        throw FormatException(
          '全台を表示してください。表示 ${records.length} 台、設置 ${known?['expected_count'] ?? '?'} 台。',
        );
      }
      day = records.first['day'] as String;
      if (records.any((r) => r['day'] != day)) {
        throw const FormatException('営業日が一致しません。');
      }
    }
    if (rackPage) {
      if (machines.length != 1 ||
          records.length != 7 ||
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
      final anchor = DateTime.parse('${day}T00:00:00Z');
      final expected = {
        for (var i = 0; i < 7; i++)
          anchor.subtract(Duration(days: i)).toIso8601String().substring(0, 10),
      };
      if (records.any((r) => !expected.contains(r['day']))) {
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
          ? '全台一覧'
          : '台別7日分',
      nextUrl: next.url,
    );
  }

  static Map<String, dynamic> _merge(
    Map<String, dynamic>? old,
    Map<String, dynamic> fresh,
  ) {
    if (old == null) return fresh;
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
    return {
      ...chosen,
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
        if (!isExcludedMachine(machine['machine'] as String?)) machine,
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
    for (final (index, machine) in machines.indexed) {
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
      if (rows.length != machine['expected_count'] ||
          (cutoff != null && oldest != null && oldest < cutoff)) {
        pending.add((index, -1, machine['url'] as String));
      } else {
        pending.addAll(
          rows
              .where(
                (r) => !captured.contains(_key(r, record: true)) && !noHits(r),
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
    )).map((r) => jsonDecode(r['payload'] as String)).toList();
    final captures = (await db.query(
      'rack_captures',
      columns: ['key'],
      orderBy: 'rowid',
    )).map((r) => r['key'] as String).toList();
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
        'machines': machines,
        'records': records,
        'rack_captures': captures,
      }),
      flush: true,
    );
    final saved = await temp.rename(file.path);
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
    // sqflite はトランザクション中の通常の問い合わせを待たせるので、先に全部読む。
    final oldMachines = {
      for (final row in await db.query('machines'))
        row['key'] as String: _asMap(jsonDecode(row['payload'] as String)),
    };
    final oldRecords = {
      for (final row in await db.query('records'))
        row['key'] as String: _asMap(jsonDecode(row['payload'] as String)),
    };
    const numbers = ['bb', 'rb', 'at_art', 'games', 'my'];
    var added = 0, updated = 0, unchanged = 0, keptLocal = 0;
    await db.transaction((txn) async {
      final batch = txn.batch();
      for (final machine in machines) {
        final key = _key(machine);
        final previous = oldMachines[key];
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
      await batch.commit(noResult: true);
    });
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
