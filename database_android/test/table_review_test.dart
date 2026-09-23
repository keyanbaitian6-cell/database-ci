import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/import_service.dart';
import 'package:database_android/web_import_page.dart';

WebTableExtraction extraction({
  String? store = 'saiwaichou',
  String? day = '2026-09-20',
  String? machine = 'Lテスト機',
}) => WebTableExtraction(
  sourceUrl: 'https://meruhenworld.pt.teramoba2.com/saiwaichou/rack_info',
  store: store,
  day: day,
  machine: machine,
  expectedCount: 1,
  rows: [EditableRow(rack: 701, games: 3000, bb: 10, rb: 5)],
);

void main() {
  test('店舗・日付・機種名がそろった表だけ、確認画面なしで保存できる', () {
    expect(canSaveWithoutReview(extraction()), isTrue);
  });

  test('ひとつでも欠けたら確認画面へ回す（今日の日付や空の機種名で保存しない）', () {
    expect(canSaveWithoutReview(extraction(store: null)), isFalse);
    expect(canSaveWithoutReview(extraction(day: null)), isFalse);
    expect(canSaveWithoutReview(extraction(machine: null)), isFalse);
    expect(canSaveWithoutReview(extraction(machine: '')), isFalse);
    expect(canSaveWithoutReview(extraction(machine: '   ')), isFalse);
  });
}
