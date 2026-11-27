import 'package:flutter/material.dart';

import 'viewer_pages.dart';

import 'data_checks.dart';
import 'list_views.dart';
import 'machine_sections.dart'
    show MachineDataTable, machineSorts, sortMachineEntries;
import 'viewer_bridge.dart' show loadViewerSetting, saveViewerSetting;
import 'models.dart';
import 'scoring.dart';
import 'shared_widgets.dart';
import 'theme.dart';
import 'viewer_data.dart' show SavedCandidate;

/// 答え合わせで「当たり」とする合計点。
const answerCheckThreshold = 60.0;

/// 答え合わせ用の「記録上のプラス判定」（稼働バイアス・推定誤差の影響を避ける補助物差し）。
/// 確定／取得差枚があればその符号、無ければグラフ終点がゼロ線から1pxを超えて上か下かで決め、
/// ゼロ線付近（±1px以内）・0G・異常値・アナスロ補完は判定不能（null）とする。
/// 大当たり0回でグラフを省略した台（v12仕様）は非プラス（false）。
bool? answerCheckPlus(SlotRecord record) {
  if (record.games <= 0 ||
      hasImplausibleNumbers(record) ||
      isExcludedSupplement(record)) {
    return null;
  }
  final net = record.isPscube ? record.netMedals : record.joNet;
  if (net != null) return net > 0;
  final g = record.graph;
  if (g != null) {
    final end = g.baselineY - g.endY;
    if (!end.isFinite || end.abs() <= 1) return null;
    return end > 1;
  }
  if (record.graphNotNeeded) return false;
  return null;
}

/// 前の日の翌日候補に挙げた台が、その日に [answerCheckThreshold] 点以上だったもの。
typedef AnswerCheckHit = ({
  ProvisionalCandidate candidate,
  SlotRecord result,
  ScoreResult score,
});

/// 1日ぶんの答え合わせ。[day] の記録を、[predictedOn]（前の日）の翌日候補と
/// 照らし合わせる。
typedef AnswerCheckDay = ({
  String day,
  String predictedOn,

  /// 前の日に挙げた候補の数。
  int candidates,

  /// そのうち、この日に同じ台・同じ機種の合計点が出た数（取り込んでいない台、
  /// 機種が入れ替わった台、500G以下などで採点しなかった台は数えない）。
  int scored,

  /// 合計点の高い順。
  List<AnswerCheckHit> hits,

  /// 前の日の候補のうち、この日に同じ台・同じ機種の記録がある台の、この日の記録と点数（台番号順。
  /// 採点しなかった台も含む）。日ごとのカードに機種一覧と同じ表で出す（2026-11-15 利用者「採点結果しか
  /// 出てなくてタップしないとデータがわかりづらいので、機種一覧から開いたような…データ一覧を見せて欲しい」、
  /// 並べる台は「前日の候補の全台」）。
  List<(SlotRecord, ScoreResult)> rows,

  /// 当時保存した候補で照らしたか（false なら、今の計算式で計算し直した候補）。
  bool saved,

  /// くらべる目安の母集団（同じ日に候補選考の対象になった台）の台数。候補0台の日は0。
  int baseCandidates,

  /// くらべる目安：同じ選考元の台のうち、点数が出た数と [answerCheckThreshold] 点以上の数。
  int baseScored,
  int baseHits,

  /// 記録上のプラス判定（[answerCheckPlus]）：候補と目安それぞれで判定できた台数とプラス台数。
  int plusJudged,
  int plusHits,
  int basePlusJudged,
  int basePlusHits,
});

String _dayBefore(String day) =>
    DateTime.parse(day)
        .subtract(const Duration(days: 1))
        .toIso8601String()
        .substring(0, 10);

/// [store] で、前の日（暦の前日）と両方に記録がある日。新しい順。
List<String> answerCheckDays(List<SlotRecord> all, String store) {
  final days = {
    for (final r in all)
      if (r.store == store) r.day,
  };
  return [
    for (final day in days)
      if (isValidRecordDay(day) && days.contains(_dayBefore(day))) day,
  ]..sort((a, b) => b.compareTo(a));
}

