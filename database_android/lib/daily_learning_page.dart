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
          return const Padding(
            padding: EdgeInsets.all(16),
            child: Text(
              '日次学習を読み込めません。PCの実行状況・同期先・閲覧用Googleスクリプトの更新を確認してください。従来候補は引き続き参考にできます。',
            ),
          );
        }
        final data = snapshot.data!;
        final today = DateTime.now()
            .toUtc()
            .add(const Duration(hours: 9))
            .toIso8601String()
            .substring(0, 10);
        final days = data['days'] as List;
        final dates = {
          today,
          ...days.map((d) => d['target'] as String),
        }.toList()..sort((a, b) => b.compareTo(a));
        final target = dates.contains(_target) ? _target! : today;
        final matching = days.where((d) => d['target'] == target).toList();
        final groups = matching
            .expand((d) => d['groups'] as List)
            .where((g) => g['store'] == _store)
            .toList();
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text(
              'PCで前日23:30〜当日8:00の間に固定した予測です。毎日学習しても、毎日改善する保証はありません。',
            ),
            Text('最終処理 ${data['updated_at']}'),
            Text(data['status'] as String),
            if (!(data['updated_at'] as String).startsWith(today))
              const Text('本日の処理結果は届いていません。古い候補を本日の予測として使わないでください。'),
            DropdownButton<String>(
              isExpanded: true,
              value: _store,
              items: dailyStoreNames.entries
                  .map(
                    (e) => DropdownMenuItem(value: e.key, child: Text(e.value)),
                  )
                  .toList(),
              onChanged: (v) => setState(() => _store = v!),
            ),
            DropdownButton<String>(
              isExpanded: true,
              value: target,
              items: dates
                  .map((d) => DropdownMenuItem(value: d, child: Text('対象日 $d')))
                  .toList(),
              onChanged: (v) => setState(() => _target = v),
            ),
            if (groups.isEmpty)
              const Text('この日の保存済み候補はありません。データ不足・締切超過・PC停止などを確認してください。'),
            for (final g in groups)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        // 2026-11-12 iPhoneで半角カナの機種名が□になった（閲覧ページの字体に無い）。ほかの画面と同じく全角にそろえる。
                        displayMachineName(g['name'] as String),
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      Text(
                        '採用中 ${g['active'] == 'learned' ? '日次学習版' : '従来方式'}',
                      ),
                      Text(g['status'] as String),
                      Text('保存 ${g['saved_at'] ?? matching.first['saved_at']}'),
                      for (final id in g['selected'] as List)
                        Text('${id[3]}番 ${displayMachineName('${id[2]}')}'),
                    ],
                  ),
                ),
              ),
            const Text('採用判断は未使用の将来予測で行います。点数は設定確率・勝率・期待収支ではありません。'),
          ],
        );
      },
    ),
  );
}
