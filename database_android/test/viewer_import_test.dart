import 'dart:convert';

import 'package:database_android/date_events.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, Object?> row(String day, int rack) => {
  'store': 'saiwaichou',
  'day': day,
  'machine': '試験+機種',
  'rack': rack,
  'games': 3000,
  'bb': 10,
  'rb': 5,
  'graph_measurement': {
    'baseline_y': 100,
    'peak_y': 80,
    'trough_y': 100,
    'end_y': 80,
    'curve': [
      [0, 100],
      [1, 80],
    ],
  },
};

void main() {
  test('手動読み込みは旧JSONなしで入力済みイベントと解除を引き継ぐ', () {
    final previous = ViewerData(
      records: const [],
      dateEvents: {
        'saiwaichou|2026-09-01': const DateEvent(
          store: 'saiwaichou',
          day: '2026-09-01',
          name: '以前のイベント',
        ),
        'saiwaichou|2026-10-22': const DateEvent(
          store: 'saiwaichou',
          day: '2026-10-22',
          name: '',
          updatedAt: '2026-10-23T01:00:00+09:00',
        ),
        'saiwaichou|2026-10-25': const DateEvent(
          store: 'saiwaichou',
          day: '2026-10-25',
          name: '先の日',
          updatedAt: '2026-10-23T01:00:00+09:00',
        ),
        'saiwaichou|2026-10-24': const DateEvent(
          store: 'saiwaichou',
          day: '2026-10-24',
          name: 'PCで解除済み',
        ),
      },
    );
    final incoming = jsonEncode({
      'records': [row('2026-10-22', 537)],
      'date_events': [
        {
          'store': 'saiwaichou',
          'day': '2026-10-22',
          'name': '古い入力',
          'updated_at': '2026-10-21T01:00:00+09:00',
        },
      ],
    });
    final prepared = ViewerData.preparePicked(incoming, previous);
    expect(prepared.data.records.single.machine, '試験 機種');
    expect(prepared.data.dateEvents['saiwaichou|2026-10-22']!.removed, isTrue);
    expect(
      prepared.data.dateEventFor('saiwaichou', '2026-09-01')!.name,
      '以前のイベント',
    );
    expect(prepared.data.dateEventFor('saiwaichou', '2026-10-25')!.name, '先の日');
    expect(prepared.data.dateEventFor('saiwaichou', '2026-10-24'), isNull);
    expect(
      ViewerData.parse(prepared.text).dateEvents.length,
      prepared.data.dateEvents.length,
    );
    expect(previous.dateEvents.length, 4);
  });

  test('統合後の保存内容と表示モデルが同じ日・台・グラフ・メタデータを持つ', () {
    final stored = jsonEncode({
      'records': [row('2026-09-01', 538)],
    });
    final incoming = jsonEncode({
      'records': [row('2026-10-22', 537)],
      'custom_metadata': {'value': '保持'},
    });
    final prepared = ViewerData.prepareMerge(stored, incoming);
    expect(prepared.data.records.map((r) => r.rack).toSet(), {537, 538});
    final saved = ViewerData.parse(prepared.text);
    expect(
      saved.records.map((r) => (r.day, r.rack, r.games)).toList(),
      prepared.data.records.map((r) => (r.day, r.rack, r.games)).toList(),
    );
    expect((jsonDecode(prepared.text) as Map)['custom_metadata'], {
      'value': '保持',
    });
    expect(prepared.note, contains('1台'));
  });

  test('P’s CUBEの表示中にメルヘンを読むときは別店舗の入力を混ぜない', () {
    const previous = ViewerData(records: [], source: 'pscube');
    final incoming = jsonEncode({
      'records': [row('2026-10-22', 537)],
    });
    final result = ViewerData.preparePicked(incoming, previous);
    expect(result.text, same(incoming));
    expect(result.data.records.single.rack, 537);
  });

  test('不完全なファイルを表示用データとして受け付けない', () {
    expect(
      () => ViewerData.preparePicked('{"records":[', null),
      throwsFormatException,
    );
    expect(
      () => ViewerData.prepareMerge(null, '{"other":1}'),
      throwsFormatException,
    );
  });

  test('別タブの最新イベントを旧画面のイベントより優先して引き継ぐ', () {
    const previous = ViewerData(
      records: [],
      dateEvents: {
        'saiwaichou|2026-10-22': DateEvent(
          store: 'saiwaichou',
          day: '2026-10-22',
          name: '古い入力',
          updatedAt: '2026-10-22T01:00:00Z',
        ),
      },
    );
    final result = ViewerData.preparePicked(
      jsonEncode({
        'records': [row('2026-10-22', 537)],
      }),
      previous,
      events: jsonEncode({
        'records': [],
        'date_events': [
          {
            'store': 'saiwaichou',
            'day': '2026-10-22',
            'name': '別タブの入力',
            'updated_at': '2026-10-23T14:00:00Z',
          },
        ],
      }),
    );
    expect(
      result.data.dateEventFor('saiwaichou', '2026-10-22')!.name,
      '別タブの入力',
    );
  });
}
