import 'package:flutter/material.dart';

import 'exploratory_candidates.dart';
import 'list_views.dart';
import 'models.dart';
import 'shared_widgets.dart';
import 'theme.dart';
import 'viewer_data.dart';
import 'viewer_pages.dart';

/// 閲覧ページの「新規予測」で使う選び方。探索（2026-09-29）で、選ぶ期間
/// （9/21〜9/24）にいちばん良かった案。
const exploratoryDisplayMethod = ExploratoryMethod.blend;

/// 新規予測の成績についての説明。検証の結果は
/// `NEXT_DAY_CANDIDATES_VALIDATION_20260929.md` の「8. 探索」。
const exploratoryValidationNote =
    '探索の結果（2026-09-29、翌日0:00までに取り込んだ記録）：9/21〜9/24の4日で4つの案を比べ、'
    'いちばん良かったこの選び方を選びました。その後の9/25〜9/27の3日では、今の翌日候補との差は'
    '確認できていません（−0.07点）。偶然の可能性が高く、翌日の設定・勝率・期待収支を示す'
    'ものではありません。';

/// 新規予測（試験）：今の翌日候補（仮）とは別の選び方を試す閲覧ページ専用の画面。
class ExploratoryForecastPage extends StatefulWidget {
  const ExploratoryForecastPage({
    super.key,
    required this.data,
    required this.store,
    required this.day,
    required this.onOpen,
    this.onDayChanged,
    this.onSelectionChanged,
    this.onOpenWithDayChange,
  });
  final ViewerData data;
  final String store, day;
  final void Function(SlotRecord record) onOpen;
  final ValueChanged<String>? onDayChanged;

  /// 親の画面にも、選んだ店舗と日付を一組で伝える。
  final void Function(String store, String day)? onSelectionChanged;

  /// 候補の詳細内で変えた日付を、この画面へ戻すための開き方。
  final void Function(SlotRecord record, ValueChanged<String> onDayChanged)?
  onOpenWithDayChange;

  @override
  State<ExploratoryForecastPage> createState() =>
      _ExploratoryForecastPageState();
}

class _ExploratoryForecastPageState extends State<ExploratoryForecastPage> {
  late String _store = widget.store;
  late String _day = widget.day;
  List<ExploratoryCandidate>? _candidates;
  int _machines = 0;
  Object? _calculatedFor;

  /// 候補のリスト（右下の「一番上へ」ボタンで戻す）。
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _calculate();
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  /// 店舗・日付を変えたとき：計算中の表示にしてから計算し直す。
  void _restart() {
    setState(() => _calculatedFor = null);
    _calculate();
  }

  /// 画面を先に出してから計算する（Webでは計算が画面と同じ処理で動くため）。
  Future<void> _calculate() async {
    final key = (_store, _day);
    await Future<void>.delayed(Duration.zero);
    if (!mounted || key != (_store, _day)) return;
    final all = widget.data.records;
    final dayRows = [
      for (final r in all)
        if (r.store == _store && r.day == _day) r,
    ];
    final candidates = exploratoryCandidates(
      dayRows,
      all,
      exploratoryDisplayMethod,
    );
    setState(() {
      _candidates = candidates;
      _machines = {for (final r in dayRows) r.machine}.length;
      _calculatedFor = key;
    });
  }

  void _changeDay(String? day) {
    if (day == null || day == _day) return;
    _day = day;
    widget.onDayChanged?.call(day);
    widget.onSelectionChanged?.call(_store, day);
    _restart();
  }

  @override
  Widget build(BuildContext context) {
    final records = widget.data.records;
    final days = viewerDays(records, _store);
    final stores = {for (final r in records) r.store};
    final ready = _calculatedFor == (_store, _day);
    return Scaffold(
      appBar: AppBar(
        title: const Text('新規予測（試験）'),
        bottom: ViewerDateBar(
          days: days,
          day: _day,
          event: widget.data.dateEventFor(_store, _day)?.name,
          eventFor: (day) => widget.data.dateEventFor(_store, day)?.name,
          onChanged: _changeDay,
        ),
      ),
      floatingActionButton: ScrollTopButton(controller: _scroll),
      body: SafeArea(
        child: ListView(
          controller: _scroll,
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 88),
          children: [
            if (stores.length > 1) ...[
              storeDropdown(_store, (v) {
                if (v == _store) return;
                _store = v;
                final storeDays = viewerDays(records, v);
                if (!storeDays.contains(_day) && storeDays.isNotEmpty) {
                  _day = storeDays.first;
                }
                widget.onSelectionChanged?.call(_store, _day);
                _restart();
              }, short: true),
              const SizedBox(height: 12),
            ],
            if (!ready) ...[
              const LinearProgressIndicator(),
              const SizedBox(height: 12),
            ] else
              ExploratoryCandidatesCard(
                day: _day,
                candidates: _candidates!,
                machines: _machines,
                onPick: (record) {
                  final openWithDayChange = widget.onOpenWithDayChange;
                  if (openWithDayChange != null) {
                    openWithDayChange(record, _changeDay);
                  } else {
                    widget.onOpen(record);
                  }
                },
              ),
          ],
        ),
      ),
    );
  }
}

