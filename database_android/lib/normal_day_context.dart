/// 幸町ノーマルの曜日傾向。採点・候補選択とは独立した表示専用の情報。
const normalDayContextAvailableFrom = '2026-10-17';
const normalDayContextEvidence =
    '出典：保存データの分析（2026/10/17確定）。2,000〜20,000Gの台が対象です。'
    '機種・月の差を調整した勝ち台の割合は、土日が平日より低めでした。'
    '2025/10/16〜12/28の74日で6.1ポイント（週単位の再抽出による条件付き95%区間：3.9〜8.4ポイント）、'
    'あとから足した2025/12/29〜2026/2/28の62日でも6.4ポイント（3.8〜8.7ポイント）、'
    '2026/3/1〜3/26の26日でも8.0ポイント（4.0〜10.5ポイント）です。'
    '合算の設定位置でも同方向でした。'
    '2025/9〜2026/3・2026/8〜10の10か月でも同方向でしたが、部分月を含みます。'
    '土日に設定が低いのか、混雑で長く打たれる台が増えるためかは、閉店後の数値だけではわかりません。'
    '曜日を加えた予測の改善は確認できていません。'
    '機種全体の過去傾向であり、この台の翌日の設定や勝率はわかりません。'
    '候補の点数・順位には反映していません。';

typedef NormalDayContext = ({
  String targetDay,
  bool weekend,
  String title,
  String body,
});

/// machinesには選択店舗・選択日の機種だけを渡す。過去の予測へ遡及しない。
NormalDayContext? normalDayContext(
  String store,
  String day,
  Iterable<String> machines,
) {
  if (store != 'saiwaichou' ||
      !machines.any((m) => m.contains('ジャグラー') || m.contains('ハナハナ')) ||
      !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(day)) {
    return null;
  }
  final parsed = DateTime.tryParse('${day}T00:00:00Z');
  // DateTimeは2/30等を翌月へ丸めるため、元の日付と照合する。
  if (parsed == null ||
      parsed.toIso8601String().substring(0, 10) != day ||
      day.compareTo(normalDayContextAvailableFrom) < 0 ||
      day == '9999-12-31') {
    return null;
  }
  final target = parsed.add(const Duration(days: 1));
  final weekend = target.weekday >= DateTime.saturday;
  final label =
      '${target.month}/${target.day}（${'月火水木金土日'[target.weekday - 1]}）';
  return (
    targetDay: target.toIso8601String().substring(0, 10),
    weekend: weekend,
    title: '$labelの曜日傾向：${weekend ? '土日' : '平日'}',
    body: weekend
        ? '幸町のジャグラー・ハナハナ全体では、過去の土日は平日より低めでした。'
        : '幸町のジャグラー・ハナハナの土日低下傾向には該当しません。'
              '平日の好結果を保証するものではありません。',
  );
}
