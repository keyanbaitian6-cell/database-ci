import 'package:flutter/material.dart';

/// イベント名の最大文字数（メルヘンのイベント名・`web/pscube/data.mjs` の DATE_EVENT_MAX と同じ）。
const eventNameMaxLength = 60;

/// P’s CUBEのイベント名を入力する画面（閲覧ページ・Android共通、2026-10-06）。
///
/// 自由記入だけ。[names]（今までに付けたイベント名、新しく使った順）はプルダウンに出し、
/// 選ぶと入力欄に入る。戻り値は保存する名前、空文字は「イベントなし」（消す）、null は
/// キャンセル。[birthdays]（「名前（作品）」）があれば、イベントとは別にその日のキャラ誕生日を出す。
Future<String?> showEventNameDialog(
  BuildContext context, {
  required String title,
  String? current,
  required List<String> names,
  List<String> birthdays = const [],
}) => showDialog<String?>(
  context: context,
  builder: (_) => EventNameDialog(
    title: title,
    current: current,
    names: names,
    birthdays: birthdays,
  ),
);

class EventNameDialog extends StatefulWidget {
  const EventNameDialog({
    super.key,
    required this.title,
    this.current,
    required this.names,
    this.birthdays = const [],
  });

  final String title;
  final String? current;
  final List<String> names;
  final List<String> birthdays;

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
      // 誕生日が多い日でも入力欄と保存が画面に収まるよう、中身はスクロールできるようにする。
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (widget.birthdays.isNotEmpty) ...[
              const Text(
                'キャラ誕生日（イベントとは別）',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
              ),
              for (final label in widget.birthdays)
                Text(
                  '🎂 $label',
                  key: ValueKey('event-name-birthday-$label'),
                  style: const TextStyle(
                    fontSize: 13,
                    color: Color(0xFF9A4D00),
                  ),
                ),
              const SizedBox(height: 12),
            ],
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
