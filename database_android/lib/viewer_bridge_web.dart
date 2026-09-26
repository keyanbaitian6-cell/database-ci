import 'dart:js_interop';

@JS('databaseViewer.pick')
external JSPromise<JSString?> _pick();

@JS('databaseViewer.fromUrl')
external JSPromise<JSString?> _fromUrl(JSString url);

@JS('databaseViewer.fromRemote')
external JSPromise<JSString?> _fromRemote(JSString url);

@JS('databaseViewer.getRemote')
external JSString? _getRemote();

@JS('databaseViewer.setRemote')
external void _setRemote(JSString? url);

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

/// Googleのスクリプト（…/exec）から、Driveの最新を読む。
Future<String?> backupFromRemote(String url) async =>
    (await _fromRemote(url.toJS).toDart)?.toDart;

/// 自動読み込みに使うスクリプトのURL（この端末に覚える）。
String? loadRemoteUrl() => _getRemote()?.toDart;

void saveRemoteUrl(String? url) => _setRemote(url?.toJS);
