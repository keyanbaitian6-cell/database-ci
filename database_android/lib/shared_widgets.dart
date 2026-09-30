import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'data_checks.dart';
import 'graph_preview.dart';
import 'list_views.dart';
import 'machine_sections.dart';
import 'models.dart';
import 'scoring.dart';
import 'setting_estimate.dart';
import 'setting_estimate_presentation.dart';
import 'theme.dart';

// 結果・記録の表示に使う部品。Android版（main.dart）と、iPhoneで見る
// ための閲覧ページ（viewer_main.dart）の両方で使う。取り込み・保存には
// 触れないので、端末のDBやアプリ内ブラウザに依存しない。

/// Top racks of the selected store and date across every machine, plus how
/// complete the day is. Tapping a row opens that rack's graph and hit details.
class DaySummaryCard extends StatelessWidget {
  const DaySummaryCard({
    super.key,
    required this.entries,
    required this.onPick,
  });
  final List<(SlotRecord, ScoreResult)> entries;
  final void Function(SlotRecord, ScoreResult) onPick;

  @override
  Widget build(BuildContext context) {
    final scored = entries.where((e) => e.$2.total != null).toList()
      ..sort((a, b) => b.$2.total!.compareTo(a.$2.total!));
    final provisional = scored.where((e) => e.$2.provisional).length;
    final noGraph = entries.where((e) => !e.$1.graphDone).length;
    final skipped = entries.where((e) => e.$1.graphNotNeeded).length;
    final odd = suspiciousDuplicates(entries.map((e) => e.$1));
    final missingByMachine = <String, List<int>>{};
    for (final e in entries.where((e) => !e.$1.graphDone)) {
      missingByMachine.putIfAbsent(e.$1.machine, () => []).add(e.$1.rack);
    }
    for (final racks in missingByMachine.values) {
      racks.sort();
    }
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'この日のまとめ',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 4),
            Text(
              '${entries.length}台　合計点確定${scored.length}台（暫定$provisional台）'
              '　保留${entries.length - scored.length}台　グラフ未取得$noGraph台'
              '${skipped > 0 ? '（大当たり0回でグラフ省略$skipped台は除く）' : ''}',
              style: const TextStyle(color: AppColors.ash, fontSize: 13),
            ),
            const SizedBox(height: 8),
            if (scored.isEmpty)
              const Text(
                '合計点が確定した台はまだありません。',
                style: TextStyle(color: AppColors.ash),
              ),
            if (odd.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(
                  '⚠ 要確認：数値（回転・BIG・REG）が完全に同じ台 — '
                  '${odd.map((g) => '${g.$1} ${g.$2.join('・')}番台').join('、')}。'
                  '台番号のずれで別の台のデータが保存された可能性があります。',
                  style: const TextStyle(fontSize: 13),
                ),
              ),
            if (missingByMachine.isNotEmpty)
              Theme(
                data: Theme.of(context)
                    .copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  childrenPadding: EdgeInsets.zero,
                  title: Text(
                    'グラフ未取得の台（$noGraph台）',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  children: [
                    for (final entry in missingByMachine.entries)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: Text(
                            '${displayMachineName(entry.key)}　${entry.value.length}台：${entry.value.join('、')}',
                          ),
                        ),
                      ),
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        '「取り込み」のブラウザで各台のグラフを取り込むと、この一覧から消えます。',
                        style: TextStyle(color: AppColors.ash, fontSize: 12),
                      ),
                    ),
                    const SizedBox(height: 8),
                  ],
                ),
              ),
            for (final e in scored.take(5))
              InkWell(
                onTap: () => onPick(e.$1, e.$2),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Row(
                    children: [
                      // 台番号は必ず出す。長い機種名の方を縮める
                      // （以前は機種名に押し出されて「710…」と切れていた）。
                      Expanded(
                        child: Text(
                          displayMachineName(e.$1.machine),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        '${e.$1.rack}番台',
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      const SizedBox(width: 8),
                      ScorePill(
                        text:
                            '${e.$2.provisional ? '暫定 ' : ''}${e.$2.total!.toStringAsFixed(1)}',
                        tier: scoreTier(e.$2.total),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// 機種名で絞り込む入力欄。ひらがな・半角カナでも一致する（[machineMatches]）。
class MachineSearchField extends StatelessWidget {
  const MachineSearchField({
    super.key,
    required this.controller,
    required this.onChanged,
  });
  final TextEditingController controller;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) => TextField(
    controller: controller,
    onChanged: (_) => onChanged(),
    textInputAction: TextInputAction.search,
    decoration: InputDecoration(
      isDense: true,
      prefixIcon: const Icon(Icons.search),
      hintText: '機種名で絞り込み（例：じゃぐらー）',
      suffixIcon: controller.text.isEmpty
          ? null
          : IconButton(
              tooltip: '絞り込みを消す',
              icon: const Icon(Icons.close),
              onPressed: () {
                controller.clear();
                onChanged();
              },
            ),
    ),
  );
}

/// 平均点の小さな表示（一覧の行の右端用）。
class AverageBadge extends StatelessWidget {
  const AverageBadge({super.key, required this.average});
  final double? average;

  @override
  Widget build(BuildContext context) => Column(
    mainAxisSize: MainAxisSize.min,
    crossAxisAlignment: CrossAxisAlignment.end,
    children: [
      const Text('平均', style: TextStyle(fontSize: 10, color: AppColors.ash)),
      ScorePill(
        compact: true,
        text: average?.toStringAsFixed(1) ?? '—',
        tier: scoreTier(average),
      ),
    ],
  );
}

/// 結果タブの機種一覧。1機種1行で、台数・平均点・最高点を並べる。
class MachineSummaryList extends StatelessWidget {
  const MachineSummaryList({
    super.key,
    required this.summaries,
    required this.onPick,
  });
  final List<MachineSummary> summaries;
  final void Function(String machine) onPick;

  @override
  Widget build(BuildContext context) {
    if (summaries.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: Text(
          '機種名に一致する機種がありません。',
          style: TextStyle(color: AppColors.ash),
        ),
      );
    }
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          for (var i = 0; i < summaries.length; i++) ...[
            if (i > 0) const Divider(height: 1),
            InkWell(
              onTap: () => onPick(summaries[i].machine),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            summaries[i].variety
                                ? '$varietyGroupName（${summaries[i].machines}機種）'
                                : displayMachineName(summaries[i].machine),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            _detail(summaries[i]),
                            style: const TextStyle(
                              fontSize: 12,
                              color: AppColors.ash,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 8),
                    AverageBadge(average: summaries[i].average),
                    const Icon(Icons.chevron_right, color: AppColors.mist),
                  ],
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  static String _detail(MachineSummary s) => [
    s.variety ? '1〜3台の機種の${s.racks}台' : '${s.racks}台',
    if (s.best != null) '最高${s.best!.toStringAsFixed(1)}',
    if (s.noGraph > 0) 'グラフ未取得${s.noGraph}台',
  ].join('・');
}

class SavedGraphPage extends StatefulWidget {
  const SavedGraphPage({
    super.key,
    required this.record,
    this.score,
    this.allRecords,
    this.dateNavigation,
    this.scrollTopButton = false,
  });
  final SlotRecord record;
  final ScoreResult? score;
  final List<SlotRecord>? allRecords;
  final PreferredSizeWidget? dateNavigation;

  /// 右下に「一番上へ」ボタン（[ScrollTopButton]）を出す（閲覧ページ用）。
  final bool scrollTopButton;

  @override
  State<SavedGraphPage> createState() => _SavedGraphPageState();
}

class _SavedGraphPageState extends State<SavedGraphPage> {
  final _scroll = ScrollController();

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final record = widget.record;
    final score = widget.score;
    final allRecords = widget.allRecords;
    final graph = record.graph;
    // ボタンを出すときだけリストに付ける（Android版はこれまでどおり）。
    final controller = widget.scrollTopButton ? _scroll : null;
    // ボタンを出すときは、最後の行がボタンに隠れないよう下を空ける。
    final bottom =
        (widget.scrollTopButton ? 88 : 16) +
        MediaQuery.of(context).viewPadding.bottom;
    return Scaffold(
      appBar: AppBar(
        title: Text('${record.rack}番台'),
        bottom: widget.dateNavigation,
      ),
      floatingActionButton: widget.scrollTopButton
          ? ScrollTopButton(controller: _scroll)
          : null,
      body: graph == null
          ? ListView(
              controller: controller,
              padding: EdgeInsets.fromLTRB(16, 16, 16, bottom),
              children: [
                RackStats(record: record, score: score),
                const SizedBox(height: 12),
                const EmptyState(
                  icon: Icons.show_chart,
                  title: 'グラフは未保存です',
                  body: 'この台は一覧だけが保存されています。',
                ),
                if (allRecords != null)
                  SlumpStrip(record: record, all: allRecords),
                if (allRecords != null)
                  RackTrend(record: record, all: allRecords),
              ],
            )
          : _SavedGraphBody(
              record: record,
              graph: graph,
              score: score,
              allRecords: allRecords,
              controller: controller,
              bottom: bottom,
            ),
    );
  }
}

/// Recent days of this rack (same machine): score, games and hit rate, so a
/// rack's habits are visible without opening each day.
class RackTrend extends StatelessWidget {
  const RackTrend({super.key, required this.record, required this.all});
  final SlotRecord record;
  final List<SlotRecord> all;

  @override
  Widget build(BuildContext context) {
    final trend = rackTrend(record, all);
    if (trend.length < 2) {
      return const Padding(
        padding: EdgeInsets.only(top: 12),
        child: Text(
          'この台の過去データ（同じ機種）はまだありません。',
          style: TextStyle(color: AppColors.ash, fontSize: 13),
        ),
      );
    }
    // 1〜3台の機種（バラエティ）は、回転数と終わり方で見る（過去傾向の指数は無い）。
    final variety = isVarietyRecord(record, all);
    final forecast = nextDayIndex(record, all);
    final evidence = nextDayEvidence(record, all);
    final totals = trend.map((e) => e.$2.total).whereType<double>().toList();
    final average = totals.isEmpty
        ? ''
        : '（平均 ${(totals.reduce((a, b) => a + b) / totals.length).toStringAsFixed(1)}点）';
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'この台の推移（同じ機種・直近${trend.length}日）$average',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 8),
              for (final (r, s) in trend)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    children: [
                      Expanded(child: Text(r.day)),
                      SizedBox(
                        width: 84,
                        child: Text(
                          s.total == null
                              ? '—'
                              : '${s.provisional ? '暫定 ' : ''}${s.total!.toStringAsFixed(1)}',
                          textAlign: TextAlign.right,
                          style: TextStyle(
                            fontWeight: FontWeight.w600,
                            color: r.day == record.day
                                ? AppColors.linkBlue
                                : null,
                          ),
                        ),
                      ),
                      SizedBox(
                        width: 70,
                        child: Text('${r.games}G', textAlign: TextAlign.right),
                      ),
                      SizedBox(
                        width: 72,
                        child: Text(
                          r.bb + r.rb > 0
                              ? '1/${(r.games / (r.bb + r.rb)).toStringAsFixed(1)}'
                              : '—',
                          textAlign: TextAlign.right,
                        ),
                      ),
                    ],
                  ),
                ),
              const SizedBox(height: 8),
              Text(
                variety
                    ? '${varietyJudgementText(record, all)}\n$nextDayValidationNote'
                    : forecast.index == null
                    ? 'この台の当たりの軽さ（過去傾向）：まだ判定できません'
                          '（同じ機種で${forecast.days}日分／3日分から判定）'
                    : 'この台の当たりの軽さ（過去傾向）：'
                          '${signedIndex(forecast.index!)}'
                          '（過去${forecast.days}日分・データ量${forecast.confidence}）\n'
                          '同じ日・同じ機種で回転数が近い台と比べた当たり頻度の差です。'
                          '★注目・☆長期傾向の根拠に使っています。今日の合計点とは別で、'
                          'データ量は計算に使えた日数の目安です。\n'
                          '$regularReferenceCandidateNote\n$nextDayValidationNote',
                style: const TextStyle(
                  color: AppColors.ash,
                  fontSize: 12,
                  height: 1.45,
                ),
              ),
              if (!variety) ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: const Text('★注目・☆長期傾向の理由', style: TextStyle(fontSize: 13)),
                children: [Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Text(regularCandidateDetail(record, all, evidence),
                    style: const TextStyle(color: AppColors.ash, fontSize: 12, height: 1.5)),
                )],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Score, hit count and hit rate at a glance -- the numbers worth reading
/// next to the graph, without expanding a list card first.
class RackStats extends StatelessWidget {
  const RackStats({super.key, required this.record, this.score});
  final SlotRecord record;
  final ScoreResult? score;

  @override
  Widget build(BuildContext context) {
    final hits = record.bb + record.rb;
    final estimate = estimateSetting(record);
    final rate = hits > 0
        ? '1/${(record.games / hits).toStringAsFixed(1)}'
        : '—';
    final total = score?.total;
    Widget chip(String label, double? value) => Chip(
      label: Text('$label　${value == null ? '—' : value.toStringAsFixed(1)}'),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${record.day}　${storeNames[record.store]}',
          style: const TextStyle(color: AppColors.ash),
        ),
        const SizedBox(height: 2),
        Text(
          displayMachineName(record.machine),
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
        ),
        if (score != null) ...[
          const SizedBox(height: 10),
          Row(
            children: [
              ScorePill(
                text: total == null
                    ? '保留'
                    : '${score!.provisional ? '暫定 ' : ''}${total.toStringAsFixed(1)}',
                tier: scoreTier(total),
              ),
              const SizedBox(width: 10),
              const Text('合計点', style: TextStyle(color: AppColors.ash)),
            ],
          ),
        ],
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: MetricCard(label: '当たり回数', value: '$hits回'),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: MetricCard(label: '当たり確率', value: rate),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: MetricCard(label: '総回転', value: '${record.games}G'),
            ),
          ],
        ),
        const SizedBox(height: 6),
        Text('BIG ${record.bb}　REG ${record.rb}　最大持玉 ${record.maxHold ?? '—'}'),
        Text(
          '観測量（設定判別の信頼度ではありません）：${reliabilityLabel(record.games)}'
          '${capturedNote(record).isEmpty ? '' : '　｜　${capturedNote(record)}'}',
          style: const TextStyle(color: AppColors.ash, fontSize: 12),
        ),
        if (estimate != null) ...[
          const SizedBox(height: 8),
          Text(
            SettingEstimatePresentation.twoChoicesOf(context)
                ? estimate.pairDetailLabel
                : estimate.detailLabel,
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          if (SettingEstimatePresentation.twoChoicesOf(context)) ...[
            Text(estimate.pairWeightLabel),
            SelectableText(
              '確率表（メーカー公表）：${estimate.source}',
              style: const TextStyle(color: AppColors.ash, fontSize: 11),
            ),
            Text(
              estimate.games <= 500
                  ? '500G以下の少数観測です。2候補とも参考扱いです。'
                  : estimate.outsideWeight >= estimate.topTwoWeight
                  ? '候補外の合計重みが半分以上あり、2つには十分絞れていません。'
                  : '表示は上位2つだけです。候補外の設定を否定するものではありません。',
              style: const TextStyle(color: AppColors.ash, fontSize: 12),
            ),
            if (record.confirmedSetting != null)
              Text('手入力の設定情報：${record.confirmedSetting}（このBB/RB推定とは別の情報）'),
          ],
          const Text(
            'BB/RBのみ・各設定同じ事前重みで比較。実際の設定確率や翌日の予測ではありません。',
            style: TextStyle(color: AppColors.ash, fontSize: 12),
          ),
        ],
        if (score != null) ...[
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              chip('持玉 /20', score!.maxHold),
              chip('当り /60', score!.hits),
              chip('終点 /10', score!.positive),
              chip('維持 /10', score!.retention),
            ],
          ),
          Text(
            score!.reasons.join('・'),
            style: const TextStyle(color: AppColors.ash, fontSize: 12),
          ),
        ],
      ],
    );
  }
}

