/// Web以外で使う、何もしない版（テスト用）。
Future<String?> pickBackup() async => null;

Future<String?> backupFromUrl(String url) async => null;

Future<void> saveViewerData(String text) async {}

Future<String?> loadViewerData() async => null;

Future<String?> backupFromRemote(
  String url, {
  String? unlessExportedAt,
}) async => null;

String? loadRemoteUrl() => null;

void saveRemoteUrl(String? url) {}

Future<void> exportPscubeBackup() async {}

void downloadText(String name, String text) {}

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
