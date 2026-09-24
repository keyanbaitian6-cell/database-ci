import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'data_checks.dart';
import 'list_views.dart';
import 'models.dart';
import 'setting_estimate.dart';
import 'theme.dart';

// 結果タブ・過去の記録で使う、機種ごとの表示。
// アナスロの機種別データ（データ表示／グラフ表示のタブ、台番号の表、平均の行）
// の見せ方に、このアプリの点数・推定設定・翌日候補（仮）を加えている。

/// 機種の見出しと「データ表示／グラフ表示」のタブ、その中身。
class MachineSection extends StatefulWidget {
  const MachineSection({
    super.key,
    required this.machine,
    required this.entries,
    required this.onTap,
    this.onLongPress,
    this.candidateRacks = const {},
    this.footer,
    this.graph,
    this.onGraphChanged,
  });

  final String machine;

  /// 台番号順の台と点数。
  final List<(SlotRecord, ScoreResult)> entries;
  final void Function(SlotRecord record, ScoreResult score) onTap;
  final void Function(SlotRecord record)? onLongPress;

  /// 翌日候補（仮）に入った台番号。表とグラフに★を付ける。
  final Set<int> candidateRacks;

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
                    widget.machine,
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
                    '${widget.candidateRacks.isEmpty ? '' : '・★翌日候補${widget.candidateRacks.length}台'}',
                    style: const TextStyle(fontSize: 12, color: AppColors.ash),
                  ),
                ],
              ),
            ),
          ],
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
        if (_graph)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: GraphGrid(
              entries: widget.entries,
              candidateRacks: widget.candidateRacks,
              onTap: widget.onTap,
              onLongPress: widget.onLongPress,
            ),
          )
        else
          MachineDataTable(
            entries: widget.entries,
            candidateRacks: widget.candidateRacks,
            onTap: widget.onTap,
            onLongPress: widget.onLongPress,
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
  });
  final List<(SlotRecord, ScoreResult)> entries;
  final void Function(SlotRecord record, ScoreResult score) onTap;
  final void Function(SlotRecord record)? onLongPress;
  final Set<int> candidateRacks;

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
  static Widget _setting(SlotRecord record) {
    if (record.confirmedSetting case final setting?) {
      return _text('設定情報 $setting', bold: true, color: AppColors.linkBlue);
    }
    final estimate = estimateSetting(record);
    if (estimate == null) return _text('—', color: AppColors.mist);
    if (estimate.range80.length == estimate.settingCount) {
      return _text('絞れず', color: AppColors.ash);
    }
    return _text(estimate.range80.join('・'));
  }

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
                  if (candidateRacks.contains(entries[i].$1.rack))
                    const Text(
                      ' ★',
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
            for (final (label, width) in _columns)
              _cell(
                Text(label, style: head),
                width: width,
                color: _headColor,
              ),
          ],
        ),
        for (var i = 0; i < entries.length; i++)
          row(i, [
            for (final (index, child) in [
              _text('${entries[i].$1.games}'),
              _text('${entries[i].$1.bb}'),
              _text('${entries[i].$1.rb}'),
              _text(
                hitRate(
                  entries[i].$1.games,
                  entries[i].$1.bb + entries[i].$1.rb,
                ),
              ),
              _text(hitRate(entries[i].$1.games, entries[i].$1.bb)),
              _text(hitRate(entries[i].$1.games, entries[i].$1.rb)),
              _text('${entries[i].$1.maxHold ?? '—'}'),
              _setting(entries[i].$1),
              _score(entries[i].$2),
            ].indexed)
              _cell(child, width: _columns[index].$2, color: stripe(i)),
          ]),
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final (index, child) in [
              _text('${avg.games}'),
              _text('${avg.bb}'),
              _text('${avg.rb}'),
              _text(avg.combined),
              _text(avg.bbRate),
              _text(avg.rbRate),
              _text('${avg.maxHold ?? '—'}'),
              _text(''),
              _text(avg.score?.toStringAsFixed(1) ?? '—', bold: true),
            ].indexed)
              _cell(child, width: _columns[index].$2, color: averageColor),
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
            if (provisional > 0)
              provisional == entries.length
                  ? '点数はすべて暫定（少数データ・欠測を含む）'
                  : '$provisional台の点数は暫定（少数データ・欠測を含む）',
            if (candidateRacks.isNotEmpty) '★＝翌日候補（仮）',
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
  });
  final List<(SlotRecord, ScoreResult)> entries;
  final void Function(SlotRecord record, ScoreResult score) onTap;
  final void Function(SlotRecord record)? onLongPress;
  final Set<int> candidateRacks;

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
                    candidate: candidateRacks.contains(record.rack),
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
    required this.onTap,
    this.onLongPress,
  });
  final SlotRecord record;
  final ScoreResult score;
  final bool candidate;
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
                    '${record.rack}${candidate ? ' ★' : ''}',
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
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
                  ? const ColoredBox(
                      color: slumpBackground,
                      child: Center(
                        child: Text(
                          'グラフ未取得',
                          style: TextStyle(color: AppColors.mist, fontSize: 12),
                        ),
                      ),
                    )
                  : SlumpTile(record: record),
            ),
            Row(
              children: [
                stat('G数', '${record.games}', 5),
                stat('BB', '${record.bb}', 3),
                stat('RB', '${record.rb}', 3),
                stat('合成', hitRate(record.games, record.bb + record.rb), 6),
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

/// 翌日候補（仮）：その日の全機種から、過去の当たりの軽さで選んだ台。
/// 1台1行で、台番号・機種・「平均より」の大きさ（棒）・過去何日分かを並べる。
class NextDayCandidatesCard extends StatefulWidget {
  const NextDayCandidatesCard({
    super.key,
    required this.day,
    required this.candidates,
    required this.machines,
    required this.judged,
    required this.onPick,
  });
  final String day;
  final List<ProvisionalCandidate> candidates;

  /// その日の機種数と、候補を出せた機種数。
  final int machines, judged;
  final void Function(SlotRecord record) onPick;

  @override
  State<NextDayCandidatesCard> createState() => _NextDayCandidatesCardState();
}

class _NextDayCandidatesCardState extends State<NextDayCandidatesCard> {
  static const _first = 10;
  var _all = false;

  @override
  Widget build(BuildContext context) {
    final shown = _all
        ? widget.candidates
        : widget.candidates.take(_first).toList();
    final next = nextDayLabel(widget.day);
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
                    next.isEmpty ? '翌日候補（仮）' : '$next の候補（仮）',
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
                    '試験中',
                    style: TextStyle(fontSize: 11, color: AppColors.ash),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            const Text(
              '過去の当たりが、同じ機種の周りの台より軽かった台です（各機種の上位4分の1）。'
              '明日どの台から見るかの参考用で、今日の点数には影響しません。',
              style: TextStyle(
                color: AppColors.ash,
                fontSize: 13,
                height: 1.45,
              ),
            ),
            const SizedBox(height: 10),
            if (widget.candidates.isEmpty)
              const Text(
                'まだ判定できる機種がありません。同じ台・同じ機種のデータが3日分たまり、'
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
                '判定できた機種：${widget.judged} / ${widget.machines}機種。'
                '「平均より」は同じ日・同じ機種で回転数が近い台との当たり頻度の差の積み重ねで、'
                '別の機種どうしの順位は目安です。★は下の表にも付けています。',
                style: const TextStyle(
                  color: AppColors.ash,
                  fontSize: 12,
                  height: 1.45,
                ),
              ),
            ],
            const SizedBox(height: 6),
            const Text(
              '翌日の設定・勝率・期待収支を示すものではありません（効果は検証中）。',
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

  Widget _row(int rank, ProvisionalCandidate c) {
    final delta = c.index - 50;
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
                          c.record.machine,
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

/// 1台ぶんのグラフの小さな表示。保存時の画像があればそれを、無ければ採点に
/// 使った4点から復元した概略を描く。
class SlumpTile extends StatelessWidget {
  const SlumpTile({super.key, required this.record});
  final SlotRecord record;

  @override
  Widget build(BuildContext context) {
    final graph = record.graph!;
    // 保存された画像は作った端末・時期で背景の暗さが違う（透明・黒・濃紺）。
    // 5日分の明るさを揃えるため、どのタイルも同じ背景色の上に描く。
    if (graph.previewPng != null) {
      return ColoredBox(
        color: slumpBackground,
        child: Image.memory(
          graph.previewPng!,
          fit: BoxFit.fill,
          filterQuality: FilterQuality.medium,
        ),
      );
    }
    // 保存時の画像がない古い記録は、採点に使った4点から復元した概略で描く。
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
    return CustomPaint(
      painter: ReconstructedGraphPainter(
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
  }
}

const slumpBackground = Color(0xFF0C0C10);

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
