import 'package:database_android/capture_notice.dart';
import 'package:database_android/home_widget.dart';
import 'package:database_android/list_views.dart' show dayCandidates;
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

/// ホーム画面のウィジェット（2026-11-04、通常版・P’s CUBE版の両方）に渡す中身。
void main() {
  late List<Map<String, String>> sent;

  setUp(() {
    sent = [];
    homeWidgetSender = (values) async => sent.add(values);
    homeWidgetNow = () => DateTime(2026, 11, 5, 1, 7);
  });

  tearDown(() => homeWidgetNow = DateTime.now);

  test('翌日候補の行：台番号は小さい順、店ごとに6台まで、日付は翌日', () {
    expect(
      homeWidgetCandidateLine([
        (label: '長町南', day: '2026-11-04', racks: [233, 12, 105]),
        (label: '幸町', day: '2026-11-04', racks: [9, 8, 7, 6, 5, 4, 3, 2]),
        (label: 'P-town', day: '2026-11-04', racks: []),
      ]),
      '★翌日候補 11/5（木）　長町南 12・105・233／幸町 2・3・4・5・6・7 ほか2台',
    );
    expect(homeWidgetCandidateLine([]), '', reason: '候補が無ければ空（前の行を消す）');
  });

  test('店ごとにもとの日が違うときは、店の後ろに日付を付ける', () {
    expect(
      homeWidgetCandidateLine([
        (label: '長町南', day: '2026-11-04', racks: [12]),
        (label: '幸町', day: '2026-11-03', racks: [8]),
      ]),
      '★翌日候補　長町南（11/5（木）） 12／幸町（11/4（水）） 8',
    );
  });

  test('候補は結果画面と同じ計算の台で、店ごとに記録のある最新の日のもの', () {
    final records = [
      for (final day in [
        '2026-10-30',
        '2026-10-31',
        '2026-11-01',
        '2026-11-02',
      ])
        for (var rack = 1; rack <= 8; rack++)
          SlotRecord(
            store: 'nagamachiminami',
            day: day,
            machine: '北斗',
            rack: rack,
            games: 6000,
            bb: rack * 3,
            rb: rack * 2,
          ),
    ];
    final stores = homeWidgetCandidates(records);
    expect(stores.single.label, '長町南');
    expect(stores.single.day, '2026-11-02');
    final expected = dayCandidates(
      [
        for (final r in records)
          if (r.day == '2026-11-02') r,
      ],
      records,
      excludeNormal: true,
    ).candidates.map((c) => c.record.rack).toList();
    expect(expected, isNotEmpty, reason: '候補が出る記録で確かめる');
    expect(stores.single.racks, expected);
  });

  test('取り込みの結果の通知と同じ文を、時刻つきでウィジェットにも出す', () async {
    captureNoticeSender = (title, text) async {};
    await notifyCaptureResult('P’s CUBE：取り込み完了', '11/4（火）：60機種・295台');
    await Future<void>.delayed(Duration.zero);
    expect(
      sent.single['status'],
      'P’s CUBE：取り込み完了（11/5 1:07）\n11/4（火）：60機種・295台',
    );
    expect(sent.single['updated'], '更新 11/5 1:07');
  });

  test('ウィジェットを書き換えられなくても止めない', () async {
    homeWidgetSender = (values) async => throw StateError('書けない');
    await updateHomeWidgetCandidates([
      (label: '長町南', day: '2026-11-04', racks: [1]),
    ]);
  });
}
