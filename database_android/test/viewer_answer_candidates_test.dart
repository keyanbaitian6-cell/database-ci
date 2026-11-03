import 'dart:convert';

import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

/// 閲覧ページが読む「当時の翌日候補」（PC core.py `saved_answer_candidates`、2026-11-04）。
void main() {
  String doc(Object? answers) => jsonEncode({
    'format': 'database-backup',
    'version': 1,
    'exported_at': '2026-11-04T09:00:00+09:00',
    'answer_candidates': ?answers,
    'records': [
      {
        'store': 'nagamachiminami',
        'day': '2026-11-03',
        'machine': '北斗',
        'rack': 1,
        'games': 3000,
        'bb': 10,
        'rb': 5,
      },
    ],
  });

  test('店・日ごとの台番号・平均より・バラエティを読み、形の合わない台は読み飛ばす', () {
    final data = ViewerData.parse(
      doc({
        'nagamachiminami|2026-11-03': [
          [12, 61.5, 0],
          [31, 55, 1],
          ['x', 60, 0],
          [7, 60.0, 2],
        ],
        'saiwaichou|2026-11-03': 'broken',
      }),
    );
    expect(data.answerCandidates.keys, ['nagamachiminami|2026-11-03']);
    expect(data.answerCandidates['nagamachiminami|2026-11-03'], [
      (rack: 12, index: 61.5, variety: false),
      (rack: 31, index: 55.0, variety: true),
    ]);
    expect(
      data.withRainbowMarks(const {}).answerCandidates,
      data.answerCandidates,
      reason: '🌈の印を当て直しても失わない',
    );
  });

  test('載っていないファイル（今までのPCの書き出し）は空のまま読む', () {
    expect(ViewerData.parse(doc(null)).answerCandidates, isEmpty);
  });
}
