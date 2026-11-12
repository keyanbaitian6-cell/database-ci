import 'dart:convert';

import 'package:flutter/material.dart';

import 'daily_learning_transport.dart';
import 'list_views.dart' show displayMachineName;

const dailyStoreNames = {
  'nagamachiminami': '長町南',
  'saiwaichou': '幸町',
  'pscube:c740601:20': 'P-STATION',
};

Map<String, dynamic> parseDailyLearning(String text) {
  final value = jsonDecode(text);
  if (value is! Map ||
      value['format'] != 'daily-learning' ||
      value['version'] != 1 ||
      value['days'] is! List ||
      value['status'] is! String ||
      value['updated_at'] is! String) {
    throw const FormatException('日次学習の形式が違います');
  }
  for (final day in value['days'] as List) {
    if (day is! Map ||
        day['target'] is! String ||
        day['groups'] is! List ||
        !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(day['target'] as String)) {
      throw const FormatException('対象日の形式が違います');
    }
    for (final g in day['groups'] as List) {
      if (g is! Map ||
          !dailyStoreNames.containsKey(g['store']) ||
          g['name'] is! String ||
          g['status'] is! String ||
          !['current', 'learned'].contains(g['active']) ||
          g['selected'] is! List) {
        throw const FormatException('候補の形式が違います');
      }
      final raw = g['saved_at'] ?? day['saved_at'];
      if (raw is! String || !RegExp(r'(Z|[+-]\d\d:\d\d)$').hasMatch(raw)) {
        throw const FormatException('保存時刻が不明です');
      }
      final saved = DateTime.parse(raw).toUtc().add(const Duration(hours: 9));
      // 保存できるのは対象日の前日23:30〜当日08:00（日本時間。2026-11-11）。
      final savedDay = saved.toIso8601String().substring(0, 10);
      final before = DateTime.parse('${day['target']}T00:00:00Z')
          .subtract(const Duration(days: 1))
          .toIso8601String()
          .substring(0, 10);
      final minutes = saved.hour * 60 + saved.minute;
      final inWindow =
          (savedDay == day['target'] && minutes < 480) ||
          (savedDay == before && minutes >= 1410);
      if (!inWindow) {
        throw const FormatException('締切前の予測ではありません');
      }
      for (final id in g['selected'] as List) {
        if (id is! List ||
            id.length != 4 ||
            id[0] != g['store'] ||
            id[2] is! String ||
            id[3] is! int) {
          throw const FormatException('台の形式が違います');
        }
      }
    }
  }
  return Map<String, dynamic>.from(value);
}

/// 最初に開く対象日（日本時間）。23:30以降は、その夜に保存される翌日の分（2026-11-12）。
String dailyDefaultTarget(DateTime now) {
  final local = now.toUtc().add(const Duration(hours: 9));
  final day = local.hour * 60 + local.minute >= 1410
      ? local.add(const Duration(days: 1))
      : local;
  return day.toIso8601String().substring(0, 10);
}

/// 最初に開く対象日の保存時間帯（その前日の23:30から）に入ってから、PCの処理結果が1回も届いていないか。
///
/// 2026-11-12：以前は「最終処理の日付が今日でない」で見ていたので、前の晩の23:30台に保存した正しい候補にも、
/// 0時を過ぎると「本日の処理結果は届いていません」と出ていた。
bool dailyStale(String updated, DateTime now) {
  final start = DateTime.parse('${dailyDefaultTarget(now)}T23:30:00+09:00')
      .subtract(const Duration(days: 1));
  final at = DateTime.tryParse(updated);
  return at == null || at.isBefore(start);
}

const _dailyWeek = '日月火水木金土';

/// 「11月12日（木）」。
String dailyDateLabel(String day) {
  final d = DateTime.parse('${day}T00:00:00Z');
  return '${d.month}月${d.day}日（${_dailyWeek[d.weekday % 7]}）';
}

/// 保存時刻などを日本時間の「11月12日 0:30」で出す。読めない値はそのまま。
String dailyTime(String stamp) {
  final parsed = DateTime.tryParse(stamp);
  if (parsed == null) return stamp;
  final d = parsed.toUtc().add(const Duration(hours: 9));
  return '${d.month}月${d.day}日 ${d.hour}:${d.minute.toString().padLeft(2, '0')}';
}

