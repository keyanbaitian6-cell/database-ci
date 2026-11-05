import 'dart:convert';
import 'dart:math';

import 'auto_capture_state.dart';
import 'pscube_store.dart' show pscubeDayTabAbsent;

/// P’s CUBEの自動取り込みで、表示中のページの判定結果（assets/pscube_auto_probe.js）から
/// 次にすることを決める。PC版 `AutoPilot.tick`（database/pscube_import.py）と同じ規則。
/// 仕様：database/PSCUBE_AUTO_CAPTURE.md。
const pscubeAutoMaxFailures = 3;

/// 一覧が進まない（機種一覧が足りない・一覧の読み込みが時間切れ）ときは、3回で止めずに続ける回数（2026-11-04、
/// 利用者「進まない場合は停止じゃなくて読み込み直ししてスクロール作業するようにしてね」）。見張りの間隔（15〜25秒）
/// ごとに1回、[pscubeListReloadEvery] 回に1回だけページを読み込み直し、ほかは同じページで下まで送り直す。
/// 60回で約20分・読み込み直しは約1分に1回（ふだんの取り込みの1分に約3ページより少ない）。それでも進まなければ待機。
const pscubeListMaxRetries = 60;
const pscubeListReloadEvery = 3;

/// 一覧が進まないときにページを読み込み直すのは、この回数まで（2026-11-05 利用者「ABCD実装」のC）。その後は同じページで
/// 下まで送り直すだけにする（通信は増えない）。11/5 0時は、同じページの読み直し1回で60機種そろった。それまでは60回の
/// うち3回に1回、最大約20回読み込み直していた（11/5、サイトにアクセスを拒否された）。
const pscubeListMaxReloads = 3;

/// 自動取り込みがOFFのまま、サイトのページを開いたり取り込んだりしないで、この時間がたったら、サイトのページを空白に
/// する（2026-11-05 利用者「ABCD実装」のA）。サイトのページは開いているだけで定期的に通信する（jquery.netcube.alive.js、
/// AGENTS.md 2026-10-06）。0時の予約を待つ間・手で開いたまま離れたときも、ページを開き続けない。
const pscubeIdlePark = Duration(minutes: 5);

/// 抜けた日を探す範囲（取り込み日を含めて7日。サイトの台別ページが持つ7日、日付指定取り込みの選択肢と同じ）。
const pscubeGapDays = 7;

/// 抜けた日として調べる日（新しい順）。[finished] は今回の自動取り込みで済ませた日（済ませた順）。
/// - 起点は最初に済ませた日だけ（2026-11-05）。取り戻した日を起点にすると、入れ替えの新台（それより前の日の
///   記録が無い）のせいで過去の日が毎回「未取得あり」に見え、記録の最初の日まで1日ずつさかのぼっていた。
///   メルヘンの `_gapBase` と同じ。
/// - サイトの台別ページが持つ7日（[now] の営業日を含む）より古い日は見ない。開いてもその日のタブが無く、
///   1ページずつサイトへのアクセスが増えるだけ（AGENTS.md「対象サイトへのアクセスを増やさない」）。
/// 済ませた日は除く。
List<String> pscubeGapCandidateDays(List<String> finished, DateTime now) {
  if (finished.isEmpty) return const [];
  DateTime utc(String day) => DateTime.parse('${day}T00:00:00Z');
  final base = utc(finished.first);
  final oldest = utc(pscubeBusinessDay(now))
      .subtract(const Duration(days: pscubeGapDays - 1));
  return [
    for (var back = 1; back < pscubeGapDays; back++)
      if (base.subtract(Duration(days: back)) case final d
          when !d.isBefore(oldest))
        if (d.toIso8601String().substring(0, 10) case final iso
            when !finished.contains(iso))
          iso,
  ];
}

/// 営業日（yyyy-mm-dd）。日本時間の午前3時まではまだ前日（利用者の指定、2026-10-04は2時、2026-10-26に3時へ）。
/// PC版 `business_day`・`recent_business_days`（database/pscube_import.py）と同じ規則。
const pscubeBusinessDayCutoffHour = 3;

