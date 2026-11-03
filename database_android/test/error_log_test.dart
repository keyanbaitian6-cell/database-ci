import 'dart:io';

import 'package:database_android/error_log.dart';
import 'package:flutter_test/flutter_test.dart';

/// Androidの記録のファイル（2026-11-04、PC版 `tests/test_error_log.py` と同じ規則）。
void main() {
  late Directory dir;
  late DateTime now;

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('error-log-');
    now = DateTime(2026, 11, 5, 0, 1, 2);
    forgetErrorLog();
    errorLogDirectory = () async => dir;
    errorLogNow = () => now;
  });

  tearDown(() async {
    errorLogNow = DateTime.now;
    await dir.delete(recursive: true);
  });

  List<String> lines() => File('${dir.path}/$errorLogName').readAsLinesSync();

  test('時刻・場所・内容をタブ区切りで足し、改行や空白の続きは1つにまとめる', () async {
    expect(
      await noteErrorLog('pscube.index', '1回目：機種一覧が少ない\n（いつもの60機種に対して40機種）'),
      isTrue,
    );
    expect(await noteErrorLog('pscube.list', '機種一覧を40件まで表示（12秒）'), isTrue);
    final [first, second] = lines();
    final fields = first.split('\t');
    expect(fields, hasLength(3));
    expect(fields[0], startsWith('2026-11-05T00:01:02'));
    expect(fields[0], matches(RegExp(r'[+-]\d\d:\d\d$')), reason: '時差つき');
    expect(fields.sublist(1), [
      'pscube.index',
      '1回目：機種一覧が少ない （いつもの60機種に対して40機種）',
    ]);
    expect(second, endsWith('\tpscube.list\t機種一覧を40件まで表示（12秒）'));
  });

  test('同じ場所・同じ内容は60秒に1回だけ書く', () async {
    expect(await noteErrorLog('pscube.save', 'A'), isTrue);
    now = now.add(const Duration(seconds: 59));
    expect(await noteErrorLog('pscube.save', 'A'), isFalse);
    expect(await noteErrorLog('pscube.save', 'B'), isTrue, reason: '内容が違えば書く');
    now = now.add(const Duration(seconds: 1));
    expect(await noteErrorLog('pscube.save', 'A'), isTrue);
    expect(lines().map((l) => l.split('\t').last), ['A', 'B', 'A']);
  });

  test('256KiBを超えたら1世代だけ残して新しく書き始める', () async {
    final file = File('${dir.path}/$errorLogName');
    await file.writeAsString('x' * (errorLogMaxBytes + 1));
    await File('${dir.path}/$errorLogName.1').writeAsString('もっと古い');
    expect(await noteErrorLog('pscube.save', '新しい行'), isTrue);
    expect(lines(), hasLength(1));
    expect(
      File('${dir.path}/$errorLogName.1').lengthSync(),
      errorLogMaxBytes + 1,
    );
  });

  test('書き先が無い・書けないときは、呼び出し元を止めずに false を返す', () async {
    errorLogDirectory = () async => null;
    expect(await noteErrorLog('pscube.save', 'A'), isFalse);
    errorLogDirectory = () async => throw const FileSystemException('書けない');
    expect(await noteErrorLog('pscube.save', 'B'), isFalse);
    errorLogDirectory = () async => dir;
    expect(await noteErrorLog('pscube.save', 'C'), isTrue, reason: '失敗の後も書ける');
  });
}