class _SavedGraphBody extends StatelessWidget {
  const _SavedGraphBody({
    required this.record,
    required this.graph,
    required this.bottom,
    this.score,
    this.allRecords,
    this.controller,
  });
  final SlotRecord record;
  final GraphMeasurement graph;
  final ScoreResult? score;
  final List<SlotRecord>? allRecords;
  final ScrollController? controller;

  /// リストの下の余白。
  final double bottom;

  @override
  Widget build(BuildContext context) {
    final hasImage = graph.hasPreview;
    // 画像が無くても、保存したグラフの線があれば（閲覧ページ）それを描く。
    final curveSize = hasImage ? null : curveCanvasSize(graph);
    final values = [graph.baselineY, graph.peakY, graph.troughY, graph.endY];
    final maxY = values.reduce((a, b) => a > b ? a : b);
    final width = curveSize?.width ?? (graph.previewWidth ?? 400).toDouble();
    final height =
        curveSize?.height ??
        math.max((graph.previewHeight ?? 400).toDouble(), maxY + 30).toDouble();
    final points =
        hasImage &&
            graph.baselineX != null &&
            graph.peakX != null &&
            graph.troughX != null &&
            graph.endX != null
        ? [
            Offset(graph.baselineX!, graph.baselineY),
            Offset(graph.peakX!, graph.peakY),
            Offset(graph.troughX!, graph.troughY),
            Offset(graph.endX!, graph.endY),
          ]
        : [
            Offset(width * .06, graph.baselineY),
            Offset(width * .34, graph.peakY),
            Offset(width * .66, graph.troughY),
            Offset(width * .94, graph.endY),
          ];
    return ListView(
      controller: controller,
      padding: EdgeInsets.fromLTRB(16, 16, 16, bottom),
      children: [
        RackStats(record: record, score: score),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                AspectRatio(
                  aspectRatio: width / height,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      if (hasImage)
                        // 画像は一覧に載せていないので、表示するときに読む。
                        StoredGraphImage(
                          record: record,
                          fallback: CustomPaint(
                            painter: ReconstructedGraphPainter(
                              points: points,
                              sourceWidth: width,
                              sourceHeight: height,
                            ),
                          ),
                        )
                      else if (curveSize != null)
                        CustomPaint(
                          painter: CurveGraphPainter(
                            curve: graph.curve!,
                            baselineY: graph.baselineY,
                            sourceWidth: width,
                            sourceHeight: height,
                          ),
                        )
                      else
                        CustomPaint(
                          painter: ReconstructedGraphPainter(
                            points: points,
                            sourceWidth: width,
                            sourceHeight: height,
                          ),
                        ),
                    ],
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  hasImage
                      ? '保存時のグラフです。'
                      : curveSize != null
                      ? '保存時のグラフの線から描いたグラフです。'
                      : '保存時の画像がないため、採点に使った4点から復元した概略グラフです。',
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ),
        if (allRecords != null) SlumpStrip(record: record, all: allRecords!),
        if (allRecords != null) RackTrend(record: record, all: allRecords!),
      ],
    );
  }
}

