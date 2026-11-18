/// Web以外で使う、何もしない版（テスト用）。
Future<String?> pickBackup() async => null;

String? pickedBackupEvents() => null;

Future<String?> backupFromUrl(String url) async => null;

Future<void> saveViewerData(String text, {bool meruhen = false}) async {}

Future<String?> loadViewerData() async => null;

Future<String?> loadViewerSummary() async => null;

Future<String?> loadRainbowMarks() async => null;

Future<void> saveRainbowMarks(String text) async {}

Future<List<String>> viewerStorageLines() async => const [];

Future<void> markViewerPhase(String name, {required bool done}) async {}

Future<String?> autoUpdateHeldUntil() async => null;

Future<String?> checkViewerDayCache() async => null;

Future<String?> checkViewerCalendar({
  required void Function(String rowsJson) onDay,
  required String Function() finish,
}) async => null;

Future<String?> checkViewerScores({
  required void Function(String rowsJson) onDay,
  required String Function() finish,
  String? from,
}) async => null;

Future<String?> backupFromRemote(
  String url, {
  String? unlessExportedAt,
}) async => null;

String? loadRemoteUrl() => null;

void saveRemoteUrl(String? url) {}

Future<void> exportPscubeBackup() async {}

void downloadText(String name, String text) {}

Future<String> fetchViewerCurves(String url, String refs) async =>
    throw UnsupportedError('グラフの線はWeb版だけで読みます。');

Future<String> fetchSharedEvents(String url, String file) async => '';

Future<String> postSharedEvents(String url, String text) async => '';

Future<String> pscubeTimedEvents() async => '[]';

Future<String?> mergePscubeSharedEvents(String text) async => null;

Future<String?> setPscubeMachineType(
  String scope,
  String machine,
  String? type,
) async => null;

Future<String?> setPscubeDateEvent(
  String scope,
  String day,
  String? name,
) async => null;

Future<String?> setPscubeDateEventDays(
  String scope,
  List<String> days,
  String? name,
) async => null;

/// 画面の選択（例：回っていない台の期間）。テストでは覚えるだけ。
final _settings = <String, String>{};

String? loadViewerSetting(String key) => _settings[key];

void saveViewerSetting(String key, String value) => _settings[key] = value;

/// 別のタブでサイトのページを開く（Web以外・テストでは開かない）。
bool openExternalUrl(String url) => false;
