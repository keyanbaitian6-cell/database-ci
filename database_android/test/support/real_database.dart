import 'dart:io';

import 'package:database_android/database_service.dart';
import 'package:database_android/models.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

/// テスト用に、本物のSQLite（PC上）で開くDB。1回ごとに別のファイル。
Future<String> newDatabasePath() async {
  sqfliteFfiInit();
  final dir = await Directory.systemTemp.createTemp('database_android_test');
  return p.join(dir.path, 'database.sqlite3');
}

DatabaseService realDatabase(String path) => DatabaseService(
  factoryOverride: databaseFactoryFfi,
  pathOverride: path,
  seed: false,
);

/// DBにある全台を、画像・曲線込みで読む。
Future<List<SlotRecord>> fullRows(DatabaseService db) async {
  final keys = [for (final r in await db.loadAll()) r.key];
  final full = await db.loadByKeys(keys);
  return [for (final key in keys) full[key]!];
}