/// The last five days' graphs of this rack side by side (oldest on the left),
/// shown once five days have a saved graph. Each graph keeps its own vertical
/// scale -- the site auto-scales every day -- so it is the shape over the days,
/// not one cumulative medal count.
class SlumpStrip extends StatelessWidget {
  const SlumpStrip({super.key, required this.record, required this.all});
  final SlotRecord record;
  final List<SlotRecord> all;

  @override
  Widget build(BuildContext context) {
    final days = slumpDays(record, all);
    if (days.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${days.length}日間のスランプグラフ（左が古い日）',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 8),
              LayoutBuilder(
                builder: (context, constraints) {
                  // 5日分を横スクロールなしで一度に見渡せるよう、幅を等分する。
                  final tile = constraints.maxWidth / days.length;
                  return Row(
                    children: [
                      for (final r in days)
                        SizedBox(
                          width: tile,
                          child: Column(
                            children: [
                              SizedBox(
                                height: 96,
                                width: tile,
                                child: SlumpTile(record: r),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                r.day.substring(5).replaceAll('-', '/'),
                                style: const TextStyle(
                                  fontSize: 10,
                                  color: AppColors.ash,
                                ),
                              ),
                              Text(
                                () {
                                  final total = scoreRecord(r, all).total;
                                  return total == null
                                      ? '—'
                                      : '${total.toStringAsFixed(1)}点';
                                }(),
                                style: const TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                          ),
                        ),
                    ],
                  );
                },
              ),
              const SizedBox(height: 6),
              const Text(
                '縦軸は日ごとに自動調整される相対形状です（日をまたいだ差枚の合計ではありません）。',
                style: TextStyle(color: AppColors.ash, fontSize: 12),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 店舗のプルダウン。[short] は狭い場所用の短い名前（長町南・幸町）。
Widget storeDropdown(
  String value,
  ValueChanged<String> onChanged, {
  bool short = false,
}) => DropdownButtonFormField<String>(
  initialValue: value,
  isExpanded: true,
  decoration: const InputDecoration(labelText: '店舗'),
  items: storeNames.entries
      .map(
        (e) => DropdownMenuItem(
          value: e.key,
          child: Text(
            short ? storeShortName(e.key) : e.value,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      )
      .toList(),
  onChanged: (v) {
    if (v != null) onChanged(v);
  },
);

class MetricCard extends StatelessWidget {
  const MetricCard({
    super.key,
    required this.label,
    required this.value,
    this.note,
  });
  final String label, value;

  /// 数字の下に小さく添える一言（例：最高点だった台番号）。
  final String? note;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(color: AppColors.ash, fontSize: 12),
          ),
          const SizedBox(height: 3),
          Text(
            value,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
          ),
          if (note != null)
            Text(
              note!,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: AppColors.ash, fontSize: 12),
            ),
        ],
      ),
    ),
  );
}

class Notice extends StatelessWidget {
  const Notice({super.key, required this.text, this.onClose});
  final String text;

  /// 渡すと右端に閉じるボタンを出す。
  final VoidCallback? onClose;
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 12),
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: AppColors.ice,
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: AppColors.hairline),
    ),
    child: Row(
      children: [
        const Icon(Icons.info_outline, color: AppColors.linkBlue),
        const SizedBox(width: 8),
        Expanded(
          child: Text(text, style: const TextStyle(color: AppColors.carbon)),
        ),
        if (onClose != null)
          IconButton(
            tooltip: '閉じる',
            visualDensity: VisualDensity.compact,
            onPressed: onClose,
            icon: const Icon(Icons.close, size: 18, color: AppColors.ash),
          ),
      ],
    ),
  );
}

