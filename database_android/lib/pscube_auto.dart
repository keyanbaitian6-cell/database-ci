/// P’s CUBEの自動取り込みで、表示中のページの判定結果（assets/pscube_auto_probe.js）から
/// 次にすることを決める。PC版 `AutoPilot.tick`（database/pscube_import.py）と同じ規則。
/// 仕様：database/PSCUBE_AUTO_CAPTURE.md。
const pscubeAutoMaxFailures = 3;

({String? capture, String message}) pscubeAutoDecision(
  Object? probe,
  Set<String> done,
  Map<String, int> failures,
) {
  if (probe is! Map) return (capture: null, message: 'ON・待機：ページの準備待ち');
  final signature = probe['signature'];
  if (probe['busy'] == true) {
    return (capture: null, message: 'ON・保存処理中・完了待ち');
  }
  if (probe['ready'] != true || signature is! String) {
    return (capture: null, message: 'ON・待機：${probe['reason'] ?? 'ページの準備待ち'}');
  }
  if (done.contains(signature)) {
    return (capture: null, message: 'ON・次のページ待ち（同じページは重複保存しません）');
  }
  if ((failures[signature] ?? 0) >= pscubeAutoMaxFailures) {
    return (
      capture: null,
      message: 'ON・同じページで3回失敗したため待機中（内容を確かめて手動で取り込むか、OFF→ONで再開）',
    );
  }
  return (capture: signature, message: 'ON・取り込み中（${probe['kind'] ?? 'ページ'}）');
}

/// 止められた気配の見張り（PC版 `AutoPilot` と同じ規則）。対象のページなのにデータが出ない
/// （人間確認の画面でもない）状態が [blockChecks] 回・[blockSpan] 以上続いたら止める（2026-10-01）。
class PscubeAutoGuard {
  PscubeAutoGuard({
    this.blockChecks = 5,
    this.blockSpan = const Duration(seconds: 60),
  });

  final int blockChecks;
  final Duration blockSpan;
  final _missing = <Duration>[];

  static const blockedMessage =
      'サイトがデータを表示しなくなりました（止められた可能性）。自動取り込みを止めました。時間を空けてから、手動でONにしてください。';

  ({String? capture, String message, bool stop}) decide(
    Object? probe,
    Set<String> done,
    Map<String, int> failures,
    Duration now,
  ) {
    if (probe is Map &&
        probe['missing'] == true &&
        probe['challenge'] != true) {
      _missing.add(now);
      if (_missing.length >= blockChecks && now - _missing.first >= blockSpan) {
        _missing.clear();
        return (capture: null, message: blockedMessage, stop: true);
      }
    } else {
      _missing.clear();
    }
    final decision = pscubeAutoDecision(probe, done, failures);
    return (capture: decision.capture, message: decision.message, stop: false);
  }
}
