/// Connection state is separate from authentication and the saved slot records.
/// A WebView load completion does not mean that its HTTP request succeeded.
class PscubeConnection {
  static const host = 'www.pscube.jp';
  static const shopPath = '/dedamajyoho-P-townDMMpachi/c740601/';
  static const pageNames = {
    'nc-v03-001.php',
    'nc-v05-011.php',
    'nc-v06-001.php',
  };

  Uri? page;
  bool loading = true;
  PscubeConnectionError? failure;
  final List<PscubeConnectionError> _history = [];

  List<PscubeConnectionError> get history => List.unmodifiable(_history);
  bool get canCapture => !loading && failure == null;

  static bool allowedPage(Uri uri) =>
      uri.scheme == 'https' &&
      uri.host == host &&
      uri.userInfo.isEmpty &&
      !uri.hasPort &&
      (uri.path == shopPath ||
          pageNames.any((name) => uri.path == '${shopPath}cgi-bin/$name'));

  static bool sameRequest(Uri a, Uri b) =>
      a.replace(fragment: '') == b.replace(fragment: '');

  void start(String url) {
    page = Uri.tryParse(url);
    loading = true;
    failure = null;
  }

  bool finish(String url) {
    final uri = Uri.tryParse(url);
    if (page == null || uri == null || !sameRequest(page!, uri)) return false;
    loading = false;
    // Retain an HTTP/network failure even if WebView then emits onPageFinished.
    return true;
  }

  bool networkError({
    required String? url,
    required bool mainFrame,
    required int code,
    required String description,
  }) {
    final target = page;
    final uri = Uri.tryParse(url ?? '');
    // A missing URL cannot be attributed to the current document safely.
    if (!mainFrame ||
        target == null ||
        uri == null ||
        !sameRequest(target, uri)) {
      return false;
    }
    final dns = code == -2 || description.contains('ERR_NAME_NOT_RESOLVED');
    _record(
      PscubeConnectionError(
        url: uri,
        code: code,
        http: false,
        message: dns
            ? '接続先の名前を確認できませんでした（DNSエラー）。'
                  'Cookieを消さずに「もう一度開く」を試してください。'
                  'Chromeだけ開ける場合はDNS・VPN・広告ブロックの設定を確認してください。'
            : 'ページの通信に失敗しました（エラー $code）。'
                  'Cookieを消さずに「もう一度開く」を試してください。',
      ),
    );
    return true;
  }

  bool httpError({required String? url, required int? status}) {
    final target = page;
    final uri = Uri.tryParse(url ?? '');
    if (target == null ||
        uri == null ||
        status == null ||
        status < 400 ||
        !allowedPage(target) ||
        !allowedPage(uri) ||
        uri.path != target.path) {
      return false;
    }
    // A data request may add action parameters to the same PHP endpoint. Keep
    // the page's identifying parameters, so a late error for another rack or
    // machine cannot stop the current document. Unknown endpoints are not
    // assumed to be slot data (ads/captcha can also return 403).
    for (final key in ['cd_ps', 'cd_dai', 'bai', 'nmk_kisyu']) {
      if (target.queryParameters[key] != uri.queryParameters[key]) return false;
    }
    _record(
      PscubeConnectionError(
        url: uri,
        code: status,
        http: true,
        message: status == 403
            ? 'サイトがページ・データへのアクセスを拒否しました（HTTP 403）。'
                  '自動取り込みを止めました。Cookie削除で直るとは限りません。'
                  '時間を空けてから手動で「もう一度開く」を試してください。'
            : 'ページ・データを読み込めませんでした（HTTP $status）。'
                  '自動取り込みを止めました。手動で「もう一度開く」を試してください。',
      ),
    );
    return true;
  }

  void _record(PscubeConnectionError error) {
    failure = error;
    loading = false;
    _history.add(error);
    if (_history.length > 8) _history.removeAt(0);
  }
}

class PscubeConnectionError {
  PscubeConnectionError({
    required this.url,
    required this.code,
    required this.http,
    required this.message,
  }) : time = DateTime.now();

  final Uri url;
  final int code;
  final bool http;
  final String message;
  final DateTime time;

  // Do not expose Cookie, tokens, query parameters or page contents in reports.
  String get report =>
      '${time.toIso8601String()} ${http ? 'HTTP' : '通信'} $code\n'
      '${url.scheme}://${url.host}${url.path}';
}

/// Every first load/retry waits for settings, including third-party Cookies.
/// The callbacks also make order/failure/disposal behavior testable without a
/// live site's authentication or requests.
Future<void> preparePscubeBrowser({
  required Future<void> Function() configureJavaScript,
  required Future<void> Function() configureNavigation,
  required Future<void> Function() configureCookies,
  required Future<void> Function() load,
  required bool Function() active,
}) async {
  for (final step in [
    configureJavaScript,
    configureNavigation,
    configureCookies,
    load,
  ]) {
    if (!active()) return;
    await step();
  }
}
