import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';

import 'error_log.dart';
import 'home_widget.dart';

/// 自動取り込みの結果（完了・止まった理由）をスマホの通知で知らせる（2026-11-04、利用者が選んだ
/// 「朝の取り込み結果通知」。P’s CUBE・メルヘンの両方）。画面を見に行かなくても、朝の時点で成否が分かる。
///
/// 通知は常駐の通知とは別で、最新の結果だけが残る（同じ番号で出す。MainActivity `postResultNotice`）。
/// 出した内容は記録のファイル（`errors.log` の `notice`）にも残す。通知の失敗では取り込みを止めない。
const _channel = MethodChannel('database/auto_capture');

/// 通知を出す処理（試験で差し替える）。
Future<void> Function(String title, String text) captureNoticeSender = _send;

/// 通知の許可を聞く処理（試験で差し替える）。
Future<void> Function() captureNoticePermission = _requestPermission;

Future<void> _send(String title, String text) async {
  if (!Platform.isAndroid) return;
  noteCaptureNoticeShown(
    await _channel.invokeMethod<bool>('notify', {'title': title, 'text': text}),
    title,
  );
}

/// 通知を出せなかった（通知の許可が無い。MainActivity `postResultNotice` が false を返す）ことを残す
/// （2026-11-05）。`notice` の行だけでは、通知が実際に出たように読めるため。
void noteCaptureNoticeShown(bool? shown, String title) {
  if (shown == false) {
    unawaited(noteErrorLog('notice.blocked', '通知の許可が無いため出せませんでした：$title'));
  }
}

Future<void> _requestPermission() async {
  if (!Platform.isAndroid) return;
  await _channel.invokeMethod<void>('requestNotices');
}

/// 取り込みの結果を通知する。
Future<void> notifyCaptureResult(String title, String text) async {
  unawaited(noteErrorLog('notice', '$title：$text'));
  // ホーム画面のウィジェットにも、同じ文を「前回の取り込みの結果」として出す。
  unawaited(updateHomeWidgetStatus(title, text));
  try {
    await captureNoticeSender(title, text);
  } catch (error) {
    unawaited(noteErrorLog('notice.failed', error));
  }
}

/// 通知の許可を聞く（Android 13以降、まだ許可が無いときだけ端末が尋ねる）。利用者が自動取り込み・0時の予約を
/// ONにしたときだけ呼ぶ（0時に始めるときに聞くと、確認の画面で取り込みが止まるおそれがある）。
Future<void> requestCaptureNotices() async {
  try {
    await captureNoticePermission();
  } catch (_) {
    // 許可を聞けなくても取り込みは続ける（通知が出ないだけ）。
  }
}
