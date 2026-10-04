import 'dart:math' as math;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import 'data_checks.dart';
import 'list_views.dart';
import 'graph_preview.dart';
import 'models.dart';
import 'scoring.dart';
import 'setting_estimate.dart';
import 'setting_estimate_presentation.dart';
import 'theme.dart';

// 結果タブ・過去の記録で使う、機種ごとの表示。
// アナスロの機種別データ（データ表示／グラフ表示のタブ、台番号の表、平均の行）
// の見せ方に、このアプリの点数・推定設定・翌日候補（仮）を加えている。

/// 機種の見出しと「データ表示／グラフ表示」のタブ、その中身。[machine] が
/// [varietyGroupName] なら、1〜3台の機種をまとめたバラエティ（台ごとに機種名を出す）。
class MachineSection extends StatefulWidget {
  const MachineSection({
    super.key,
    required this.machine,
    required this.entries,
    required this.onTap,
    this.onLongPress,
    this.candidateRacks = const {},
    this.longTrendRacks = const {},
    this.footer,
    this.graph,
    this.onGraphChanged,
    this.showMachine = false,
  });

  final String machine;

  /// 複数機種を一緒に出すときに、台ごとの機種名を表示する。
  final bool showMachine;

  /// 台番号順の台と点数。
  final List<(SlotRecord, ScoreResult)> entries;
  final void Function(SlotRecord record, ScoreResult score) onTap;
  final void Function(SlotRecord record)? onLongPress;

  /// 翌日候補（仮）に入った台番号。表とグラフに★を付ける。
  final Set<int> candidateRacks;
  final Set<int> longTrendRacks;

  /// 見出しの下に置く補足（「設置機種一覧へ戻る」など）。
  final Widget? footer;

  /// グラフ表示か。親が覚える場合に渡す（結果タブは画面外の機種を作らないので、
  /// 切り替えを親で覚えておかないとスクロールで戻したときに元に戻ってしまう）。
  /// null ならこの部品の中で覚える。
  final bool? graph;
  final ValueChanged<bool>? onGraphChanged;

  /// 画面に出す前の高さの見積もり。結果タブで、まだ作っていない機種へ飛ぶときの
  /// 目安に使う（実際の位置は飛んだ後で合わせ直す）。
  static double estimateHeight(int racks, {required bool graph}) {
    const header = 48.0 + 10 + 40; // 見出し2行・間・タブ
    const footer = 32.0 + 48; // 注記・戻るボタンの行
    final body = graph
        ? ((racks + 1) ~/ 2) * 190.0 + 8 + 36
        : (racks + 2) * MachineDataTable._rowHeight + 1;
    return header + body + footer;
  }

  @override
  State<MachineSection> createState() => _MachineSectionState();
}

class _MachineSectionState extends State<MachineSection> {
  var _ownGraph = false;

  bool get _graph => widget.graph ?? _ownGraph;

  void _setGraph(bool value) {
    if (widget.onGraphChanged != null) {
      widget.onGraphChanged!(value);
    } else {
      setState(() => _ownGraph = value);
    }
  }

  @override
  Widget build(BuildContext context) {
    final average = rackAverages(widget.entries).score;
    final variety = widget.machine == varietyGroupName;
    final machines = {for (final e in widget.entries) e.$1.machine};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Container(width: 5, height: 30, color: AppColors.carbon),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    variety
                        ? '$varietyGroupName（${machines.length}機種）'
                        : displayMachineName(widget.machine),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  Text(
                    '${widget.entries.length}台・平均 '
                    '${average?.toStringAsFixed(1) ?? '—'}点'
                    '${widget.candidateRacks.isEmpty ? '' : '・★${variety ? '参考候補' : '注目'}${widget.candidateRacks.length}台'}'
                    '${widget.longTrendRacks.isEmpty ? '' : '・☆長期傾向${widget.longTrendRacks.length}台'}',
                    style: const TextStyle(fontSize: 12, color: AppColors.ash),
                  ),
                ],
              ),
            ),
          ],
        ),
        if (variety)
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: Text(
              '1〜3台の機種をまとめています。点数・推定設定は台ごとに、その台の機種の'
              '過去と比べたもので、別の機種の台どうしは比べていません。',
              style: TextStyle(fontSize: 12, color: AppColors.ash),
            ),
          ),
        if (widget.candidateRacks.isNotEmpty ||
            widget.longTrendRacks.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              '★＝$referenceCandidateLegend'
              '${variety ? '' : '\n$regularReferenceCandidateNote'}',
              style: const TextStyle(fontSize: 12, color: AppColors.ash),
            ),
          ),
        if (!variety &&
            widget.longTrendRacks.isNotEmpty &&
            widget.candidateRacks.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 4),
            child: Text(
              '翌日向けの注目なし（当日情報・安定性・88点未満の条件を満たす台なし）',
              style: TextStyle(fontSize: 12, color: AppColors.ash),
            ),
          ),
        const SizedBox(height: 10),
        Row(
          children: [
            _TabButton(
              label: 'データ表示',
              selected: !_graph,
              onTap: () => _setGraph(false),
            ),
            const SizedBox(width: 6),
            _TabButton(
              label: 'グラフ表示',
              selected: _graph,
              onTap: () => _setGraph(true),
            ),
          ],
        ),
        if (SettingEstimatePresentation.twoChoicesOf(context) &&
            machines.any((m) => settingModelForMachine(m) != null))
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 6),
            child: Text(
              SettingEstimatePresentation.explanation,
              style: TextStyle(fontSize: 11, color: AppColors.ash),
            ),
          ),
        if (_graph)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: GraphGrid(
              entries: widget.entries,
              candidateRacks: widget.candidateRacks,
              longTrendRacks: widget.longTrendRacks,
              onTap: widget.onTap,
              onLongPress: widget.onLongPress,
              showMachine: variety || widget.showMachine,
            ),
          )
        else
          MachineDataTable(
            entries: widget.entries,
            candidateRacks: widget.candidateRacks,
            longTrendRacks: widget.longTrendRacks,
            onTap: widget.onTap,
            onLongPress: widget.onLongPress,
            showMachine: variety || widget.showMachine,
          ),
        ?widget.footer,
      ],
    );
  }
}

