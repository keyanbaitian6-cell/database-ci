import 'dart:js_interop';

@JS('databaseViewer.pick')
external JSPromise<JSString?> _pick();

@JS('databaseViewer.fromUrl')
external JSPromise<JSString?> _fromUrl(JSString url);

@JS('databaseViewer.save')
external JSPromise<JSAny?> _save(JSString text);

@JS('databaseViewer.load')
external JSPromise<JSString?> _load();

/// ファイルを選んで読んだ結果（軽くしたJSON）。選ばなければ null。
Future<String?> pickBackup() async => (await _pick().toDart)?.toDart;

/// 同じサイトの中のファイルを読む（手元での確認用）。
Future<String?> backupFromUrl(String url) async =>
    (await _fromUrl(url.toJS).toDart)?.toDart;

Future<void> saveViewerData(String text) async {
  await _save(text.toJS).toDart;
}

Future<String?> loadViewerData() async => (await _load().toDart)?.toDart;
