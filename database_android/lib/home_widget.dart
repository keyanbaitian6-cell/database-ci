import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'list_views.dart' show dayCandidates, nextDayLabel;
import 'models.dart'
    show SlotRecord, isPscubeStore, storeDisplayName, storeNames;

/// ホーム画面のウィジェット（2026-11-04、利用者が選んだ「ホーム画面のウィジェット」。通常版・P’s CUBE版の
/// 両方）へ渡す中身。アプリを開かずに、前回の取り込みの結果と翌日候補が見える。
///
/// ウィジェット（CaptureWidgetProvider.kt）は渡した文をそのまま出すだけ。取り込みの結果は通知と同じ文
/// （`notifyCaptureResult`）、翌日候補は結果画面と同じ計算（`dayCandidates`）の台番号。
const _channel = MethodChannel('database/widget');

/// 値を渡す処理（試験で差し替える）。
Future<void> Function(Map<String, String> values) homeWidgetSender = _send;

/// 今の時刻（試験で差し替える）。
DateTime Function() homeWidgetNow = DateTime.now;

Future<void> _send(Map<String, String> values) async {
  if (!Platform.isAndroid) return;
  await _channel.invokeMethod<void>('update', values);
}

/// メルヘンの自動取り込みの間は true（2026-11-05）。数秒ごとに保存するので、その都度全記録を写して翌日候補を
/// 計算し直すと電池・メモリを余計に使う。取り込みを止めたとき（false に戻ったとき）に1回だけ計算する。
final homeWidgetCapturing = ValueNotifier<bool>(false);

/// 1店の翌日候補（[day] はもとの日。候補はその翌日のもの）。
typedef WidgetCandidates = ({String label, String day, List<int> racks});

/// ウィジェットに出す台番号の数（店ごと）。多いときは「ほかN台」とまとめる。
const homeWidgetRacks = 6;

/// 翌日候補の行。例「★翌日候補 11/5（水）　長町南 12・105・233／幸町 8・77 ほか2台」。
/// 店ごとにもとの日が違うときは、店の後ろに日付を付ける。候補が無ければ空文字。
String homeWidgetCandidateLine(List<WidgetCandidates> stores) {
  final shown = [
    for (final s in stores)
      if (s.racks.isNotEmpty) s,
  ];
  if (shown.isEmpty) return '';
  final days = shown.map((s) => s.day).toSet();
  String racks(List<int> all) {
    final sorted = [...all]..sort();
    final head = sorted.take(homeWidgetRacks).join('・');
    final rest = sorted.length - homeWidgetRacks;
    return rest > 0 ? '$head ほか$rest台' : head;
  }

  final parts = [
    for (final s in shown)
      '${s.label}${days.length > 1 ? '（${nextDayLabel(s.day)}）' : ''} ${racks(s.racks)}',
  ];
  return '★翌日候補${days.length == 1 ? ' ${nextDayLabel(days.single)}' : ''}　${parts.join('／')}';
}

/// ウィジェットでの店の呼び名（メルヘンは取り込み画面の進み具合と同じ短い名前）。
String homeWidgetStoreLabel(String store) =>
    const {'nagamachiminami': '長町南', 'saiwaichou': '幸町'}[store] ??
    storeDisplayName(store);

/// 店ごとに、記録のある最新の日の翌日候補（結果画面と同じ `dayCandidates`、ノーマルタイプの別ページの機種を
/// 除く）。メルヘンの店は決まった順、P’s CUBEの店はその後ろ。重いので compute で呼ぶ。
List<WidgetCandidates> homeWidgetCandidates(List<SlotRecord> records) {
  final latest = <String, String>{};
  for (final r in records) {
    if ((latest[r.store] ?? '').compareTo(r.day) < 0) latest[r.store] = r.day;
  }
  final order = [
    for (final store in storeNames.keys)
      if (latest.containsKey(store)) store,
    for (final store in latest.keys.toList()..sort())
      if (isPscubeStore(store)) store,
  ];
  return [
    for (final store in order)
      (
        label: homeWidgetStoreLabel(store),
        day: latest[store]!,
        racks: [
          for (final c in dayCandidates(
            [
              for (final r in records)
                if (r.store == store && r.day == latest[store]) r,
            ],
            records,
            excludeNormal: true,
          ).candidates)
            c.record.rack,
        ],
      ),
  ];
}

String _stamp() {
  final now = homeWidgetNow();
  return '更新 ${now.month}/${now.day} ${now.hour}:${now.minute.toString().padLeft(2, '0')}';
}

/// 前回の取り込みの結果を渡す（通知と同じ文。いつの結果か分かるよう、見出しに時刻を付ける）。
Future<void> updateHomeWidgetStatus(String title, String text) {
  final now = homeWidgetNow();
  final at =
      '${now.month}/${now.day} ${now.hour}:${now.minute.toString().padLeft(2, '0')}';
  return _update({'status': '$title（$at）\n$text'});
}

/// 翌日候補を渡す。
Future<void> updateHomeWidgetCandidates(List<WidgetCandidates> stores) =>
    _update({'candidates': homeWidgetCandidateLine(stores)});

Future<void> _update(Map<String, String> values) async {
  try {
    await homeWidgetSender({...values, 'updated': _stamp()});
  } catch (_) {
    // ウィジェットを書き換えられなくても、取り込み・画面は止めない。
  }
}
