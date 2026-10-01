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
