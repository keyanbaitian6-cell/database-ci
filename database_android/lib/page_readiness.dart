import 'dart:async';
import 'dart:convert';

/// 読込完了・通信待ちなし・内容の安定をすべて確認する。
/// 回数や「1行届いた」だけでは完了にしない。時間切れは未完了として返す。
Future<Map<String, dynamic>> waitForStablePage({
  required Future<Map<String, dynamic>> Function() read,
  required bool Function() isCurrent,
  Duration timeout = const Duration(seconds: 30),
  Duration settle = const Duration(milliseconds: 1500),
  Duration interval = const Duration(milliseconds: 250),
  Duration Function()? elapsed,
  Future<void> Function(Duration)? delay,
}) async {
  final watch = Stopwatch()..start();
  final now = elapsed ?? () => watch.elapsed;
  final pause = delay ?? Future<void>.delayed;
  String? signature;
  Duration? stableSince;
  while (now() < timeout) {
    if (!isCurrent()) throw const FormatException('ページが切り替わったため中止しました。');
    final remaining = timeout - now();
    final value = await read().timeout(remaining);
    if (!isCurrent()) throw const FormatException('ページが切り替わったため中止しました。');
    final current = jsonEncode(value['content']);
    if (value['ready'] == true && value['hasContent'] == true) {
      if (current != signature) stableSince = now();
      if (stableSince != null && now() - stableSince >= settle) return value;
      signature = current;
    } else {
      signature = null;
      stableSince = null;
    }
    await pause(interval);
  }
  throw const FormatException('ページの読み込み完了を確認できません。通信状態を確認し、再読み込みしてください。');
}
