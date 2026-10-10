import 'package:flutter/material.dart';

import 'app_controller.dart';
import 'list_views.dart';
import 'models.dart';
import 'shared_widgets.dart';
import 'viewer_pages.dart' show ViewerDateBar, viewerDays;

/// 店舗・機種・台番号を固定して、保存済みの記録日を切り替える。
/// Controllerを監視し、取り込み・削除・イベント編集も画面へ反映する。
class AndroidRecordPage extends StatefulWidget {
  const AndroidRecordPage({
    super.key,
    required this.controller,
    required this.record,
  });

  final AppController controller;
  final SlotRecord record;

  @override
  State<AndroidRecordPage> createState() => _AndroidRecordPageState();
}

class _AndroidRecordPageState extends State<AndroidRecordPage> {
  late String _day = widget.record.day;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) {
      final controller = widget.controller;
      final original = widget.record;
      final bar = ViewerDateBar(
        days: viewerDays(controller.records, original.store),
        day: _day,
        event: controller.dateEventFor(original.store, _day)?.name,
        eventFor: (day) => controller.dateEventFor(original.store, day)?.name,
        onChanged: (day) {
          if (day != null && day != _day) setState(() => _day = day);
        },
      );
      Widget scaffold(Widget body) => Scaffold(
        appBar: AppBar(title: Text('${original.rack}番台'), bottom: bar),
        body: SafeArea(child: body),
      );
      return FutureBuilder<DayView>(
        future: controller.dayView(original.store, _day),
        builder: (context, snapshot) {
          // 日付変更中は前の日のsnapshotを表示しない。
          if (snapshot.connectionState != ConnectionState.done) {
            return scaffold(const Center(child: CircularProgressIndicator()));
          }
          if (snapshot.hasError) {
            return scaffold(
              Center(child: Text('採点できませんでした：${snapshot.error}')),
            );
          }
          final entry = snapshot.data!.scored.values
              .where(
                (e) =>
                    e.$1.machine == original.machine &&
                    e.$1.rack == original.rack,
              )
              .firstOrNull;
          if (entry == null) {
            return scaffold(
              ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  Text(displayMachineName(original.machine)),
                  Text(dayWithWeekday(_day)),
                  const EmptyState(
                    icon: Icons.inbox_outlined,
                    title: 'この日の記録はありません',
                    body: '同じ店舗・機種・台番号の記録がありません。別の日付を選んでください。',
                  ),
                ],
              ),
            );
          }
          return SavedGraphPage(
            key: ValueKey(entry.$1.key),
            record: entry.$1,
            score: entry.$2,
            allRecords: controller.records,
            dateNavigation: bar,
            onOpenDay: (day) {
              if (day != _day) setState(() => _day = day);
            },
          );
        },
      );
    },
  );
}