/// 状態の文（「長町南：…／幸町：…／同期先…」）を、この店舗の分と全体の分に分ける。
({List<String> mine, List<String> general}) dailyStatusParts(
  String status,
  String store,
) {
  final prefixes = [
    for (final e in dailyStoreNames.entries) ...['${e.key}：', '${e.value}：'],
  ];
  final own = ['${dailyStoreNames[store]}：', '$store：'];
  final mine = <String>[], general = <String>[];
  for (final raw in status.split('／')) {
    final part = raw.trim();
    if (part.isEmpty) continue;
    final hit = own.where(part.startsWith).firstOrNull;
    if (hit != null) {
      mine.add(part.substring(hit.length));
    } else if (!prefixes.any(part.startsWith)) {
      general.add(part);
    }
  }
  return (mine: mine, general: general);
}

final _dailyImportant = RegExp(r'処理失敗|取り込み待ち|締切超過|同期先|書けません|読めません');

class DailyRack {
  const DailyRack(this.rack, this.machine);
  final int rack;

  /// バラエティのように機種名が組の名前と違うときだけ。
  final String? machine;
}

class DailyGroupView {
  const DailyGroupView({
    required this.name,
    required this.learned,
    required this.status,
    required this.saved,
    required this.racks,
  });
  final String name;
  final bool learned;
  final String status;
  final String saved;
  final List<DailyRack> racks;
}

/// 表示する中身（4画面で同じ意味・順序。2026-11-12）。保存済みの selected の台と順番をそのまま使い、画面で計算し直さない。
class DailyView {
  DailyView(Map<String, dynamic> data, this.store, this.target, DateTime now) {
    final days = data['days'] as List;
    final day = days
        .cast<Map>()
        .where((d) => d['target'] == target)
        .firstOrNull;
    for (final g in (day?['groups'] as List? ?? const [])) {
      if (g['store'] != store) continue;
      final name = g['name'] as String;
      groups.add(
        DailyGroupView(
          name: name,
          learned: g['active'] == 'learned',
          status: g['status'] as String,
          saved: (g['saved_at'] ?? day!['saved_at']) as String,
          racks: [
            for (final id in g['selected'] as List)
              DailyRack(id[3] as int, id[2] == name ? null : id[2] as String),
          ],
        ),
      );
    }
    final parts = dailyStatusParts(data['status'] as String, store);
    mine = parts.mine;
    general = parts.general;
    updated = data['updated_at'] as String;
    final initial = dailyDefaultTarget(now);
    past = target.compareTo(initial) < 0;
    alerts.addAll([...mine, ...general].where(_dailyImportant.hasMatch));
    if (dailyStale(updated, now)) {
      alerts.add(
        '${dailyDateLabel(initial)}の分の処理結果は届いていません。古い候補をこの日の予測として使わないでください。',
      );
    }
    if (past) {
      alerts.add(
        '${dailyDateLabel(target)}は過去の対象日です。記録として表示しています。次の営業日の候補として使わないでください。',
      );
    }
    if (groups.isEmpty) {
      alerts.add('この日の保存済み候補はありません。データ不足・締切超過・PC停止などを確認してください。');
    }
    dates = {
      initial,
      target,
      ...days.map((d) => d['target'] as String),
    }.toList()..sort((a, b) => b.compareTo(a));
  }
  final String store;
  final String target;
  final groups = <DailyGroupView>[];
  final alerts = <String>[];
  late final List<String> mine, general, dates;
  late final String updated;
  late final bool past;
  int get count => groups.fold(0, (n, g) => n + g.racks.length);
  String get scope {
    final machines = groups.where((g) => g.name != 'バラエティ').length;
    final variety = groups.any((g) => g.name == 'バラエティ');
    if (machines > 0 && variety) return '$machines機種とバラエティ';
    return variety ? 'バラエティ' : '$machines機種';
  }
}

const _dailyMethodText = {
  true: '日次学習版：店舗ごとの判定で、将来の成績による改善を確認したため採用している方式です。',
  false: '従来方式：これまでの翌日候補と同じ選び方です。日次学習版は、将来の成績で改善を確認するまで採用しません。',
};

/// 全端末でPCが固定した同じ候補を読む。画面側で再学習しない。
class DailyLearningPage extends StatefulWidget {
  const DailyLearningPage({super.key, this.load, this.store});
  final Future<String> Function()? load;
  final String? store;
  @override
  State<DailyLearningPage> createState() => _DailyLearningPageState();
}

