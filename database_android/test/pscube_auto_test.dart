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

  test('ランダム間隔の30,001通りと端点・100マイクロ秒刻みを確認', () {
    var now = Duration.zero;
    var choice = 0;
    final auto = pscubeRandomAutoState(
      elapsed: () => now,
      nextInt: (bound) {
        expect(bound, 30001);
        return choice++;
      },
    )..turnOn();
    final values = {auto.interval.inMicroseconds};
    for (var i = 1; i <= 30000; i++) {
      auto.nextPage(i);
      values.add(auto.interval.inMicroseconds);
    }
    expect(values.length, 30001);
    expect(values.first, 5000000);
    expect(values.last, 8000000);
    expect(values.every((v) => v % 100 == 0), isTrue);
    now = const Duration(microseconds: 7999999);
    expect(auto.due(busy: false), isNull);
    expect(choice, 30001, reason: '待機中の確認で再抽選しない');
    choice = 0;
    now += const Duration(microseconds: 1);
    expect(auto.due(busy: false), isNotNull);
    expect(auto.interval, const Duration(seconds: 5));
    auto.turnOff();
    now += const Duration(seconds: 100);
    expect(auto.due(busy: false), isNull);
  });

  test('保存中は開始せず、新しい待機を抽選する', () {
    var choice = 12345;
    final auto = pscubeRandomAutoState(nextInt: (_) => choice)..turnOn();
    expect(auto.interval.inMicroseconds, 6234500);
    choice = 30000;
    expect(auto.due(busy: true), isNull);
    expect(auto.interval, const Duration(seconds: 8));
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

  test('営業日は日本時間の午前2時で切り替わり、取り込み日は直近7日から選ぶ', () {
    expect(pscubeBusinessDay(DateTime(2026, 10, 4, 1, 59)), '2026-10-03');
    expect(pscubeBusinessDay(DateTime(2026, 10, 4, 2, 0)), '2026-10-04');
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
}
