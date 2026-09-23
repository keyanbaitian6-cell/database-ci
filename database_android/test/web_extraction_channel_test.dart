import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/web_extraction_channel.dart';

Future<void> tick() => Future<void>.delayed(Duration.zero);
void main() {
  test('同時に届く2要求を順番に処理し、応答を取り違えない', () async {
    final channel = WebExtractionChannel();
    final sent = <int>[];
    final first = channel.run((id) async => sent.add(id));
    final second = channel.run((id) async => sent.add(id));
    await tick();
    expect(sent, [1]);
    channel.receive(jsonEncode({'id': 1, 'value': 'first'}));
    expect(await first, 'first');
    await tick();
    expect(sent, [1, 2]);
    channel.receive(jsonEncode({'id': 1, 'value': 'stale'}));
    channel.receive(jsonEncode({'id': 2, 'value': 'second'}));
    expect(await second, 'second');
    channel.dispose();
  });
  test('遷移時に進行中と待機中の旧ページ要求を取り消す', () async {
    final channel = WebExtractionChannel();
    final sent = <int>[];
    final a = channel.run((id) async => sent.add(id));
    final b = channel.run((id) async => sent.add(id));
    final checks = Future.wait([
      expectLater(a, throwsFormatException),
      expectLater(b, throwsFormatException),
    ]);
    await tick();
    channel.navigationStarted();
    await checks;
    expect(sent, [1]);
    final c = channel.run((id) async {
      channel.receive(jsonEncode({'id': id, 'value': 'new'}));
    });
    expect(await c, 'new');
    channel.dispose();
  });
  test('送信失敗・タイムアウト後も次の要求を受け付ける', () async {
    final channel = WebExtractionChannel(
      timeout: const Duration(milliseconds: 20),
    );
    await expectLater(
      channel.run((_) async => throw StateError('send failed')),
      throwsStateError,
    );
    await expectLater(channel.run((_) async {}), throwsFormatException);
    final next = channel.run((id) async {
      channel.receive(jsonEncode({'id': id, 'value': 0}));
    });
    expect(await next, 0);
    channel.dispose();
  });
  test('画面を閉じると要求を解除し、閉じた後は送信しない', () async {
    final channel = WebExtractionChannel();
    final reply = channel.run((_) async {});
    final check = expectLater(reply, throwsFormatException);
    await tick();
    channel.dispose();
    await check;
    await expectLater(
      channel.run((_) async => fail('closed')),
      throwsFormatException,
    );
  });
}
