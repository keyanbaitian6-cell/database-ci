import 'package:database_android/csv_export_service.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('CSVは日付と台番号を含む共有用の9項目を出力する', () {
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
      '日付',
      '機種名',
      '台番号',
      '採点結果',
      'G数',
      '最大持ち球',
      'B',
      'R',
      '設定情報',
    ]);
    expect(lines, hasLength(2));
    expect(lines[1], hasLength(9));
    expect(lines[1][0], '2026-09-22');
    expect(lines[1][1], 'テスト機種');
    expect(lines[1][2], '1217');
    expect(lines[1][3], matches(RegExp(r'^\d+\.\d点$')), reason: '「暫定」「参考」は付けない');
    expect(lines[1].sublist(4), ['2408', '2111', '11', '6', '5以上']);
  });
}
