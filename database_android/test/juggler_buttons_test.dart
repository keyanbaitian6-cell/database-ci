// ジャグラーオンライン：「読み取る」と「保存」を横に並べ、「撮った画面を消す」は下の行に小さく
// （2026-10-11 利用者「読み取ったあとの保存ボタンを読み取ると並べて配置してほしい」
// 「読み取って保存したら画面を消すと思うのでこの消すボタンはもっと小さくてもいいよ」）。
import 'package:database_android/juggler_capture_page.dart';
import 'package:database_android/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('save label follows what is left to save', () {
    String label(int days, int savable, int saved, {bool saving = false}) =>
        joSaveButtonLabel(
          days: days,
          savable: savable,
          saved: saved,
          saving: saving,
        );
    expect(label(0, 0, 0), '保存');
    expect(label(1, 1, 0), '保存');
    expect(label(2, 2, 0), '保存（2日分）');
    expect(label(2, 1, 1), '保存');
    expect(label(1, 0, 1), '保存しました');
    expect(label(1, 0, 0), '足せる台なし');
    expect(label(1, 1, 0, saving: true), '保存中…');
  });

  testWidgets('read and save sit side by side; delete is smaller below', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(393, 852));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    var saves = 0, reads = 0, deletes = 0;
    Future<void> pump({required bool canSave}) => tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: Padding(
            padding: const EdgeInsets.all(16),
            child: JoReadSaveButtons(
              readLabel: '読み取る',
              onRead: () => reads++,
              saveLabel: canSave ? '保存' : '保存しました',
              onSave: canSave ? () => saves++ : null,
              onDeleteAll: () => deletes++,
            ),
          ),
        ),
      ),
    );
    await pump(canSave: true);
    final read = tester.getRect(find.byKey(const ValueKey('jo-read')));
    final save = tester.getRect(find.byKey(const ValueKey('jo-save')));
    final delete = tester.getRect(find.byKey(const ValueKey('jo-delete')));
    expect(save.center.dy, read.center.dy, reason: '同じ行');
    expect(save.left, greaterThan(read.right), reason: '読み取るの右隣');
    expect(delete.top, greaterThanOrEqualTo(read.bottom), reason: '消すボタンは下の行');
    expect(delete.height, lessThan(read.height), reason: '消すボタンは小さい');
    expect(delete.width, lessThan(read.width));
    await tester.tap(find.byKey(const ValueKey('jo-save')));
    await tester.tap(find.byKey(const ValueKey('jo-read')));
    await tester.tap(find.byKey(const ValueKey('jo-delete')));
    expect((saves, reads, deletes), (1, 1, 1));
    await pump(canSave: false);
    await tester.tap(find.byKey(const ValueKey('jo-save')));
    expect(saves, 1, reason: '保存済みなら押せない');
    expect(find.text('保存しました'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
