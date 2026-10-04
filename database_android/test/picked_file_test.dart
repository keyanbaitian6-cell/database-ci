import 'dart:io';

import 'package:database_android/picked_file.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('file_pickerの写しだけを消し、元のファイルには触れない', () async {
    final root = await Directory.systemTemp.createTemp('picked-');
    addTearDown(() => root.delete(recursive: true));
    final stamp = await Directory('${root.path}/file_picker/1790000000000')
        .create(recursive: true);
    final copy = await File('${stamp.path}/database-backup-auto.json')
        .writeAsString('{}');
    final original = await File('${root.path}/database-backup-auto.json')
        .writeAsString('{}');

    await discardPickedCopy(original.path);
    expect(await original.exists(), isTrue, reason: '写しでないファイルは消さない');

    await discardPickedCopy(copy.path);
    expect(await copy.exists(), isFalse);
    expect(await stamp.exists(), isFalse, reason: '空になった時刻のフォルダも消す');
    expect(await Directory('${root.path}/file_picker').exists(), isTrue);

    await discardPickedCopy(null);
    await discardPickedCopy('${root.path}/file_picker/0/missing.json');
  });

  test('同じ時刻のフォルダにほかのファイルがあれば、フォルダは残す', () async {
    final root = await Directory.systemTemp.createTemp('picked-');
    addTearDown(() => root.delete(recursive: true));
    final stamp = await Directory('${root.path}/file_picker/1')
        .create(recursive: true);
    final a = await File('${stamp.path}/a.json').writeAsString('{}');
    final b = await File('${stamp.path}/b.json').writeAsString('{}');
    await discardPickedCopy(a.path);
    expect(await a.exists(), isFalse);
    expect(await b.exists(), isTrue);
    expect(await stamp.exists(), isTrue);
  });

  test('以前の版が残した一時ファイルだけを、日数に関係なく片付けの対象にする', () {
    for (final name in [
      'backup_2026-09-23T005639345106.json',
      'backup_2026-09-21T132840439828.json',
      'database-import-1789512998536.jpg',
    ]) {
      expect(isOldVersionLeftover(name), isTrue, reason: name);
    }
    for (final name in [
      'database-backup-android-20261004-102306.json',
      'backup.json',
      'my-backup_2026-09-23T005639345106.json',
      'database-import-abc.jpg',
      'pscube-viewer.json',
    ]) {
      expect(isOldVersionLeftover(name), isFalse, reason: name);
    }
    expect(
      isSharedTemporaryFile('database-backup-android-20261004-102306.json'),
      isTrue,
    );
    expect(isSharedTemporaryFile('database-web-graph-1.png'), isTrue);
    expect(isSharedTemporaryFile('database-2026-10-04.csv'), isTrue);
    expect(
      isSharedTemporaryFile('backup_2026-09-23T005639345106.json'),
      isFalse,
    );
  });
}
