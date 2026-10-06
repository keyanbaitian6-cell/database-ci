import 'package:flutter/material.dart';

/// イベント名の最大文字数（メルヘンのイベント名・`web/pscube/data.mjs` の DATE_EVENT_MAX と同じ）。
const eventNameMaxLength = 60;

/// P’s CUBEのイベント名を入力する画面（閲覧ページ・Android共通、2026-10-06）。
///
/// 自由記入だけ。[names]（今までに付けたイベント名、新しく使った順）はプルダウンに出し、
/// 選ぶと入力欄に入る。戻り値は保存する名前、空文字は「イベントなし」（消す）、null は
/// キャンセル。
Future<String?> showEventNameDialog(
  BuildContext context, {
  required String title,
  String? current,
  required List<String> names,
}) => showDialog<String?>(
  context: context,
  builder: (_) => EventNameDialog(title: title, current: current, names: names),
);

class EventNameDialog extends StatefulWidget {
  const EventNameDialog({
    super.key,
    required this.title,
    this.current,
    required this.names,
  });

  final String title;
  final String? current;
  final List<String> names;

  @override
  State<EventNameDialog> createState() => _EventNameDialogState();
}

class _EventNameDialogState extends State<EventNameDialog> {
  late final _text = TextEditingController(text: widget.current ?? '');

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final value = _text.text.trim();
    final chosen = widget.names.contains(value) ? value : null;
    return AlertDialog(
      title: Text(widget.title),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (widget.names.isNotEmpty) ...[
            DropdownButtonFormField<String>(
              key: ValueKey('event-choice-$chosen'),
              initialValue: chosen,
              isExpanded: true,
              decoration: const InputDecoration(labelText: '今までのイベントから選ぶ'),
              items: [
                for (final name in widget.names)
                  DropdownMenuItem(
                    value: name,
                    child: Text(name, overflow: TextOverflow.ellipsis),
                  ),
              ],
              onChanged: (name) => setState(() {
                if (name != null) _text.text = name;
              }),
            ),
            const SizedBox(height: 12),
          ],
          TextField(
            controller: _text,
            autofocus: widget.names.isEmpty,
            maxLength: eventNameMaxLength,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(labelText: 'イベント名（自由記入）'),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('キャンセル'),
        ),
        if (widget.current != null)
          TextButton(
            onPressed: () => Navigator.pop(context, ''),
            child: const Text('イベントなしにする'),
          ),
        FilledButton(
          onPressed: value.isEmpty || value.length > eventNameMaxLength
              ? null
              : () => Navigator.pop(context, value),
          child: const Text('保存'),
        ),
      ],
    );
  }
}
