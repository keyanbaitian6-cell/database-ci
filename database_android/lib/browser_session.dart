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

/// Force a reload for an unchanged URL, retaining hash-based history dates.
Future<void> reopenBrowserPage({
  required Uri target,
  required Future<String?> Function() currentUrl,
  required Future<void> Function() reload,
  required Future<void> Function(Uri) load,
  required bool Function() active,
}) async {
  if (!active()) return;
  String? current;
  try {
    current = await currentUrl();
  } catch (_) {}
  if (!active()) return;
  final uri = Uri.tryParse(current ?? '');
  if (uri != null &&
      uri.replace(fragment: '') == target.replace(fragment: '')) {
    await reload();
  } else {
    await load(target);
  }
}
