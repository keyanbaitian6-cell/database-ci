import 'dart:convert';

import 'package:flutter/material.dart';

import 'list_views.dart' show displayMachineName;

const pscubeValidationStore = 'pscube:c740601:20';
const _methods = <String, String>{
  'random_draw': '同機種内の無作為',
  'day23': '23日の下2桁23',
  'date_two_exploratory': '日付と下2桁が一致（探索）',
};

/// 事前に保存された候補を表示する。表示時点の記録からは再計算しない。
class PscubeValidationPage extends StatefulWidget {
  const PscubeValidationPage({super.key, required this.load});

  final Future<String> Function() load;

  @override
  State<PscubeValidationPage> createState() => _PscubeValidationPageState();
}

class _PscubeValidationPageState extends State<PscubeValidationPage> {
  late Future<Map<String, Map<String, dynamic>>> _data = _read();
  String? _target;

  Future<Map<String, Map<String, dynamic>>> _read() async {
    final value = jsonDecode(await widget.load());
    if (value is! Map ||
        value['format'] != 'pscube-validation' ||
        value['version'] != 1 ||
        value['days'] is! List) {
      throw const FormatException('検証候補の形式が不正です。');
    }
    return {
      for (final day in value['days'] as List)
        day['target'] as String: Map<String, dynamic>.from(day as Map),
    };
  }

  void _refresh() => setState(() => _data = _read());

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('検証候補'),
        actions: [
          IconButton(
            tooltip: '検証候補を更新',
            onPressed: _refresh,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: FutureBuilder<Map<String, Map<String, dynamic>>>(
        future: _data,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return const Center(
              child: Padding(
                padding: EdgeInsets.all(16),
                child: Text('検証候補を読み込めませんでした。Driveの出力と閲覧用スクリプトの設定を確認してください。'),
              ),
            );
          }
          final data = snapshot.data!;
          final today = DateTime.now()
              .toUtc()
              .add(const Duration(hours: 9))
              .toIso8601String()
              .substring(0, 10);
          final dates = {today, ...data.keys}.toList()
            ..sort((a, b) => b.compareTo(a));
          final target = dates.contains(_target) ? _target! : today;
          final day = data[target];
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              const Text('P-STATION・20スロ・ジャグラー'),
              const Text('PCで午前9時前に保存した比較用の候補です。'),
              const SizedBox(height: 12),
              DropdownButton<String>(
                value: target,
                isExpanded: true,
                items: [
                  for (final date in dates)
                    DropdownMenuItem(value: date, child: Text('対象日 $date')),
                ],
                onChanged: (value) => setState(() => _target = value),
              ),
              if (day == null)
                const Text('この日の検証候補はまだ届いていません。')
              else ...[
                Text('元データの営業日 ${day['input_day']}'),
                Text(
                  '保存時刻 ${(day['saved_at'] as String).substring(11, 19)}（日本時間）',
                ),
                if ((day['preliminary'] as int) > 0)
                  Text('前日データに確定前のサイトセブン記録が${day['preliminary']}台分含まれます。'),
                if ((day['machines'] as List).isEmpty)
                  const Text('対象機種の候補はありません。'),
                for (final machine in day['machines'] as List)
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            // 半角カナの機種名は全角に（2026-11-22、Geminiの点検 H-12④。AGENTS.md の決まり）。
                            displayMachineName(machine['name'] as String),
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          for (final entry in _methods.entries)
                            if ((machine['candidates'] as Map).containsKey(
                              entry.key,
                            ))
                              Padding(
                                padding: const EdgeInsets.only(top: 6),
                                child: Text(
                                  '${entry.value}\n${(machine['candidates'][entry.key] as List).join('、')}',
                                ),
                              ),
                        ],
                      ),
                    ),
                  ),
              ],
            ],
          );
        },
      ),
    );
  }
}