/// [store] の [day] の答え合わせ。前の日の記録が無ければ null。
///
/// [saved]（{"店|日": 当時の候補}、PCが閲覧用ファイルに載せる）に前の日の分があれば、それを使う
/// （2026-11-04。10/23の再検討で、当時保存した候補と後から計算し直した候補は一致しないことが
/// 多かった）。無ければ、今の計算式で前の日までの記録から計算し直す（[dayCandidates]。前の日の分を
/// 翌日以降に取り込んだ記録や、あとから直した記録も使うので、当時画面に出ていた候補と違うことがある）。
/// 点数は結果画面と同じ [scoreRecord]。
AnswerCheckDay? answerCheckFor(
  List<SlotRecord> all,
  String store,
  String day, {
  Map<String, List<SavedCandidate>> saved = const {},
}) {
  final before = _dayBefore(day);
  final previousRows = <SlotRecord>[];
  final results = <(String, int), SlotRecord>{};
  for (final r in all) {
    if (r.store != store) continue;
    if (r.day == before) previousRows.add(r);
    if (r.day == day) results[(r.machine, r.rack)] = r;
  }
  if (previousRows.isEmpty) return null;
  final kept = saved['$store|$before'];
  final List<ProvisionalCandidate> candidates;
  if (kept == null) {
    candidates = dayCandidates(previousRows, all).candidates;
  } else {
    final byRack = {for (final r in previousRows) r.rack: r};
    final seenRacks = <int>{};
    candidates = [
      for (final c in kept)
        if (seenRacks.add(c.rack))
          if (byRack[c.rack] case final record?)
            (
              record: record,
              index: c.index,
              days: 0,
              confidence: '',
              variety: c.variety,
            ),
    ];
  }
  // くらべる目安：同じ日に実際に候補の選考母集団に入った台（シンプソンのパラドックスを防ぐため、
  // 履歴不足の新台や3,000G未満の放置バラエティ台、候補が0台の日の全台を混ぜない）。
  final baselineKeys = <(String, int)>{};
  if (candidates.isNotEmpty) {
    for (final c in candidates) {
      baselineKeys.add((c.record.machine, c.record.rack));
    }
    final normalMachines = {
      for (final c in candidates)
        if (!c.variety) c.record.machine,
    };
    for (final machine in normalMachines) {
      final rows = [
        for (final r in previousRows)
          if (r.machine == machine) r,
      ];
      final history = machineHistory(all, store, machine);
      final eligible = [
        for (final r in rows)
          if (nextDayEvidence(r, history).rawIndex != null) r,
      ];
      final candidateRacks = {
        for (final c in candidates)
          if (!c.variety && c.record.machine == machine) c.record.rack,
      };
      final eligibleRacks = {for (final r in eligible) r.rack};
      final useEligible =
          kept == null ||
          (eligible.length >= 4 && eligibleRacks.containsAll(candidateRacks));
      final pool = useEligible
          ? eligible
          : [
              for (final r in rows)
                if (!hasImplausibleNumbers(r) && !isExcludedSupplement(r)) r,
            ];
      for (final r in pool) {
        baselineKeys.add((r.machine, r.rack));
      }
    }
    if (candidates.any((c) => c.variety)) {
      final previousVariety = varietyMachines(previousRows);
      final order = varietyOrder(store);
      for (final r in previousRows) {
        if (!previousVariety.contains(r.machine) || hasImplausibleNumbers(r)) {
          continue;
        }
        if (order.contains(varietyState(r))) {
          baselineKeys.add((r.machine, r.rack));
        }
      }
    }
  }
  var baseScored = 0;
  var baseHits = 0;
  var basePlusJudged = 0;
  var basePlusHits = 0;
  for (final key in baselineKeys) {
    final result = results[key];
    if (result == null) continue;
    final plus = answerCheckPlus(result);
    if (plus != null) {
      basePlusJudged++;
      if (plus) basePlusHits++;
    }
    final total = scoreRecord(result, all).total;
    if (total == null) continue;
    baseScored++;
    if (total >= answerCheckThreshold) baseHits++;
  }
  var scored = 0;
  var plusJudged = 0;
  var plusHits = 0;
  final hits = <AnswerCheckHit>[];
  final rows = <(SlotRecord, ScoreResult)>[];
  for (final c in candidates) {
    final result = results[(c.record.machine, c.record.rack)];
    if (result == null) continue;
    final plus = answerCheckPlus(result);
    if (plus != null) {
      plusJudged++;
      if (plus) plusHits++;
    }
    final score = scoreRecord(result, all);
    rows.add((result, score));
    final total = score.total;
    if (total == null) continue;
    scored++;
    if (total >= answerCheckThreshold) {
      hits.add((candidate: c, result: result, score: score));
    }
  }
  hits.sort((a, b) {
    final byScore = b.score.total!.compareTo(a.score.total!);
    return byScore != 0 ? byScore : a.result.rack.compareTo(b.result.rack);
  });
  rows.sort((a, b) => a.$1.rack.compareTo(b.$1.rack));
  return (
    day: day,
    predictedOn: before,
    candidates: candidates.length,
    scored: scored,
    hits: hits,
    rows: rows,
    saved: kept != null,
    baseCandidates: baselineKeys.length,
    baseScored: baseScored,
    baseHits: baseHits,
    plusJudged: plusJudged,
    plusHits: plusHits,
    basePlusJudged: basePlusJudged,
    basePlusHits: basePlusHits,
  );
}

