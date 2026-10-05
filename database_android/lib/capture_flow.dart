import 'dart:async';

/// 取り込みで次の機種へ進むために開いた機種一覧のURLか（読み終えたら、
/// そのまま次の未取り込みの機種を探す）。
bool isNextMachineUrl(String url) =>
    url.contains('rack_info_kt') && url.contains('database_next_machine=1');

/// メルヘンの同じページのURLか。ページの location.href とWebViewの報告では、日本語の
/// 機種名が%の形と元の文字の形に分かれることがあるので、%を戻して比べる（PC版
/// `same_page_url` と同じ規則）。#以降は取り込む日付を持つので比べる。
bool meruhenSamePageUrl(Object? first, Object? second) {
  if (first is! String || second is! String) return first == second;
  String key(String url) {
    try {
      return Uri.decodeFull(url);
    } catch (_) {
      return url;
    }
  }

  return key(first) == key(second);
}

/// 内部ブラウザの取り込み画面の状態。
///
/// 以前は「読み込み中」「読み取り中」などの印を画面のあちこちで別々に立て
/// 下ろししていて、処理が重なったり（取り込みの中から表の読み取りを呼ぶ等）、
/// 読み込みの知らせが来なかったりすると「読み込み中のまま押せない」状態に
/// なることがあった。状態はここにまとめ、変え方もここだけにする。
///
/// * [page]：ページ読み込みの回数（世代）。非同期の処理は始めたときの世代を
///   覚えておき、終わったときに世代が変わっていれば（別のページへ移った）
///   結果を捨てる。
/// * [loading]：ページを読み込み中（取り込みボタンは押せない）。
/// * [busy]：読み取り・保存・移動などの処理中。処理の中から別の処理を呼んで
///   も（入れ子）、いちばん外の処理が終わるまで処理中のまま。
/// * 次のページを読み終えたときの予定（知らせ・次の機種へ進む）は1回きり。
class CaptureFlow {
  CaptureFlow({this.onChanged});

  /// 状態が変わったとき（画面を描き直す）。
  final void Function()? onChanged;

  int get page => _page;
  int _page = 0;

  bool get loading => _loading;
  bool _loading = true;

  bool get busy => _busy > 0;
  int _busy = 0;

  /// 取り込みボタンを押せるか。
  bool get canCapture => !_loading && !busy && !_blocked;
  bool _blocked = false;

  String? _afterLoadNotice;
  bool _advanceAfterLoad = false;
  int _finishedPage = -1;
  final _idleWaiters = <Completer<void>>[];

  bool isCurrent(int page) => page == _page;

  /// ページの読み込みが始まった。新しい世代を返す。次の機種へ進む予定は、
  /// そのための機種一覧を開いたときだけ残す。
  int pageStarted(String url) {
    _page++;
    _loading = true;
    _blocked = false;
    if (!isNextMachineUrl(url)) _advanceAfterLoad = false;
    onChanged?.call();
    return _page;
  }

  /// [page] の読み込みが終わった。同じページについて2回目なら false
  /// （WebViewは同じページの完了を2回知らせることがある）。
  bool pageFinished(int page) {
    if (!isCurrent(page) || _finishedPage == page) return false;
    _finishedPage = page;
    return true;
  }

  /// [page] の表示が整った（補助の読み取りも済んだ）。
  void ready(int page) {
    if (!isCurrent(page)) return;
    _blocked = false;
    _loading = false;
    onChanged?.call();
  }

  /// 自分でページを開く（読み込みの知らせを待つ）。
  void startLoading() {
    if (_loading) return;
    _loading = true;
    onChanged?.call();
  }

  /// 読み込み中の表示を外す（開けなかった・移動しなかったとき）。[page] を
  /// 渡すと、そのページのままのときだけ。
  void stopLoading([int? page]) {
    if (page != null && !isCurrent(page)) return;
    if (!_loading) return;
    _loading = false;
    onChanged?.call();
  }

  /// 時間切れは完了ではない。待機表示は外すが、確認できるまで取り込ませない。
  void loadTimedOut(int page) {
    fail(page);
  }

  void fail(int page) {
    if (!isCurrent(page)) return;
    _blocked = true;
    _loading = false;
    onChanged?.call();
  }

  /// [body] の間は処理中にする（入れ子にできる）。
  Future<T> whileBusy<T>(Future<T> Function() body) async {
    _busy++;
    if (_busy == 1) onChanged?.call();
    try {
      return await body();
    } finally {
      _busy--;
      if (_busy == 0) {
        for (final waiter in _idleWaiters) {
          waiter.complete();
        }
        _idleWaiters.clear();
        onChanged?.call();
      }
    }
  }

  /// 処理中でなくなるまで待つ（処理中でなければすぐ）。
  Future<void> whenIdle() {
    if (!busy) return Future<void>.value();
    final waiter = Completer<void>();
    _idleWaiters.add(waiter);
    return waiter.future;
  }

  /// 次のページを読み終えたら [notice] を出し、[advance] なら次の機種を探す。
  void expectPage({String? notice, bool advance = false}) {
    _afterLoadNotice = notice;
    if (advance) _advanceAfterLoad = true;
  }

  /// 次のページでの予定を取りやめる（移動できなかったとき・別の店へ移るとき）。
  void cancelExpectation() {
    _afterLoadNotice = null;
    _advanceAfterLoad = false;
  }

  /// 次のページで出す知らせ（1回だけ。取ったら消える）。
  String? takeAfterLoadNotice() {
    final notice = _afterLoadNotice;
    _afterLoadNotice = null;
    return notice;
  }

  /// 次の機種を探す予定があるか（1回だけ。取ったら消える）。
  bool takeAdvance() {
    final advance = _advanceAfterLoad;
    _advanceAfterLoad = false;
    return advance;
  }
}
