import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';

const _channel = MethodChannel('database/backup_destination');

/// Androidでは保存先を選んで書き込み、成功した場所を次回の初期表示に使う。
/// キャンセルと書き込み失敗を成功扱いしない。Driveへのアップロード完了は
/// この結果だけでは分からないため、全期間バックアップの確認は呼び出し元で行う。
Future<bool> saveBackup(File file) async {
  if (defaultTargetPlatform == TargetPlatform.android) {
    final saved = await _channel.invokeMethod<bool>('save', {
      'path': file.path,
    });
    if (saved == null) {
      throw PlatformException(code: 'backup_save_no_result');
    }
    return saved;
  }
  // Android以外では従来の共有を維持。タイトルを実ファイル名と揃える。
  final name = file.uri.pathSegments.last;
  final result = await SharePlus.instance.share(
    ShareParams(
      title: name,
      subject: name,
      text: 'Google Driveの「database共有」に保存するバックアップです。',
      files: [XFile(file.path, mimeType: 'application/json')],
    ),
  );
  return result.status != ShareResultStatus.dismissed;
}
