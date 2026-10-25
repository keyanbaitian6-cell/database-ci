import 'package:flutter/material.dart';

/// 週表のセルの顔文字・記号を選ぶボタン。今の値だけを描き、押したときに選択肢を出す（2026-10-25）。
/// DropdownButton は幅を決めるために全選択肢を常に作るため、閲覧ページの週表（66機種×7日）では
/// 数百の選択欄と数千の絵文字を抱え、iPhoneのSafariが「問題が繰り返し起きました」で落ちた。
/// 読み上げは「[label]」のボタン、選択肢は従来どおり menuitem になる。
class FaceMenuButton extends StatelessWidget {
  const FaceMenuButton({
    super.key,
    required this.label,
    required this.display,
    required this.value,
    required this.options,
    required this.onSelected,
    this.fontSize = 20,
  });

  /// 読み上げの名前（例：「2026-10-26 機種Aの顔文字」）。
  final String label;

  /// セルに出す文字（空欄なら「—」など）。
  final String display;

  /// 今選ばれている値（選択肢を開いたときに印を付ける）。
  final String value;

  /// （値, 選択肢に出す文字）。
  final List<(String, String)> options;

  /// null の間は押せない（保存中など）。
  final ValueChanged<String>? onSelected;
  final double fontSize;

  @override
  Widget build(BuildContext context) {
    final enabled = onSelected != null;
    // PopupMenuButton もセルごとに部品が多く、週表のセル数ぶん重かった。押したときだけ showMenu で出す。
    return Semantics(
      label: label,
      button: true,
      enabled: enabled,
      child: InkWell(
        onTap: enabled ? () => _open(context) : null,
        child: Container(
          height: 32,
          decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: Color(0xffbdbdbd))),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Flexible(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text(display, style: TextStyle(fontSize: fontSize)),
                ),
              ),
              Icon(
                Icons.arrow_drop_down,
                size: 10,
                color: enabled ? null : Theme.of(context).disabledColor,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _open(BuildContext context) async {
    final cell = context.findRenderObject()! as RenderBox;
    final overlay =
        Overlay.of(context).context.findRenderObject()! as RenderBox;
    final position = RelativeRect.fromRect(
      Rect.fromPoints(
        cell.localToGlobal(Offset.zero, ancestor: overlay),
        cell.localToGlobal(
          cell.size.bottomRight(Offset.zero),
          ancestor: overlay,
        ),
      ),
      Offset.zero & overlay.size,
    );
    final chosen = await showMenu<String>(
      context: context,
      position: position,
      initialValue: value,
      items: [
        for (final (choice, text) in options)
          PopupMenuItem(
            value: choice,
            child: Text(text, style: TextStyle(fontSize: fontSize)),
          ),
      ],
    );
    final save = onSelected;
    if (chosen != null && save != null) save(chosen);
  }
}
