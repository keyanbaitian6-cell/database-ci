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
Future<void> waitForPscubeList({
  required Future<PscubeListView> Function(PscubeScroll action) scroll,
  required bool Function() isCurrent,
  int? expectedCount,
  Future<void> Function(Duration)? delay,
}) async {
  final wait = delay ?? (duration) => Future<void>.delayed(duration);
  var last = -1;
  var quiet = 0;
  var nudges = 0;
  // 最後に増えてから少し戻った回数（台数不明の一覧の終わりの判定）。
  var idleNudges = 0;
  var armed = true;
  var action = PscubeScroll.none;
  for (var tick = 0; tick < pscubeListMaxTicks; tick++) {
    if (!isCurrent()) return;
    final view = await scroll(action);
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
    final done = expectedCount == null
        ? quiet >= 16 && idleNudges >= pscubeUnknownListNudges
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
        if (++nudges > 5) return;
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
}

/// 1回250ミリ秒で、最長およそ90秒。
const pscubeListMaxTicks = 360;

/// 台数が不明の一覧で、終わる前に少し戻って下へ着き直す回数（PC版 `SCROLL_SCRIPT` と同じ）。
const pscubeUnknownListNudges = 2;