String pscubeBusinessDay([DateTime? now]) {
  final day = (now ?? DateTime.now()).subtract(
    const Duration(hours: pscubeBusinessDayCutoffHour),
  );
  String two(int value) => value.toString().padLeft(2, '0');
  return '${day.year}-${two(day.month)}-${two(day.day)}';
}

/// 0時の予約（2026-10-26 利用者「0時ちょうどに取り込みが起動して自動取り込みを開始する」案A）。
/// 予約した時刻から見た次の0時（端末の時刻＝日本時間）。
DateTime pscubeNextMidnight(DateTime now) =>
    DateTime(now.year, now.month, now.day + 1);

/// 予約の0時 [armedFor] を過ぎていれば、取り込む日（その時点の営業日＝前日）を返す。
/// まだなら null。営業日が切り替わる3時を過ぎたら（端末が眠っていた等）その夜は始めず、
/// [PscubeMidnight.missed] を返す（次の0時を待つ）。
Object? pscubeMidnightDue(DateTime now, DateTime armedFor) {
  if (now.isBefore(armedFor)) return null;
  final limit = armedFor.add(
    const Duration(hours: pscubeBusinessDayCutoffHour),
  );
  return now.isBefore(limit) ? pscubeBusinessDay(now) : PscubeMidnight.missed;
}

enum PscubeMidnight { missed }

/// 0時の予約を待つ間の画面。null＝普段どおり（予約なし・0時に始めた分が終わって手放した後）、
/// 'bright'＝消さない（23時まで。昼に開いても暗くしない）、'dim'＝消さずに暗く（23時から）。
String? pscubeWaitingScreen({
  required bool reserved,
  required bool released,
  required DateTime now,
}) => !reserved || released ? null : (now.hour >= 23 ? 'dim' : 'bright');

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
/// ただし全台一覧に取り込み日の日付タブが無い（新台・入れ替え）ときだけは読み取りへ進め、保存側
/// （`PscubeStore._skipAbsentDay`）が読み取った日付タブで確かめて飛ばす（2026-10-22、PC版 `AutoPilot._absent_tab` と同じ）。
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
  final days = probe['days'];
  // タブが読めない・取り込み日のタブがある・取り込み日がタブより新しい・台別ページは、今までどおり待つ。
  final absentTab =
      targetDay != null &&
      shown is String &&
      shown != targetDay &&
      probe['kind'] == '全台一覧' &&
      days is List &&
      days.contains(shown) &&
      pscubeDayTabAbsent(targetDay, days);
  if (targetDay != null &&
      shown is String &&
      shown != targetDay &&
      !absentTab) {
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
  return (
    capture: signature,
    message: absentTab
        ? 'ON・${_shortDay(targetDay)}の日付タブが無い機種か確かめています（全台一覧）'
        : 'ON・取り込み中（${probe['kind'] ?? 'ページ'}）',
  );
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

/// 台別ページの差枚の元データの通信が、サイトに拒否された（403＝拒否、429＝アクセスが多すぎる）なら、その状態番号
/// （2026-11-05 利用者「その修正も入れよう」。PCで20:03に差枚の通信だけ403になり、次の台へ進み続けた）。数値は保存
/// するが、自動取り込みは止める。PC版 `net_denied_status` と同じ。
int? pscubeNetDenied(String raw) {
  try {
    final decoded = jsonDecode(raw);
    final records = decoded is Map ? decoded['records'] : null;
    if (records is! List) return null;
    for (final r in records) {
      final capture = r is Map ? r['net_capture'] : null;
      final status = capture is Map ? capture['http_status'] : null;
      if (capture is Map &&
          capture['reason'] == 'network' &&
          (status == 403 || status == 429)) {
        return status as int;
      }
    }
  } on FormatException {
    return null;
  }
  return null;
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
