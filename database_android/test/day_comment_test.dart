import 'dart:convert';
import 'dart:io';

import 'package:database_android/day_comment.dart';
import 'package:flutter_test/flutter_test.dart';

/// お店のひとこと（2026-11-04）：閲覧ページの文が、共有カレンダー（share_viewer/data.mjs）と同じ試験データの
/// 期待値どおりか。JS 側は tool/test_day_comment.mjs が同じファイルを読む。
void main() {
  final fixture = jsonDecode(
    File('test/fixtures/day_comment_cases.json').readAsStringSync(),
  ) as Map;
  for (final c in (fixture['cases'] as List).cast<Map>()) {
    test('ひとこと：${c['name']}', () {
      final input = c['input'] as Map;
      expect(
        dayComment(
          day: input['day'] as String,
          event: input['event'] as String?,
          racks: [
            for (final r in (input['racks'] as List).cast<Map>())
              (
                rack: r['rack'] as int,
                machine: r['machine'] as String,
                net: r['net'] as int?,
                won: r['won'] as bool?,
                estimated: r['estimated'] as bool,
              ),
          ],
          recent: [
            for (final x in (input['recent'] as List).cast<Map>())
              (judged: x['judged'] as int, won: x['won'] as int),
          ],
        ),
        c['expected'],
      );
    });
  }
}