class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.body,
  });
  final IconData icon;
  final String title, body;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        children: [
          Icon(icon, size: 42, color: AppColors.mist),
          const SizedBox(height: 10),
          Text(
            title,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 5),
          Text(body, textAlign: TextAlign.center),
        ],
      ),
    ),
  );
}

/// 下へ600pxより多くスクロールすると出る「一番上へ」ボタン。見た目と動きは
/// Android版の結果タブの右下のボタンと同じ。閲覧ページの長い画面で、
/// Scaffold の floatingActionButton に置く（右下。メッセージが出ている間は
/// その上へよける）。[controller] は同じ画面のリストに付けたもの。
class ScrollTopButton extends StatefulWidget {
  const ScrollTopButton({super.key, required this.controller});
  final ScrollController controller;

  /// ボタンを出し始める位置（Android版と同じ）。
  static const threshold = 600.0;

  @override
  State<ScrollTopButton> createState() => _ScrollTopButtonState();
}

class _ScrollTopButtonState extends State<ScrollTopButton> {
  var _visible = false;
  ScrollNotificationObserverState? _observer;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_update);
    _updateAfterLayout();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final observer = ScrollNotificationObserver.maybeOf(context);
    if (observer == _observer) return;
    _observer?.removeListener(_onScrollNotification);
    _observer = observer;
    _observer?.addListener(_onScrollNotification);
  }

  @override
  void didUpdateWidget(ScrollTopButton oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_update);
      widget.controller.addListener(_update);
    }
    _updateAfterLayout();
  }

  // 日付・絞り込みでリストが短くなると、レイアウト時の位置補正では
  // controllerのスクロール通知が来ない場合がある。新しい寸法で判定する。
  // 初回接続・controllerの差し替え時にも現在位置を取り込む。
  void _updateAfterLayout() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _update();
    });
  }

  @override
  void dispose() {
    _observer?.removeListener(_onScrollNotification);
    widget.controller.removeListener(_update);
    super.dispose();
  }

  // Scaffoldのobserverは、通常のスクロールだけでなく、一覧の折りたたみや
  // 画面サイズ変更によるScrollMetricsNotificationも届ける。子だけが更新され、
  // このボタンのdidUpdateWidgetが呼ばれない場合も、補正後の位置に合わせる。
  void _onScrollNotification(ScrollNotification notification) {
    if (mounted && notification.depth == 0) _update();
  }

  void _update() {
    // 日付を変えてリストを作り直す間は、新旧2つのリストがつながっている
    // ことがある。後からつながった新しい方の位置で決める。
    final positions = widget.controller.positions;
    final position = positions.isEmpty ? null : positions.last;
    final visible =
        position != null &&
        position.hasPixels &&
        position.pixels > ScrollTopButton.threshold;
    if (visible != _visible) setState(() => _visible = visible);
  }

  @override
  Widget build(BuildContext context) => !_visible
      ? const SizedBox.shrink()
      : Material(
          color: AppColors.carbon.withValues(alpha: .8),
          shape: const CircleBorder(),
          elevation: 2,
          child: IconButton(
            tooltip: '一番上へ',
            color: Colors.white,
            iconSize: 28,
            onPressed: () => widget.controller.animateTo(
              0,
              duration: const Duration(milliseconds: 350),
              curve: Curves.easeOutCubic,
            ),
            icon: const Icon(Icons.keyboard_arrow_up),
          ),
        );
}
