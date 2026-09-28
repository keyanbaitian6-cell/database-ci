import 'package:flutter/material.dart';

/// Only the viewer opts into the two-choice presentation. Android and CSV keep
/// their existing interval presentation; the underlying likelihood is shared.
class SettingEstimatePresentation extends InheritedWidget {
  const SettingEstimatePresentation({super.key, required super.child});

  static bool twoChoicesOf(BuildContext context) =>
      context
          .dependOnInheritedWidgetOfExactType<SettingEstimatePresentation>() !=
      null;

  static const explanation =
      '設定はBB/RBが適合する上位2候補（左が1位）。候補外もあり、確定ではありません。'
      '各台の詳細で重みを確認できます。';

  @override
  bool updateShouldNotify(SettingEstimatePresentation oldWidget) => false;
}