class _TabButton extends StatelessWidget {
  const _TabButton({
    required this.label,
    required this.selected,
    required this.onTap,
  });
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: selected ? AppColors.appleBlue : Colors.white,
    shape: RoundedRectangleBorder(
      borderRadius: const BorderRadius.vertical(top: Radius.circular(8)),
      side: BorderSide(
        color: selected ? AppColors.appleBlue : AppColors.hairline,
      ),
    ),
    child: InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 9),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 14,
            fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
            color: selected ? Colors.white : AppColors.carbon,
          ),
        ),
      ),
    ),
  );
}

/// 台番号の表。台番号の列は固定し、残りは横にスクロールする。
/// 一番下に平均の行（緑）。行は交互に色を付ける。
class MachineDataTable extends StatelessWidget {
  const MachineDataTable({
    super.key,
    required this.entries,
    required this.onTap,
    this.onLongPress,
    this.candidateRacks = const {},
    this.longTrendRacks = const {},
    this.showMachine = false,
  });
  final List<(SlotRecord, ScoreResult)> entries;
  final void Function(SlotRecord record, ScoreResult score) onTap;
  final void Function(SlotRecord record)? onLongPress;
  final Set<int> candidateRacks;
  final Set<int> longTrendRacks;

  /// 台番号の右に機種名の列を出す（バラエティ：別の機種の台が並ぶ）。
  /// 平均の行は、機種によって意味が変わる数字（BB・RB・確率・最大持玉）を
  /// 出さず、G数と点数だけにする。
  final bool showMachine;

  static const _machineWidth = 124.0;

  static const _rowHeight = 36.0;
  static const _rackWidth = 66.0;
  static const _headColor = Color(0xFF2B2B2E);
  static const _stripe = Color(0xFFF2F2F4);
  static const averageColor = Color(0xFFEAF6E4);

  // 列の見出しと幅。台番号の右に並ぶ列。
  static const _columns = <(String, double)>[
    ('G数', 56),
    ('BB', 40),
    ('RB', 40),
    ('合成確率', 76),
    ('BB確率', 76),
    ('RB確率', 76),
    ('最大持玉', 66),
    ('推定設定', 96),
    ('点数', 66),
  ];

  static const _cellBorder = Border(
    right: BorderSide(color: AppColors.hairline, width: .5),
    bottom: BorderSide(color: AppColors.hairline, width: .5),
  );

  static Widget _cell(
    Widget child, {
    required double width,
    Color? color,
    double height = _rowHeight,
  }) => Ink(
    // Container ではなく Ink：色付きのマスの上にもタップの波紋が見えるように。
    width: width,
    height: height,
    padding: const EdgeInsets.symmetric(horizontal: 4),
    decoration: BoxDecoration(color: color, border: _cellBorder),
    child: Center(
      child: FittedBox(fit: BoxFit.scaleDown, child: child),
    ),
  );

  static Text _text(String value, {bool bold = false, Color? color}) => Text(
    value,
    maxLines: 1,
    style: TextStyle(
      fontSize: 13,
      fontWeight: bold ? FontWeight.w700 : FontWeight.w400,
      color: color ?? AppColors.carbon,
    ),
  );

