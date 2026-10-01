import 'package:flutter/material.dart';

/// 利用者指定のボタンデザイン（CSSの `.btn-grad`、2026-10-01）。
///
/// 背景は #16A085 → #F4D03F（51%）→ #16A085 の横グラデーションを幅200%で敷き、
/// 押している間（マウスなら乗せている間）は0.5秒かけて右端へ流す
/// （CSSの `background-position: right center`）。角丸10・文字は白・
/// 余白は上下15／左右45・影は `0 0 20px #eee`。
class GradientButton extends StatefulWidget {
  const GradientButton({super.key, required this.label, this.onPressed});

  final String label;
  final VoidCallback? onPressed;

  static const colors = [
    Color(0xFF16A085),
    Color(0xFFF4D03F),
    Color(0xFF16A085),
  ];
  static const stops = [0.0, 0.51, 1.0];

  /// 幅200%のグラデーションの左端（ふだん）と右端（押している間）。
  static const restingGradient = LinearGradient(
    colors: colors,
    stops: stops,
    begin: Alignment(-1, 0),
    end: Alignment(3, 0),
  );
  static const shiftedGradient = LinearGradient(
    colors: colors,
    stops: stops,
    begin: Alignment(-3, 0),
    end: Alignment(1, 0),
  );

  @override
  State<GradientButton> createState() => _GradientButtonState();
}

class _GradientButtonState extends State<GradientButton> {
  bool _shifted = false;

  void _shift(bool value) {
    if (_shifted != value) setState(() => _shifted = value);
  }

  @override
  Widget build(BuildContext context) {
    final enabled = widget.onPressed != null;
    final radius = BorderRadius.circular(10);
    return Semantics(
      button: true,
      enabled: enabled,
      child: Opacity(
        opacity: enabled ? 1 : 0.5,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 500),
          decoration: BoxDecoration(
            borderRadius: radius,
            gradient: _shifted
                ? GradientButton.shiftedGradient
                : GradientButton.restingGradient,
            boxShadow: const [
              BoxShadow(color: Color(0xFFEEEEEE), blurRadius: 20),
            ],
          ),
          child: Material(
            type: MaterialType.transparency,
            child: InkWell(
              borderRadius: radius,
              onTap: widget.onPressed,
              onHighlightChanged: enabled ? _shift : null,
              onHover: enabled ? _shift : null,
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  vertical: 15,
                  horizontal: 45,
                ),
                child: Text(
                  widget.label,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
