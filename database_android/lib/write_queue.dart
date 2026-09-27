import 'dart:async';

/// 書き込みを1列に並べる順番待ち。
///
/// 保存・削除・取り込みなどを1つずつ順に行い、途中で読んだ古い一覧が新しい
/// 一覧を上書きするような行き違いを防ぐ。次の2つを仕組みで止める。
///
/// * 順番待ちの中から、もう一度順番待ちに入ろうとする（自分の終わりを待って
///   永遠に止まる）。[run] は待たずに失敗を返す。
/// * 1つの処理がいつまでも終わらない。呼んだ側は [timeout] で失敗を受け取る
///   （処理そのものは止められないので、順番は崩さない）。まだ始まって
///   いなかった処理は、その後も行わない。
class WriteQueue {
  WriteQueue({this.timeout = const Duration(seconds: 60)});

  /// 1回の処理（待ち時間を含む）の上限。null なら無制限。
  final Duration? timeout;

  Future<void> _tail = Future<void>.value();
  final _zoneKey = Object();

  /// いま順番待ちの中（[run] に渡した処理の中）で動いているか。
  bool get inWrite => Zone.current[_zoneKey] == true;

  /// [action] を順番に行う。[unlimited] は、大きなバックアップの取り込みの
  /// ように時間のかかる処理（上限を設けない）。
  Future<T> run<T>(Future<T> Function() action, {bool unlimited = false}) {
    if (inWrite) {
      return Future<T>.error(
        StateError('書き込みの途中で、別の書き込みを始めようとしました（止まるのを防ぐため中止しました）。'),
      );
    }
    var started = false;
    var abandoned = false;
    final result = _tail.then((_) {
      if (abandoned) {
        throw TimeoutException('前の処理が終わらないため、この処理はしていません。');
      }
      started = true;
      return runZoned(action, zoneValues: {_zoneKey: true});
    });
    _tail = result.then<void>(
      (_) {},
      onError: (Object error, StackTrace stack) {},
    );
    final limit = unlimited ? null : timeout;
    if (limit == null) return result;
    return result.timeout(
      limit,
      onTimeout: () {
        if (!started) {
          abandoned = true;
          throw TimeoutException(
            '前の処理が${limit.inSeconds}秒たっても終わらないため、この処理はしていません。'
            'アプリを開き直してください。',
          );
        }
        throw TimeoutException(
          '処理が${limit.inSeconds}秒たっても終わりません。終わったかどうか分からないので、'
          'アプリを開き直してから記録を確かめてください。',
        );
      },
    );
  }

  /// 順番待ちの中でだけ呼べる処理の入口で使う。外から呼ばれたら失敗させる。
  void checkInside(String what) {
    if (!inWrite) {
      throw StateError('$whatは書き込みの順番待ちの中でだけ行えます（行き違いを防ぐため）。');
    }
  }
}
