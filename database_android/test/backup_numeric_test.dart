import 'dart:convert';

import 'package:database_android/backup_service.dart';
import 'package:database_android/models.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> record() => {
  'store': 'nagamachiminami',
  'kind_code': 21,
  'day': '2026-10-01',
  'machine': '試験機種',
  'rack': 101,
  'games': 3000,
  'bb': 12,
  'rb': 6,
};

void main() {
  final service = BackupService();
  for (final field in ['games', 'bb', 'rb', 'rack']) {
    for (final value in [null, '3', true, -1, 1.5]) {
      test('$field=$value は0に変えたり切り捨てたりせず対象外にする', () {
        final raw = {...record(), field: value};
        final plan = service.plan([raw], []);
        expect(plan.skipped, 1);
        expect(plan.toSave, isEmpty);
        final viewer = ViewerData.parse(
          jsonEncode({
            'records': [raw],
          }),
        );
        expect(viewer.skipped, 1);
        expect(viewer.records, isEmpty);
      });
    }
  }
  for (final field in ['games', 'bb', 'rb']) {
    test('$field が無い台も対象外にする', () {
      final raw = record()..remove(field);
      expect(service.plan([raw], []).skipped, 1);
      expect(
        ViewerData.parse(
          jsonEncode({
            'records': [raw],
          }),
        ).skipped,
        1,
      );
    });
  }
  test('本物の0回転・当たり0回は読み込める', () {
    final raw = {...record(), 'games': 0, 'bb': 0, 'rb': 0};
    final plan = service.plan([raw], []);
    expect(plan.skipped, 0);
    expect(plan.added.single.games, 0);
    expect(plan.added.single.graphNotNeeded, isTrue);
    expect(
      ViewerData.parse(
        jsonEncode({
          'records': [raw],
        }),
      ).records,
      hasLength(1),
    );
  });
  test('小数表記でも整数の値ならPC・Androidで読み込める', () {
    final raw = {...record(), 'rack': 101.0, 'games': 3000.0};
    expect(service.plan([raw], []).added.single.rack, 101);
    expect(hasValidRecordNumbers(raw), isTrue);
  });
}
