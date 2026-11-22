import 'package:flutter/material.dart';

import 'list_views.dart' show dayWithWeekday, displayMachineName;
import 'models.dart';
import 'shared_widgets.dart';
import 'store_pattern.dart';
import 'theme.dart';
import 'viewer_data.dart';
import 'viewer_pages.dart';

/// 店の入れ方のふり返り（閲覧ページだけ。メルヘン版・P’s CUBE版。2026-11-17 利用者「２だけ作る。
/// iPhoneブラウザ版の2種類のみで」）。計算は `store_pattern.dart`。探索の結果で、候補・採点には使わない。
class StorePatternPage extends StatefulWidget {
  const StorePatternPage({
    super.key,
    required this.data,
    required this.store,
    required this.day,
    this.onDayChanged,
  });
  final ViewerData data;
  final String store, day;
  final ValueChanged<String>? onDayChanged;
  @override
  State<StorePatternPage> createState() => _StorePatternPageState();
}

class _StorePatternPageState extends State<StorePatternPage> {
  late String _day = widget.day;
  // 日ごとに分けておく（日を選ぶたびに全部の記録を見直さない）。
  late final Map<String, List<SlotRecord>> _byDay = () {
    final out = <String, List<SlotRecord>>{};
    for (final r in widget.data.records) {
      if (r.store == widget.store) out.putIfAbsent(r.day, () => []).add(r);
    }
    return out;
  }();
  late final List<String> _days = viewerDays(widget.data.records, widget.store);
  final _scroll = ScrollController();
  final _cache = <String, StorePatternDay>{};
  List<StorePatternDay> _history = [];
  bool _historyDone = false;
  bool _eventsOnly = false;
  bool _disposed = false;

  @override
  void initState() {
    super.initState();
    _buildHistory();
  }

  @override
  void dispose() {
    _disposed = true;
    _scroll.dispose();
    super.dispose();
  }

  StorePatternDay _report(String day) => _cache[day] ??= storePatternDay(
    widget.store,
    day,
    _byDay[day] ?? const [],
  );

  /// 履歴は日ごとに少しずつ計算する（並びの並べ替えで画面が固まらないように）。
  Future<void> _buildHistory() async {
    for (final day in _days) {
      if (_disposed) return;
      final report = _report(day);
      if (_disposed) return;
      setState(() => _history = [..._history, report]);
      await Future<void>.delayed(Duration.zero);
    }
    if (!_disposed) setState(() => _historyDone = true);
  }

  void _changeDay(String? day) {
    if (day == null || day == _day) return;
    setState(() => _day = day);
    widget.onDayChanged?.call(day);
    _scroll.jumpTo(0);
  }

  String? _event(String day) =>
      widget.data.dateEventFor(widget.store, day)?.name;

  String _percent(double value) => '${(value * 100).round()}%';

  String _chanceDetail(double p) =>
      p < .001 ? '0.1%未満' : '約${(p * 100).toStringAsFixed(p < .1 ? 1 : 0)}%';

  Color _chanceColor(PatternChance chance) => switch (chance) {
    PatternChance.rare => const Color(0xFFB3261E),
    PatternChance.sometimes => const Color(0xFF9A6700),
    PatternChance.common => AppColors.ash,
  };

