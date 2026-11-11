import 'viewer_bridge.dart';

Future<String> loadDailyDocument() async {
  final url = loadRemoteUrl();
  if (url == null) throw StateError('Driveの読み込み先を設定してください');
  return fetchSharedEvents(url, 'daily-learning');
}

Future<void> saveDailyUrl(String value) async {
  final uri = Uri.tryParse(value);
  if (uri == null ||
      uri.scheme != 'https' ||
      uri.host != 'script.google.com' ||
      !uri.path.endsWith('/exec')) {
    throw const FormatException('閲覧用スクリプトのURLが必要です');
  }
  saveRemoteUrl(value);
}
