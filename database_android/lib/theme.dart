import 'package:flutter/material.dart';

/// Design tokens from the Apple style reference the user provided: a
/// near-white canvas, hairline borders instead of shadows, and exactly one
/// chromatic accent (Apple Blue) reserved for filled buttons and selected
/// states. Link Blue is the text/outline variant -- Apple Blue must never
/// be used as plain text or a border by itself.
class AppColors {
  AppColors._();
  static const appleBlue = Color(0xFF0071E3);
  static const linkBlue = Color(0xFF0066CC);
  static const carbon = Color(0xFF1D1D1F);
  static const frost = Color(0xFFF5F5F7);
  static const ice = Color(0xFFF4F8FB);
  static const ash = Color(0xFF707070);
  static const mist = Color(0xFF858585);
  static const pebble = Color(0xFFE2E2E5);
  static const hairline = Color(0xFFD2D2D7);
}

const _cardRadius = 8.0;

/// 字間。Material の既定は +0.1〜+0.5 と字を広げるが、Apple の文字組みは
/// 大きい文字ほど少しずつ詰める（参考資料：本文17pxで-0.016em）。大きさは
/// 変えず、字間だけを寄せる。日本語が窮屈にならないよう、資料の値より控えめ。
TextStyle _tracking(double spacing, {Color? color}) =>
    TextStyle(letterSpacing: spacing, color: color);

ThemeData buildAppTheme() => ThemeData(
  useMaterial3: true,
  scaffoldBackgroundColor: AppColors.frost,
  colorScheme: const ColorScheme.light(
    primary: AppColors.appleBlue,
    onPrimary: Colors.white,
    secondary: AppColors.linkBlue,
    onSecondary: Colors.white,
    surface: Colors.white,
    onSurface: AppColors.carbon,
    surfaceContainerHighest: AppColors.pebble,
    onSurfaceVariant: AppColors.ash,
    outline: AppColors.hairline,
    error: Color(0xFFD70015),
  ),
  appBarTheme: const AppBarTheme(
    backgroundColor: Colors.white,
    foregroundColor: AppColors.carbon,
    elevation: 0,
    // 下へスクロールしても影を出さない（影ではなく細い線で区切る）。
    scrolledUnderElevation: 0,
    surfaceTintColor: Colors.transparent,
    shape: Border(bottom: BorderSide(color: AppColors.hairline)),
    titleTextStyle: TextStyle(
      color: AppColors.carbon,
      fontSize: 20,
      fontWeight: FontWeight.w600,
      letterSpacing: -0.3,
    ),
  ),
  cardTheme: CardThemeData(
    elevation: 0,
    margin: EdgeInsets.zero,
    color: Colors.white,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(_cardRadius),
      side: const BorderSide(color: AppColors.hairline),
    ),
  ),
  chipTheme: const ChipThemeData(
    backgroundColor: AppColors.pebble,
    labelStyle: TextStyle(color: AppColors.ash, fontSize: 12),
    side: BorderSide.none,
    shape: StadiumBorder(),
    padding: EdgeInsets.symmetric(horizontal: 10, vertical: 4),
  ),
  dividerTheme: const DividerThemeData(
    color: AppColors.hairline,
    thickness: 1,
    space: 1,
  ),
  inputDecorationTheme: InputDecorationTheme(
    filled: true,
    fillColor: Colors.white,
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(_cardRadius),
      borderSide: const BorderSide(color: AppColors.hairline),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(_cardRadius),
      borderSide: const BorderSide(color: AppColors.hairline),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(_cardRadius),
      borderSide: const BorderSide(color: AppColors.appleBlue, width: 2),
    ),
  ),
  filledButtonTheme: FilledButtonThemeData(
    style: FilledButton.styleFrom(
      backgroundColor: AppColors.appleBlue,
      foregroundColor: Colors.white,
      shape: const StadiumBorder(),
      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
      textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
    ),
  ),
  outlinedButtonTheme: OutlinedButtonThemeData(
    style: OutlinedButton.styleFrom(
      foregroundColor: AppColors.linkBlue,
      side: const BorderSide(color: AppColors.linkBlue),
      shape: const StadiumBorder(),
      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
    ),
  ),
  textButtonTheme: TextButtonThemeData(
    style: TextButton.styleFrom(foregroundColor: AppColors.linkBlue),
  ),
  iconTheme: const IconThemeData(color: AppColors.ash),
  navigationBarTheme: NavigationBarThemeData(
    backgroundColor: Colors.white,
    indicatorColor: AppColors.appleBlue,
    elevation: 0,
    surfaceTintColor: Colors.transparent,
    // 選んだタブの名前は青い丸の外（白地）に出るので、白ではなく濃い色にする
    // （白だと背景に溶けて見えなかった）。アイコンは青い丸の上なので白のまま。
    labelTextStyle: WidgetStateProperty.resolveWith(
      (states) => TextStyle(
        fontSize: 12,
        fontWeight: FontWeight.w600,
        color: states.contains(WidgetState.selected)
            ? AppColors.carbon
            : AppColors.ash,
      ),
    ),
    iconTheme: WidgetStateProperty.resolveWith(
      (states) => IconThemeData(
        color: states.contains(WidgetState.selected)
            ? Colors.white
            : AppColors.ash,
      ),
    ),
  ),
  checkboxTheme: CheckboxThemeData(
    fillColor: WidgetStateProperty.resolveWith(
      (states) => states.contains(WidgetState.selected)
          ? AppColors.appleBlue
          : Colors.transparent,
    ),
    side: const BorderSide(color: AppColors.hairline, width: 1.5),
  ),
  snackBarTheme: SnackBarThemeData(
    backgroundColor: AppColors.carbon,
    contentTextStyle: const TextStyle(color: Colors.white),
    behavior: SnackBarBehavior.floating,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(_cardRadius),
    ),
  ),
  textTheme: TextTheme(
    displayLarge: _tracking(-0.5),
    displayMedium: _tracking(-0.5),
    displaySmall: _tracking(-0.4),
    headlineLarge: _tracking(-0.4),
    headlineMedium: _tracking(-0.3),
    headlineSmall: _tracking(-0.3),
    titleLarge: _tracking(-0.3),
    titleMedium: _tracking(-0.2),
    titleSmall: _tracking(-0.15),
    bodyLarge: _tracking(-0.2),
    bodyMedium: _tracking(-0.15, color: AppColors.carbon),
    bodySmall: _tracking(-0.1, color: AppColors.ash),
    labelLarge: _tracking(-0.1),
    labelMedium: _tracking(0),
    labelSmall: _tracking(0),
  ),
);

