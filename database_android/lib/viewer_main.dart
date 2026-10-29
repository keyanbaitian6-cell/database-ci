import 'dart:convert';

import 'capture_health_ui.dart';

import 'package:flutter/material.dart';

import 'answer_check.dart';
import 'data_checks.dart';
import 'exploratory_page.dart';
import 'list_views.dart';
import 'machine_sections.dart';
import 'models.dart';
import 'daily_net_page.dart';
import 'date_events.dart';
import 'event_calendar_page.dart';
import 'event_history.dart';
import 'event_name_dialog.dart';
import 'pscube_suffix.dart' show meruhenSuffixStores;
import 'pscube_suffix_page.dart';
import 'rainbow_marks.dart';
import 'remote_curve.dart';
import 'scoring.dart';
import 'setting_estimate_presentation.dart';
import 'shared_widgets.dart';
import 'theme.dart';
import 'variety_idle.dart';
import 'variety_week.dart';
import 'viewer_bridge.dart';
import 'viewer_data.dart';
import 'viewer_pages.dart';

/// iPhoneなどで見るための閲覧専用ページ（Web）。
///
/// `flutter build web -t lib/viewer_main.dart` で作る。取り込み・保存はしない。
/// DriveなどにあるバックアップJSONを端末の中だけで読み、Android版と同じ
/// 採点・翌日候補・表とグラフ（画像は使わず、保存したグラフの線から描く）で見せる。
void main() => runApp(const ViewerApp());

class ViewerApp extends StatelessWidget {
  const ViewerApp({super.key});

  @override
  Widget build(BuildContext context) => SettingEstimatePresentation(
    child: MaterialApp(
      title: 'database 閲覧',
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: const ViewerHome(),
    ),
  );
}

/// [store] の [day] より前の30日間に、記録がある日の数（採点の比較に使える日数）。
int historyDays(List<SlotRecord> all, String store, String day) {
  final first = DateTime.parse(day)
      .subtract(const Duration(days: 30))
      .toIso8601String()
      .substring(0, 10);
  return {
    for (final r in all)
      if (r.store == store &&
          r.day.compareTo(first) >= 0 &&
          r.day.compareTo(day) < 0)
        r.day,
  }.length;
}

class ViewerHome extends StatefulWidget {
  const ViewerHome({super.key, this.initialData});

  /// 読み込み済みの内容で開く場合に指定する（通常はブラウザ内の保存内容を読む）。
  final ViewerData? initialData;
  @override
  State<ViewerHome> createState() => _ViewerHomeState();
}

class _ViewerHomeState extends State<ViewerHome> {
  ViewerData? _data;
  var _loading = true;

  /// Driveの自動読み込みに使う、Googleのスクリプトのアドレス（未設定なら null）。
  String? _remote;
  var _syncing = false;

  /// Driveの最新かどうかを最後に確かめた時刻（中身が同じで読み直さなかったときも）。
  DateTime? _checkedAt;
  String? _error;
  String? _store;
  String? _day;
  final _query = TextEditingController();

  /// 結果のリスト（右下の「一番上へ」ボタンで戻す）。
  final _scroll = ScrollController();

  // 表示中の日の採点（読み込んだ内容・店舗・日付が変わったときだけ計算し直す）。
  // 読み込んだ内容は、読み込むたびに1つ進む番号で見分ける。
  Object? _scoredFor;
  var _dataVersion = 0;
  List<(SlotRecord, ScoreResult)> _digest = const [];
  ({List<ProvisionalCandidate> candidates, int machines, int judged})?
  _candidates;

  /// 本体と別に置いた🌈の印（端末の 'rainbow_marks'、2026-10-29）。起動時に読み、付け外し・共有の
  /// 取り込みで更新する。表示する内容には [_show] で必ず当てる（本体に前から入っている印とは
  /// 付け外しした時刻の新しい方）。読めなかったら [_deviceMarksError] に残し、上書きしない。
  Map<String, RainbowMark> _deviceMarks = const {};
  Object? _deviceMarksError;

  @override
  void initState() {
    super.initState();
    // 台の画面の🌈のボタン（RAINBOW.md「iPhoneから付ける」）。
    viewerRainbowEditor = _editRainbow;
    if (widget.initialData case final data?) {
      _show(data);
      _loading = false;
    } else {
      _start();
    }
  }

  @override
  void dispose() {
    if (viewerRainbowEditor == _editRainbow) viewerRainbowEditor = null;
    _query.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    _remote = loadRemoteUrl();
    await _readDeviceMarks();
    try {
      // 手元での確認用：同じサイト内のファイルを ?load= で読む。
      final url = Uri.base.queryParameters['load'];
      final text = url != null
          ? await backupFromUrl(url)
          : await loadViewerData();
      if (text != null) _show(ViewerData.parse(text));
    } catch (error) {
      _error = '前に読み込んだ内容を開けませんでした。もう一度読み込んでください。\n$error';
    }
    if (mounted) setState(() => _loading = false);
    // 前の内容をすぐ出してから、Driveの最新を読みに行く。
    if (_remote != null && Uri.base.queryParameters['load'] == null) {
      await _refreshFromDrive();
    }
  }