/// 新規予測の候補のカード。見た目は翌日候補（仮）のカードに合わせる。
class ExploratoryCandidatesCard extends StatefulWidget {
  const ExploratoryCandidatesCard({
    super.key,
    required this.day,
    required this.candidates,
    required this.machines,
    required this.onPick,
  });
  final String day;
  final List<ExploratoryCandidate> candidates;

  /// その日の機種数。
  final int machines;
  final void Function(SlotRecord record) onPick;

  @override
  State<ExploratoryCandidatesCard> createState() =>
      _ExploratoryCandidatesCardState();
}

class _ExploratoryCandidatesCardState extends State<ExploratoryCandidatesCard> {
  static const _first = 7;
  var _all = false;

  @override
  Widget build(BuildContext context) {
    final shown = _all
        ? widget.candidates
        : widget.candidates.take(_first).toList();
    final next = nextDayLabel(widget.day);
    final judged = {for (final c in widget.candidates) c.record.machine}.length;
    const note = TextStyle(color: AppColors.ash, fontSize: 12, height: 1.45);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    next.isEmpty ? '新規予測' : '$next の新規予測',
                    style: const TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 3,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.pebble,
                    borderRadius: BorderRadius.circular(980),
                  ),
                  child: const Text(
                    '探索中',
                    style: TextStyle(fontSize: 11, color: AppColors.ash),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              '${next.isEmpty ? '選択日' : '${shortDayLabel(widget.day)}（選択日）'}までの記録から、'
              '${next.isEmpty ? '翌日' : next}向けに選んだ台です。今の「翌日候補（仮）」とは別の'
              '選び方を試しています。同じ機種の中で、当たりの軽さ（過去の傾向）の順位と'
              '前日の点数の順位を半分ずつ合わせ、上位4分の1を選びます。',
              style: const TextStyle(
                color: AppColors.ash,
                fontSize: 13,
                height: 1.45,
              ),
            ),
            const SizedBox(height: 10),
            if (widget.candidates.isEmpty)
              const Text(
                'まだ選べる機種がありません。同じ台・同じ機種のデータが3日分たまり、'
                '1機種で4台以上判定できると表示します。',
                style: TextStyle(
                  color: AppColors.ash,
                  fontSize: 13,
                  height: 1.45,
                ),
              )
            else ...[
              for (final (i, c) in shown.indexed) _row(i + 1, c),
              if (widget.candidates.length > _first)
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton(
                    onPressed: () => setState(() => _all = !_all),
                    child: Text(
                      _all
                          ? '上位$_first台だけ表示'
                          : 'すべて表示（${widget.candidates.length}台）',
                    ),
                  ),
                ),
              Text(
                '判定できた機種：$judged / ${widget.machines}機種。'
                '「組み合わせ」は同じ機種の中での順位（0〜100）で、別の機種どうしの順位は目安です。',
                style: note,
              ),
            ],
            const SizedBox(height: 6),
            const Text(exploratoryValidationNote, style: note),
          ],
        ),
      ),
    );
  }

  Widget _row(int rank, ExploratoryCandidate c) {
    final value = c.value ?? 0;
    final delta = c.index - 50;
    final previous = c.previousScore;
    return InkWell(
      onTap: () => widget.onPick(c.record),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 7),
        child: Row(
          children: [
            SizedBox(
              width: 26,
              child: Text(
                '$rank',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  color: AppColors.ash,
                ),
              ),
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        '${c.record.rack}番台',
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          displayMachineName(c.record.machine),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 12,
                            color: AppColors.ash,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  // 棒の長さは「組み合わせ」の大きさ（100で満タン）。
                  ClipRRect(
                    borderRadius: BorderRadius.circular(3),
                    child: LinearProgressIndicator(
                      value: value.clamp(0.04, 1.0),
                      minHeight: 6,
                      color: AppColors.appleBlue,
                      backgroundColor: AppColors.pebble,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    '当たりの軽さ 平均より ${delta >= 0 ? '+' : '-'}${delta.abs().toStringAsFixed(0)}'
                    '・前日 ${previous == null ? '点数なし' : '${previous.toStringAsFixed(1)}点'}',
                    style: const TextStyle(fontSize: 11, color: AppColors.ash),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                const Text(
                  '組み合わせ',
                  style: TextStyle(fontSize: 10, color: AppColors.ash),
                ),
                Text(
                  (value * 100).toStringAsFixed(0),
                  style: const TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w800,
                    color: AppColors.linkBlue,
                  ),
                ),
              ],
            ),
            const Icon(Icons.chevron_right, color: AppColors.mist),
          ],
        ),
      ),
    );
  }
}
