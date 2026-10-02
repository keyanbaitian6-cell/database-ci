import 'package:database_android/pscube_list_wait.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('各機種で6台の一時安定を越えて、3秒後の31台まで毎回スクロールする', () async {
    for (var machine = 0; machine < 2; machine++) {
      var elapsed = Duration.zero;
      final counts = <int>[];
      await waitForPscubeList(
        expectedCount: 31,
        isCurrent: () => true,
        scrollAndCount: () async {
          final count = elapsed < const Duration(seconds: 3) ? 6 : 31;
          counts.add(count);
          return count;
        },
        delay: (duration) async => elapsed += duration,
      );
      expect(counts.first, 6);
      expect(counts.last, 31);
      expect(elapsed, greaterThan(const Duration(seconds: 3)));
    }
  });

  test('台数不足が続いても最大70回で終了する', () async {
    var calls = 0;
    var elapsed = Duration.zero;
    await waitForPscubeList(
      expectedCount: 31,
      isCurrent: () => true,
      scrollAndCount: () async {
        calls++;
        return 6;
      },
      delay: (duration) async => elapsed += duration,
    );
    expect(calls, 70);
    expect(elapsed, const Duration(milliseconds: 24500));
  });

  test('設置台数不明の一覧は既存の安定待ちで終了する', () async {
    var calls = 0;
    await waitForPscubeList(
      isCurrent: () => true,
      scrollAndCount: () async {
        calls++;
        return 6;
      },
      delay: (_) async {},
    );
    expect(calls, 7);
  });

  test('台別など一覧がないページは待機しない', () async {
    await waitForPscubeList(
      isCurrent: () => true,
      scrollAndCount: () async => -1,
      delay: (_) async => fail('一覧がない場合は待たない'),
    );
  });

  test('別ページへ移動した後はそのページをスクロールしない', () async {
    var current = true;
    var calls = 0;
    await waitForPscubeList(
      expectedCount: 31,
      isCurrent: () => current,
      scrollAndCount: () async {
        calls++;
        return 6;
      },
      delay: (_) async => current = false,
    );
    expect(calls, 1);
  });
}