enum ScoreTier { high, mid, low }

ScoreTier scoreTier(double? total) {
  if (total == null) return ScoreTier.low;
  if (total >= 80) return ScoreTier.high;
  if (total >= 60) return ScoreTier.mid;
  return ScoreTier.low;
}

/// A tiered score pill: a strong result gets the filled blue pill, a
/// middling one the outlined version, everything else stays neutral gray --
/// the "one accent, used deliberately" rule applied to score scanning
/// instead of buttons.
class ScorePill extends StatelessWidget {
  const ScorePill({
    super.key,
    required this.text,
    required this.tier,
    this.compact = false,
  });
  final String text;
  final ScoreTier tier;

  /// 表の1行に収める小さい版。
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final Color background;
    final Color foreground;
    final Border? border;
    switch (tier) {
      case ScoreTier.high:
        background = AppColors.appleBlue;
        foreground = Colors.white;
        border = null;
      case ScoreTier.mid:
        background = Colors.transparent;
        foreground = AppColors.linkBlue;
        border = Border.all(color: AppColors.linkBlue);
      case ScoreTier.low:
        background = AppColors.pebble;
        foreground = AppColors.ash;
        border = null;
    }
    return Container(
      padding: compact
          ? const EdgeInsets.symmetric(horizontal: 8, vertical: 3)
          : const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(999),
        border: border,
      ),
      child: Text(
        text,
        style: TextStyle(
          color: foreground,
          fontWeight: FontWeight.w600,
          fontSize: compact ? 13 : 14,
        ),
      ),
    );
  }
}