  /// Googleのスクリプト経由で、Driveの最新（database-viewer.json）を読む。
  /// 表示中の内容と同じ書き出しなら、先頭の1行だけで読むのをやめ、組み立て直し・
  /// 保存し直し・採点のやり直しもしない（開くたびに同じ中身を丸ごと読み直すと、
  /// 通信と計算で電池を使うため）。読めなければ、前に読み込んだ内容のまま理由を
  /// 出す。[manual] は利用者が押したとき（変わっていなくても知らせる）。
  Future<void> _refreshFromDrive({bool manual = false}) async {
    final url = _remote;
    if (url == null || _syncing || _loading) return;
    setState(() {
      _syncing = true;
      _error = null;
    });
    try {
      final current = _data;
      final text = await backupFromRemote(
        url,
        unlessExportedAt: current?.exportedAtText,
      );
      if (!mounted) return;
      _checkedAt = DateTime.now();
      if (text == null) {
        final at = current?.exportedAt;
        if (manual && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                'Googleドライブの内容は変わっていません'
                '${at == null ? '' : '（${_when(at)}書き出し）'}。',
              ),
            ),
          );
        }
      } else {
        // 前に読み込んだ内容と合わせる（新しい方を使い、Driveに無い古い日は残す）。
        String? stored;
        try {
          stored = await loadViewerData();
        } on Object {
          stored = null;
        }
        final merged = ViewerData.prepareMerge(stored, text);
        final data = merged.data;
        if (merged.text != stored) {
          await saveViewerData(merged.text, meruhen: data.source != 'pscube');
        }
        if (!mounted) return;
        _show(data);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                merged.note ??
                    'Googleドライブの最新（${data.records.length}台）を読み込みました。',
              ),
            ),
          );
        }
      }
    } catch (error) {
      _error = 'Googleドライブから読めませんでした（前に読み込んだ内容を表示しています）。\n$error';
    }
    // 共有カレンダー：Driveの中身が変わっていなくても、ほかの端末で入れたイベントは取り込む。
    await _pullShared(url);
    if (mounted) setState(() => _syncing = false);
  }

  /// 共有カレンダー（EVENT_CALENDAR.md）：ほかの端末で入れたイベントを取り込む。共有ファイルが
  /// 無い・古いスクリプト・通信の失敗では何もしない（次に読むときにまた試す）。
  Future<void> _pullShared(String url) async {
    final data = _data;
    if (data == null) return;
    try {
      if (data.source == 'pscube') {
        final text = await mergePscubeSharedEvents(
          await fetchSharedEvents(url, 'pscube-events'),
        );
        if (text != null && mounted) {
          setState(() => _show(ViewerData.parse(text)));
        }
        return;
      }
      try {
        final shared = await fetchSharedEvents(url, 'events');
        // 表示中のイベントで変わらないと分かれば、端末の本体は読まない。
        final stored = ViewerData.sharedEventsChange(data.dateEvents, shared)
            ? await loadViewerData()
            : null;
        if (stored != null) {
          final text = ViewerData.withSharedEvents(stored, shared);
          if (text != null) {
            await saveViewerData(text);
            if (mounted) setState(() => _show(ViewerData.parse(text)));
          }
        }
      } on Object {
        // イベントが読めなくても🌈は読む。
      }
      // ほかの端末（別のiPhoneなど）で付け外しした🌈。PCが取り込む前でも表示に入れる。本体とは別の
      // 印だけを書き、本体は読み直さない（本体の書き直しと読み直しで、iPhoneが落ちた、2026-10-29）。
      try {
        final shared = sharedRainbowMarks(
          await fetchSharedEvents(url, 'rainbow'),
        );
        if (shared != null && shared.isNotEmpty) {
          await _addDeviceMarks(shared.values);
        }
      } on Object {
        // 古いスクリプト（🌈を足す前）・通信の失敗では何もしない。
      }
    } on Object {
      // 表示中の内容はそのまま。
    }
  }

  /// 端末の 'rainbow_marks' を読んで [_deviceMarks] にする。読めなければ前の値のまま
  /// [_deviceMarksError] に残す（壊れた印を空で上書きしない）。
  Future<void> _readDeviceMarks() async {
    try {
      _deviceMarks = rainbowMarksFromText(await loadRainbowMarks());
      _deviceMarksError = null;
    } on Object catch (error) {
      _deviceMarksError = error;
    }
  }

  /// 印を足して端末に保存し、表示へ当てる。本体（数十MB）は読み書きしない。全部の印を返す。
  /// ほかのタブが書いた印も落とさないよう、書く直前に読み直して合わせる。
  Future<Map<String, RainbowMark>> _addDeviceMarks(
    Iterable<RainbowMark> incoming,
  ) async {
    await _readDeviceMarks();
    if (_deviceMarksError case final error?) {
      throw StateError('端末の$rainbowMarkの印を読めませんでした：$error');
    }
    final data = _data;
    final current = mergeRainbowMarks(
      data?.rainbowMarks ?? const {},
      _deviceMarks.values,
    ).marks;
    final merged = mergeRainbowMarks(current, incoming);
    if (merged.changed == 0 && _deviceMarks.length == current.length) {
      return current;
    }
    await saveRainbowMarks(rainbowMarksText(merged.marks));
    _deviceMarks = merged.marks;
    final shown = _data;
    if (shown != null && mounted) {
      setState(
        () => _show(shown.withRainbowMarks(merged.marks), rainbowOnly: true),
      );
    }
    return merged.marks;
  }

  /// 台の画面の🌈のボタン（RAINBOW.md「iPhoneから付ける」）：端末に保存してすぐ表示に入れ、
  /// 共有ファイルへ送る（PCは開いたとき・カレンダーやバラエティ🌈のタブを開いたときに取り込む）。
  Future<ViewerData?> _editRainbow(SlotRecord record, bool on) async {
    final data = _data;
    if (data == null || data.source == 'pscube') return null;
    // 印は本体（数十MB）と別の 'rainbow_marks' に書く。本体は読み書きしない（2026-10-29。それまでは
    // 付け外しのたびに本体をまるごと読み書きし、iPhoneで🌈を付けると落ちた）。
    final current = mergeRainbowMarks(
      data.rainbowMarks,
      _deviceMarks.values,
    ).marks;
    final marks = await _addDeviceMarks([
      nextRainbowMark(current, record, on, DateTime.now()),
    ]);
    final next = _data;
    final done = on
        ? '${record.rack}番台に$rainbowMarkを付けました。'
        : '${record.rack}番台の$rainbowMarkを外しました。';
    final url = _remote;
    if (url == null) {
      _say('$done（この端末だけ。PCへ届けるには、Googleドライブの自動読み込みを設定してください）');
      return next;
    }
    try {
      final result = await sendSharedRainbowMarks(
        marks,
        (body) => postSharedEvents(url, body),
        canBatch: () async =>
            sharedRainbowCanBatch(await fetchSharedEvents(url, 'diagnostic')),
      );
      _say(
        result.ok
            ? '$done PCへ送りました（PCで開いたときに取り込みます）。'
            : '$done PCへは送れませんでした（次に付け外しするときにまた送ります）：${result.message}',
      );
    } catch (error) {
      _say('$done PCへは送れませんでした（次に付け外しするときにまた送ります）：$error');
    }
    return next;
  }

  /// 共有カレンダーへ、この端末の入力時刻つきイベントを全部送る（前に送れなかった分も届く）。
  Future<void> _pushShared({required bool pscube}) async {
    final url = _remote;
    final data = _data;
    const saved = 'イベントはこの端末に保存しました。';
    if (url == null || data == null) {
      _say('$saved ほかの端末と共有するには、Googleドライブの自動読み込みを設定してください。');
      return;
    }
    try {
      final body = pscube
          ? jsonEncode({
              'file': 'pscube-events',
              'events': jsonDecode(await pscubeTimedEvents()),
            })
          : ViewerData.sharedEventsBody(data.dateEvents.values);
      final result = ViewerData.sharedResult(await postSharedEvents(url, body));
      _say(
        result.ok
            ? result.message
            : '$saved 共有には送れませんでした（次に保存するときにまた送ります）：${result.message}',
      );
    } catch (error) {
      _say('$saved 共有には送れませんでした（次に保存するときにまた送ります）：$error');
    }
  }

  void _say(String text) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _editRemote() async {
    if (_loading || _syncing) return;
    final field = TextEditingController(text: _remote ?? '');
    final result = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Googleドライブの自動読み込み'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Googleのスクリプト（Apps Script）の「ウェブアプリのURL」（…/exec）を貼ると、'
              '開くたびにGoogleドライブの最新を読みます。URLはこの端末にだけ覚えます。'
              '人には教えないでください。',
              style: TextStyle(fontSize: 13, color: AppColors.ash),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: field,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                labelText: 'ウェブアプリのURL',
                hintText: 'https://script.google.com/macros/s/…/exec',
              ),
            ),
          ],
        ),
        actions: [
          if (_remote != null)
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(''),
              child: const Text('自動読み込みをやめる'),
            ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('閉じる'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(field.text.trim()),
            child: const Text('保存して読み込む'),
          ),
        ],
      ),
    );
    field.dispose();
    if (result == null || !mounted) return;
    final url = result.isEmpty ? null : result;
    saveRemoteUrl(url);
    setState(() => _remote = url);
    if (url != null) await _refreshFromDrive(manual: true);
  }

  /// [rainbowOnly]：🌈の印だけを変えた内容（[ViewerData.withRainbowMarks]）。線パーツと取得先は
  /// 同じなので、読んだ線と取得処理をそのまま使う（付け外しのたびに線を読み直していた、2026-10-29
  /// Codexのレビュー）。写した記録にも同じ取得処理を結び付ける。
  void _show(ViewerData data, {bool rainbowOnly = false}) {
    if (_deviceMarks.isNotEmpty && data.source != 'pscube') {
      final merged = mergeRainbowMarks(data.rainbowMarks, _deviceMarks.values);
      if (merged.changed > 0) data = data.withRainbowMarks(merged.marks);
    }
    _data = data;
    if (rainbowOnly) {
      bindRemoteCurves(data.records, remoteCurveFetcher);
    } else {
      _attachRemoteCurves(data);
    }
    _dataVersion++;
    viewerDataRevision.value++;
    _scoredFor = null;
    final first = data.records.firstOrNull;
    if (!data.records.any((r) => r.store == _store)) _store = first?.store;
  }

  void _attachRemoteCurves(ViewerData data) {
    // グラフの線は台の画面を開いたときにその日の分だけ読む（remote_curve.dart）。
    clearRemoteCurves();
    final curveUrl = _remote;
    final curveParts = data.curveParts;
    remoteCurveFetcher = data.curveParts.isEmpty
        ? null
        : (day) async {
            final url = curveUrl;
            if (url == null) throw StateError('Googleドライブの自動読み込みが設定されていません。');
            final refs = [
              for (final c in curveParts)
                if (c['day'] == day) c,
            ];
            if (refs.isEmpty) throw StateError('この日のグラフの線がありません。');
            final rows = jsonDecode(
              await fetchViewerCurves(url, jsonEncode(refs)),
            ) as List;
            return {
              for (final row in rows)
                (row as List)[0] as int: SavedCurve(row[1] as List),
            };
          };
    bindRemoteCurves(data.records, remoteCurveFetcher);
  }

  Future<void> _pick() async {
    if (_loading || _syncing) return;
    setState(() {
      _error = null;
      _loading = true;
    });
    try {
      final picked = await pickBackup();
      if (picked != null && mounted) {
        // 古い台データを組み立て直さず、端末の最新イベントだけを引き継ぐ。
        final prepared = ViewerData.preparePicked(
          picked,
          _data,
          events: pickedBackupEvents(),
        );
        final data = prepared.data;
        await saveViewerData(prepared.text, meruhen: data.source != 'pscube');
        if (!mounted) return;
        _show(data);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('${data.records.length}台を読み込みました。')),
          );
        }
      }
    } catch (error) {
      if (mounted) _error = 'バックアップを読み込めませんでした。\n$error';
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _exportPscube() async {
    try {
      await exportPscubeBackup();
      if (!mounted) return;
      final supported = _data?.syncStatus?['supplement_supported'] == true;
      await showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('スマホの補完を共有する'),
          content: Text(
            '書き出した pscube-backup-browser-…json をGoogleドライブの「database共有」に保存してください。'
            '${supported ? 'Google側の次の自動処理で、数値が一致する記録の空欄差枚だけを補完します。' : 'Google側がスマホ補完に対応しているか未確認です。既存のApps Scriptの更新が必要です。'}'
            '取得済みの差枚・回転数・BB/RB・機種設定・イベントは変更しません。'
            '保存しただけで反映済みとは限りません。「更新・差枚の取得状況」でGoogle側の補完結果を確認してください。',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('閉じる'),
            ),
          ],
        ),
      );
    } catch (error) {
      if (mounted) setState(() => _error = 'バックアップを書き出せませんでした。\n$error');
    }
  }

  Future<void> _editPscubeType() async {
    final records =
        _data?.records.where((r) => r.store == _store).toList() ?? [];
    final names = records.map((r) => r.machine).toSet().toList()
      ..sort(compareMachineNames);
    if (names.isEmpty) return;
    var machine = names.first;
    String typeOf(String name) =>
        records.firstWhere((r) => r.machine == name).extra['machine_type']
            as String? ??
        '';
    var type = typeOf(machine);
    final result = await showDialog<(String, String)>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: const Text('機種タイプ'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<String>(
                initialValue: machine,
                isExpanded: true,
                decoration: const InputDecoration(labelText: '機種'),
                items: [
                  for (final name in names)
                    DropdownMenuItem(
                      value: name,
                      child: Text(displayMachineName(name)),
                    ),
                ],
                onChanged: (value) {
                  if (value != null) {
                    update(() {
                      machine = value;
                      type = typeOf(machine);
                    });
                  }
                },
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<String>(
                key: ValueKey(machine),
                initialValue: type,
                decoration: const InputDecoration(labelText: 'タイプ'),
                items: const [
                  DropdownMenuItem(value: '', child: Text('機種名から自動判定')),
                  DropdownMenuItem(value: 'normal', child: Text('ノーマルタイプ')),
                  DropdownMenuItem(value: 'other', child: Text('その他')),
                ],
                onChanged: (value) => update(() => type = value ?? ''),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('閉じる'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, (machine, type)),
              child: const Text('保存'),
            ),
          ],
        ),
      ),
    );
    if (result == null || !mounted || _store == null) return;
    try {
      final text = await setPscubeMachineType(
        _store!,
        result.$1,
        result.$2.isEmpty ? null : result.$2,
      );
      if (text != null && mounted) {
        await saveViewerData(text);
        setState(() => _show(ViewerData.parse(text)));
      }
    } catch (error) {
      if (mounted) setState(() => _error = '機種タイプを保存できませんでした。\n$error');
    }
  }

  /// メルヘンのイベントカレンダー（先の日にも入れられる、EVENT_CALENDAR.md）。
  /// 入れたイベントは端末に保存し、書き出したファイルでPC・Androidへ渡す。
  void _openEventCalendar(String store) => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => EventCalendarPage(
        stores: storeNames,
        initialStore: store,
        eventFor: (store, day) => _data?.dateEventFor(store, day),
        namesFor: (store) =>
            dateEventNames(_data?.dateEvents.values ?? const [], store: store),
        onSave: _saveMeruhenEvents,
        netFor: _netFor,
        netNote: dailyNetNote(store),
        recordsFor: _recordsFor,
        onOpenRecord: (record) => _openRecord(record, null),
        actions: [
          IconButton(
            tooltip: 'イベントを書き出す',
            onPressed: _exportMeruhenEvents,
            icon: const Icon(Icons.file_download_outlined),
          ),
        ],
        note:
            'ここで入れたイベントは、この端末に保存し、Googleドライブの自動読み込みを設定していれば'
            '共有カレンダーにも送ります（PCは次に開いたときなどに取り込み、Androidへは'
            'PCのバックアップで届きます）。PCで入れたイベントは、Googleドライブの自動読み込みで届きます。'
            '同じ日は、あとから入れた方が残ります。送れないときは、右上の「イベントを書き出す」で'
            '作ったファイルをGoogleドライブの database共有 に保存しても渡せます。',
      ),
    ),
  );

  /// P’s CUBEのイベントカレンダー（2026-10-08、メルヘンと同じ画面）。店舗・貸玉ごと。
  void _openPscubeCalendar(String store) => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => EventCalendarPage(
        stores: {
          for (final e in viewerStoreNames(_data?.records ?? const []).entries)
            if (isPscubeStore(e.key)) e.key: e.value,
        },
        initialStore: store,
        eventFor: (store, day) => _data?.dateEventFor(store, day),
        namesFor: (store) => _data?.eventNames[store] ?? const [],
        onSave: _savePscubeEvents,
        netFor: _netFor,
        netNote: dailyNetNote(store),
        recordsFor: _recordsFor,
        onOpenRecord: (record) => _openRecord(record, null),
        note:
            'ここで入れたイベントは、この端末に保存し、Googleドライブの自動読み込みを設定していれば'
            '共有カレンダーにも送ります（PCは「カレンダー」を開いたときなどに取り込みます）。'
            '同じ日は、あとから入れた方が残ります。',
      ),
    ),
  );

  Future<void> _savePscubeEvents(
    String store,
    List<String> days,
    String? name,
  ) async {
    final text = await setPscubeDateEventDays(store, days, name);
    if (text == null) return;
    await saveViewerData(text);
    if (mounted) setState(() => _show(ViewerData.parse(text)));
    await _pushShared(pscube: true);
  }

  /// カレンダーの差枚（その店・その日の総差枚）と、日付を押したときのその日の台。
  /// 読み込んだデータが変わったときだけ数え直す。
  ViewerData? _netData;
  DayNet? Function(String store, String day)? _netLookup;
  Map<String, List<SlotRecord>> _dayRecords = const {};
  void _indexCalendar(ViewerData data) {
    if (identical(data, _netData)) return;
    _netData = data;
    _netLookup = dailyNetLookup(data.records);
    final byDay = <String, List<SlotRecord>>{};
    for (final r in data.records) {
      (byDay['${r.store}|${r.day}'] ??= []).add(r);
    }
    _dayRecords = byDay;
  }

  DayNet? _netFor(String store, String day) {
    final data = _data;
    if (data == null) return null;
    _indexCalendar(data);
    return _netLookup!(store, day);
  }

  List<SlotRecord> _recordsFor(String store, String day) {
    final data = _data;
    if (data == null) return const [];
    _indexCalendar(data);
    return _dayRecords['$store|$day'] ?? const [];
  }

  Future<void> _saveMeruhenEvents(
    String store,
    List<String> days,
    String? name,
  ) async {
    final stored = await loadViewerData();
    if (stored == null) throw StateError('先にバックアップを読み込んでください。');
    final text = ViewerData.setEvents(
      stored,
      store,
      days,
      name,
      DateTime.now(),
    );
    if (identical(text, stored)) return;
    await saveViewerData(text);
    if (mounted) setState(() => _show(ViewerData.parse(text)));
    await _pushShared(pscube: false);
  }

  void _exportMeruhenEvents() {
    final data = _data;
    if (data == null) return;
    final now = DateTime.now();
    downloadText(
      ViewerData.eventsBackupFileName(now),
      ViewerData.eventsOnlyBackup(data.dateEvents.values, now),
    );
  }

  /// P’s CUBEのその日のイベント名を付ける・変える・消す（自由記入、今までの名前はプルダウン）。
  Future<void> _editPscubeEvent(String store, String day) async {
    final data = _data;
    if (data == null) return;
    final name = await showEventNameDialog(
      context,
      title: '${dayWithWeekday(day)} のイベント',
      current: data.dateEventFor(store, day)?.name,
      names: data.eventNames[store] ?? const [],
    );
    if (name == null || !mounted) return;
    try {
      final text = await setPscubeDateEvent(
        store,
        day,
        name.isEmpty ? null : name,
      );
      if (text != null && mounted) {
        await saveViewerData(text);
        setState(() => _show(ViewerData.parse(text)));
      }
    } catch (error) {
      if (mounted) setState(() => _error = 'イベント名を保存できませんでした。\n$error');
      return;
    }
    await _pushShared(pscube: true);
  }

  void _openRecord(
    SlotRecord record,
    ScoreResult? score, {
    ValueChanged<String>? onDayChanged,
  }) => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => ViewerRecordPage(
        data: _data!,
        record: record,
        onDayChanged: (day) {
          setState(() {
            _store = record.store;
            _day = day;
          });
          onDayChanged?.call(day);
        },
      ),
    ),
  );

  void _openEventHistory([String location = 'nagamachiminami']) =>
      Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => EventHistoryPage(
            store: location,
            data: _data ?? const ViewerData(records: []),
            remoteUrl: _remote,
          ),
        ),
      );

  void _openMachine(String machine) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ViewerMachinePage(
          data: _data!,
          store: _store!,
          machine: machine,
          day: _day!,
          // バラエティを機種名で絞り込んで開いたときは、その機種の台だけを出す。
          query: _query.text,
          onDayChanged: (day) => setState(() => _day = day),
        ),
      ),
    );
  }

  static String _two(int v) => v.toString().padLeft(2, '0');

  /// 「9/30 01:19」の形。
  static String _when(DateTime at) =>
      '${at.month}/${at.day} ${_two(at.hour)}:${_two(at.minute)}';

  String _sourceText(ViewerData data) {
    final at = data.exportedAt;
    final when = at == null ? '' : '${_when(at)}書き出し・';
    final from = switch (data.source) {
      'android' => 'Android版',
      'pc' || 'pc-deleted' => 'PC版',
      'pc-viewer' => 'PC版（閲覧用・直近60日）',
      'pscube' => 'P’s CUBE・',
      _ => '',
    };
    if (data.file == 'Googleドライブ（自動）') {
      final older = data.keptOlder > 0
          ? '（うち${data.keptOlder}台は前に読み込んだ古い日の記録）'
          : '';
      final checked = _checkedAt == null
          ? ''
          : '・${_two(_checkedAt!.hour)}:${_two(_checkedAt!.minute)}に最新か確認';
      return 'Googleドライブから自動で読み込み：$from$when${data.records.length}台$older'
          '$checked（グラフは保存した線から描画。線の無い台は概略図）';
    }
    return '読み込んだバックアップ：$from$when${data.records.length}台'
        '（グラフは保存した線から描画。線の無い台は概略図）';
  }

  @override
  Widget build(BuildContext context) {
    final data = _data;
    final days = data == null
        ? <String>[]
        : viewerDays(data.records, _store ?? '');
    if (!days.contains(_day)) _day = days.firstOrNull;
    return Scaffold(
      appBar: AppBar(
        title: const Text('database 閲覧'),
        bottom: days.isEmpty
            ? null
            : ViewerDateBar(
                days: days,
                day: _day,
                event: data?.dateEventFor(_store!, _day!)?.name,
                eventFor: (day) => data?.dateEventFor(_store!, day)?.name,
                onChanged: (day) => setState(() => _day = day),
              ),
        actions: [
          if (data?.source == 'pscube') ...[
            IconButton(
              tooltip: '機種タイプ',
              onPressed: _editPscubeType,
              icon: const Icon(Icons.tune),
            ),
            IconButton(
              tooltip: 'バックアップを書き出す',
              onPressed: _exportPscube,
              icon: const Icon(Icons.file_download_outlined),
            ),
          ],
          if (_remote != null)
            IconButton(
              tooltip: 'Googleドライブの最新を読み込む',
              onPressed: _syncing || _loading
                  ? null
                  : () => _refreshFromDrive(manual: true),
              icon: const Icon(Icons.refresh),
            ),
          IconButton(
            tooltip: 'Googleドライブの自動読み込み',
            onPressed: _loading || _syncing ? null : _editRemote,
            icon: Icon(
              _remote == null ? Icons.link : Icons.cloud_done_outlined,
            ),
          ),
          IconButton(
            tooltip: 'バックアップを読み込む',
            onPressed: _loading || _syncing ? null : _pick,
            icon: const Icon(Icons.file_open_outlined),
          ),
        ],
      ),
      // Android版の結果タブと同じく、下へスクロールしたら右下に出す。
      floatingActionButton: ScrollTopButton(controller: _scroll),
      body: SafeArea(
        child: _loading && data == null
            ? const Center(child: CircularProgressIndicator())
            : data == null || data.records.isEmpty
            ? _welcome()
            : _results(data),
      ),
    );
  }

  Widget _welcome() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      if (_error != null) Notice(text: _error!),
      EmptyState(
        icon: Icons.cloud_download_outlined,
        title: 'バックアップを読み込んでください',
        body:
            '「バックアップを読み込む」を押し、「ファイル」からGoogleドライブの'
            '${Uri.base.path.contains('/pscube/') ? 'P’s CUBEのJSONまたはWebArchive' : 'バックアップJSON'} を選びます。読み込んだ内容はこの端末の中だけで'
            '使い、どこにも送りません。次からは選び直さなくても開けます。',
      ),
      const SizedBox(height: 12),
      Center(
        child: TextButton.icon(
          onPressed: _loading || _syncing ? null : _editRemote,
          icon: const Icon(Icons.link),
          label: const Text('Googleドライブの自動読み込みを設定する'),
        ),
      ),
      const SizedBox(height: 12),
      const Notice(
        text:
            'Googleドライブが出ないとき：Googleドライブのアプリを入れてログインし、'
            '「ファイル」アプリの「ブラウズ」→右上の「…」→「編集」でGoogleドライブを'
            'オンにします。それでも開けないときは、Googleドライブのアプリでファイルの'
            '「…」→「アプリで開く」→「"ファイル"に保存」でiCloud Driveに保存し、'
            'そこから選んでください。',
      ),
      const SizedBox(height: 16),
      Center(
        child: FilledButton.icon(
          onPressed: _loading || _syncing ? null : _pick,
          icon: const Icon(Icons.file_open_outlined),
          label: Text(_loading ? '読み込み中…' : 'バックアップを読み込む'),
        ),
      ),
    ],
  );

  Widget _dailyNetButton(
    List<SlotRecord> all,
    String store,
    String day,
    String label, {
    String? Function(String day)? eventFor,
  }) => OutlinedButton.icon(
    onPressed: () => Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => DailyNetPage(
          records: all,
          store: store,
          day: day,
          onDayChanged: (changed) => setState(() => _day = changed),
          eventFor: eventFor,
        ),
      ),
    ),
    icon: const Icon(Icons.calendar_month_outlined),
    label: Text(label),
  );

  Widget _results(ViewerData data) {
    final all = data.records;
    final store = _store ?? all.first.store;
    final storeRows = [
      for (final r in all)
        if (r.store == store) r,
    ];
    final days = storeRows.map((r) => r.day).toSet().toList()
      ..sort((a, b) => b.compareTo(a));
    if (!days.contains(_day)) _day = days.firstOrNull;
    final day = _day;
    final dayRows = [
      for (final r in storeRows)
        if (r.day == day) r,
    ];
    final key = (_dataVersion, store, day);
    if (_scoredFor != key) {
      _digest = [for (final r in dayRows) (r, scoreRecord(r, all))];
      _candidates = dayCandidates(dayRows, all, excludeNormal: true);
      _scoredFor = key;
    }
    // 1〜3台の機種は「バラエティ」1つにまとめる。
    final summaries = summarizeMachines(_digest);
    final grouped = groupForList(_digest);
    final machineCount = {for (final e in _digest) e.$1.machine}.length;
    final history = day == null ? 0 : historyDays(all, store, day);
    final shown = [
      for (final s in summaries)
        if (filterForList(s, grouped[s.machine]!, _query.text) != null) s,
    ];
    return ListView(
      controller: _scroll,
      // 下は、最後の行が「一番上へ」ボタンに隠れないだけ空ける。
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 88),
      children: [
        if (_error != null) Notice(text: _error!),
        Notice(text: _sourceText(data)),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => showCaptureHealth(
              context,
              records: data.records.map(healthRecord).toList(),
              syncStatus: data.syncStatus,
              exportedAt: data.exportedAtText,
              loadedAt: data.loadedAt?.toIso8601String(),
              checkedAt: _checkedAt?.toIso8601String(),
              store: store,
              day: day,
              pscube: data.source == 'pscube',
            ),
            icon: const Icon(Icons.info_outline),
            label: const Text('更新・差枚の取得状況'),
          ),
        ),
        if (day != null && history < 3)
          Notice(
            text:
                'このバックアップには、この日より前の記録が$history日分しかありません。'
                '採点は前の30日分と比べるため、点数が中立（50〜60点前後）に寄っています。'
                '${data.source == 'pscube' ? '以前の日付も含むP’s CUBEのバックアップを追加で読み込んでください。' : '全期間のバックアップ（PC版の「database共有」にある database-backup-auto.json か、Android版で「すべての日付」を選んで書き出したもの）を読み込んでください。'}',
          ),
        if (_loading) const LinearProgressIndicator(),
        // Driveの確認中は動く表示にしない（動いている間は画面を描き直し続け、
        // 電池を使うため）。90秒間なにも届かなければ打ち切る（web/index.html）。
        if (_syncing)
          const Padding(
            padding: EdgeInsets.only(bottom: 8),
            child: Text(
              'Googleドライブの最新を確認しています…',
              style: TextStyle(fontSize: 12, color: AppColors.ash),
            ),
          ),
        storeDropdown(
          store,
          (v) => setState(() {
            _store = v;
            _day = null;
          }),
          short: true,
          stores: viewerStoreNames(all),
        ),
        const SizedBox(height: 10),
        if (isPscubeStore(store)) ...[
          OutlinedButton.icon(
            onPressed: () => _openPscubeCalendar(store),
            icon: const Icon(Icons.calendar_month_outlined),
            label: const Text('イベントカレンダー'),
          ),
          const SizedBox(height: 8),
        ],
        if (isPscubeStore(store) && day != null) ...[
          OutlinedButton.icon(
            onPressed: () => _editPscubeEvent(store, day),
            icon: const Icon(Icons.event_note_outlined),
            label: Text(
              'イベント：${data.dateEventFor(store, day)?.name ?? 'なし'}（編集）',
            ),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => PscubeSuffixPage(
                  data: data,
                  store: store,
                  day: day,
                  onDayChanged: (changed) => setState(() => _day = changed),
                  onDataChanged: (updated) {
                    if (mounted) setState(() => _show(updated));
                  },
                ),
              ),
            ),
            icon: const Icon(Icons.table_chart_outlined),
            label: const Text('末尾別データまとめ'),
          ),
          const SizedBox(height: 8),
          _dailyNetButton(
            all,
            store,
            day,
            '日別の差枚',
            eventFor: (changed) => data.dateEventFor(store, changed)?.name,
          ),
          const SizedBox(height: 8),
        ],
        if (!isPscubeStore(store)) ...[
          OutlinedButton.icon(
            onPressed: () => _openEventCalendar(store),
            icon: const Icon(Icons.calendar_month_outlined),
            label: const Text('イベントカレンダー'),
          ),
          const SizedBox(height: 8),
          if (store == 'nagamachiminami' || store == 'saiwaichou') ...[
            OutlinedButton.icon(
              onPressed: () => _openEventHistory(store),
              icon: const Icon(Icons.history),
              label: Text(store == 'saiwaichou' ? '幸町のバラエティ履歴' : '長町南のイベント履歴'),
            ),
            const SizedBox(height: 8),
          ],
        ],
        // メルヘンは保存したグラフと最大持玉からの推定差枚（P’s CUBEと同じ画面）。
        if (!isPscubeStore(store) && day != null) ...[
          _dailyNetButton(
            all,
            store,
            day,
            '日別の差枚（推定）',
            eventFor: (changed) => data.dateEventFor(store, changed)?.name,
          ),
          const SizedBox(height: 8),
          // 幸町の末尾別データまとめ（2026-10-12 利用者「幸町にもつくってもらうだけでいい」。P’s CUBEと同じ画面）。
          if (meruhenSuffixStores.contains(store)) ...[
            OutlinedButton.icon(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => PscubeSuffixPage(
                    data: data,
                    store: store,
                    day: day,
                    onDayChanged: (changed) => setState(() => _day = changed),
                  ),
                ),
              ),
              icon: const Icon(Icons.table_chart_outlined),
              label: const Text('末尾別データまとめ'),
            ),
            const SizedBox(height: 8),
          ],
        ],
        if (store == 'saiwaichou' && day != null) ...[
          OutlinedButton.icon(
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => VarietyWeekPage(
                  data: data,
                  store: store,
                  day: day,
                  currentData: () => _data!,
                  onDayChanged: (changed) => setState(() => _day = changed),
                ),
              ),
            ),
            icon: const Icon(Icons.view_week_outlined),
            label: const Text('バラエティの候補（7日間🌈なし）'),
          ),
          const SizedBox(height: 8),
        ],
        OutlinedButton.icon(
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => AnswerCheckPage(
                records: all,
                store: store,
                onOpen: _openRecord,
                eventFor: (store, day) => data.dateEventFor(store, day)?.name,
              ),
            ),
          ),
          icon: const Icon(Icons.fact_check_outlined),
          label: const Text('答え合わせ（前の日の候補の結果）'),
        ),
        if (day != null) ...[
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => ExploratoryForecastPage(
                  data: data,
                  store: store,
                  day: day,
                  onOpen: (record) => _openRecord(record, null),
                  onOpenWithDayChange: (record, changed) =>
                      _openRecord(record, null, onDayChanged: changed),
                  onSelectionChanged: (store, day) => setState(() {
                    _store = store;
                    _day = day;
                  }),
                ),
              ),
            ),
            icon: const Icon(Icons.science_outlined),
            label: const Text('新規予測（試験中の別の選び方）'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => VarietyIdlePage(
                  records: all,
                  store: store,
                  day: day,
                  onOpen: (record) => _openRecord(record, null),
                  onDayChanged: (changed) => setState(() => _day = changed),
                  eventFor: (changed) =>
                      data.dateEventFor(store, changed)?.name,
                ),
              ),
            ),
            icon: const Icon(Icons.hourglass_empty),
            label: const Text('バラエティの回っていない台（期間・ゲーム数を選べる）'),
          ),
        ],
        const SizedBox(height: 14),
        if (dayRows.isEmpty || day == null)
          const EmptyState(
            icon: Icons.inbox_outlined,
            title: 'この店舗の記録はありません',
            body: '別の店舗を選ぶか、新しいバックアップを読み込んでください。',
          )
        else ...[
          if (hasNormalRecommendations(store)) ...[
            FilledButton.tonalIcon(
              key: const ValueKey('open-normal-recommendations'),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => NormalRecommendationsPage(
                    store: store,
                    day: day,
                    records: all,
                    onPick: (record) => _openRecord(record, null),
                  ),
                ),
              ),
              icon: const Icon(Icons.recommend_outlined),
              label: const Text('ジャグラー・ハナハナのおすすめ'),
            ),
            const SizedBox(height: 10),
          ],
          NextDayCandidatesCard(
            normalSeparated: true,
            store: store,
            allRecords: all,
            day: day,
            candidates: _candidates!.candidates,
            machines: _candidates!.machines,
            judged: _candidates!.judged,
            onPick: (record) => _openRecord(
              record,
              _digest.where((e) => e.$1.key == record.key).firstOrNull?.$2,
            ),
          ),
          const SizedBox(height: 14),
          DaySummaryCard(entries: _digest, onPick: _openRecord),
          const SizedBox(height: 18),
          Text(
            'この日の機種一覧　$machineCount機種'
            '・${_digest.length}台',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 6),
          const Text(
            '選んだ日の取り込み済みデータです。入れ替え前の機種・台番号は、日付を戻して確認できます。',
            style: TextStyle(fontSize: 12, color: AppColors.ash),
          ),
          const SizedBox(height: 8),
          // 1機種だけでも台番号から探せる。
          MachineSearchField(
            controller: _query,
            onChanged: () => setState(() {}),
          ),
          const SizedBox(height: 8),
          MachineSummaryList(summaries: shown, onPick: _openMachine),
        ],
      ],
    );
  }
}