/// 答え合わせのページ：前の日の翌日候補に挙げた台のうち、その日に
/// [answerCheckThreshold] 点以上だった台の一覧。
class AnswerCheckPage extends StatefulWidget {
  const AnswerCheckPage({
    super.key,
    required this.records,
    required this.store,
    required this.onOpen,
    this.eventFor,
    this.saved = const {},
  });

  final List<SlotRecord> records;

  /// 当時の翌日候補（[answerCheckFor] の saved）。
  final Map<String, List<SavedCandidate>> saved;
  final String store;
  final void Function(SlotRecord record, ScoreResult score) onOpen;

  /// [store] の [day] のイベント名（日付一覧に添える。無ければ null）。
  final String? Function(String store, String day)? eventFor;

  @override
  State<AnswerCheckPage> createState() => _AnswerCheckPageState();
}

/// 答え合わせの表の並べ方を覚える名前（機種一覧の 'machine-sort' とは別に覚える）。
const answerSortSetting = 'answer-check-sort';

/// 答え合わせの表の並べ方の呼び名。機種一覧と同じ（候補は機種が混ざるので機種順も出す）。
/// 差枚の呼び名は記録に合わせる（メルヘンは推定差枚、P’s CUBEは差枚）。
Map<String, String> answerSortLabels(List<(SlotRecord, ScoreResult)> rows) {
  final netLabel = rows.firstOrNull?.$1.netLabel ?? '差枚';
  return {
    for (final e in machineSorts.entries)
      e.key: e.value.replaceFirst('差枚', netLabel),
  };
}

class _AnswerCheckPageState extends State<AnswerCheckPage> {
  late String _store = widget.store;

  /// 表の並べ方（2026-11-15 利用者「並べ方もプルダウンで選べるように」）。全部の日のカードで共通。
  /// 選んだ並べ方は端末に覚える（機種一覧と同じ。閲覧ページはブラウザ）。
  String get _sort {
    final saved = loadViewerSetting(answerSortSetting);
    return saved != null && machineSorts.containsKey(saved) ? saved : 'rack';
  }

  var _days = <String>[];
  final _results = <AnswerCheckDay>[];
  var _run = 0;
  String? _selectedDay;

  /// 日ごとのカードのリスト（右下の「一番上へ」ボタンで戻す）。
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

  /// 1日ずつ計算して、できた日から出す（Webでは計算が画面と同じ処理で
  /// 動くので、全部終わるまで固まらないように、1日ごとに画面へ返す）。
  Future<void> _calculate() async {
    final run = ++_run;
    final all = widget.records;
    setState(() {
      _days = answerCheckDays(all, _store);
      _selectedDay = null;
      _results.clear();
    });
    for (final day in _days) {
      await Future<void>.delayed(Duration.zero);
      if (!mounted || run != _run) return;
      final result = answerCheckFor(all, _store, day, saved: widget.saved);
      if (result != null) setState(() => _results.add(result));
    }
  }

