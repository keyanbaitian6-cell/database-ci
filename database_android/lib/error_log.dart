import 'dart:async';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'models.dart';

/// 続行のために捕まえた失敗を、後から調べられるように記録する（2026-11-04、PC版 `error_log.py` と同じ形）。
///
/// 0時の自動取り込みが機種一覧で3回止まったとき、画面の知らせしか手がかりが無く、その知らせも次の確認で
/// 上書きされて原因を追えなかった（利用者「次のビルドでそれをいれよう」）。
///
/// - 書き先はアプリ専用の外部フォルダーの `errors.log`（`/sdcard/Android/data/<アプリID>/files/errors.log`、
///   PCから `adb pull` で読める）。バックアップ・同期の対象外。
/// - 1行はタブ区切りで「時刻・場所・内容」。同じ場所・同じ内容は60秒に1回だけ書く。256KiBを超えたら
///   `errors.log.1` へ1世代だけ残す。
/// - 記録そのものの失敗では呼び出し元を止めない。Cookie・入力値は書かない（画面に出した文と件数だけ）。
const errorLogName = 'errors.log';
const errorLogMaxBytes = 256 * 1024;
const errorLogRepeat = Duration(seconds: 60);
const _messageLimit = 500;

/// 書き先のフォルダー（試験で差し替える）。null なら書かない。
Future<Directory?> Function() errorLogDirectory = _defaultDirectory;

/// 今の時刻（試験で差し替える）。
DateTime Function() errorLogNow = DateTime.now;

/// 書く前に1行を受け取る（試験用。ファイルに書けない画面の試験で、何を残したかを確かめる）。
void Function(String where, String text)? errorLogObserver;

final _last = <String, DateTime>{};
Future<void> _queue = Future<void>.value();

Future<Directory?> _defaultDirectory() async {
  try {
    return await getExternalStorageDirectory();
  } catch (_) {
    return null;
  }
}

/// 画面に出した失敗の文や、調べるのに要る件数などを1行足す。書いたら true（間引き・失敗は false）。
Future<bool> noteErrorLog(String where, Object message) {
  final text = '$message'
      .split(RegExp(r'\s+'))
      .where((s) => s.isNotEmpty)
      .join(' ');
  final clipped = text.length > _messageLimit
      ? text.substring(0, _messageLimit)
      : text;
  final now = errorLogNow();
  final key = '$where\t$clipped';
  final previous = _last[key];
  if (previous != null && now.difference(previous) < errorLogRepeat) {
    return Future.value(false);
  }
  _last[key] = now;
  errorLogObserver?.call(where, clipped);
  final done = Completer<bool>();
  _queue = _queue.then((_) async {
    try {
      final folder = await errorLogDirectory();
      if (folder == null) return done.complete(false);
      await folder.create(recursive: true);
      final file = File('${folder.path}/$errorLogName');
      if (await file.exists() && await file.length() > errorLogMaxBytes) {
        await file.rename('${folder.path}/$errorLogName.1');
      }
      await file.writeAsString(
        '${timestampWithOffset(now)}\t$where\t$clipped\n',
        mode: FileMode.append,
        flush: true,
      );
      done.complete(true);
    } catch (_) {
      done.complete(false); // 記録の失敗で取り込みを止めない
    }
  });
  return done.future;
}

/// 試験用：間引きの記憶を消す。
void forgetErrorLog() => _last.clear();
