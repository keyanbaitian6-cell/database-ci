import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/backup_service.dart';

Map<String, Object> sample({int games = 3000}) => {
  'store': 'saiwaichou',
  'kind_code': 21,
  'day': '2026-09-22',
  'machine': 'テスト',
  'rack': 703,
  'games': games,
  'bb': 20,
  'rb': 5,
};

void main() {
  test('実在しない日付や日時形式のバックアップは保存対象にしない', () {
    for (final day in ['2026-02-30', '2026-13-01', '2026-09-22T12:00:00']) {
      final plan = BackupService().plan([
        {...sample(), 'day': day},
      ], []);
      expect(plan.toSave, isEmpty, reason: day);
      expect(plan.skipped, 1);
    }
    expect(
      BackupService().plan([
        {...sample(), 'day': '2024-02-29'},
      ], []).toSave,
      hasLength(1),
    );
  });
  test('バックアップ内の異なる重複は保存前に拒否する', () {
    expect(
      () => BackupService().plan([sample(), sample(games: 4000)], []),
      throwsA(
        isA<FormatException>().having(
          (e) => e.message,
          'message',
          contains('重複'),
        ),
      ),
    );
  });
  test('バックアップ内の同じ重複は1件として扱う', () {
    expect(BackupService().plan([sample(), sample()], []).toSave, hasLength(1));
  });
}