  @override
  Widget build(BuildContext context) {
    final stores = {for (final r in widget.records) r.store};
    final done = _results.length;
    final loading = done < _days.length;
    final candidates = _results.fold(0, (n, d) => n + d.candidates);
    final scored = _results.fold(0, (n, d) => n + d.scored);
    final hits = _results.fold(0, (n, d) => n + d.hits.length);
    final baseCandidates = _results.fold(0, (n, d) => n + d.baseCandidates);
    final baseScored = _results.fold(0, (n, d) => n + d.baseScored);
    final baseHits = _results.fold(0, (n, d) => n + d.baseHits);
    final plusJudged = _results.fold(0, (n, d) => n + d.plusJudged);
    final plusHits = _results.fold(0, (n, d) => n + d.plusHits);
    final basePlusJudged = _results.fold(0, (n, d) => n + d.basePlusJudged);
    final basePlusHits = _results.fold(0, (n, d) => n + d.basePlusHits);
    final savedDays = _results.where((d) => d.saved).length;
    return Scaffold(
      appBar: AppBar(
        title: const Text('答え合わせ'),
        bottom: _days.isEmpty
            ? null
            : ViewerDateBar(
                days: _days,
                day: _selectedDay,
                allowAll: true,
                event: _selectedDay == null
                    ? null
                    : widget.eventFor?.call(_store, _selectedDay!),
                eventFor: widget.eventFor == null
                    ? null
                    : (day) => widget.eventFor!(_store, day),
                onChanged: (day) => setState(() => _selectedDay = day),
              ),
      ),
      floatingActionButton: ScrollTopButton(controller: _scroll),
      body: SafeArea(
        child: ListView(
          controller: _scroll,
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 88),
          children: [
            if (stores.length > 1) ...[
              storeDropdown(
                _store,
                (v) {
                  if (v == _store) return;
                  _store = v;
                  _calculate();
                },
                short: true,
                stores: viewerStoreNames(widget.records),
              ),
              const SizedBox(height: 12),
            ],
            const Text(
              '前の日の「参考候補（翌日向け）」（★注目・☆長期傾向・バラエティ）が、その日に合計点'
              '${answerCheckThreshold ~/ 1}点以上だったか・記録上プラスだったかを、同じ選考元の台と照らし合わせます。'
              '点数は結果画面と同じです。候補は、PCが当時（その翌日の午前8時まで）に保存したものを使います。'
              '保存の無い日は、今の計算式で記録から計算し直した候補を使い、日ごとのカードにそう書きます。'
              '計算し直した候補は、あとから取り込んだ記録も使うので、当時画面に出ていた候補と違うことがあります。',
              style: TextStyle(
                color: AppColors.ash,
                fontSize: 13,
                height: 1.45,
              ),
            ),
            const SizedBox(height: 12),
            if (loading) ...[
              LinearProgressIndicator(
                value: _days.isEmpty ? null : done / _days.length,
              ),
              const SizedBox(height: 12),
            ],
            if (_days.isEmpty)
              const EmptyState(
                icon: Icons.fact_check_outlined,
                title: '答え合わせできる日がありません',
                body: '前の日とその日の両方の記録がそろうと、答え合わせできます。',
              )
            else ...[
              _totals(
                candidates,
                scored,
                hits,
                loading,
                baseCandidates: baseCandidates,
                baseScored: baseScored,
                baseHits: baseHits,
                plusJudged: plusJudged,
                plusHits: plusHits,
                basePlusJudged: basePlusJudged,
                basePlusHits: basePlusHits,
                savedDays: savedDays,
              ),
              const SizedBox(height: 14),
              // 日ごとの表の並べ方（機種一覧と同じプルダウン）。
              DropdownButtonFormField<String>(
                key: const ValueKey('answer-check-sort'),
                initialValue: _sort,
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: '並べ方',
                  isDense: true,
                ),
                items: [
                  for (final e in answerSortLabels(
                    _results.firstOrNull?.rows ?? const [],
                  ).entries)
                    DropdownMenuItem(value: e.key, child: Text(e.value)),
                ],
                onChanged: (value) {
                  if (value == null) return;
                  setState(() => saveViewerSetting(answerSortSetting, value));
                },
              ),
              const SizedBox(height: 12),
              if (_selectedDay != null &&
                  !_results.any((d) => d.day == _selectedDay))
                const Padding(
                  padding: EdgeInsets.all(16),
                  child: Text('選択した日を計算しています…'),
                ),
              for (final day in _results.where(
                (d) => _selectedDay == null || d.day == _selectedDay,
              )) ...[
                _DayCard(result: day, onOpen: widget.onOpen, sort: _sort),
                const SizedBox(height: 12),
              ],
            ],
          ],
        ),
      ),
    );
  }

  Widget _totals(
    int candidates,
    int scored,
    int hits,
    bool loading, {
    required int baseCandidates,
    required int baseScored,
    required int baseHits,
    required int plusJudged,
    required int plusHits,
    required int basePlusJudged,
    required int basePlusHits,
    required int savedDays,
  }) {
    String percent(int part, int whole) =>
        whole == 0 ? '—' : '${(part * 100 / whole).toStringAsFixed(0)}%';
    final rate = percent(hits, scored);
    final recomputed = _results.length - savedDays;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${_results.length}日分の合計${loading ? '（計算中）' : ''}',
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 6),
            Text(
              '参考候補$candidates台のうち、翌日に点数が出た台$scored台（${percent(scored, candidates)}）。'
              'そのうち${answerCheckThreshold ~/ 1}点以上は$hits台（$rate）。',
              style: const TextStyle(fontSize: 14, height: 1.45),
            ),
            const SizedBox(height: 4),
            Text(
              'くらべる目安（同じ選考元の台）：$baseCandidates台のうち点数が出た$baseScored台'
              '（${percent(baseScored, baseCandidates)}）、'
              '${answerCheckThreshold ~/ 1}点以上は$baseHits台（${percent(baseHits, baseScored)}）。',
              style: const TextStyle(fontSize: 14, height: 1.45),
            ),
            if (plusJudged > 0 || basePlusJudged > 0) ...[
              const SizedBox(height: 4),
              Text(
                '記録上のプラス率：参考候補$plusHits/$plusJudged台（${percent(plusHits, plusJudged)}、'
                '判定可能${percent(plusJudged, candidates)}）／'
                '目安$basePlusHits/$basePlusJudged台（${percent(basePlusHits, basePlusJudged)}、'
                '判定可能${percent(basePlusJudged, baseCandidates)}）。',
                style: const TextStyle(fontSize: 14, height: 1.45),
              ),
            ],
            const SizedBox(height: 4),
            Text(
              '当時の候補で照らした日$savedDays日・計算し直した候補の日$recomputed日。'
              '候補の割合が目安より高くても、設定や勝ちを約束するものではありません。'
              '日数が少ないうちは、たまたまの差が大きく出ます。'
              '取り込んでいない台・機種が入れ替わった台・採点しなかった台（500G以下など）は、'
              '点数が出た台に数えていません（点数が出た割合に差がある日は稼働の偏りにも注意）。',
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
}