  /// 推定設定の欄。手入力の設定情報があればそちらを優先して出す。
  static Widget _setting(BuildContext context, SlotRecord record) {
    if (record.confirmedSetting case final setting?) {
      return _text('設定情報 $setting', bold: true, color: AppColors.linkBlue);
    }
    final estimate = estimateSetting(record);
    if (estimate == null) return _text('—', color: AppColors.mist);
    if (SettingEstimatePresentation.twoChoicesOf(context)) {
      return Tooltip(
        message: '${estimate.pairDetailLabel}\n${estimate.pairWeightLabel}',
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _text(estimate.pairLabel),
            Text(
              estimate.pairCaution,
              style: const TextStyle(fontSize: 10, color: AppColors.ash),
            ),
          ],
        ),
      );
    }
    if (estimate.range80.length == estimate.settingCount) {
      return _text('絞れず', color: AppColors.ash);
    }
    return _text(estimate.range80.join('・'));
  }

  /// 機種名のマス。長い名前は縮めずに「…」で切る（ほかのマスのように文字を
  /// 小さくすると読めなくなるため）。
  static Widget _machineCell(String machine, Color? color) => Ink(
    width: _machineWidth,
    height: _rowHeight,
    padding: const EdgeInsets.symmetric(horizontal: 6),
    decoration: BoxDecoration(color: color, border: _cellBorder),
    child: Align(
      alignment: Alignment.centerLeft,
      child: Text(
        displayMachineName(machine),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(fontSize: 12, color: AppColors.carbon),
      ),
    ),
  );

  static Widget _score(ScoreResult score) => ScorePill(
    compact: true,
    text: score.total?.toStringAsFixed(1) ?? '保留',
    tier: scoreTier(score.total),
  );

  @override
  Widget build(BuildContext context) {
    const head = TextStyle(
      fontSize: 12,
      fontWeight: FontWeight.w700,
      color: Colors.white,
    );
    final avg = rackAverages(entries);
    final pscube = entries.firstOrNull?.$1.isPscube == true;
    // P’s CUBEは元グラフの確定差枚、メルヘンはグラフと最大持玉からの推定差枚。
    final netLabel = entries.firstOrNull?.$1.netLabel ?? '差枚';
    final columns = <(String, double)>[
      ..._columns.take(7),
      (netLabel, 78.0),
      ..._columns.skip(7),
    ];
    final netValues = [
      for (final e in entries)
        if (!hasImplausibleNumbers(e.$1) && e.$1.netValue != null)
          e.$1.netValue!,
    ];
    // 暫定点は、記録が少ないうちはほぼ全台に付く。各行には書かず、
    // 表の上に1回だけ断る。
    final provisional = entries
        .where((e) => e.$2.total != null && e.$2.provisional)
        .length;
    Color? stripe(int i) => i.isOdd ? _stripe : Colors.white;

    Widget row(int i, List<Widget> cells) {
      final (record, score) = entries[i];
      return InkWell(
        onTap: () => onTap(record, score),
        onLongPress: onLongPress == null ? null : () => onLongPress!(record),
        child: Row(mainAxisSize: MainAxisSize.min, children: cells),
      );
    }

    final fixed = Column(
      children: [
        _cell(
          const Text('台番号', style: head),
          width: _rackWidth,
          color: _headColor,
        ),
        for (var i = 0; i < entries.length; i++)
          row(i, [
            _cell(
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _text('${entries[i].$1.rack}', bold: true),
                  if (candidateRacks.contains(entries[i].$1.rack) ||
                      longTrendRacks.contains(entries[i].$1.rack))
                    Text(
                      candidateRacks.contains(entries[i].$1.rack) ? ' ★' : ' ☆',
                      style: TextStyle(color: AppColors.linkBlue, fontSize: 13),
                    ),
                ],
              ),
              width: _rackWidth,
              color: stripe(i),
            ),
          ]),
        _cell(_text('平均', bold: true), width: _rackWidth, color: averageColor),
      ],
    );

    final scrolling = Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (showMachine)
              _cell(
                const Text('機種', style: head),
                width: _machineWidth,
                color: _headColor,
              ),
            for (final (label, width) in columns)
              _cell(
                Text(
                  label == '推定設定' &&
                          SettingEstimatePresentation.twoChoicesOf(context)
                      ? '推定2候補'
                      : label == '最大持玉' &&
                            entries.firstOrNull?.$1.isPscube == true
                      ? 'MY'
                      : label,
                  style: head,
                ),
                width: width,
                color: _headColor,
              ),
          ],
        ),
        for (var i = 0; i < entries.length; i++)
          row(i, [
            if (showMachine) _machineCell(entries[i].$1.machine, stripe(i)),
            for (final (index, child)
                in (hasImplausibleNumbers(entries[i].$1)
                        // サイトの数値が異常な台（88888888など）は、数字を出さない。
                        ? [
                            _text('異常'),
                            for (var k = 0; k < 6; k++) _text('—'),
                            if (pscube) _text('—'),
                            _setting(context, entries[i].$1),
                            _score(entries[i].$2),
                          ]
                        : [
                            _text('${entries[i].$1.games}'),
                            _text('${entries[i].$1.bb}'),
                            _text('${entries[i].$1.rb}'),
                            _text(
                              hitRate(
                                entries[i].$1.games,
                                entries[i].$1.bb + entries[i].$1.rb,
                              ),
                            ),
                            _text(
                              hitRate(entries[i].$1.games, entries[i].$1.bb),
                            ),
                            _text(
                              hitRate(entries[i].$1.games, entries[i].$1.rb),
                            ),
                            _text('${entries[i].$1.outputValue ?? '—'}'),
                            _text(
                              hasImplausibleNumbers(entries[i].$1) ||
                                      entries[i].$1.netValue == null
                                  ? '—'
                                  : signedMedals(entries[i].$1.netValue!),
                            ),
                            _setting(context, entries[i].$1),
                            _score(entries[i].$2),
                          ])
                    .indexed)
              _cell(child, width: columns[index].$2, color: stripe(i)),
          ]),
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (showMachine)
              _cell(_text(''), width: _machineWidth, color: averageColor),
            for (final (index, child) in [
              _text('${avg.games}'),
              if (showMachine) ...[
                for (var k = 0; k < 6; k++) _text('—', color: AppColors.mist),
              ] else ...[
                _text('${avg.bb}'),
                _text('${avg.rb}'),
                _text(avg.combined),
                _text(avg.bbRate),
                _text(avg.rbRate),
                _text('${avg.maxHold ?? '—'}'),
              ],
              _text(
                netValues.isEmpty
                    ? '—'
                    : signedMedals(
                        (netValues.reduce((a, b) => a + b) / netValues.length)
                            .round(),
                      ),
              ),
              _text(''),
              _text(avg.score?.toStringAsFixed(1) ?? '—', bold: true),
            ].indexed)
              _cell(child, width: columns[index].$2, color: averageColor),
          ],
        ),
      ],
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          decoration: BoxDecoration(
            border: Border.all(color: AppColors.hairline, width: .5),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 固定列の右に薄い影を付け、右側が横に動くことを分かりやすくする。
              DecoratedBox(
                decoration: const BoxDecoration(
                  color: Colors.white,
                  boxShadow: [
                    BoxShadow(
                      color: Color(0x22000000),
                      blurRadius: 4,
                      offset: Offset(2, 0),
                    ),
                  ],
                ),
                // マスは Ink で描くので、その下に Material を置く。
                child: Material(color: Colors.white, child: fixed),
              ),
              Expanded(
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Material(color: Colors.white, child: scrolling),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 4),
        Text(
          [
            '表は横にスライドできます',
            pscube
                ? '差枚は元グラフの取得済み${netValues.length}/${entries.length}台'
                : '推定差枚はグラフと最大持玉からの計算（誤差あり・計算できた${netValues.length}/${entries.length}台）',
            if (provisional > 0)
              provisional == entries.length
                  ? '点数はすべて暫定（少数データ・欠測を含む）'
                  : '$provisional台の点数は暫定（少数データ・欠測を含む）',
            if (candidateRacks.isNotEmpty || longTrendRacks.isNotEmpty)
              '★＝$referenceCandidateLegend',
          ].join('・'),
          style: const TextStyle(fontSize: 11, color: AppColors.ash),
        ),
      ],
    );
  }
}

