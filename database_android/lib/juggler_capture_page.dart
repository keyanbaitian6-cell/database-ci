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

  /// 読み取りの進み具合（全機種表示では数百枚になる）。
  int _done = 0;
  String? _error;
  List<JoDay> _days = const [];
  final _problems = <String>[];
  final _saved = <String>{};
  bool _saving = false;

  /// 店舗・営業日ごとの、読み取りに使った画面のファイル。保存できたら消す（利用者「正常に取り込んだら勝手にけして」）。
  final _sources = <String, List<String>>{};

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
    final read = <(String, List<JoTextLine>, JoScreen)>[];
    try {
      final now = DateTime.now();
      for (final path in _captures) {
        if (mounted) setState(() => _done = read.length + _problems.length);
        // 1枚読めなくても、ほかの画面は読み続ける。
        final List<JoTextLine> lines;
        try {
          final text = await recognizer.processImage(
            InputImage.fromFilePath(path),
          );
          lines = [
            for (final block in text.blocks)
              for (final line in block.lines)
                JoTextLine(line.text, top: line.boundingBox.top.round()),
          ];
        } catch (error) {
          _problems.add('${_captureLabel(path)}：文字（店名・日付）を読めませんでした：$error');
          continue;
        }
        read.add((path, lines, await compute(_parse, (path, lines, now))));
      }
      // 連続で撮った画面は、スクロールで画面の外に出た店名・機種名を同じ組の画面から補う。
      final filled = fillJoGroupHeaders([
        for (final (path, _, screen) in read) (joCaptureGroup(path), screen),
      ]);
      // 全機種表示：見出しが画面の外に出た台の機種名を、前の画面・1ページ目から補う。
      fillJoRackMachines([
        for (var i = 0; i < read.length; i++)
          (joCaptureGroup(read[i].$1), filled[i]),
      ]);
      final screens = <JoScreen>[];
      _sources.clear();
      for (var i = 0; i < read.length; i++) {
        final (path, lines, _) = read[i];
        final screen = filled[i];
        final name = _captureLabel(path);
        if (screen.problem != null) {
          _problems.add('$name：${screen.problem}');
        } else if (screen.header.store == null || screen.header.day == null) {
          // どの画面か・何と読んだかが分かるように（撮り直しと、読み取りの直しのため）。
          final missing = [
            if (screen.header.store == null) '店舗',
            if (screen.header.day == null) '日付',
          ].join('と');
          final text = lines
              .map((l) => l.text.trim())
              .where((t) => t.isNotEmpty)
              .take(8)
              .join('／');
          _problems.add(
            '$name：$missingを読めませんでした。この画面は撮り直してください'
            '（メルヘンの幸町・長町南の「データ一覧」だけ読めます）。読めた文字：$text',
          );
        } else {
          screens.add(screen);
          _sources
              .putIfAbsent(
                '${screen.header.store}|${screen.header.day}',
                () => [],
              )
              .add(path);
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
      final plan = planJoSave(day, widget.controller.records);
      final result = await widget.controller.attachJugglerOnline(
        store: day.store,
        day: day.day,
        racks: plan.add,
        create: plan.create,
      );
      // 保存できたら、その日の画面は消す（読めなかった画面は撮り直しの目安に残す）。
      final key = '${day.store}|${day.day}';
      final saved = result.updated + result.created > 0;
      final used = saved
          ? (_sources.remove(key) ?? const <String>[])
          : const <String>[];
      var deleted = 0;
      if (used.isNotEmpty) {
        deleted = await _channel.invokeMethod<int>('delete', used) ?? 0;
      }
      await _refresh();
      if (!mounted) return;
      setState(() => _saved.add(key));
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${deleted == 0 ? '' : '撮った画面$deleted枚を消しました。'}'
            '${result.updated}台に足しました。'
            '${result.created == 0 ? '' : '${result.created}台を作りました（グラフ無し）。'}'
            '${result.missing.isEmpty ? '' : '取り込んでいない台（${result.missing.join('・')}番）は足していません。'}',
          ),
        ),
      );
    } catch (error) {
      if (mounted) setState(() => _error = '保存できませんでした：$error');
    }
  }

  /// 保存できる日（まだ保存していない・足す台か作る台がある日）。
  List<JoDay> _savableDays() {
    final records = widget.controller.records;
    return [
      for (final day in _days)
        if (!_saved.contains('${day.store}|${day.day}') &&
            _hasWork(planJoSave(day, records)))
          day,
    ];
  }

  /// 「読み取る」の隣の保存ボタン：読み取った日をまとめて保存する（1日ずつ順に）。
  Future<void> _saveAll() async {
    if (_saving) return;
    setState(() => _saving = true);
    try {
      for (final day in _savableDays()) {
        await _save(day);
        if (!mounted) return;
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _deleteAll() async {
    await _channel.invokeMethod<int>('delete', _captures);
    if (!mounted) return;
    setState(() {
      _days = const [];
      _problems.clear();
      _sources.clear();
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
                'お試し（最長2週間）。ジャグラーオンラインの「データ一覧」で「取込」ボタンを1回押すと、表のいちばん上から'
                '下まで（BB〜総回転数のページ）と、差枚のページを自動でスクロールしながら撮ります（止めるときはホームに戻る）。'
                'ここで読み取って確認し、メルヘンの同じ日・同じ台に差枚などを足します（差枚はこちらを優先）。'
                'メルヘンで取り込めなかった台は、前の日の同じ台番号の機種名で作ります。保存できた日の画面は自動で消します。',
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
                          'ボタンはジャグラーオンラインを表示している間だけ出ます（指でずらせる、長押しでこのアプリ）。'
                          '自動でスクロールするため、更新後は一度このサービスをオフにしてからオンにし直す必要があることがあります。'
                          '出ないときは、一度ホーム画面に戻ってからジャグラーオンラインを開き直してください。',
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
          JoReadSaveButtons(
            readLabel: _reading ? '読み取り中 $_done/${_captures.length}枚' : '読み取る',
            onRead: _captures.isEmpty || _reading || _saving ? null : _read,
            saveLabel: joSaveButtonLabel(
              days: _days.length,
              savable: _savableDays().length,
              saved: _saved.length,
              saving: _saving,
            ),
            onSave: _reading || _saving || _savableDays().isEmpty
                ? null
                : _saveAll,
            onDeleteAll: _captures.isEmpty || _reading || _saving
                ? null
                : _deleteAll,
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
    final machines = day.rackMachines.values.toSet();
    final plan = planJoSave(day, records);
    final inDb = plan.add.length, toCreate = plan.create.length;
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
            if (machines.length > 1)
              Text('ジャグラーオンライン：全機種表示（${machines.length}機種）')
            else if (day.machine != null)
              Text('ジャグラーオンライン：${displayMachineName(day.machine!)}'),
            Text(
              '読めた台 ${racks.length}台（メルヘンで取り込み済み $inDb台）。'
              '${toCreate == 0 ? '' : 'メルヘンに無い$toCreate台は、前の日の同じ台番号の機種名で作ります（グラフ・最大持玉は無し）。'}'
              '${_skipSummary(plan)}'
              '?＝読めなかった、⚠＝画面ごとに値が違った（足さない。撮り直すと直ります）、—＝その画面を撮っていない',
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
                columns: [
                  const DataColumn(label: Text('台')),
                  if (machines.length > 1) const DataColumn(label: Text('機種')),
                  const DataColumn(label: Text('BB'), numeric: true),
                  const DataColumn(label: Text('RB'), numeric: true),
                  const DataColumn(label: Text('スタート'), numeric: true),
                  const DataColumn(label: Text('総回転'), numeric: true),
                  const DataColumn(label: Text('差枚'), numeric: true),
                  const DataColumn(label: Text('メルヘン')),
                ],
                rows: [
                  for (final rack in racks)
                    DataRow(
                      cells: [
                        DataCell(Text('$rack')),
                        if (machines.length > 1)
                          DataCell(
                            SizedBox(
                              width: 120,
                              child: Text(
                                displayMachineName(
                                  day.rackMachines[rack] ?? '—',
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ),
                        DataCell(Text(cell(rack, 'bb'))),
                        DataCell(Text(cell(rack, 'rb'))),
                        DataCell(Text(cell(rack, 'start'))),
                        DataCell(Text(cell(rack, 'total'))),
                        DataCell(Text(cell(rack, 'net'))),
                        DataCell(
                          Text(
                            _dbText(
                              recordOf(rack),
                              day.racks[rack]!,
                              plan,
                              rack,
                            ),
                          ),
                        ),
                      ],
                    ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            // 保存のボタンは画面の上（「読み取る」の隣）。ここには保存すると何をするかだけ出す。
            Text(
              saved
                  ? '保存しました'
                  : '保存すると：${[if (inDb > 0) '取り込み済みの$inDb台に足す', if (toCreate > 0) '$toCreate台を作る'].join('・').ifEmpty('足せる台がありません')}',
              style: TextStyle(
                fontWeight: FontWeight.w700,
                color: saved ? AppColors.appleBlue : null,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// メルヘンの記録との違い（BB・RB・総回転数）。足すのは差枚などで、メルヘンの数値は変えない。
  String _dbText(
    SlotRecord? record,
    Map<String, int> values,
    JoSavePlan plan,
    int rack,
  ) {
    if (record == null) {
      final create = plan.create[rack];
      if (create != null) {
        return 'なし→作る（${create.reference.day.substring(5).replaceAll('-', '/')}の機種名）';
      }
      return 'なし（${plan.skipped[rack] ?? '足さない'}）';
    }
    final diffs = [
      if (values['bb'] != null && values['bb'] != record.bb) 'BB${record.bb}',
      if (values['rb'] != null && values['rb'] != record.rb) 'RB${record.rb}',
      if (values['total'] != null && values['total'] != record.games)
        '${record.games}G',
    ];
    return diffs.isEmpty ? 'あり' : 'あり（メルヘン：${diffs.join(' ')}）';
  }
}

bool _hasWork(JoSavePlan plan) => plan.add.isNotEmpty || plan.create.isNotEmpty;

/// 「読み取る」と「保存」を横に並べる（利用者 2026-10-11「読み取ったあとの保存ボタンを読み取ると
/// 並べて配置してほしい」）。以前の保存ボタンは、日ごとの表（数十〜数百台）のいちばん下にあった。
/// 「撮った画面を消す」はその下の行。null のボタンは押せない。
class JoReadSaveButtons extends StatelessWidget {
  const JoReadSaveButtons({
    super.key,
    required this.readLabel,
    required this.onRead,
    required this.saveLabel,
    required this.onSave,
    required this.onDeleteAll,
  });
  final String readLabel, saveLabel;
  final VoidCallback? onRead, onSave, onDeleteAll;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Row(
        children: [
          Expanded(
            child: FilledButton.icon(
              key: const ValueKey('jo-read'),
              onPressed: onRead,
              icon: const Icon(Icons.document_scanner_outlined),
              label: Text(readLabel),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: FilledButton.icon(
              key: const ValueKey('jo-save'),
              onPressed: onSave,
              icon: const Icon(Icons.save_outlined),
              label: Text(saveLabel),
            ),
          ),
        ],
      ),
      // 保存できた日の画面は自動で消すので、手で消すボタンは小さく（利用者 2026-10-11）。
      Align(
        alignment: Alignment.centerRight,
        child: TextButton(
          key: const ValueKey('jo-delete'),
          onPressed: onDeleteAll,
          style: TextButton.styleFrom(
            visualDensity: VisualDensity.compact,
            padding: const EdgeInsets.symmetric(horizontal: 8),
            textStyle: const TextStyle(fontSize: 12),
          ),
          child: const Text('撮った画面を消す'),
        ),
      ),
    ],
  );
}

/// 保存ボタンの文字。[days]：読み取った日の数、[savable]：まだ保存していない・足せる台がある日の数、
/// [saved]：保存した日の数。
String joSaveButtonLabel({
  required int days,
  required int savable,
  required int saved,
  required bool saving,
}) {
  if (saving) return '保存中…';
  if (days == 0) return '保存';
  if (savable == 0) return saved > 0 ? '保存しました' : '足せる台なし';
  return savable == 1 ? '保存' : '保存（$savable日分）';
}

/// 足さない・作らない台の理由ごとの台数（「作らない：前の日に無い 12台、機種が違う 3台」）。
String _skipSummary(JoSavePlan plan) {
  if (plan.skipped.isEmpty) return '';
  final counts = <String, int>{};
  for (final reason in plan.skipped.values) {
    final key = reason.split('（').first.replaceAll('ので', '・');
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return '足さない・作らない台：'
      '${counts.entries.map((e) => '${e.key} ${e.value}台').join('、')}。';
}

/// 撮った画面のファイル名（jo-20261010-001530-123.png）から「10/10 00:15:30に撮った画面」。
String _captureLabel(String path) {
  final file = path.split(RegExp(r'[\\/]')).last;
  final m = RegExp(r'jo-\d{4}(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})')
      .firstMatch(file);
  if (m == null) return file;
  return '${int.parse(m.group(1)!)}/${int.parse(m.group(2)!)} '
      '${m.group(3)}:${m.group(4)}:${m.group(5)}に撮った画面';
}

extension on String {
  String ifEmpty(String other) => isEmpty ? other : this;
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