class _DayCard extends StatelessWidget {
  const _DayCard({
    required this.result,
    required this.onOpen,
    this.sort = 'rack',
  });
  final AnswerCheckDay result;

  /// 表の並べ方（[machineSorts] の鍵）。
  final String sort;
  final void Function(SlotRecord record, ScoreResult score) onOpen;

  @override
  Widget build(BuildContext context) {
    final hits = result.hits;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              dayWithWeekday(result.day),
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 2),
            Text(
              '${dayWithWeekday(result.predictedOn)}の参考候補${result.candidates}台'
              '（${result.saved ? '当時の候補' : '計算し直した候補'}）'
              '・点数が出た${result.scored}台・'
              '${answerCheckThreshold ~/ 1}点以上${hits.length}台'
              '${result.plusJudged > 0 ? '・プラス${result.plusHits}/${result.plusJudged}台' : ''}',
              style: const TextStyle(color: AppColors.ash, fontSize: 13),
            ),
            const SizedBox(height: 6),
            if (hits.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Text(
                  result.candidates == 0
                      ? '前の日は、参考候補を出せる機種がありませんでした。'
                      : '${answerCheckThreshold ~/ 1}点以上の台はありませんでした。',
                  style: const TextStyle(color: AppColors.ash),
                ),
              ),
            for (final hit in hits)
              InkWell(
                onTap: () => onOpen(hit.result, hit.score),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Row(
                    children: [
                      Text(
                        '${hit.result.rack}番台',
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              hit.candidate.variety
                                  ? '${displayMachineName(hit.result.machine)}（$varietyGroupName）'
                                  : displayMachineName(hit.result.machine),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 13),
                            ),
                            Text(
                              hit.candidate.variety
                                  ? '参考候補のとき：前日 ${hit.candidate.record.games}G・'
                                        '${varietyState(hit.candidate.record).label}'
                                  : '参考候補のとき：平均より'
                                        '${hit.candidate.index >= 50 ? '+' : '-'}'
                                        '${(hit.candidate.index - 50).abs().toStringAsFixed(0)}',
                              style: const TextStyle(
                                fontSize: 11,
                                color: AppColors.ash,
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 8),
                      ScorePill(
                        text: hit.score.total!.toStringAsFixed(1),
                        tier: scoreTier(hit.score.total),
                      ),
                      const Icon(Icons.chevron_right, color: AppColors.mist),
                    ],
                  ),
                ),
              ),
            // 候補の全台のこの日の数字を、機種一覧と同じ表で出す（2026-11-15 利用者「タップしないとデータが
            // わかりづらいので、機種一覧から開いたような…データ一覧を見せて欲しい」「前日の候補の全台」）。
            if (result.rows.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text(
                '候補の台のこの日のデータ（${answerSortLabels(result.rows)[sort] ?? '台番号順'}・${result.rows.length}台）',
                style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 6),
              MachineDataTable(
                entries: sortMachineEntries(result.rows, sort),
                onTap: onOpen,
                showMachine: true,
                markedRacks: {for (final hit in hits) hit.result.rack},
                markLegend: '合計${answerCheckThreshold ~/ 1}点以上',
              ),
            ],
            if (result.candidates > result.rows.length)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  'この日の記録が無い候補${result.candidates - result.rows.length}台は表にありません'
                  '（取り込んでいない台・機種が入れ替わった台）。',
                  style: const TextStyle(fontSize: 11, color: AppColors.ash),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
