import 'package:database_android/csv_export_service.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('CSVは共有用の7項目だけを出力する', () {
    final lines = CsvExportService.buildLines([
      const SlotRecord(
        store: 'saiwaichou',
        day: '2026-09-22',
        machine: 'テスト機種',
        rack: 1217,
        games: 2408,
        bb: 11,
        rb: 6,
        maxHold: 2111,
        confirmedSetting: '5以上',
      ),
    ]);

    expect(lines.first, [
      '機種名',
      '採点結果',
      'G数',
      '最大持ち球',
      'B',
      'R',
      '設定情報',
    ]);
    expect(lines, hasLength(2));
    expect(lines[1], hasLength(7));
    expect(lines[1][0], 'テスト機種');
    expect(lines[1][1], startsWith('暫定 '));
    expect(lines[1].sublist(2), ['2408', '2111', '11', '6', '5以上']);
  });
}
