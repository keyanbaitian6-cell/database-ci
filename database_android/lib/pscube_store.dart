import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

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

  Future<({int saved, int remaining, String kind, String? nextUrl})> importPage(
    String raw,
    String? currentUrl,
  ) => _serial(() => _importPage(raw, currentUrl));

  Future<({int saved, int remaining, String kind, String? nextUrl})>
  _importPage(String raw, String? currentUrl) async {
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
    final machines = (data['machines'] as List).map(_asMap).toList();
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
    final next = indexPage
        ? (url: machines.first['url'] as String?, remaining: machines.length)
        : await _nextTarget(day);
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
    if (!same) return chosen;
    final graph = chosen['graph'];
    final alternate = other['graph'];
    return {
      ...chosen,
      'graph': graph is Map && graph['kind'] == 'daily'
          ? graph
          : alternate is Map && alternate['kind'] == 'daily'
          ? alternate
          : graph ?? alternate,
    };
  }

  Future<({String? url, int remaining})> nextTarget([String? day]) =>
      _serial(() => _nextTarget(day));

  Future<({String? url, int remaining})> _nextTarget([String? day]) async {
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
    final pending = <String>[];
    for (final machine in machines) {
      final rows =
          records
              .where((r) => _key(r) == _key(machine) && r['day'] == day)
              .toList()
            ..sort((a, b) => (a['rack'] as int).compareTo(b['rack'] as int));
      if (rows.length != machine['expected_count']) {
        pending.add(machine['url'] as String);
      } else {
        pending.addAll(
          rows
              .where((r) => !captured.contains(_key(r, record: true)))
              .map((r) => r['detail_url'] as String),
        );
      }
    }
    return (
      url: pending.isEmpty ? null : pending.first,
      remaining: pending.length,
    );
  }

  Future<File> exportViewer({String? path}) =>
      _serial(() => _exportViewer(path));

  Future<File> _exportViewer(String? path) async {
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
    final file = File(
      path ??
          '${(await getApplicationDocumentsDirectory()).path}/pscube-viewer.json',
    );
    final temp = File('${file.path}.tmp');
    await temp.writeAsString(
      jsonEncode({
        'format': 'pscube-viewer',
        'version': 1,
        'machines': machines,
        'records': records,
      }),
      flush: true,
    );
    return temp.rename(file.path);
  }
}