class _DailyLearningPageState extends State<DailyLearningPage> {
  late String _store = widget.store ?? 'nagamachiminami';
  String? _target;
  late Future<Map<String, dynamic>> _data = _read();
  Future<Map<String, dynamic>> _read() async =>
      parseDailyLearning(await (widget.load?.call() ?? loadDailyDocument()));
  void _refresh() => setState(() => _data = _read());
  Future<void> _configure() async {
    final controller = TextEditingController();
    final url = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('日次学習の読み込み先'),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(
            labelText: '既存の閲覧用GoogleスクリプトのURL',
            hintText: 'https://script.google.com/macros/s/…/exec',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, controller.text.trim()),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (url == null || !mounted) return;
    try {
      await saveDailyUrl(url);
      _refresh();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('URLを確認してください。設定は変更していません。')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('日次学習・採用中の候補'),
      actions: [
        if (widget.load == null)
          IconButton(
            onPressed: _configure,
            tooltip: '読み込み先の設定',
            icon: const Icon(Icons.settings),
          ),
        IconButton(
          onPressed: _refresh,
          tooltip: '日次学習を更新',
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: FutureBuilder<Map<String, dynamic>>(
      future: _data,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return ListView(
            padding: const EdgeInsets.all(16),
            children: const [
              _DailyAlerts([
                '日次学習を読み込めません。PCの実行状況・同期先・閲覧用Googleスクリプトの更新を確認してください。従来候補は引き続き参考にできます。',
              ]),
            ],
          );
        }
        final data = snapshot.data!;
        final now = DateTime.now();
        final initial = dailyDefaultTarget(now);
        final known = {
          initial,
          ...(data['days'] as List).map((d) => d['target'] as String),
        };
        final view = DailyView(
          data,
          _store,
          known.contains(_target) ? _target! : initial,
          now,
        );
        final theme = Theme.of(context);
        final muted = theme.textTheme.bodySmall?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
        );
        // 4画面で同じ順：切り替え → 重要な注意 → 候補数 → 機種ごとの候補 → 開閉式の説明（2026-11-12）。
        return ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
          children: [
            _DailyFilters(
              store: _store,
              target: view.target,
              dates: view.dates,
              past: (d) => d.compareTo(initial) < 0,
              onStore: (v) => setState(() => _store = v),
              onTarget: (v) => setState(() => _target = v),
            ),
            const SizedBox(height: 12),
            if (view.alerts.isNotEmpty) ...[
              _DailyAlerts(view.alerts),
              const SizedBox(height: 12),
            ],
            Wrap(
              crossAxisAlignment: WrapCrossAlignment.end,
              spacing: 10,
              runSpacing: 2,
              children: [
                Text(
                  view.count > 0 ? '${view.count}台' : '候補なし',
                  style: theme.textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
                Text(
                  '${dailyStoreNames[_store]}・${dailyDateLabel(view.target)}'
                  '${view.count > 0 ? '・${view.scope}の保存済み候補' : ''}',
                ),
              ],
            ),
            Text('最終処理 ${dailyTime(view.updated)}（日本時間）', style: muted),
            const SizedBox(height: 8),
            for (final g in view.groups) _DailyGroupCard(g),
            const SizedBox(height: 4),
            _DailyMore(
              title: '処理状況・日次学習について',
              lines: [
                for (final s in view.mine) '${dailyStoreNames[_store]}：$s',
                ...view.general,
                if (view.mine.isEmpty && view.general.isEmpty) '処理状況の記録はありません。',
                'PCで前日23:30〜当日8:00の間に保存した候補を表示します。画面を開いても予測を作り直しません。',
                '採用は店舗ごとに、保存した予測の将来の成績で判定します。判定までは従来方式を採用します。',
              ],
            ),
            const SizedBox(height: 8),
            Text(
              '毎日学習しても、毎日の改善を保証しません。設定確率・勝率・期待収支を示すものではありません。',
              style: muted,
            ),
          ],
        );
      },
    ),
  );
}

class _DailyFilters extends StatelessWidget {
  const _DailyFilters({
    required this.store,
    required this.target,
    required this.dates,
    required this.past,
    required this.onStore,
    required this.onTarget,
  });
  final String store, target;
  final List<String> dates;
  final bool Function(String) past;
  final ValueChanged<String> onStore, onTarget;

