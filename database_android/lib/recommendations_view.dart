import 'package:flutter/material.dart';

import 'list_views.dart' show displayMachineName;
import 'models.dart';
import 'recommendations.dart';

/// 機種構成はPCだけで編集し、4画面では同じ台別週表の顔文字を編集する。
class RecommendationsView extends StatefulWidget {
  const RecommendationsView({
    super.key,
    required this.records,
    required this.plans,
    required this.results,
    required this.onResult,
    required this.onOpen,
  });
  final List<SlotRecord> records;
  final List<dynamic> plans;
  final List<dynamic> results;
  final Future<void> Function(Map<String, dynamic>) onResult;
  final ValueChanged<SlotRecord> onOpen;
  @override
  State<RecommendationsView> createState() => _RecommendationsViewState();
}

class _RecommendationsViewState extends State<RecommendationsView> {
  String? _week;
  bool _saving = false;
  String _notice = '';

  Future<void> _save(Map<String, dynamic> fields, String value) async {
    setState(() => _saving = true);
    try {
      var now = DateTime.now().toUtc();
      final old = recommendationResultIndex(
        widget.results,
      )[recommendationResultKey(fields)];
      if (old != null && !now.isAfter(DateTime.parse(old['updated_at']))) {
        now = DateTime.parse(old['updated_at'])
            .add(const Duration(microseconds: 1));
      }
      await widget.onResult(
        recommendationResult({
          ...fields,
          'value': value == 'auto' ? null : value,
          'updated_at': now.toIso8601String(),
          'device': 'android',
        }),
      );
      if (mounted) setState(() => _notice = '顔文字を保存しました。');
    } on Object catch (e) {
      if (mounted) setState(() => _notice = '保存できませんでした：$e');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final plans = recommendationPlans(widget.plans);
    if (!plans.any((p) => p['week'] == _week)) {
      _week = plans.first['week'] as String;
    }
    final current = plans.firstWhere((p) => p['week'] == _week),
        days = recommendationDays(_week!);
    final index = recommendationResultIndex(widget.results),
        theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        DropdownButtonFormField<String>(
          key: ValueKey('recommendation-week:$_week'),
          initialValue: _week,
          isExpanded: true,
          decoration: const InputDecoration(labelText: '対象週'),
          items: [
            for (final p in plans)
              DropdownMenuItem(
                value: p['week'] as String,
                child: Text(
                  '${p['week']}〜${recommendationDays(p['week']).last}',
                ),
              ),
          ],
          onChanged: _saving
              ? null
              : (w) => setState(() {
                  _week = w;
                  _notice = '';
                }),
        ),
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 8),
          child: Text('機種構成・週の追加はPCで行います。顔文字はここで選んで保存できます。'),
        ),
        if (_notice.isNotEmpty) Text(_notice),
        if (_saving) const LinearProgressIndicator(),
        for (var slot = 0; slot < 4; slot++)
          Container(
            key: ValueKey('recommendation-card:$slot'),
            margin: const EdgeInsets.only(top: 14),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: theme.colorScheme.surface,
              border: Border.all(color: const Color(0xffdce4ef)),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  displayMachineName(current['machines'][slot] as String),
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 15,
                  ),
                ),
                const SizedBox(height: 10),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final width = constraints.maxWidth < 340
                            ? 340.0
                            : constraints.maxWidth,
                        column = (width - 44) / 7;
                    final machine = current['machines'][slot] as String,
                        rows = recommendationRows(
                          widget.records,
                          _week!,
                          machine,
                        );
                    return SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: SizedBox(
                        width: width,
                        child: Column(
                          children: [
                            Row(
                              children: [
                                const SizedBox(
                                  width: 44,
                                  child: Text(
                                    '台番号',
                                    style: TextStyle(fontSize: 11),
                                  ),
                                ),
                                for (var i = 0; i < 7; i++)
                                  SizedBox(
                                    width: column,
                                    child: Text(
                                      '${'月火水木金土日'[i]}\n${days[i].substring(5)}',
                                      textAlign: TextAlign.center,
                                      style: const TextStyle(fontSize: 10),
                                    ),
                                  ),
                              ],
                            ),
                            for (final row in rows)
                              Row(
                                children: [
                                  SizedBox(
                                    width: 44,
                                    child: Text(
                                      '${row.rack}番',
                                      style: const TextStyle(fontSize: 11),
                                    ),
                                  ),
                                  for (var i = 0; i < 7; i++)
                                    SizedBox(
                                      width: column,
                                      child: Builder(
                                        builder: (context) {
                                          final record = row.cells[i],
                                              net =
                                                  record == null ||
                                                      hasImplausibleNumbers(
                                                        record,
                                                      )
                                                  ? null
                                                  : record.netValue;
                                          final fields = <String, dynamic>{
                                            'store': 'nagamachiminami',
                                            'week': _week,
                                            'machine': machine,
                                            'rack': row.rack,
                                            'day': days[i],
                                          };
                                          final saved =
                                                  index[recommendationResultKey(
                                                    fields,
                                                  )],
                                              choice =
                                                  saved == null ||
                                                      saved['value'] == null
                                                  ? 'auto'
                                                  : saved['value'] as String;
                                          final face = choice == 'auto'
                                              ? recommendationFace(net)
                                              : choice;
                                          return Column(
                                            children: [
                                              Semantics(
                                                label:
                                                    '${days[i]} $machine ${row.rack}番の顔文字',
                                                child: DropdownButton<String>(
                                                  key: ValueKey(
                                                    'recommendation-face:$slot:${row.rack}:$i',
                                                  ),
                                                  value: choice,
                                                  isExpanded: true,
                                                  iconSize: 10,
                                                  alignment: Alignment.center,
                                                  selectedItemBuilder: (_) => [
                                                    for (final _ in [
                                                      'auto',
                                                      '',
                                                      ...recommendationFaces,
                                                    ])
                                                      Center(
                                                        child: Text(
                                                          face.isEmpty
                                                              ? '—'
                                                              : face,
                                                          style:
                                                              const TextStyle(
                                                                fontSize: 18,
                                                              ),
                                                        ),
                                                      ),
                                                  ],
                                                  items: [
                                                    DropdownMenuItem(
                                                      value: 'auto',
                                                      child: Text(
                                                        '自動 ${recommendationFace(net)}',
                                                      ),
                                                    ),
                                                    const DropdownMenuItem(
                                                      value: '',
                                                      child: Text('空欄'),
                                                    ),
                                                    for (final f
                                                        in recommendationFaces)
                                                      DropdownMenuItem(
                                                        value: f,
                                                        child: Text(f),
                                                      ),
                                                  ],
                                                  onChanged: _saving
                                                      ? null
                                                      : (v) =>
                                                            _save(fields, v!),
                                                ),
                                              ),
                                              TextButton(
                                                style: TextButton.styleFrom(
                                                  padding: EdgeInsets.zero,
                                                  minimumSize: const Size(
                                                    0,
                                                    30,
                                                  ),
                                                ),
                                                onPressed: record == null
                                                    ? null
                                                    : () =>
                                                          widget.onOpen(record),
                                                child: FittedBox(
                                                  fit: BoxFit.scaleDown,
                                                  child: Text(
                                                    net == null
                                                        ? '—'
                                                        : '${record!.joNet == null ? '約' : ''}${signedMedals(net)}',
                                                    style: TextStyle(
                                                      fontSize: 10,
                                                      color: net == null
                                                          ? null
                                                          : net > 0
                                                          ? const Color(
                                                              0xff15803d,
                                                            )
                                                          : net < 0
                                                          ? const Color(
                                                              0xffb91c1c,
                                                            )
                                                          : null,
                                                    ),
                                                  ),
                                                ),
                                              ),
                                            ],
                                          );
                                        },
                                      ),
                                    ),
                                ],
                              ),
                            if (rows.isEmpty)
                              const Padding(
                                padding: EdgeInsets.symmetric(vertical: 14),
                                child: Text('この週の保存データはまだありません。'),
                              ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
              ],
            ),
          ),
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 12),
          child: Text(
            '「自動」は台ごとの差枚で判定：3,000枚以上😍 · 1,000枚以上😀 · 0枚以上😌 · マイナス🥶 · 不明—。約は推定差枚です。顔文字だけ手動で変更でき、差枚は変更しません。',
          ),
        ),
      ],
    );
  }
}
