import 'package:flutter/material.dart';

import 'capture_health.dart';
import 'release_info.dart';
import 'models.dart';

Map<String, dynamic> healthRecord(SlotRecord r) => {
  ...r.extra,
  'store': r.store,
  'day': r.day,
  'machine': r.machine,
  'rack': r.rack,
};

Future<void> showCaptureHealth(
  BuildContext context, {
  required List<Map<String, dynamic>> records,
  dynamic syncStatus,
  String? exportedAt,
  String? loadedAt,
  String? checkedAt,
  String? store,
  String? day,
  bool pscube = false,
  // 閲覧ページだけ：この端末の保存の診断（viewer_main.dart）。Androidアプリでは空。
  List<String> deviceLines = const [],
}) async {
  final scope = records
      .where(
        (r) =>
            (store == null || r['store'] == store) &&
            (day == null || r['day'] == day),
      )
      .toList();
  final stores = <String, String>{};
  for (final r in records) {
    final key =
            '${RegExp(r'^c\d+$').hasMatch('${r['store']}') ? 'P’s CUBE' : storeDisplayName('${r['store']}')}${r['rate'] == null ? '' : '・${r['rate']}スロ'}',
        d = '${r['day']}';
    if (!stores.containsKey(key) || d.compareTo(stores[key]!) > 0) {
      stores[key] = d;
    }
  }
  final lines = [
    'このアプリ・閲覧ページの版：$applicationRelease',
    ...updateStatusLines(
      syncStatus,
      exportedAt: exportedAt,
      loadedAt: loadedAt,
      checkedAt: checkedAt,
    ),
    '端末内の最新営業日：',
    for (final s in stores.entries) '${s.key}：${s.value}',
    if (day != null) '確認する営業日：$day',
    if (pscube) ...netStatusLines(scope),
    ...deviceLines,
    'PC・Androidで書き出しただけでは、Driveへのアップロードや他の端末での読み込みは確認できません。',
  ];
  await showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('更新・差枚の取得状況'),
      content: SizedBox(
        width: 560,
        child: SingleChildScrollView(child: Text(lines.join('\n\n'))),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('閉じる'),
        ),
      ],
    ),
  );
}