  @override
  Widget build(BuildContext context) {
    final storeField = DropdownButtonFormField<String>(
      key: const ValueKey('daily-store'),
      initialValue: store,
      isExpanded: true,
      decoration: const InputDecoration(
        labelText: '店舗',
        border: OutlineInputBorder(),
      ),
      items: [
        for (final e in dailyStoreNames.entries)
          DropdownMenuItem(value: e.key, child: Text(e.value)),
      ],
      onChanged: (v) => onStore(v!),
    );
    final dayField = DropdownButtonFormField<String>(
      key: ValueKey('daily-day-$target'),
      initialValue: target,
      isExpanded: true,
      decoration: const InputDecoration(
        labelText: '対象日',
        border: OutlineInputBorder(),
      ),
      items: [
        for (final d in dates)
          DropdownMenuItem(
            value: d,
            child: Text(
              '${dailyDateLabel(d)}${past(d) ? '・過去日' : ''}',
              overflow: TextOverflow.ellipsis,
            ),
          ),
      ],
      onChanged: (v) => onTarget(v!),
    );
    return LayoutBuilder(
      builder: (context, box) => box.maxWidth < 420
          ? Column(children: [storeField, const SizedBox(height: 12), dayField])
          : Row(
              children: [
                Expanded(child: storeField),
                const SizedBox(width: 12),
                Expanded(child: dayField),
              ],
            ),
    );
  }
}

/// 折りたたまない重要な注意（処理失敗・取り込み待ち・過去日・未更新・候補なし・読み込み失敗）。
class _DailyAlerts extends StatelessWidget {
  const _DailyAlerts(this.alerts);
  final List<String> alerts;

  @override
  Widget build(BuildContext context) => Semantics(
    liveRegion: true,
    child: Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF8E8),
        border: Border.all(color: const Color(0xFFB37413)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final (i, a) in alerts.indexed)
            Padding(
              padding: EdgeInsets.only(top: i == 0 ? 0 : 6),
              child: Text(a, style: const TextStyle(color: Color(0xFF1D1D1F))),
            ),
        ],
      ),
    ),
  );
}

class _DailyGroupCard extends StatelessWidget {
  const _DailyGroupCard(this.group);
  final DailyGroupView group;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall?.copyWith(
      color: theme.colorScheme.onSurfaceVariant,
    );
    final learned = group.learned;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              // 2026-11-12 iPhoneで半角カナの機種名が□になった（閲覧ページの字体に無い）。ほかの画面と同じく全角にそろえる。
              displayMachineName(group.name),
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 6),
            // ラベルは1行のまま左に置き、台数は右端（以前は Flexible と Spacer で幅を半分ずつ取り、320px幅でラベルが2行に折れた）。
            Row(
              children: [
                Expanded(
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 3,
                      ),
                      decoration: BoxDecoration(
                        color: learned
                            ? const Color(0xFFE8F1FD)
                            : const Color(0xFFE6E6E8),
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        '採用中 ${learned ? '日次学習版' : '従来方式'}',
                        style: TextStyle(
                          fontSize: 13,
                          color: learned
                              ? const Color(0xFF0066CC)
                              : const Color(0xFF1D1D1F),
                          fontWeight: learned ? FontWeight.w600 : null,
                        ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Text('${group.racks.length}台', style: muted),
              ],
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final r in group.racks)
                  Container(
                    constraints: const BoxConstraints(minWidth: 76),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF2F2F4),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text.rich(
                          TextSpan(
                            children: [
                              TextSpan(
                                text: '${r.rack}',
                                style: const TextStyle(
                                  fontSize: 26,
                                  fontWeight: FontWeight.w600,
                                  color: Color(0xFF1D1D1F),
                                  fontFeatures: [FontFeature.tabularFigures()],
                                ),
                              ),
                              const TextSpan(
                                text: '番',
                                style: TextStyle(
                                  fontSize: 13,
                                  color: Color(0xFF707070),
                                ),
                              ),
                            ],
                          ),
                        ),
                        if (r.machine != null)
                          Text(
                            displayMachineName(r.machine!),
                            style: const TextStyle(
                              fontSize: 12,
                              color: Color(0xFF707070),
                            ),
                          ),
                      ],
                    ),
                  ),
              ],
            ),
            _DailyMore(
              title: '採用方式の説明・保存時刻',
              lines: [
                group.status,
                _dailyMethodText[learned]!,
                '保存 ${dailyTime(group.saved)}（日本時間）',
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// 開閉式の説明。最初は閉じている。
class _DailyMore extends StatelessWidget {
  const _DailyMore({required this.title, required this.lines});
  final String title;
  final List<String> lines;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Theme(
      data: theme.copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.only(bottom: 8),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        title: Text(
          title,
          style: TextStyle(fontSize: 15, color: theme.colorScheme.primary),
        ),
        children: [
          for (final line in lines)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                line,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ),
        ],
      ),
    );
  }
}
