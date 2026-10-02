/// Every first load/retry waits for settings, including third-party Cookies.
/// The callbacks also make order/failure/disposal behavior testable without a
/// live site's authentication or requests.
Future<void> prepareBrowserSession({
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
