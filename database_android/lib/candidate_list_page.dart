import 'package:flutter/material.dart';

import 'data_checks.dart';
import 'list_views.dart';
import 'machine_sections.dart';
import 'models.dart';
import 'theme.dart';

/// 狙い台一覧（台番号順）の1行の種類。
enum CandidateKind { focus, longTrend, normal, variety }

typedef CandidateListRow = ({
  CandidateKind kind,
  ProvisionalCandidate candidate,
});

/// 「狙い台一覧」に出す台（2026-11-17 利用者「かなりみやすい」一覧がほしい、iPhone閲覧ページ・
/// P’s CUBEとメルヘンの両方）。選び方は今までの翌日候補と同じで、新しい計算はしない。
/// 従来の★注目・☆長期傾向・バラエティの参考候補（[dayCandidates]）と、幸町のジャグラー・
/// ハナハナのおすすめ（[normalDayCandidates]）を1つに集め、台番号の順に並べ替えるだけ。
List<CandidateListRow> candidateListRows(
  String store,
  String day,
  List<SlotRecord> records,
) {
  final dayRows = [
    for (final r in records)
      if (r.store == store && r.day == day) r,
  ];
  final rows = <CandidateListRow>[];
  for (final c in dayCandidates(dayRows, records, excludeNormal: true).candidates) {
    rows.add((
      kind: c.variety
          ? CandidateKind.variety
          : candidateIsFocus(c, records)
          ? CandidateKind.focus
          : CandidateKind.longTrend,
      candidate: c,
    ));
  }
  if (hasNormalRecommendations(store)) {
    for (final c in normalDayCandidates(dayRows, records).candidates) {
      rows.add((kind: CandidateKind.normal, candidate: c));
    }
  }
  rows.sort((a, b) {
    final byRack = a.candidate.record.rack.compareTo(b.candidate.record.rack);
    return byRack != 0
        ? byRack
        : a.candidate.record.machine.compareTo(b.candidate.record.machine);
  });
  return rows;
}

String _kindMark(CandidateKind kind) => switch (kind) {
  CandidateKind.focus => '★注目',
  CandidateKind.longTrend => '☆長期',
  CandidateKind.normal => 'おすすめ',
  CandidateKind.variety => 'バラエティ',
};

String _kindFilterLabel(CandidateKind kind) => switch (kind) {
  CandidateKind.focus => '★注目',
  CandidateKind.longTrend => '☆長期傾向',
  CandidateKind.normal => 'ジャグラー・ハナハナ',
  CandidateKind.variety => 'バラエティ',
};

String _withComma(int value) => value.toString().replaceAllMapped(
  RegExp(r'(\d)(?=(\d{3})+$)'),
  (m) => '${m[1]},',
);

/// 一行の理由。通常機種は「平均より」と過去の日数、バラエティは前日の回転数と終わり方。
String candidateReasonLine(CandidateListRow row) {
  final c = row.candidate;
  final delta = c.index - 50;
  final sign = delta >= 0 ? '+' : '-';
  if (row.kind == CandidateKind.variety) {
    final state = varietyState(c.record);
    final hit = c.confidence == '比較なし'
        ? '当たりは比べる記録が足りない'
        : '当たり 普段より $sign${delta.abs().toStringAsFixed(0)}（比べた記録${c.days}件）';
    return '前日 ${_withComma(c.record.games)}G・${state.label}・$hit';
  }
  return '平均より $sign${delta.abs().toStringAsFixed(0)}'
      '・過去${c.days}日分・データ量 ${c.confidence}';
}

/// 店の1日分の狙い台を、台番号の順に1画面で見る（歩きながら見るための一覧）。
class CandidateListPage extends StatefulWidget {
  const CandidateListPage({
    super.key,
    required this.store,
    required this.day,
    required this.records,
    required this.onPick,
  });
  final String store, day;
  final List<SlotRecord> records;
  final void Function(SlotRecord record) onPick;

  @override
  State<CandidateListPage> createState() => _CandidateListPageState();
}

class _CandidateListPageState extends State<CandidateListPage> {
  CandidateKind? _only;
  late final List<CandidateListRow> _rows = candidateListRows(
    widget.store,
    widget.day,
    widget.records,
  );

  @override
  Widget build(BuildContext context) {
    final next = nextDayLabel(widget.day);
    final kinds = [
      for (final k in CandidateKind.values)
        if (_rows.any((r) => r.kind == k)) k,
    ];
    final shown = [
      for (final r in _rows)
        if (_only == null || r.kind == _only) r,
    ];
    const note = TextStyle(color: AppColors.ash, fontSize: 12, height: 1.45);
    return Scaffold(
      appBar: AppBar(title: const Text('狙い台一覧（台番号順）')),
      body: SafeArea(
        child: ListView(
          key: const ValueKey('candidate-list'),
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
          children: [
            Text(
              '${storeShortName(widget.store)}　${next.isEmpty ? '' : '$next 向け　'}${shown.length}台',
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 4),
            Text(
              '${shortDayLabel(widget.day)}（選択日）までの記録から選んだ、今までの翌日候補を台番号の順に並べ直したものです。'
              '選び方は変えていません。',
              style: note,
            ),
            const SizedBox(height: 4),
            const Text(nextDayValidationNote, style: note),
            if (kinds.length > 1) ...[
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  ChoiceChip(
                    key: const ValueKey('candidate-filter-all'),
                    label: Text('すべて（${_rows.length}）'),
                    selected: _only == null,
                    onSelected: (_) => setState(() => _only = null),
                  ),
                  for (final k in kinds)
                    ChoiceChip(
                      key: ValueKey('candidate-filter-${k.name}'),
                      label: Text(
                        '${_kindFilterLabel(k)}（${_rows.where((r) => r.kind == k).length}）',
                      ),
                      selected: _only == k,
                      onSelected: (_) => setState(() => _only = k),
                    ),
                ],
              ),
            ],
            const SizedBox(height: 8),
            if (_rows.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 16),
                child: Text(
                  'この日は判定できる候補がありません。候補がないことは、不調を意味しません。',
                  style: note,
                ),
              )
            else
              for (final row in shown) _row(row),
          ],
        ),
      ),
    );
  }

  Widget _row(CandidateListRow row) {
    final c = row.candidate;
    return InkWell(
      key: ValueKey('candidate-row-${c.record.rack}'),
      onTap: () => widget.onPick(c.record),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 9),
        child: Row(
          children: [
            SizedBox(
              width: 62,
              child: Text(
                '${c.record.rack}',
                textAlign: TextAlign.right,
                style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 8,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: AppColors.pebble,
                          borderRadius: BorderRadius.circular(980),
                        ),
                        child: Text(
                          _kindMark(row.kind),
                          style: const TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          displayMachineName(c.record.machine),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 3),
                  Text(
                    candidateReasonLine(row),
                    style: const TextStyle(fontSize: 12, color: AppColors.ash),
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, color: AppColors.mist),
          ],
        ),
      ),
    );
  }
}
