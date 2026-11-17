import 'dart:convert';
import 'dart:js_interop';
import 'dart:js_interop_unsafe';

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
external JSPromise<JSAny?> _save(JSString text, JSBoolean meruhen);

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

@JS('databaseViewer.pickedEvents')
external JSString? _pickedEvents();

/// 手動読み込み直前の、端末に保存済みのイベントだけ。
String? pickedBackupEvents() => _pickedEvents()?.toDart;

/// 同じサイトの中のファイルを読む（手元での確認用）。
Future<String?> backupFromUrl(String url) async =>
    (await _fromUrl(url.toJS).toDart)?.toDart;

Future<void> saveViewerData(String text, {bool meruhen = false}) async {
  await _save(text.toJS, meruhen.toJS).toDart;
}

Future<String?> loadViewerData() async => (await _load().toDart)?.toDart;

@JS('databaseViewer.loadMarks')
external JSPromise<JSString?> _loadMarks();

@JS('databaseViewer.saveMarks')
external JSPromise<JSAny?> _saveMarks(JSString text);

@JS('databaseViewer.storageReport')
external JSPromise<JSString?> _storageReport();

@JS('databaseViewer.phase')
external JSPromise<JSAny?> _phase(JSString name, JSBoolean done);

/// この端末の保存の診断（web/storage_report.mjs、2026-10-31）。保存した内容は読み直さない。
/// 調べられなければ、その理由の1行。
Future<List<String>> viewerStorageLines() async {
  try {
    final text = (await _storageReport().toDart)?.toDart;
    return text == null
        ? const []
        : (jsonDecode(text) as List).map((e) => '$e').toList();
  } on Object catch (error) {
    return ['この端末の保存（診断）：確認できませんでした（$error）'];
  }
}

/// 重い読み込み（[name]：open・drive）の始まりと終わり。途中でページが終わったら次に開いたときに
/// 数える。記録できなくても読み込みは続ける。
Future<void> markViewerPhase(String name, {required bool done}) async {
  try {
    await _phase(name.toJS, done.toJS).toDart;
  } on Object {
    // 診断の記録だけなので、読み込みは止めない。
  }
}

@JS('databaseViewer.autoUpdateHold')
external JSPromise<JSString?> _autoUpdateHold();

/// 前回のGoogleドライブの更新が途中で終わっていたら、起動時の自動更新を止めている期限（ISO）。
/// 止めていない・調べられないときは null（その場合は今までどおり自動で更新する）。
Future<String?> autoUpdateHeldUntil() async {
  try {
    return (await _autoUpdateHold().toDart)?.toDart;
  } on Object {
    return null;
  }
}

/// 本体と別に置いた🌈の印（JSONの配列）。無ければ null。
Future<String?> loadRainbowMarks() async => (await _loadMarks().toDart)?.toDart;

Future<void> saveRainbowMarks(String text) async {
  await _saveMarks(text.toJS).toDart;
}

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

@JS('databaseViewer.curves')
external JSPromise<JSString> _curves(JSString url, JSString refs);

/// 1日分のグラフの線（[通し番号, 線] の一覧のJSON）を、Googleのスクリプトから読む。
Future<String> fetchViewerCurves(String url, String refs) async =>
    (await _curves(url.toJS, refs.toJS).toDart).toDart;

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

@JS('databaseViewer.setDateEventDays')
external JSPromise<JSString?> _setDateEventDays(
  JSString scope,
  JSArray<JSString> days,
  JSString? name,
);

/// P’s CUBEのイベントカレンダー：先の日・期間にも同じ名前を付ける（null・空はイベントなし）。
Future<String?> setPscubeDateEventDays(
  String scope,
  List<String> days,
  String? name,
) async => (await _setDateEventDays(
  scope.toJS,
  [for (final d in days) d.toJS].toJS,
  name?.toJS,
).toDart)?.toDart;

// 画面の選択（例：回っていない台の期間・ゲーム数）を端末に覚える。メルヘン・P’s CUBEの
// どちらのページでも使えるよう、橋渡し（databaseViewer）を通さず localStorage を直接使う。
// 覚えられない（プライベートブラウズなど）ときは、覚えずに既定の値で動く。
@JS('localStorage.getItem')
external JSString? _settingGet(JSString key);

@JS('localStorage.setItem')
external void _settingSet(JSString key, JSString value);

String? loadViewerSetting(String key) {
  try {
    return _settingGet(key.toJS)?.toDart;
  } catch (_) {
    return null;
  }
}

void saveViewerSetting(String key, String value) {
  try {
    _settingSet(key.toJS, value.toJS);
  } catch (_) {}
}

@JS('window.open')
external JSObject? _windowOpen(JSString url, JSString target);

/// 別のタブでサイトのページを開く（狙い台一覧の台番号、2026-11-17）。開いたタブから閲覧ページを
/// 操作されないよう opener を外す（noopener を指定すると開けたかどうかが分からなくなるため、開いたあとで外す）。
/// 開けなかった（ポップアップを止められた）ら false。
bool openExternalUrl(String url) {
  try {
    final opened = _windowOpen(url.toJS, '_blank'.toJS);
    if (opened == null) return false;
    try {
      opened.setProperty('opener'.toJS, null);
    } catch (_) {}
    return true;
  } catch (_) {
    return false;
  }
}
