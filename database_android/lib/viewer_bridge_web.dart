import 'dart:js_interop';

@JS('databaseViewer.pick')
external JSPromise<JSString?> _pick();

@JS('databaseViewer.fromUrl')
external JSPromise<JSString?> _fromUrl(JSString url);

@JS('databaseViewer.fromRemote')
external JSPromise<JSString?> _fromRemote(JSString url, JSString? known);

@JS('databaseViewer.getRemote')
external JSString? _getRemote();

@JS('databaseViewer.setRemote')
external void _setRemote(JSString? url);

@JS('databaseViewer.save')
external JSPromise<JSAny?> _save(JSString text);

@JS('databaseViewer.load')
external JSPromise<JSString?> _load();

@JS('databaseViewer.exportBackup')
external JSPromise<JSAny?> _exportBackup();

@JS('databaseViewer.setPscubeType')
external JSPromise<JSString?> _setPscubeType(
  JSString scope,
  JSString machine,
  JSString? type,
);

/// ファイルを選んで読んだ結果（軽くしたJSON）。選ばなければ null。
Future<String?> pickBackup() async => (await _pick().toDart)?.toDart;

/// 同じサイトの中のファイルを読む（手元での確認用）。
Future<String?> backupFromUrl(String url) async =>
    (await _fromUrl(url.toJS).toDart)?.toDart;

Future<void> saveViewerData(String text) async {
  await _save(text.toJS).toDart;
}

Future<String?> loadViewerData() async => (await _load().toDart)?.toDart;

/// Googleのスクリプト（…/exec）から、Driveの最新を読む。ファイルの書き出し
/// 時刻が [unlessExportedAt]（表示中の内容の時刻）と同じなら、先頭の1行だけで
/// 読むのをやめて null を返す（中身が同じなので読み直さない）。
Future<String?> backupFromRemote(
  String url, {
  String? unlessExportedAt,
}) async =>
    (await _fromRemote(url.toJS, unlessExportedAt?.toJS).toDart)?.toDart;

/// 自動読み込みに使うスクリプトのURL（この端末に覚える）。
String? loadRemoteUrl() => _getRemote()?.toDart;

void saveRemoteUrl(String? url) => _setRemote(url?.toJS);

Future<void> exportPscubeBackup() async => await _exportBackup().toDart;

@JS('databaseViewer.download')
external void _download(JSString name, JSString text);

/// [text] を [name] のファイルとして保存する（iPhoneでは「ファイル」に保存できる）。
void downloadText(String name, String text) => _download(name.toJS, text.toJS);

Future<String?> setPscubeMachineType(
  String scope,
  String machine,
  String? type,
) async =>
    (await _setPscubeType(scope.toJS, machine.toJS, type?.toJS).toDart)?.toDart;

@JS('databaseViewer.setDateEvent')
external JSPromise<JSString?> _setDateEvent(
  JSString scope,
  JSString day,
  JSString? name,
);

/// P’s CUBEの日付のイベント名を閲覧ページの端末に保存する（null・空はイベントなし）。
Future<String?> setPscubeDateEvent(
  String scope,
  String day,
  String? name,
) async =>
    (await _setDateEvent(scope.toJS, day.toJS, name?.toJS).toDart)?.toDart;