  Widget _chancePill(PatternChance chance) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
    decoration: BoxDecoration(
      border: Border.all(color: _chanceColor(chance)),
      borderRadius: BorderRadius.circular(999),
    ),
    child: Text(
      displayMachineName(chance.label),
      style: TextStyle(
        fontSize: 12,
        color: _chanceColor(chance),
        fontWeight: FontWeight.w600,
      ),
    ),
  );

  Widget _card(String key, String title, List<Widget> children) => Card(
    key: ValueKey(key),
    child: Padding(
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 6),
          ...children,
        ],
      ),
    ),
  );

  Widget _note(String text) => Text(
    text,
    style: const TextStyle(fontSize: 12, color: AppColors.ash, height: 1.4),
  );

  Widget _groupRow(PatternGroup g, double dayRate) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          displayMachineName(g.label),
          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 2),
        Wrap(
          spacing: 8,
          runSpacing: 4,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text(
              'プラス ${g.plus}/${g.total}台（${_percent(g.rate)}）',
              style: const TextStyle(fontSize: 14),
            ),
            if (g.rate > dayRate) _chancePill(g.chance) else _note('店全体より多くない'),
          ],
        ),
        if (g.rate > dayRate)
          _note(
            'ランダムに配ってこれ以上になる確率 ${_chanceDetail(g.p)}・${g.compared}通り比べた分を割り引くと ${_chanceDetail(g.adjusted)}',
          ),
      ],
    ),
  );

  Widget _summary(StorePatternDay r) => _card(
    'pattern-summary',
    '${storeDisplayName(widget.store)}　${dayWithWeekday(_day)}',
    [
      if (_event(_day) != null)
        Text('イベント：${_event(_day)}', style: const TextStyle(fontSize: 14)),
      Text(
        r.total == 0
            ? '判定に使える台がありません'
            : '判定に使った台 ${r.total}台・プラス ${r.plus}台（${_percent(r.rate)}）',
        style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
      ),
      const SizedBox(height: 4),
      _note('500G以下の台と、プラスかどうか分からない台（${r.excluded}台）は除いています。'),
      if (!r.usable && r.total > 0)
        Padding(
          padding: const EdgeInsets.only(top: 6),
          // 理由はPC（store_pattern_ui.py）と同じ順に選ぶ。2026-11-22（Geminiの点検 M-7①）：以前は、分かる台が
          // 7割に届かない日（アナスロで補った日など）にも「全部プラス、または全部マイナス」と出していた。
          child: _note(
            r.total < patternMinRacks
                ? '台が少ない（$patternMinRacks台未満）ので、偏りは判定しません。'
                : r.total < patternKnownShare * r.played
                ? 'プラスかどうか分かる台が、稼働した台の7割に届かない（アナスロで補った日など）ので、偏りは判定しません。'
                : '全部プラス、または全部マイナスの日なので、偏りは判定しません。',
          ),
        ),
    ],
  );

  Widget _machines(StorePatternDay r) {
    final shown = r.machines.take(8).toList();
    return _card('pattern-machines', '全台系（機種ごと）', [
      if (shown.isEmpty)
        _note('$patternMinGroup台以上ある機種がありません。')
      else ...[
        for (final g in shown) _groupRow(g, r.rate),
        if (r.machines.length > shown.length)
          _note('ほか${r.machines.length - shown.length}機種は偏りが小さいので省略。'),
      ],
    ]);
  }

  Widget _suffixes(StorePatternDay r) => _card('pattern-suffixes', '末尾', [
    if (r.suffixes.isEmpty)
      _note('$patternMinGroup台以上ある末尾がありません。')
    else
      for (final g in r.suffixes) _groupRow(g, r.rate),
  ]);

  Widget _run(StorePatternDay r) {
    final run = r.run;
    return _card('pattern-run', '並び（台番が続いてプラス）', [
      if (run == null)
        _note('プラスの台がありません。')
      else ...[
        Text(
          'いちばん長い並び：${run.label}（${run.length}台）',
          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 4),
        Wrap(
          spacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            _chancePill(run.chance),
            _note('プラスの印をランダムに配り直して、これ以上長く続く割合 ${_chanceDetail(run.p)}'),
          ],
        ),
      ],
      const SizedBox(height: 4),
      _note('台番が1つずつ続く台を隣とみなします（島の切れ目・角は台番からは分からないので見ていません）。'),
    ]);
  }

  Widget _historyCard() {
    final days = [
      for (final h in _history)
        if (!_eventsOnly || _event(h.day) != null) h,
    ];
    return _card('pattern-history', '日ごとの履歴', [
      Row(
        children: [
          FilterChip(
            key: const ValueKey('pattern-events-only'),
            label: const Text('イベントの日だけ'),
            selected: _eventsOnly,
            onSelected: (v) => setState(() => _eventsOnly = v),
          ),
          const SizedBox(width: 8),
          if (!_historyDone) _note('計算中（${_history.length}/${_days.length}日）'),
        ],
      ),
      const SizedBox(height: 4),
      if (days.isEmpty)
        _note(_historyDone ? '該当する日がありません。' : '')
      else
        for (final h in days)
          ListTile(
            key: ValueKey('pattern-day-${h.day}'),
            dense: true,
            contentPadding: EdgeInsets.zero,
            selected: h.day == _day,
            onTap: () => _changeDay(h.day),
            title: Text(
              '${dayWithWeekday(h.day)}${_event(h.day) == null ? '' : '　${_event(h.day)}'}',
            ),
            subtitle: Text(
              !h.usable
                  ? '判定しない日（台が少ない・全部プラスかマイナス）'
                  : h.highlights.isEmpty
                  ? '目立つ偏りなし（プラス ${_percent(h.rate)}）'
                  : h.highlights.join('\n'),
            ),
          ),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final r = _report(_day);
    return Scaffold(
      appBar: AppBar(
        title: const Text('店の入れ方のふり返り'),
        bottom: ViewerDateBar(
          days: _days,
          day: _day,
          onChanged: _changeDay,
          event: _event(_day),
          eventFor: _event,
        ),
      ),
      floatingActionButton: ScrollTopButton(controller: _scroll),
      body: SafeArea(
        child: ListView(
          controller: _scroll,
          padding: const EdgeInsets.all(12),
          children: [
            _summary(r),
            if (r.usable) ...[_machines(r), _suffixes(r), _run(r)],
            _historyCard(),
            Padding(
              padding: const EdgeInsets.all(8),
              child: _note(
                'プラスで終わった台（勝率と同じ数え方）が、機種・末尾・台番の並びに、ランダムに配ったときより偏っていたかを見ます。'
                '「偶然では出にくい」は、何通りも比べた中の一番であることを割り引いても5%未満、「ときどき出る」は20%未満です。\n'
                '探索の結果です。翌日候補・採点には使っていません。候補に使うなら、先に確かめ方を決めて前向きに確かめてから。'
                '設定そのものではなく、差枚のプラス・マイナスで見ています。',
              ),
            ),
          ],
        ),
      ),
    );
  }
}
