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

Future<String?> setPscubeMachineType(
  String scope,
  String machine,
  String? type,
) async => null;

Future<String?> setPscubeSuffixEvent(
  String scope,
  String day,
  bool enabled,
) async => null;
