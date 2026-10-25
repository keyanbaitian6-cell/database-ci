import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

const _channel = MethodChannel('database/web_requests');

/// 取り込み画面の内部ブラウザで、通信そのものを起こさない YouTube の宛先。
/// PC（database/pscube_connection.py の _YOUTUBE_HOSTS）と同じホスト名。
/// 動画（youtube.com・youtube-nocookie.com・youtu.be）、サムネイル（ytimg.com）、
/// 再生の通信（googlevideo.com）。
const youTubeRequestHosts = [
  'youtube.com',
  'youtube-nocookie.com',
  'youtu.be',
  'ytimg.com',
  'googlevideo.com',
];

/// YouTube の宛先か。ホスト名だけで判定する（パスに youtube を含む別サイトは対象外）。
/// 端末側（YouTubeRequestBlocker.kt）も同じ規則で判定する。
bool isYouTubeRequestUrl(String? url) {
  final host = (Uri.tryParse(url ?? '')?.host ?? '').toLowerCase();
  return host.isNotEmpty &&
      youTubeRequestHosts.any(
        (name) => host == name || host.endsWith('.$name'),
      );
}

/// 内部ブラウザから YouTube への要求を、端末の中で空の応答（204）にして外へ出さない。
///
/// webview_flutter には要求を断る機能が無いため、端末側で WebView の WebViewClient を
/// 包み、shouldInterceptRequest で止める（他のコールバックは元のまま渡す）。
/// [WebViewController.setNavigationDelegate] は WebViewClient を置き換えるので、
/// その後に毎回呼ぶ。止められなかった（古い Android など）ときは false で、
/// 取り込みは止めない（メルヘンでは枠をこれまでどおり JS で隠す）。
Future<bool> blockYouTubeRequests(WebViewController web) async {
  final platform = web.platform;
  if (defaultTargetPlatform != TargetPlatform.android ||
      platform is! AndroidWebViewController) {
    return false;
  }
  return blockYouTubeRequestsFor(platform.webViewIdentifier);
}

@visibleForTesting
Future<bool> blockYouTubeRequestsFor(int webViewIdentifier) async {
  try {
    return await _channel.invokeMethod<bool>('blockYouTube', {
          'webView': webViewIdentifier,
          'hosts': youTubeRequestHosts,
        }) ??
        false;
  } on PlatformException {
    return false;
  } on MissingPluginException {
    return false;
  }
}
