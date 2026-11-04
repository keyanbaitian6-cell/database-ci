import 'package:flutter/material.dart';

import 'theme.dart';

/// 差枚の一覧（全機種の台一覧）で選んだ台番の末尾（2026-11-05 利用者「差枚一覧で選んだ末尾を、機種一覧でも追えるようにする」）。
/// 選んだ末尾の台番の横に小さな印。同じ店・同じ日の機種の表へ移っても引き継ぐ（台は全部出したまま）。「末尾7 ×」で解除、
/// 店や日付を変えたら解除。閲覧ページだけ（ViewerHome が [viewerSuffixPick] を用意する。Android版では null で出さない）。
/// 共有カレンダー（share_viewer/app.mjs `suffixPicker`）・PC（machine_list.py）も同じ。
class RackSuffixPick {
  const RackSuffixPick(this.store, this.day, this.digit);
  final String store, day;
  final int digit;
}

/// 選んだ末尾。null の間（Android版）は選ぶ欄も印も出さない。
ValueNotifier<RackSuffixPick?>? viewerSuffixPick;

/// 台番の末尾（0〜9）。
int rackSuffix(int rack) => rack.abs() % 10;

/// この店・日で選んでいる末尾（無ければ null）。
int? suffixDigitFor(String store, String day) {
  final pick = viewerSuffixPick?.value;
  return pick != null && pick.store == store && pick.day == day
      ? pick.digit
      : null;
}

/// 店・日がこれと違う選択を消す（日付・店を変えたとき）。
void clearSuffixPickUnless(String? store, String? day) {
  final notifier = viewerSuffixPick;
  final pick = notifier?.value;
  if (pick != null && (pick.store != store || pick.day != day)) {
    notifier!.value = null;
  }
}

/// 台番の横の小さな印「末7」。
class SuffixMark extends StatelessWidget {
  const SuffixMark(this.digit, {super.key, this.size = 10});
  final int digit;
  final double size;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(left: 3),
    padding: const EdgeInsets.symmetric(horizontal: 3),
    decoration: BoxDecoration(
      color: AppColors.appleBlue,
      borderRadius: BorderRadius.circular(4),
    ),
    child: Text(
      '末$digit',
      style: TextStyle(
        color: Colors.white,
        fontSize: size,
        fontWeight: FontWeight.w700,
        height: 1.4,
      ),
    ),
  );
}

/// 末尾を選ぶ欄（0〜9）と、選んでいるときの「末尾7 ×」。[picker] が false なら「末尾7 ×」だけ（機種の表）。
class SuffixPickBar extends StatelessWidget {
  const SuffixPickBar({
    super.key,
    required this.store,
    required this.day,
    this.picker = true,
  });
  final String store, day;
  final bool picker;

  @override
  Widget build(BuildContext context) {
    final notifier = viewerSuffixPick;
    if (notifier == null) return const SizedBox.shrink();
    final digit = suffixDigitFor(store, day);
    if (!picker && digit == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Wrap(
        spacing: 6,
        runSpacing: 6,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          if (picker) ...[
            const Text('末尾', style: TextStyle(color: AppColors.ash)),
            for (var d = 0; d < 10; d++)
              SizedBox(
                width: 34,
                height: 34,
                child: d == digit
                    ? FilledButton(
                        key: ValueKey('suffix-$d'),
                        style: FilledButton.styleFrom(padding: EdgeInsets.zero),
                        onPressed: () => notifier.value = null,
                        child: Text('$d'),
                      )
                    : OutlinedButton(
                        key: ValueKey('suffix-$d'),
                        style: OutlinedButton.styleFrom(
                          padding: EdgeInsets.zero,
                        ),
                        onPressed: () =>
                            notifier.value = RackSuffixPick(store, day, d),
                        child: Text('$d'),
                      ),
              ),
          ],
          if (digit != null)
            SizedBox(
              height: 34,
              child: OutlinedButton(
                key: const ValueKey('suffix-clear'),
                onPressed: () => notifier.value = null,
                child: Text('末尾$digit ×'),
              ),
            ),
        ],
      ),
    );
  }
}
