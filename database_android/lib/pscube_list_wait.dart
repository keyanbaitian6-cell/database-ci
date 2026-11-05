import 'dart:async';

/// 一覧に対して行うスクロールの種類。
enum PscubeScroll {
  /// 動かさず、台数と位置だけ読む。
  none,

  /// 画面の8割ほど下へ進む。
  step,

  /// 最後の台を見せて、一番下へ。サイトは一番下に着いたときに続きを読み込む。
  arrive,

  /// 少し上に戻る（読み込みが始まらなかったとき、もう一度下へ着くため）。
  nudge,
}

/// スクロール後の一覧の様子。[count] が負なら一覧が無いページ。
typedef PscubeListView = ({int count, bool atBottom});

/// 台数の多い機種の全台一覧を、サイトの続きの読み込みに合わせて表示する。
/// PC版 `SCROLL_SCRIPT`（database/pscube_import.py）と同じ動き。
///
/// 以前は350ミリ秒ごとに毎回一番下へ飛んでいたため、読み込みの途中で何度も押し込んで
/// 詰まることがあった（2026-10-04、利用者の報告）。今は少しずつ進み、一番下に着いたら
/// 新しい台が出るまで待つ（待つ間は下へ押し込まない）。1秒（4回）増えなくても急がず、
/// 4秒増えないときだけ少し戻ってもう一度下へ進む（最大5回）。
/// 設置台数が分かっていれば届いたところで終わる。不明（機種一覧）なら、一番下で4秒増えないことを、
/// 少し戻ってもう一度下へ着き直しながら3回続けて確かめてから終わる（およそ12秒以上）。
/// 以前は一番下で3秒増えなければ終わり、20件ずつ届く機種一覧を20件・40件で読み取って、残りの機種を
/// 取り込まずに「すべて取り込みました」で止まった（2026-10-24〜26、Android）。
///
/// 機種一覧では [lastShown]（前回の一覧の最後の機種が出たか。スクロールの問い合わせごとに読み直す）を渡す。出たら、
/// 入れ替えでその後ろに新台が増えた日のために、一番下で4秒増えないことを着き直し1回で確かめてから終わる。出ないうちは
/// 一番下で4秒増えないときの着き直しを [pscubeIndexMissingLastNudges] 回まで続ける（2026-11-05
/// 利用者「いったん下まで行く→機種読み込まれたのを確認→また下まで行く。いまならうみねこを確認するまでやる」。PC版
/// `SCROLL_SCRIPT` の expectedLast と同じ）。撤去でその機種が無い日は、着き直しを使い切って終わる。
Future<void> waitForPscubeList({
  required Future<PscubeListView> Function(PscubeScroll action) scroll,
  required bool Function() isCurrent,
  int? expectedCount,
  bool Function()? lastShown,
  Future<void> Function(Duration)? delay,
  Duration Function()? elapsed,
}) async {
  final clock = Stopwatch()..start();
  final now = elapsed ?? () => clock.elapsed;
  final started = now();
  final pause = delay ?? (duration) => Future<void>.delayed(duration);
  FormatException timeout() => const FormatException(pscubeListTimeoutMessage);
  final limit = expectedCount == null
      ? pscubeIndexListTimeout
      : pscubeListTimeout;
  final maxTicks = expectedCount == null
      ? pscubeIndexListMaxTicks
      : pscubeListMaxTicks;
  Duration remaining() {
    final left = limit - (now() - started);
    if (left <= Duration.zero) throw timeout();
    return left;
  }

  Future<T> bounded<T>(Future<T> Function() action) async {
    final left = remaining();
    final value = await action().timeout(
      left,
      onTimeout: () => throw timeout(),
    );
    remaining();
    return value;
  }

  Future<void> wait(Duration duration) => bounded(() {
    final left = remaining();
    return pause(duration < left ? duration : left);
  });
  var last = -1;
  var quiet = 0;
  var nudges = 0;
  // 最後に増えてから少し戻った回数（台数不明の一覧の終わりの判定）。
  var idleNudges = 0;
  var armed = true;
  var action = PscubeScroll.none;
  for (var tick = 0; tick < maxTicks; tick++) {
    if (!isCurrent()) return;
    final view = await bounded(() => scroll(action));
    action = PscubeScroll.none;
    if (!isCurrent() || view.count < 0) return;
    if (view.count > last) {
      // 続きが届いた：描画が落ち着くのを待ち、新しい最後の台まで、もう一度下へ。
      last = view.count;
      quiet = 0;
      armed = true;
      nudges = 0;
      idleNudges = 0;
      await wait(const Duration(milliseconds: 400));
    } else if (view.atBottom) {
      quiet++;
    }
    // 件数がちょうど20の倍数で止まったときは、続きがある見込みが高いので、着き直す回数を増やす
    // （2026-11-03、11/1は20件・11/2は40件の区切りで止まった一覧を読み取った）。
    final needed = lastShown != null
        ? (lastShown() ? 1 : pscubeIndexMissingLastNudges)
        : last > 0 && last % pscubeListChunk == 0
        ? pscubeUnknownListChunkNudges
        : pscubeUnknownListNudges;
    final done = expectedCount == null
        ? quiet >= 16 && idleNudges >= needed
        : view.count >= expectedCount && quiet >= 1;
    if (done) {
      await wait(const Duration(milliseconds: 300));
      return;
    }
    if (view.atBottom) {
      if (armed) {
        action = PscubeScroll.arrive;
        armed = false;
      } else if (quiet >= 16) {
        if (++nudges > (needed > 5 ? needed : 5)) return;
        idleNudges++;
        action = PscubeScroll.nudge;
        armed = true;
        quiet = 0;
        await wait(const Duration(milliseconds: 400));
      }
    } else {
      action = PscubeScroll.step;
      armed = true;
    }
    await wait(const Duration(milliseconds: 250));
  }
  throw timeout(); // 回数の安全上限でも、未完了の一覧を保存させない。
}

/// 追加待機・WebViewの問い合わせも含む時間上限。
const pscubeListTimeout = Duration(seconds: 90);

/// 一覧の読み込みの時間切れの文（自動取り込みは、この失敗を3回で止めずに読み直す。2026-11-04）。
const pscubeListTimeoutMessage = '一覧の読み込みが時間切れになりました。保存せずに再試行します。';

/// ループ回数の安全上限。実時間の上限は [pscubeListTimeout]。
const pscubeListMaxTicks = 360;

/// 台数が不明の一覧（機種一覧）の時間とループ回数の上限。20件の区切りで止まったときに着き直しを増やした分
/// （2026-11-03）、長い一覧でも読み切れるよう長くする。同じページの中で下へ送るだけで、サイトへのアクセスは増えない。
/// PC版 `SCROLL_SCRIPT` と同じ。
const pscubeIndexListTimeout = Duration(seconds: 120);
const pscubeIndexListMaxTicks = 480;

/// 台数が不明の一覧で、終わる前に少し戻って下へ着き直す回数（PC版 `SCROLL_SCRIPT` と同じ）。
const pscubeUnknownListNudges = 2;

/// サイトが機種一覧を届ける件数と、件数がちょうどその倍数で止まったときに着き直す回数（PC版と同じ）。
const pscubeListChunk = 20;
const pscubeUnknownListChunkNudges = 3;

/// 機種一覧で、前回の一覧の最後の機種がまだ出ないときに着き直す回数（約30秒。PC版と同じ、2026-11-05）。
const pscubeIndexMissingLastNudges = 6;
