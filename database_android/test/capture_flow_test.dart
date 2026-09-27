import 'package:database_android/capture_flow.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('処理の中から処理を呼んでも、いちばん外が終わるまで処理中のまま', () async {
    var changes = 0;
    final flow = CaptureFlow(onChanged: () => changes++);
    flow.ready(flow.page); // 最初のページは読み込み済みとする
    expect(flow.canCapture, isTrue);
    await flow.whileBusy(() async {
      expect(flow.busy, isTrue);
      await flow.whileBusy(() async {});
      expect(flow.busy, isTrue); // 内側が終わっても外側の途中
      expect(flow.canCapture, isFalse);
    });
    expect(flow.busy, isFalse);
    expect(flow.canCapture, isTrue);
    expect(changes, greaterThan(0));
  });

  test('失敗しても処理中が残らず、待っていた人に知らせる', () async {
    final flow = CaptureFlow();
    var idle = false;
    final waiting = Future<void>(() async {
      await Future<void>.delayed(Duration.zero);
      await flow.whenIdle();
      idle = true;
    });
    await expectLater(
      flow.whileBusy(() async {
        await Future<void>.delayed(const Duration(milliseconds: 10));
        throw StateError('x');
      }),
      throwsStateError,
    );
    await waiting;
    expect(idle, isTrue);
    expect(flow.busy, isFalse);
  });

  test('ページが変わると世代が進み、古い世代の完了・表示の整いは無視する', () {
    final flow = CaptureFlow();
    final first = flow.pageStarted('https://x/nagamachiminami/rack_info');
    expect(flow.pageFinished(first), isTrue);
    expect(flow.pageFinished(first), isFalse); // 2回目の完了は無視
    final second = flow.pageStarted('https://x/nagamachiminami/rack_info_kt');
    flow.ready(first);
    expect(flow.loading, isTrue); // 古いページの「整った」では外さない
    flow.ready(second);
    expect(flow.loading, isFalse);
  });

  test('読み込みの知らせが来ないときは、処理中でなければ読み込み中を外す', () async {
    final flow = CaptureFlow();
    final page = flow.pageStarted('https://x/a');
    await flow.whileBusy(() async {
      flow.loadTimedOut(page);
      expect(flow.loading, isTrue); // 処理中は外さない
    });
    flow.loadTimedOut(page);
    expect(flow.loading, isFalse);
  });

  test('次のページでの知らせは1回だけ。次の機種へ進む予定は機種一覧を開くときだけ残る', () {
    final flow = CaptureFlow();
    flow.expectPage(notice: '次：12番台', advance: true);
    flow.pageStarted(
      'https://x/saiwaichou/rack_info_kt/?kind_code=21#database_next_machine=1',
    );
    expect(flow.takeAfterLoadNotice(), '次：12番台');
    expect(flow.takeAfterLoadNotice(), isNull);
    expect(flow.takeAdvance(), isTrue);
    expect(flow.takeAdvance(), isFalse);

    flow.expectPage(advance: true);
    flow.pageStarted('https://x/saiwaichou/rack_info/?rack_no=3');
    expect(flow.takeAdvance(), isFalse); // 別のページへ移ったら取りやめ
  });
}
