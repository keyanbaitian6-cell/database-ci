import 'package:flutter/material.dart';

import 'viewer_pages.dart';

import 'data_checks.dart';
import 'list_views.dart';
import 'models.dart';
import 'scoring.dart';
import 'shared_widgets.dart';
import 'theme.dart';

/// 答え合わせで「当たり」とする合計点。
const answerCheckThreshold = 60.0;

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
});

String _dayBefore(String day) => DateTime.parse(
  day,
).subtract(const Duration(days: 1)).toIso8601String().substring(0, 10);

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
/// 翌日候補（[dayCandidates]）はその日までの記録しか使わないので、いま計算
/// し直しても、前の日の結果画面に出ていた候補と同じになる（記録をあとから
/// 直した場合を除く）。点数も結果画面と同じ [scoreRecord]。
AnswerCheckDay? answerCheckFor(List<SlotRecord> all, String store, String day) {
  final before = _dayBefore(day);
  final previousRows = <SlotRecord>[];
  final results = <(String, int), SlotRecord>{};
  for (final r in all) {
    if (r.store != store) continue;
    if (r.day == before) previousRows.add(r);
    if (r.day == day) results[(r.machine, r.rack)] = r;
  }
  if (previousRows.isEmpty) return null;
  final candidates = dayCandidates(previousRows, all).candidates;
  var scored = 0;
  final hits = <AnswerCheckHit>[];
  for (final c in candidates) {
    final result = results[(c.record.machine, c.record.rack)];
    if (result == null) continue;
    final score = scoreRecord(result, all);
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
  return (
    day: day,
    predictedOn: before,
    candidates: candidates.length,
    scored: scored,
    hits: hits,
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
  });

  final List<SlotRecord> records;
  final String store;
  final void Function(SlotRecord record, ScoreResult score) onOpen;

  /// [store] の [day] のイベント名（日付一覧に添える。無ければ null）。
  final String? Function(String store, String day)? eventFor;

  @override
  State<AnswerCheckPage> createState() => _AnswerCheckPageState();
}

class _AnswerCheckPageState extends State<AnswerCheckPage> {
  late String _store = widget.store;
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
      final result = answerCheckFor(all, _store, day);
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
              '前の日の「参考候補（翌日向け）」の★注目・☆長期傾向・バラエティを合わせて答え合わせします。'
              '現在の方式で再計算した候補で、当時保存された予想の検証ではありません。候補のうち、その日に合計点'
              '${answerCheckThreshold ~/ 1}点以上だった台です。候補は、今の計算式で'
              '前の日までの記録から計算し直したものです。前の日の分を翌日以降に取り込んだ'
              '記録も使うので、当時画面に出ていた候補と違うことがあります。'
              '点数は結果画面と同じです。',
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
              _totals(candidates, scored, hits, loading),
              const SizedBox(height: 14),
              if (_selectedDay != null &&
                  !_results.any((d) => d.day == _selectedDay))
                const Padding(
                  padding: EdgeInsets.all(16),
                  child: Text('選択した日を計算しています…'),
                ),
              for (final day in _results.where(
                (d) => _selectedDay == null || d.day == _selectedDay,
              )) ...[
                _DayCard(result: day, onOpen: widget.onOpen),
                const SizedBox(height: 12),
              ],
            ],
          ],
        ),
      ),
    );
  }

  Widget _totals(int candidates, int scored, int hits, bool loading) {
    final rate = scored == 0
        ? '—'
        : '${(hits * 100 / scored).toStringAsFixed(0)}%';
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
              '参考候補$candidates台のうち、翌日に点数が出た台$scored台。'
              'そのうち${answerCheckThreshold ~/ 1}点以上は$hits台（$rate）。',
              style: const TextStyle(fontSize: 14, height: 1.45),
            ),
            const SizedBox(height: 4),
            const Text(
              '取り込んでいない台・機種が入れ替わった台・採点しなかった台（500G以下など）は、'
              '点数が出た台に数えていません。',
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
  const _DayCard({required this.result, required this.onOpen});
  final AnswerCheckDay result;
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
              '・点数が出た${result.scored}台・'
              '${answerCheckThreshold ~/ 1}点以上${hits.length}台',
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
                        text:
                            '${hit.score.provisional ? '暫定 ' : ''}${hit.score.total!.toStringAsFixed(1)}',
                        tier: scoreTier(hit.score.total),
                      ),
                      const Icon(Icons.chevron_right, color: AppColors.mist),
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
