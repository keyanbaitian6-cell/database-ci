import 'dart:async';
import 'dart:convert';

/// One outstanding request at a time. Navigation invalidates both active and
/// queued reads so a reply from an old document cannot be used for a new page.
class WebExtractionChannel {
  WebExtractionChannel({this.timeout = const Duration(seconds: 15)});
  final Duration timeout;
  Future<void> _tail = Future<void>.value();
  Completer<Object?>? _pending;
  int _id = 0;
  int _page = 0;
  bool _closed = false;

  Future<Object?> run(Future<void> Function(int id) send) {
    final page = _page;
    final result = _tail.then<Object?>((_) async {
      if (_closed || page != _page) {
        throw const FormatException('ページが切り替わったため読み取りを中止しました。');
      }
      final pending = Completer<Object?>();
      _pending = pending;
      final id = ++_id;
      final reply = pending.future.timeout(
        timeout,
        onTimeout: () {
          throw const FormatException('ページから応答がありません。表示を確認して再試行してください。');
        },
      );
      // A failed send completes the same reply, rather than leaving a timeout.
      unawaited(
        Future<void>.sync(() => send(id)).catchError((Object error) {
          if (!pending.isCompleted) pending.completeError(error);
        }),
      );
      try {
        return await reply;
      } finally {
        if (identical(_pending, pending)) _pending = null;
      }
    });
    _tail = result.then<void>((_) {}, onError: (Object error, StackTrace stack) {});
    return result;
  }

  void receive(String message) {
    try {
      final reply = jsonDecode(message);
      final pending = _pending;
      if (reply is! Map ||
          reply['id'] != _id ||
          pending == null ||
          pending.isCompleted) {
        return;
      }
      if (reply['error'] != null) {
        pending.completeError(FormatException('${reply['error']}'));
      } else {
        pending.complete(reply['value']);
      }
    } on FormatException {
      // Unrelated messages do not consume the pending request.
    }
  }

  void navigationStarted() {
    _page++;
    final pending = _pending;
    _pending = null;
    if (pending != null && !pending.isCompleted) {
      pending.completeError(const FormatException('ページが切り替わったため読み取りを中止しました。'));
    }
  }

  void dispose() {
    _closed = true;
    navigationStarted();
  }
}