/// グラフ表示：台ごとの小さなグラフを2列に並べ、下に数字を添える。
class GraphGrid extends StatelessWidget {
  const GraphGrid({
    super.key,
    required this.entries,
    required this.onTap,
    this.onLongPress,
    this.candidateRacks = const {},
    this.longTrendRacks = const {},
    this.showMachine = false,
  });
  final List<(SlotRecord, ScoreResult)> entries;
  final void Function(SlotRecord record, ScoreResult score) onTap;
  final void Function(SlotRecord record)? onLongPress;
  final Set<int> candidateRacks;
  final Set<int> longTrendRacks;

  /// 台番号の横に機種名を出す（バラエティ）。
  final bool showMachine;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      LayoutBuilder(
        builder: (context, constraints) {
          const gap = 8.0;
          final width = (constraints.maxWidth - gap) / 2;
          return Wrap(
            spacing: gap,
            runSpacing: gap,
            children: [
              for (final (record, score) in entries)
                SizedBox(
                  width: width,
                  child: _GraphCard(
                    record: record,
                    score: score,
                    showMachine: showMachine,
                    candidate: candidateRacks.contains(record.rack),
                    longTrend: longTrendRacks.contains(record.rack),
                    onTap: () => onTap(record, score),
                    onLongPress: onLongPress == null
                        ? null
                        : () => onLongPress!(record),
                  ),
                ),
            ],
          );
        },
      ),
      const SizedBox(height: 4),
      const Text(
        'グラフの縦の目盛りは台ごとに違います（サイトの表示に合わせた形）。タップで大きく表示。',
        style: TextStyle(fontSize: 11, color: AppColors.ash),
      ),
    ],
  );
}

class _GraphCard extends StatelessWidget {
  const _GraphCard({
    required this.record,
    required this.score,
    required this.candidate,
    this.longTrend = false,
    required this.onTap,
    this.onLongPress,
    this.showMachine = false,
  });
  final SlotRecord record;
  final ScoreResult score;
  final bool candidate;
  final bool longTrend;
  final bool showMachine;
  final VoidCallback onTap;
  final VoidCallback? onLongPress;

