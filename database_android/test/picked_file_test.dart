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
}
