import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

Future<File> _setting() async => File(
  '${(await getApplicationSupportDirectory()).path}/daily-learning-url.txt',
);
Uri _url(String value) {
  final uri = Uri.tryParse(value);
  if (uri == null ||
      uri.scheme != 'https' ||
      uri.host != 'script.google.com' ||
      !uri.path.startsWith('/macros/s/') ||
      !uri.path.endsWith('/exec')) {
    throw const FormatException('閲覧用スクリプトのURLが必要です');
  }
  return uri;
}

Future<void> saveDailyUrl(String value) async {
  _url(value);
  final file = await _setting();
  final temporary = File('${file.path}.tmp');
  await temporary.writeAsString(value, flush: true);
  await temporary.rename(file.path);
}

Future<String> loadDailyDocument() async {
  final uri = _url((await (await _setting()).readAsString()).trim());
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 30);
  try {
    final request = await client.getUrl(
      uri.replace(queryParameters: {'file': 'daily-learning'}),
    );
    final response = await request.close().timeout(const Duration(seconds: 30));
    if (response.statusCode != 200) throw const HttpException('日次学習を読めません');
    final bytes = <int>[];
    await for (final chunk in response.timeout(const Duration(seconds: 30))) {
      bytes.addAll(chunk);
      if (bytes.length > 4 * 1024 * 1024) {
        throw const FormatException('日次学習が大きすぎます');
      }
    }
    return utf8.decode(bytes);
  } finally {
    client.close(force: true);
  }
}
