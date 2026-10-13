import 'dart:io';

import 'package:database_android/backup_destination.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('database/backup_destination');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  tearDown(() => messenger.setMockMethodCallHandler(channel, null));

  for (final name in [
    'database-backup-android-20261014-120000.json',
    'pscube-backup-android-20261014-120000.json',
  ]) {
    test('$name は名前を維持し、ファイルの内容をメモリへ読み込まず保存する', () async {
      final file = File('${Directory.systemTemp.path}/$name');
      // 実ファイルなしでもchannelへパスだけ渡せる。大容量のbytes送信を防ぐ。
      messenger.setMockMethodCallHandler(channel, (call) async {
        expect(call.method, 'save');
        expect(call.arguments, {'path': file.path});
        return true;
      });
      expect(await saveBackup(file), isTrue);
    });
  }

  test('キャンセルは保存成功にしない', () async {
    messenger.setMockMethodCallHandler(channel, (_) async => false);
    expect(await saveBackup(File('backup.json')), isFalse);
  });

  test('書き込み失敗を成功や別の共有へ変換しない', () async {
    messenger.setMockMethodCallHandler(channel, (_) async {
      throw PlatformException(code: 'backup_save_write', message: '容量不足');
    });
    await expectLater(
      saveBackup(File('backup.json')),
      throwsA(
        isA<PlatformException>().having(
          (e) => e.code,
          'code',
          'backup_save_write',
        ),
      ),
    );
  });

  test('保存結果がない場合もバックアップ済みにしない', () async {
    messenger.setMockMethodCallHandler(channel, (_) async => null);
    await expectLater(
      saveBackup(File('backup.json')),
      throwsA(
        isA<PlatformException>().having(
          (e) => e.code,
          'code',
          'backup_save_no_result',
        ),
      ),
    );
  });
}