  @override
  Widget build(BuildContext context) {
    const small = TextStyle(fontSize: 11, color: AppColors.carbon);
    const head = TextStyle(
      fontSize: 11,
      fontWeight: FontWeight.w700,
      color: Colors.white,
    );
    final estimate = estimateSetting(record);
    final setting = record.confirmedSetting != null
        ? '設定情報 ${record.confirmedSetting}'
        : estimate == null
        ? null
        : SettingEstimatePresentation.twoChoicesOf(context)
        ? '候補 ${estimate.pairLabel}（${estimate.pairCaution}）'
        : estimate.range80.length == estimate.settingCount
        ? '推定 絞れず'
        : '推定 ${estimate.range80.join('・')}';
    Widget stat(String label, String value, int flex) => Expanded(
      flex: flex,
      child: Column(
        children: [
          Container(
            width: double.infinity,
            color: MachineDataTable._headColor,
            alignment: Alignment.center,
            child: Text(label, style: head),
          ),
          FittedBox(
            fit: BoxFit.scaleDown,
            child: Text(value, maxLines: 1, style: small),
          ),
        ],
      ),
    );
    return Material(
      color: Colors.white,
      clipBehavior: Clip.antiAlias,
      shape: const RoundedRectangleBorder(
        side: BorderSide(color: AppColors.hairline, width: .5),
      ),
      child: InkWell(
        onTap: onTap,
        onLongPress: onLongPress,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              color: slumpBackground,
              padding: const EdgeInsets.fromLTRB(8, 5, 6, 5),
              child: Row(
                children: [
                  Text(
                    '${record.rack}${candidate
                        ? ' ★'
                        : longTrend
                        ? ' ☆'
                        : ''}',
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  if (showMachine) ...[
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        displayMachineName(record.machine),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: Colors.white70,
                          fontSize: 10,
                        ),
                      ),
                    ),
                    const SizedBox(width: 4),
                  ] else
                    const Spacer(),
                  FittedBox(
                    child: ScorePill(
                      compact: true,
                      text: score.total?.toStringAsFixed(1) ?? '保留',
                      tier: scoreTier(score.total),
                    ),
                  ),
                ],
              ),
            ),
            SizedBox(
              height: 92,
              child: record.graph == null
                  ? ColoredBox(
                      color: slumpBackground,
                      child: Center(
                        child: Text(
                          record.graphNotNeeded ? '大当たり0回（グラフ省略）' : 'グラフ未取得',
                          style: const TextStyle(
                            color: AppColors.mist,
                            fontSize: 12,
                          ),
                        ),
                      ),
                    )
                  : SlumpTile(record: record),
            ),
            Row(
              children: [
                if (hasImplausibleNumbers(record)) ...[
                  stat('G数', '異常', 5),
                  stat('BB', '—', 3),
                  stat('RB', '—', 3),
                  stat('合成', '—', 6),
                ] else ...[
                  stat('G数', '${record.games}', 5),
                  stat('BB', '${record.bb}', 3),
                  stat('RB', '${record.rb}', 3),
                  stat('合成', hitRate(record.games, record.bb + record.rb), 6),
                ],
              ],
            ),
            if (setting != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(6, 2, 6, 4),
                child: Text(
                  setting,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 11, color: AppColors.ash),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// 通常の★と、その参考候補のカードで共用する説明。
const referenceCandidateLegend = '翌日向けの参考候補（通常機種は注目のみ）。☆＝長期傾向の上位。予測精度は検証中です。';

/// 4台以上の通常機種の選び方。バラエティの説明には使わない。
const regularReferenceCandidateNote =
    '直近10記録日の当たり順位を使うため、同じ台が続くことがあります。'
    '★注目は当日情報あり・安定性基準を満たす・当日88点未満（未採点は除外しない）の台だけです。'
    '翌日の良さを保証する印ではありません。';

/// 翌日向けの参考候補の効果についての説明。検証の結果は
/// `NEXT_DAY_CANDIDATES_VALIDATION_20260929.md` と
/// `NEXT_DAY_REFERENCE_REVIEW_20260930.md`。
const nextDayValidationNote =
    'これまでの検証では、参考候補の翌日の点数が判定できた台全体の平均より良いとは'
    '確認できていません（予測精度は検証中）。'
    '翌日の設定・勝率・期待収支を示すものではありません。';

/// 翌日候補（仮）：その日の全機種から、過去の当たりの軽さで選んだ台。
/// 1台1行で、台番号・機種・「平均より」の大きさ（棒）・過去何日分かを並べる。
/// バラエティ（1〜3台の機種）から選んだ台は、選び方の目盛りが違うので、
/// その後ろに「501番台　機種名（バラエティ）」の形で、前日の回転数と終わり方を
/// 添えて並べる（最初から全台を出す）。
class NextDayCandidatesCard extends StatefulWidget {
  const NextDayCandidatesCard({
    super.key,
    required this.day,
    required this.candidates,
    required this.machines,
    required this.judged,
    required this.onPick,
    this.allRecords = const [],
  });
  final String day;
  final List<ProvisionalCandidate> candidates;
  final List<SlotRecord> allRecords;

  /// その日の機種数と、候補を出せた機種数。
  final int machines, judged;
  final void Function(SlotRecord record) onPick;

  @override
  State<NextDayCandidatesCard> createState() => _NextDayCandidatesCardState();
}

class _NextDayCandidatesCardState extends State<NextDayCandidatesCard> {
  static const _first = 7;
  var _all = false;

  @override
  Widget build(BuildContext context) {
    final regular = [
      for (final c in widget.candidates)
        if (!c.variety) c,
    ];
    final variety = [
      for (final c in widget.candidates)
        if (c.variety) c,
    ];
    final focus = [
      for (final c in regular)
        if (candidateIsFocus(c, widget.allRecords)) c,
    ];
    final longTrend = [
      for (final c in regular)
        if (!candidateIsFocus(c, widget.allRecords)) c,
    ];
    final next = nextDayLabel(widget.day);
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
                    next.isEmpty ? '参考候補・長期傾向' : '$next の参考候補・長期傾向',
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
                    '検証中',
                    style: TextStyle(fontSize: 11, color: AppColors.ash),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              '${next.isEmpty ? '選択日' : '${shortDayLabel(widget.day)}（選択日）'}までの記録から、'
              '${next.isEmpty ? '翌日' : next}向けの★注目と、☆長期傾向を分けています。'
              '印は下の表・グラフと共通です。この日の点数には影響しません。',
              style: const TextStyle(
                color: AppColors.ash,
                fontSize: 13,
                height: 1.45,
              ),
            ),
            const SizedBox(height: 10),
            if (regular.isEmpty)
              const Text(
                'まだ判定できる機種（4台以上）がありません。同じ台・同じ機種のデータが'
                '3日分たまり、1機種で4台以上判定できると表示します。'
                '候補がないことは、不調を意味しません。',
                style: TextStyle(
                  color: AppColors.ash,
                  fontSize: 13,
                  height: 1.45,
                ),
              )
            else ...[
              const Text(
                '$regularReferenceCandidateNote'
                'この日の回転数が少ない台も、過去の記録から選ばれる場合があります。',
                style: note,
              ),
              const SizedBox(height: 8),
              Text(
                '★ 翌日向けに注目（${focus.length}台）',
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              if (focus.isEmpty)
                const Text('翌日向けの注目なし（当日情報・安定性・88点未満の条件を満たす台なし）', style: note),
              for (final (i, c) in (_all ? focus : focus.take(_first)).indexed)
                _row(i + 1, c),
              const SizedBox(height: 12),
              Text(
                '☆ 長期傾向の上位（${longTrend.length}台）',
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              for (final (i, c)
                  in (_all ? longTrend : longTrend.take(_first)).indexed)
                _row(i + 1, c),
              if (longTrend.length > _first || focus.length > _first)
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton(
                    onPressed: () => setState(() => _all = !_all),
                    child: Text(
                      _all ? '上位$_first台だけ表示' : 'すべて表示（${regular.length}台）',
                    ),
                  ),
                ),
              Text(
                '判定できた機種：${widget.judged} / ${widget.machines}機種'
                '（バラエティはまとめて1つ）。'
                '通常機種は判定できた台の上位4分の1を選んでいます。'
                '「平均より」は同じ日・同じ機種で回転数が近い台との当たり頻度の差の積み重ねで、'
                '別の機種どうしの順位は目安です。データ量は計算に使えた日数の目安で、'
                '当たりやすさを示すものではありません。',
                style: note,
              ),
            ],
            if (variety.isNotEmpty) ...[
              const SizedBox(height: 14),
              Text(
                '$varietyGroupName（1〜3台の機種）の参考候補${variety.length}台',
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                '${storeShortName(variety.first.record.store)}の狙い方：'
                '${varietyRuleText(variety.first.record.store)}。'
                '機種ごとに当たりの重さが違うので、別の機種の台どうしは比べていません。'
                '店ごとの狙い方は7日分の傾向に合わせたもので、外れる可能性も高いです。',
                style: note,
              ),
              for (final (i, c) in variety.indexed) _varietyRow(i + 1, c),
            ],
            const SizedBox(height: 6),
            const Text(
              nextDayValidationNote,
              style: TextStyle(
                color: AppColors.ash,
                fontSize: 12,
                height: 1.45,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// バラエティの1台：「501番台　機種名（バラエティ）」、前日の回転数・当たりの
  /// 普段比、右に前日の終わり方（凹み・プラス）。
  Widget _varietyRow(int rank, ProvisionalCandidate c) {
    final state = varietyState(c.record);
    final delta = c.index - 50;
    final hit = c.confidence == '比較なし'
        ? '当たりは普段と比べる記録が足りない'
        : '当たり 普段より ${delta >= 0 ? '+' : '-'}${delta.abs().toStringAsFixed(0)}'
              '（比べた記録${c.days}件）';
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
                      Flexible(
                        child: Text(
                          displayMachineName(c.record.machine),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 12,
                            color: AppColors.carbon,
                          ),
                        ),
                      ),
                      const Text(
                        '（$varietyGroupName）',
                        style: TextStyle(fontSize: 12, color: AppColors.ash),
                      ),
                    ],
                  ),
                  const SizedBox(height: 3),
                  Text(
                    '前日 ${_withComma(c.record.games)}G・${state.label}・$hit',
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
                  '前日',
                  style: TextStyle(fontSize: 10, color: AppColors.ash),
                ),
                Text(
                  state == VarietyState.plus ? 'プラス' : '凹み',
                  style: const TextStyle(
                    fontSize: 17,
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

  static String _withComma(int value) => value.toString().replaceAllMapped(
    RegExp(r'(\d)(?=(\d{3})+$)'),
    (m) => '${m[1]},',
  );

  Widget _row(int rank, ProvisionalCandidate c) {
    final delta = c.index - 50;
    final evidence = nextDayEvidence(c.record, widget.allRecords);
    final score = scoreRecord(c.record, widget.allRecords).total;
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
                        '${candidateIsFocus(c, widget.allRecords) ? '★' : '☆'} ${c.record.rack}番台',
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
                  // 棒の長さは「平均より」の大きさ（+25で満タン）。
                  ClipRRect(
                    borderRadius: BorderRadius.circular(3),
                    child: LinearProgressIndicator(
                      value: (delta / 25).clamp(0.04, 1.0),
                      minHeight: 6,
                      color: AppColors.appleBlue,
                      backgroundColor: AppColors.pebble,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    '過去${c.days}日分・データ量 ${c.confidence}',
                    style: const TextStyle(fontSize: 11, color: AppColors.ash),
                  ),
                  Text(
                    kIsWeb
                        // iPhoneの閲覧ページだけ、専門用語のあとに意味を添える。
                        ? '${evidence.todayTextExplained}\n'
                              '当たり順位の内訳：${evidence.bandsText}（上＝多い方から4分の1以内、下＝少ない方から4分の1以内）\n'
                              '${focusReason(evidence, score, explain: true)}'
                        : '${evidence.todayText}\n${evidence.bandsText}\n${focusReason(evidence, score)}',
                    style: const TextStyle(fontSize: 11, color: AppColors.ash),
                  ),
                  Text(
                    nextDayBottomScenario(
                      c.record,
                      widget.allRecords,
                      explain: kIsWeb,
                    ),
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
                  '平均より',
                  style: TextStyle(fontSize: 10, color: AppColors.ash),
                ),
                Text(
                  '${delta >= 0 ? '+' : '-'}${delta.abs().toStringAsFixed(0)}',
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

/// 50を中立とした過去傾向の指数を「平均より +13」の形にする。
/// 素の「63 / 100」では、50が中立であることも、上下どちらが良いのかも
/// 画面から読み取れないため。
String signedIndex(double index) {
  final delta = index - 50;
  final sign = delta >= 0 ? '+' : '-';
  return '平均より $sign${delta.abs().toStringAsFixed(0)}';
}

/// バラエティ（1〜3台の機種）の台の、翌日候補の見方（台の詳細に出す）。
String varietyJudgementText(SlotRecord record, List<SlotRecord> all) {
  final state = varietyState(record);
  final hit = varietyHitPercent(record, all);
  final delta = (hit.percent ?? 50) - 50;
  final detail = switch (state) {
    VarietyState.quiet => '${varietyBusyGames}G未満で、判断の材料が少ないので候補にしません',
    VarietyState.unknown => 'グラフが未取得で、終わり方が分からないので候補にしません',
    _ =>
      '${state.label}'
          '${hit.percent == null ? '（当たりは普段と比べる記録が足りない）' : '・当たり 普段より ${delta >= 0 ? '+' : '-'}${delta.abs().toStringAsFixed(0)}（比べた記録${hit.refs}件）'}',
  };
  return 'この台は1〜3台の機種なので「$varietyGroupName」にまとめています。'
      '翌日向けの参考候補は、${storeShortName(record.store)}で'
      '${varietyRuleText(record.store)}。\n'
      'この日のこの台：${record.games}G・$detail。'
      '当たりは同じ機種の前の30日（1台の機種ならこの台自身の過去）とだけ比べ、'
      '別の機種の台とは比べていません。';
}

/// 1台ぶんのグラフの小さな表示。保存時の画像があればそれを、無ければ採点に
/// 使った4点から復元した概略を描く。
class SlumpTile extends StatelessWidget {
  const SlumpTile({super.key, required this.record});
  final SlotRecord record;

  @override
  Widget build(BuildContext context) {
    final graph = record.graph!;
    // 保存時の画像がない古い記録（と、画像を読み込むまでの間）は、採点に
    // 使った4点から復元した概略で描く。
    final width = (graph.previewWidth ?? 400).toDouble();
    final height = math.max(
      (graph.previewHeight ?? 400).toDouble(),
      [
            graph.baselineY,
            graph.peakY,
            graph.troughY,
            graph.endY,
          ].reduce((a, b) => a > b ? a : b) +
          30,
    );
    // 保存したグラフの線があれば（閲覧ページなど）、それを描く。
    final curveSize = curveCanvasSize(graph);
    final sketch = CustomPaint(
      painter: curveSize != null
          ? CurveGraphPainter(
              curve: graph.curve!,
              baselineY: graph.baselineY,
              sourceWidth: curveSize.width,
              sourceHeight: curveSize.height,
              background: slumpBackground,
            )
          : ReconstructedGraphPainter(
              points: [
                Offset(width * .06, graph.baselineY),
                Offset(width * .34, graph.peakY),
                Offset(width * .66, graph.troughY),
                Offset(width * .94, graph.endY),
              ],
              sourceWidth: width,
              sourceHeight: height,
              background: slumpBackground,
            ),
    );
    // 保存された画像は作った端末・時期で背景の暗さが違う（透明・黒・濃紺）。
    // 5日分の明るさを揃えるため、どのタイルも同じ背景色の上に描く。
    // 画像は一覧に載せていないので、表示するときにDBから読む。
    return graph.hasPreview
        ? StoredGraphImage(
            record: record,
            fallback: sketch,
            background: slumpBackground,
          )
        : sketch;
  }
}

const slumpBackground = Color(0xFF0C0C10);

/// 保存したグラフの線（曲線）を描くときの座標の大きさ（幅・高さ）。描ける曲線が
/// 無ければ null。
///
/// 曲線は画像と同じ座標系で、ふつうは保存した幅・高さ（preview_width/height）に
/// 収まる。PC版の取り込みの一部は曲線の座標の方が広いので、そのときは幅を曲線に
/// 合わせ、高さも同じ割合で広げる（縦横の比は画像と同じ）。
({double width, double height})? curveCanvasSize(GraphMeasurement graph) {
  final curve = graph.curve;
  if (curve == null || curve.length < 2 || curve.any((p) => p.length < 2)) {
    return null;
  }
  final maxX = curve.map((p) => p[0]).reduce(math.max);
  final maxY = [...curve.map((p) => p[1]), graph.baselineY].reduce(math.max);
  final previewWidth = graph.previewWidth?.toDouble();
  final previewHeight = graph.previewHeight?.toDouble();
  if (previewWidth == null || previewHeight == null || previewWidth <= 0) {
    return (width: math.max(maxX, 1), height: maxY + 30);
  }
  final width = math.max(previewWidth, maxX);
  final height = previewHeight * width / previewWidth;
  return (width: width, height: math.max(height, maxY + 10));
}

/// 保存したグラフの線（サイトのSVGの線そのもの）を描く。画像を持たない
/// 閲覧ページで、概略図の代わりに使う。
class CurveGraphPainter extends CustomPainter {
  const CurveGraphPainter({
    required this.curve,
    required this.baselineY,
    required this.sourceWidth,
    required this.sourceHeight,
    this.background = AppColors.carbon,
  });
  final List<List<double>> curve;
  final double baselineY;
  final double sourceWidth, sourceHeight;
  final Color background;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = background);
    Offset scale(List<double> p) => Offset(
      p[0] / sourceWidth * size.width,
      p[1] / sourceHeight * size.height,
    );
    final baseline = baselineY / sourceHeight * size.height;
    canvas.drawLine(
      Offset(0, baseline),
      Offset(size.width, baseline),
      Paint()
        ..color = Colors.redAccent
        ..strokeWidth = 1.2,
    );
    final first = scale(curve.first);
    final path = Path()..moveTo(first.dx, first.dy);
    for (final point in curve.skip(1)) {
      final scaled = scale(point);
      path.lineTo(scaled.dx, scaled.dy);
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = const Color(0xffe8edf0)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.6
        ..strokeJoin = StrokeJoin.round
        ..isAntiAlias = true,
    );
  }

  @override
  bool shouldRepaint(covariant CurveGraphPainter oldDelegate) =>
      !identical(oldDelegate.curve, curve) ||
      oldDelegate.baselineY != baselineY ||
      oldDelegate.sourceWidth != sourceWidth ||
      oldDelegate.sourceHeight != sourceHeight ||
      oldDelegate.background != background;
}

class ReconstructedGraphPainter extends CustomPainter {
  const ReconstructedGraphPainter({
    required this.points,
    required this.sourceWidth,
    required this.sourceHeight,
    this.background = AppColors.carbon,
  });
  final List<Offset> points;
  final double sourceWidth, sourceHeight;
  final Color background;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = background);
    Offset scale(Offset p) => Offset(
      p.dx / sourceWidth * size.width,
      p.dy / sourceHeight * size.height,
    );
    final baseline = scale(points.first).dy;
    canvas.drawLine(
      Offset(0, baseline),
      Offset(size.width, baseline),
      Paint()
        ..color = Colors.redAccent
        ..strokeWidth = 1.5,
    );
    final path = Path()..moveTo(0, baseline);
    for (final point in points.skip(1)) {
      final scaled = scale(point);
      path.lineTo(scaled.dx, scaled.dy);
    }
    path.lineTo(size.width, scale(points.last).dy);
    canvas.drawPath(
      path,
      Paint()
        ..color = const Color(0xffe8edf0)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  @override
  bool shouldRepaint(covariant ReconstructedGraphPainter oldDelegate) =>
      oldDelegate.points != points ||
      oldDelegate.sourceWidth != sourceWidth ||
      oldDelegate.sourceHeight != sourceHeight ||
      oldDelegate.background != background;
}
