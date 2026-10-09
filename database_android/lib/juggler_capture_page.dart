import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:image/image.dart' as imglib;

import 'app_controller.dart';
import 'juggler_online.dart';
import 'list_views.dart' show dayWithWeekday, displayMachineName;
import 'models.dart';
import 'shared_widgets.dart';
import 'theme.dart';

const _channel = MethodChannel('database/juggler');

/// ジャグラーオンラインの取り込み（お試し、2026-10-09から最長2週間。`JUGGLER_ONLINE.md`）。
/// アクセシビリティの「取込」ボタンで撮った画面を読み、確認してから、取り込み済みの台に差枚などを足す。
class JugglerCapturePage extends StatefulWidget {
  const JugglerCapturePage({super.key, required this.controller});
  final AppController controller;

  @override
  State<JugglerCapturePage> createState() => _JugglerCapturePageState();
}

class _JugglerCapturePageState extends State<JugglerCapturePage>
    with WidgetsBindingObserver {
  bool? _enabled;
  int _sdk = 0;
  List<String> _captures = const [];
  bool _reading = false;
  String? _error;
  List<JoDay> _days = const [];
  final _problems = <String>[];
  final _saved = <String>{};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  // 設定画面から戻ったとき・ジャグラーオンラインで撮って戻ったときに数え直す。
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refresh();
  }

  Future<void> _refresh() async {
    try {
      final status = await _channel.invokeMapMethod<String, Object?>('status');
      if (!mounted || status == null) return;
      setState(() {
        _enabled = status['enabled'] == true;
        _sdk = (status['sdk'] as num?)?.toInt() ?? 0;
        _captures = [
          for (final p in (status['captures'] as List? ?? const []))
            p as String,
        ];
      });
    } catch (error) {
      if (mounted) setState(() => _error = '状態を読めませんでした：$error');
    }
  }

  Future<void> _read() async {
    setState(() {
      _reading = true;
      _error = null;
      _days = const [];
      _problems.clear();
      _saved.clear();
    });
    final recognizer = TextRecognizer(script: TextRecognitionScript.japanese);
    final screens = <JoScreen>[];
    try {
      final now = DateTime.now();
      for (final path in _captures) {
        final text = await recognizer.processImage(
          InputImage.fromFilePath(path),
        );
        final lines = [
          for (final block in text.blocks)
            for (final line in block.lines)
              JoTextLine(line.text, top: line.boundingBox.top.round()),
        ];
        final screen = await compute(_parse, (path, lines, now));
        final name = path.split(RegExp(r'[\\/]')).last;
        if (screen.problem != null) {
          _problems.add('$name：${screen.problem}');
        } else if (screen.header.store == null || screen.header.day == null) {
          _problems.add('$name：店舗か日付を読めませんでした（メルヘンの幸町・長町南の「データ一覧」だけ読めます）。');
        } else {
          screens.add(screen);
        }
      }
      if (mounted) setState(() => _days = mergeJoScreens(screens));
    } catch (error) {
      if (mounted) setState(() => _error = '読み取れませんでした：$error');
    } finally {
      await recognizer.close();
      if (mounted) setState(() => _reading = false);
    }
  }

  Future<void> _save(JoDay day) async {
    try {
      final result = await widget.controller.attachJugglerOnline(
        store: day.store,
        day: day.day,
        racks: day.racks,
      );
      if (!mounted) return;
      setState(() => _saved.add('${day.store}|${day.day}'));
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${result.updated}台に足しました。'
            '${result.missing.isEmpty ? '' : '取り込んでいない台（${result.missing.join('・')}番）は足していません。'}',
          ),
        ),
      );
    } catch (error) {
      if (mounted) setState(() => _error = '保存できませんでした：$error');
    }
  }

  Future<void> _deleteAll() async {
    await _channel.invokeMethod<int>('delete', _captures);
    if (!mounted) return;
    setState(() {
      _days = const [];
      _problems.clear();
    });
    await _refresh();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('ジャグラーオンライン（お試し）')),
    body: SafeArea(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          if (_error != null) Notice(text: _error!),
          const Notice(
            text:
                'お試し（最長2週間）。ジャグラーオンラインの「データ一覧」で、画面の端に出る「取込」ボタンを押して画面を撮り、'
                '右へスクロールした画面（差枚）でももう一度押します。下の台も、スクロールして同じように撮ります。'
                'ここで読み取って確認し、メルヘンで取り込み済みの同じ日・同じ台に差枚などを足します（差枚はこちらを優先）。',
          ),
          Card(
            child: ListTile(
              title: Text(
                '「取込」ボタン：${_enabled == null
                    ? '確認中'
                    : _enabled!
                    ? 'オン'
                    : 'オフ'}',
              ),
              subtitle: Text(
                _sdk > 0 && _sdk < 30
                    ? 'この端末のAndroidでは画面を撮れません（Android 11以降）。'
                    : 'オンにするには、端末の設定の「ユーザー補助（アクセシビリティ）」で'
                          '「database ジャグラーオンライン取込」を選んでオンにします。'
                          'ボタンはジャグラーオンラインを表示している間だけ出ます（指でずらせる、長押しでこのアプリ）。',
              ),
              trailing: _enabled == true
                  ? const Icon(Icons.check_circle, color: AppColors.appleBlue)
                  : TextButton(
                      onPressed: () =>
                          _channel.invokeMethod<void>('openSettings'),
                      child: const Text('設定を開く'),
                    ),
            ),
          ),
          const SizedBox(height: 12),
          Text(
            '撮った画面：${_captures.length}枚',
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: _captures.isEmpty || _reading ? null : _read,
                  icon: const Icon(Icons.document_scanner_outlined),
                  label: Text(_reading ? '読み取り中…' : '読み取る'),
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton(
                onPressed: _captures.isEmpty || _reading ? null : _deleteAll,
                child: const Text('撮った画面を消す'),
              ),
            ],
          ),
          if (_reading)
            const Padding(
              padding: EdgeInsets.only(top: 8),
              child: LinearProgressIndicator(),
            ),
          for (final p in _problems) Notice(text: p),
          for (final day in _days) _dayCard(day),
        ],
      ),
    ),
  );

  Widget _dayCard(JoDay day) {
    final records = widget.controller.records;
    SlotRecord? recordOf(int rack) {
      for (final r in records) {
        if (r.store == day.store && r.day == day.day && r.rack == rack) {
          return r;
        }
      }
      return null;
    }

    final racks = day.racks.keys.toList()..sort();
    final inDb = racks.where((r) => recordOf(r) != null).length;
    final saved = _saved.contains('${day.store}|${day.day}');
    String cell(int rack, String field) {
      final value = day.racks[rack]![field];
      final mark = (day.conflicts[rack]?.contains(field) ?? false) ? '⚠' : '';
      if (value != null) {
        return '${field == 'net' ? signedMedals(value) : value}$mark';
      }
      return (day.unreadable[rack]?.contains(field) ?? false) ? '?' : '—';
    }

    return Card(
      margin: const EdgeInsets.only(top: 16),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${storeDisplayName(day.store)}　${dayWithWeekday(day.day)}',
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
            ),
            if (day.machine != null)
              Text('ジャグラーオンライン：${displayMachineName(day.machine!)}'),
            Text(
              '読めた台 ${racks.length}台（メルヘンで取り込み済み $inDb台）。'
              '?＝読めなかった、⚠＝画面ごとに値が違った、—＝その画面を撮っていない',
              style: const TextStyle(fontSize: 12, color: AppColors.ash),
            ),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                columnSpacing: 14,
                horizontalMargin: 4,
                headingRowHeight: 36,
                dataRowMinHeight: 32,
                dataRowMaxHeight: 40,
                columns: const [
                  DataColumn(label: Text('台')),
                  DataColumn(label: Text('BB'), numeric: true),
                  DataColumn(label: Text('RB'), numeric: true),
                  DataColumn(label: Text('スタート'), numeric: true),
                  DataColumn(label: Text('総回転'), numeric: true),
                  DataColumn(label: Text('差枚'), numeric: true),
                  DataColumn(label: Text('メルヘン')),
                ],
                rows: [
                  for (final rack in racks)
                    DataRow(
                      cells: [
                        DataCell(Text('$rack')),
                        DataCell(Text(cell(rack, 'bb'))),
                        DataCell(Text(cell(rack, 'rb'))),
                        DataCell(Text(cell(rack, 'start'))),
                        DataCell(Text(cell(rack, 'total'))),
                        DataCell(Text(cell(rack, 'net'))),
                        DataCell(
                          Text(_dbText(recordOf(rack), day.racks[rack]!)),
                        ),
                      ],
                    ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: inDb == 0 || saved ? null : () => _save(day),
                child: Text(saved ? '保存しました' : '取り込み済みの$inDb台に足す'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// メルヘンの記録との違い（BB・RB・総回転数）。足すのは差枚などで、メルヘンの数値は変えない。
  String _dbText(SlotRecord? record, Map<String, int> values) {
    if (record == null) return 'なし（足さない）';
    final diffs = [
      if (values['bb'] != null && values['bb'] != record.bb) 'BB${record.bb}',
      if (values['rb'] != null && values['rb'] != record.rb) 'RB${record.rb}',
      if (values['total'] != null && values['total'] != record.games)
        '${record.games}G',
    ];
    return diffs.isEmpty ? 'あり' : 'あり（メルヘン：${diffs.join(' ')}）';
  }
}

JoScreen _parse((String, List<JoTextLine>, DateTime) input) {
  final (path, lines, now) = input;
  final image = imglib.decodePng(File(path).readAsBytesSync());
  if (image == null) {
    return const JoScreen(
      header: JoHeader(),
      side: null,
      racks: [],
      problem: '画像を読めませんでした。',
    );
  }
  return parseJoScreen(image, lines, now);
}
