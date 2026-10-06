import 'dart:convert';
import 'dart:math';

import 'auto_capture_state.dart';

/// P’s CUBEの自動取り込みで、表示中のページの判定結果（assets/pscube_auto_probe.js）から
/// 次にすることを決める。PC版 `AutoPilot.tick`（database/pscube_import.py）と同じ規則。
/// 仕様：database/PSCUBE_AUTO_CAPTURE.md。
const pscubeAutoMaxFailures = 3;

/// 営業日（yyyy-mm-dd）。日本時間の午前2時まではまだ前日（利用者の指定、2026-10-04）。
/// PC版 `business_day`・`recent_business_days`（database/pscube_import.py）と同じ規則。
const pscubeBusinessDayCutoffHour = 2;

String pscubeBusinessDay([DateTime? now]) {
  final day = (now ?? DateTime.now()).subtract(
    const Duration(hours: pscubeBusinessDayCutoffHour),
  );
  String two(int value) => value.toString().padLeft(2, '0');
  return '${day.year}-${two(day.month)}-${two(day.day)}';
}

/// 取り込み日として選べる営業日（新しい順）。サイトが見せるのは本日〜6日前の7日分。
List<String> pscubeRecentBusinessDays([DateTime? now, int count = 7]) {
  final latest = DateTime.parse('${pscubeBusinessDay(now)}T00:00:00Z');
  return [
    for (var i = 0; i < count; i++)
      latest.subtract(Duration(days: i)).toIso8601String().substring(0, 10),
  ];
}

String _shortDay(String day) {
  final parts = day.split('-');
  return '${int.parse(parts[1])}/${int.parse(parts[2])}';
}

/// [targetDay]：取り込み日を指定しているとき。違う日のページは取り込まず待つ
/// （サイトのボタンはアプリが押さない。アプリが開く全台一覧は日付つきのURLで開く（`pscubeTableUrlForDay`）ので、
/// ここで待つのは利用者が自分で開いた全台一覧だけ。日付タブを手で合わせてもらう）。
({String? capture, String message}) pscubeAutoDecision(
  Object? probe,
  Set<String> done,
  Map<String, int> failures, {
  String? targetDay,
}) {
  if (probe is! Map) return (capture: null, message: 'ON・待機：ページの準備待ち');
  final signature = probe['signature'];
  if (probe['busy'] == true) {
    return (capture: null, message: 'ON・保存処理中・完了待ち');
  }
  if (probe['ready'] != true || signature is! String) {
    return (capture: null, message: 'ON・待機：${probe['reason'] ?? 'ページの準備待ち'}');
  }
  final shown = probe['day'];
  if (targetDay != null && shown is String && shown != targetDay) {
    final hint = probe['kind'] == '全台一覧' ? '全台一覧の日付タブを' : 'このページを';
    return (
      capture: null,
      message:
          'ON・待機：取り込み日は${_shortDay(targetDay)}ですが、表示中は${_shortDay(shown)}です。'
          '$hint${_shortDay(targetDay)}に合わせてください',
    );
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

/// 15〜25秒を100マイクロ秒刻みの100,001通りから待機ごとに抽選する。
AutoCaptureState pscubeRandomAutoState({
  Duration Function()? elapsed,
  int Function(int)? nextInt,
}) {
  final draw = nextInt ?? Random.secure().nextInt;
  return AutoCaptureState(
    elapsed: elapsed,
    minTenths: 150,
    maxTenths: 250,
    intervalTenths: 200,
    selectInterval: () => Duration(microseconds: 15000000 + draw(100001) * 100),
  );
}

/// 台別ページの取り込み結果に付いた「差枚は未取得」の理由（無ければ null）。
/// 差枚の元データが取れなくても数値・グラフは保存し、差枚は空欄のまま進む（2026-10-03）。
String? pscubeNetWarning(String raw) {
  try {
    final decoded = jsonDecode(raw);
    final warning = decoded is Map ? decoded['net_warning'] : null;
    return warning is String && warning.isNotEmpty ? warning : null;
  } on FormatException {
    return null;
  }
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
      'サイトがデータを表示しなくなりました（止められた可能性）。自動取り込みを止めました。'
      '時間を空けてから、Cookieを消さずに「もう一度開く」を試してください。';

  /// サイトの記録を消してやり直したとき：それまでの「データが出ない」の数えをやめる。
  void reset() => _missing.clear();

  ({String? capture, String message, bool stop}) decide(
    Object? probe,
    Set<String> done,
    Map<String, int> failures,
    Duration now, {
    String? targetDay,
  }) {
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
    final decision = pscubeAutoDecision(
      probe,
      done,
      failures,
      targetDay: targetDay,
    );
    return (capture: decision.capture, message: decision.message, stop: false);
  }
}
