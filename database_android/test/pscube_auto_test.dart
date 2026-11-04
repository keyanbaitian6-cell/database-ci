import 'package:database_android/auto_capture_state.dart';
import 'package:database_android/pscube_auto.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, Object> ready(String signature, [String kind = '全台一覧']) => {
  'ready': true,
  'kind': kind,
  'signature': signature,
  'busy': false,
};

void main() {
  test('差枚は未取得の理由を取り込み結果から読む（無い・壊れた結果は null）', () {
    expect(
      pscubeNetWarning(
        '{"records":[],"net_warning":"差枚は未取得：通信に失敗しました（HTTP 403）"}',
      ),
      '差枚は未取得：通信に失敗しました（HTTP 403）',
    );
    expect(pscubeNetWarning('{"records":[]}'), isNull);
    expect(pscubeNetWarning('{"net_warning":""}'), isNull);
    expect(pscubeNetWarning('not json'), isNull);
    expect(pscubeNetWarning('[1]'), isNull);
  });

  test('確認画面・読み込み中・対象外は理由を出して待つ（押さない）', () {
    final d = pscubeAutoDecision(
      {'ready': false, 'reason': '台別7日分の表示待ち（人間確認・同意の画面なら手動で操作してください）'},
      {},
      {},
    );
    expect(d.capture, isNull);
    expect(d.message, contains('人間確認'));
    expect(pscubeAutoDecision(null, {}, {}).capture, isNull);
    expect(pscubeAutoDecision('壊れた結果', {}, {}).capture, isNull);
  });

  test('取り込める表示なら、そのページを取り込む', () {
    final d = pscubeAutoDecision(ready('A', '台別7日分'), {}, {});
    expect(d.capture, 'A');
    expect(d.message, 'ON・取り込み中（台別7日分）');
  });

  test('保存中・保存済み・3回失敗したページは取り込まない', () {
    expect(
      pscubeAutoDecision({...ready('A'), 'busy': true}, {}, {}).message,
      contains('完了待ち'),
    );
    expect(pscubeAutoDecision(ready('A'), {'A'}, {}).capture, isNull);
    expect(pscubeAutoDecision(ready('A'), {}, {'A': 2}).capture, 'A');
    final stopped = pscubeAutoDecision(ready('A'), {}, {'A': 3});
    expect(stopped.capture, isNull);
    expect(stopped.message, contains('3回失敗'));
  });

  test('ランダム間隔の100,001通りと端点・100マイクロ秒刻みを確認', () {
    var now = Duration.zero;
    var choice = 0;
    final auto = pscubeRandomAutoState(
      elapsed: () => now,
      nextInt: (bound) {
        expect(bound, 100001);
        return choice++;
      },
    )..turnOn();
    final values = {auto.interval.inMicroseconds};
    for (var i = 1; i <= 100000; i++) {
      auto.nextPage(i);
      values.add(auto.interval.inMicroseconds);
    }
    expect(values.length, 100001);
    expect(values.first, 15000000);
    expect(values.last, 25000000);
    expect(values.every((v) => v % 100 == 0), isTrue);
    now = const Duration(microseconds: 24999999);
    expect(auto.due(busy: false), isNull);
    expect(choice, 100001, reason: '待機中の確認で再抽選しない');
    choice = 0;
    now += const Duration(microseconds: 1);
    expect(auto.due(busy: false), isNotNull);
    expect(auto.interval, const Duration(seconds: 15));
    auto.turnOff();
    now += const Duration(seconds: 100);
    expect(auto.due(busy: false), isNull);
  });

  test('保存中は開始せず、新しい待機を抽選する', () {
    var choice = 12345;
    final auto = pscubeRandomAutoState(nextInt: (_) => choice)..turnOn();
    expect(auto.interval.inMicroseconds, 16234500);
    choice = 100000;
    expect(auto.due(busy: true), isNull);
    expect(auto.interval, const Duration(seconds: 25));
  });

  test('起動時はOFF・間隔10秒（5〜60秒）。OFFやページ移動の後の古い判定は使わない', () {
    var now = Duration.zero;
    final auto = AutoCaptureState(
      elapsed: () => now,
      minTenths: 50,
      maxTenths: 600,
      intervalTenths: 100,
    );
    expect(auto.enabled, isFalse);
    expect(auto.intervalTenths, 100);
    auto.turnOn();
    expect(auto.due(busy: false), isNull, reason: '間隔が経つまでは見ない');
    now += const Duration(seconds: 10);
    final token = auto.due(busy: false)!;
    expect(auto.current(token, 0), isTrue);
    auto.nextPage(1);
    expect(auto.current(token, 1), isFalse, reason: 'ページが移ったら古い判定は無効');
    now += const Duration(seconds: 10);
    final next = auto.due(busy: false)!;
    auto.turnOff();
    expect(auto.current(next, 1), isFalse, reason: 'OFFの後は始めない');
    expect(() => auto.setIntervalTenths(49), throwsRangeError);
    expect(() => auto.setIntervalTenths(601), throwsRangeError);
    expect(AutoCaptureState().intervalTenths, 35, reason: 'メルヘンは今までどおり3.5秒');
  });

  test('確認画面ではない「データが出ない」が1分以上・5回以上続いたら止める。確認画面・表示の回復では数え直す', () {
    final guard = PscubeAutoGuard();
    const missing = {'ready': false, 'missing': true, 'reason': '表示待ち'};
    const challenge = {'ready': false, 'challenge': true, 'reason': '人間確認'};
    var now = Duration.zero;
    ({String? capture, String message, bool stop}) at(Object probe) {
      now += const Duration(seconds: 10);
      return guard.decide(probe, {}, {}, now);
    }

    for (var i = 0; i < 6; i++) {
      expect(at(missing).stop, isFalse);
    }
    final stopped = at(missing);
    expect(stopped.stop, isTrue);
    expect(stopped.message, contains('止められた可能性'));
    expect(stopped.message, contains('Cookieを消さずに'), reason: '止まったときに次の手を案内する');
    for (var i = 0; i < 4; i++) {
      at(missing);
    }
    expect(at(challenge).stop, isFalse, reason: '確認画面で数え直す');
    for (var i = 0; i < 6; i++) {
      expect(at(missing).stop, isFalse);
    }
    expect(at(ready('A')).capture, 'A', reason: '表示が戻れば取り込む');
    for (var i = 0; i < 20; i++) {
      expect(at(challenge).stop, isFalse, reason: '確認画面ではずっと待つ');
    }
  });

  test('0時の予約：次の0時から3時（営業日の切り替え）まで、前日を取り込む日として始める', () {
    final armed = pscubeNextMidnight(DateTime(2026, 10, 26, 22, 30));
    expect(armed, DateTime(2026, 10, 27));
    expect(
      pscubeNextMidnight(DateTime(2026, 10, 31, 0, 0, 1)),
      DateTime(2026, 11, 1),
    );
    expect(
      pscubeMidnightDue(DateTime(2026, 10, 26, 23, 59, 59), armed),
      isNull,
    );
    expect(pscubeMidnightDue(DateTime(2026, 10, 27), armed), '2026-10-26');
    expect(
      pscubeMidnightDue(DateTime(2026, 10, 27, 2, 59, 59), armed),
      '2026-10-26',
    );
    expect(
      pscubeMidnightDue(DateTime(2026, 10, 27, 3), armed),
      PscubeMidnight.missed,
    );
    expect(
      pscubeMidnightDue(DateTime(2026, 10, 28, 1), armed),
      PscubeMidnight.missed,
    );
  });

  test('0時の予約を待つ間の画面：23時まで明るさはそのまま、23時から暗く。予約なし・取り込み後は普段どおり', () {
    String? at(int hour, {bool reserved = true, bool released = false}) =>
        pscubeWaitingScreen(
          reserved: reserved,
          released: released,
          now: DateTime(2026, 10, 26, hour),
        );
    expect(at(15), 'bright', reason: '昼に開いても暗くしない');
    expect(at(22), 'bright');
    expect(at(23), 'dim');
    expect(at(1), 'bright', reason: '0時に始められず待っている間（3時まで）');
    expect(at(23, reserved: false), isNull);
    expect(at(23, released: true), isNull, reason: '0時に始めた分が終わったら手放す');
  });

  test('営業日は日本時間の午前3時で切り替わり、取り込み日は直近7日から選ぶ', () {
    expect(pscubeBusinessDay(DateTime(2026, 10, 4, 2, 59)), '2026-10-03');
    expect(pscubeBusinessDay(DateTime(2026, 10, 4, 3, 0)), '2026-10-04');
    expect(pscubeBusinessDay(DateTime(2026, 10, 4, 23, 30)), '2026-10-04');
    final days = pscubeRecentBusinessDays(DateTime(2026, 10, 4, 1, 0));
    expect(
      (days.first, days[1], days.last, days.length),
      ('2026-10-03', '2026-10-02', '2026-09-27', 7),
    );
  });

  test('取り込み日と違う日のページは取り込まず待つ。指定なしならこれまでどおり取り込む', () {
    final probe = {
      'ready': true,
      'kind': '全台一覧',
      'signature': 'T',
      'day': '2026-10-04',
    };
    final wait = pscubeAutoDecision(probe, {}, {}, targetDay: '2026-10-03');
    expect(wait.capture, isNull);
    expect(wait.message, contains('取り込み日は10/3ですが、表示中は10/4'));
    expect(wait.message, contains('日付タブ'));
    final same = pscubeAutoDecision(
      {...probe, 'day': '2026-10-03'},
      {},
      {},
      targetDay: '2026-10-03',
    );
    expect(same.capture, 'T');
    expect(pscubeAutoDecision(probe, {}, {}).capture, 'T');
    // 台別ページでは「このページを」。
    final rack = pscubeAutoDecision(
      {...probe, 'kind': '台別7日分'},
      {},
      {},
      targetDay: '2026-10-03',
    );
    expect(rack.message, contains('このページを'));
    // 日付タブの食い違いは「止められた」扱いにしない（待つだけ）。
    final guard = PscubeAutoGuard();
    for (var i = 0; i < 20; i++) {
      final d = guard.decide(
        probe,
        {},
        {},
        Duration(seconds: 10 * i),
        targetDay: '2026-10-03',
      );
      expect(d.stop, isFalse);
    }
  });

  // 2026-10-22：新台は取り込み日のタブが無く、サイトは最新のタブを選ぶ。以前は日付違いとして待ち続け、保存側の
  // 飛ばす処理まで届かなかった。タブが無いと読めるときだけ読み取りへ進め、保存側が確かめる（PC版と同じ表）。
  test('取り込み日のタブが無い全台一覧だけは、表示中の日が違っても読み取りへ進める', () {
    final cases = <(String, String, String, Object?, bool)>[
      // (取り込み日, 表示中の日, 種類, 日付タブ, 読み取るか)
      ('2026-10-18', '2026-10-19', '全台一覧', ['2026-10-19'], true),
      ('2026-10-18', '2026-10-19', '全台一覧', ['2026-10-17', '2026-10-19'], true),
      ('2026-10-18', '2026-10-19', '全台一覧', ['2026-10-18', '2026-10-19'], false),
      ('2026-10-19', '2026-10-18', '全台一覧', ['2026-10-17', '2026-10-18'], false),
      ('2026-10-18', '2026-10-19', '全台一覧', <String>[], false),
      ('2026-10-18', '2026-10-19', '全台一覧', null, false),
      ('2026-10-18', '2026-10-19', '全台一覧', ['2026-10-19', '10/17'], false),
      ('2026-10-18', '2026-10-19', '全台一覧', ['2026-10-20'], false),
      ('2026-10-18', '2026-10-19', '台別7日分', ['2026-10-19'], false),
    ];
    for (final (target, shown, kind, days, reads) in cases) {
      final probe = {...ready('T', kind), 'day': shown, 'days': ?days};
      final decision = pscubeAutoDecision(probe, {}, {}, targetDay: target);
      expect(
        decision.capture,
        reads ? 'T' : isNull,
        reason: '$target $kind $days',
      );
      expect(
        decision.message,
        contains(reads ? '日付タブが無い機種か確かめています' : '合わせてください'),
      );
    }
    // 人間確認・読み込み中・保存中の画面は、タブが無く見えても読み取らない。
    for (final probe in [
      {
        'ready': false,
        'challenge': true,
        'reason': '人間確認・同意の画面',
        'days': ['2026-10-19'],
      },
      {
        'ready': false,
        'missing': true,
        'reason': '全台一覧の表示待ち',
        'days': ['2026-10-19'],
      },
      {
        ...ready('T'),
        'day': '2026-10-19',
        'days': ['2026-10-19'],
        'busy': true,
      },
    ]) {
      expect(
        pscubeAutoDecision(probe, {}, {}, targetDay: '2026-10-18').capture,
        isNull,
      );
    }
  });

  // 2026-11-05：取り戻した日を起点にしてさかのぼり続けない・サイトの7日より古い日を見ない。
  test('抜けた日は最初に済ませた日から前の6日だけ、サイトの7日の中で探す', () {
    final midnight = DateTime(2026, 10, 19, 0, 0, 1); // 営業日は10/18
    expect(pscubeGapCandidateDays([], midnight), isEmpty);
    expect(pscubeGapCandidateDays(['2026-10-18'], midnight), [
      '2026-10-17',
      '2026-10-16',
      '2026-10-15',
      '2026-10-14',
      '2026-10-13',
      '2026-10-12',
    ]);
    // 10/12を取り戻した後も起点は10/18のまま。10/11より前へは進まない。
    expect(pscubeGapCandidateDays(['2026-10-18', '2026-10-12'], midnight), [
      '2026-10-17',
      '2026-10-16',
      '2026-10-15',
      '2026-10-14',
      '2026-10-13',
    ]);
    // 日付を選んで古い日を取り込んだときも、サイトの7日（10/12〜10/18）より古い日は見ない。
    expect(pscubeGapCandidateDays(['2026-10-14'], midnight), [
      '2026-10-13',
      '2026-10-12',
    ]);
    // 月をまたぐ。
    expect(
      pscubeGapCandidateDays(['2026-11-04'], DateTime(2026, 11, 5, 0, 1)),
      [
        '2026-11-03',
        '2026-11-02',
        '2026-11-01',
        '2026-10-31',
        '2026-10-30',
        '2026-10-29',
      ],
    );
  });
}
