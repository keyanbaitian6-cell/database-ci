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

@JS('databaseViewer.fetchShared')
external JSPromise<JSString> _fetchShared(JSString url, JSString file);

@JS('databaseViewer.postShared')
external JSPromise<JSString> _postShared(JSString url, JSString text);

@JS('databaseViewer.pscubeEvents')
external JSPromise<JSString> _pscubeEvents();

@JS('databaseViewer.mergePscubeShared')
external JSPromise<JSString?> _mergePscubeShared(JSString text);

/// 共有カレンダー（EVENT_CALENDAR.md）：共有ファイル（[file] は events・pscube-events）を読む。
Future<String> fetchSharedEvents(String url, String file) async =>
    (await _fetchShared(url.toJS, file.toJS).toDart).toDart;

/// イベントをスクリプトへ送り、返事の文字を返す。
Future<String> postSharedEvents(String url, String text) async =>
    (await _postShared(url.toJS, text.toJS).toDart).toDart;

/// P’s CUBEの端末のイベント（JSON）。
Future<String> pscubeTimedEvents() async =>
    (await _pscubeEvents().toDart).toDart;

/// P’s CUBEの共有ファイルを端末に足す。変わらなければ null。
Future<String?> mergePscubeSharedEvents(String text) async =>
    (await _mergePscubeShared(text.toJS).toDart)?.toDart;

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
