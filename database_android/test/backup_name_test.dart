import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/backup_service.dart';

void main() {
  test('共有フォルダに置く名前は、どの機械のいつの分か分かる形（半角英数字だけ）', () {
    expect(
      backupFileName(DateTime(2026, 9, 23, 11, 40, 5)),
      'database-backup-android-20260923-114005.json',
    );
    expect(
      backupFileName(DateTime(2026, 1, 2, 3, 4, 5), source: 'android'),
      'database-backup-android-20260102-030405.json',
    );
    // PC版が書く自動バックアップとは別の名前（読み込み時に取り違えない）
    expect(
      backupFileName(DateTime(2026, 9, 23)),
      isNot('database-backup-auto.json'),
    );
    // 半角英数字とハイフン・ピリオドだけ
    expect(
      RegExp(r'^[A-Za-z0-9.\-]+$')
          .hasMatch(backupFileName(DateTime(2026, 9, 23))),
      isTrue,
    );
    // 差出元の名前に妙な文字が入っても、ファイル名を壊さない
    expect(
      backupFileName(DateTime(2026, 9, 23, 1, 2, 3), source: 'ｽﾏﾎ/端末'),
      'database-backup-app-20260923-010203.json',
    );
  });
}
