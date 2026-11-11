import 'package:flutter/material.dart';

import 'list_views.dart' show displayMachineName, foldForSearch;
import 'models.dart' show SlotRecord;
import 'pscube_validation_page.dart' show pscubeValidationStore;
import 'shared_widgets.dart' show Notice;
import 'theme.dart';

/// P-STATION【20】スロの翌日候補に添える、暦の注記（iPhoneの閲覧ページだけ。
/// 2026-11-11 利用者「iPhoneのページにお願いします」）。
///
/// 指数・採点・候補の計算には使わない。過去の記録（保存データ）で見えた傾向を、
/// 該当する日の前日にだけ文で出す。根拠は 2026-11-11 の分析
/// （AI_COLLABORATION.md「4月からのデータで翌日候補は良くなるか」）：
/// - 5・15・25日のゴーゴージャグラー3は、機種全体の合算がほかの日の約1.10倍・RBが約1.18倍
///   （2026年4月〜11月7日の22回。22回中21回でその月の平均より上）。
/// - 23日の台番号下2桁23のジャグラー（当時は1323番・マイジャグラーVの1台）は、
///   4〜10月の7回すべてで同じ機種の全台の1.10〜1.37倍。
/// 前向き検証（v1）が同じ2つを未見の日で確かめている。店が運用を変えれば終わるので、
/// 数字は「過去の記録では」として出す。台番号と機種名は、その日の記録から拾う
/// （入れ替えで機種が変わっていれば、変わった名前がそのまま出る）。
List<String> pscubeCalendarNotes(
  String store,
  String day,
  Iterable<SlotRecord> dayRows,
) {
  if (store != pscubeValidationStore) return const [];
  final parts = day.split('-');
  if (parts.length != 3) return const [];
  final y = int.tryParse(parts[0]), m = int.tryParse(parts[1]);
  final d = int.tryParse(parts[2]);
  if (y == null || m == null || d == null) return const [];
  // 候補は「次の日」のもの。月末は翌月1日になる（UTCで足して夏時間の影響を受けない）。
  final next = DateTime.utc(y, m, d + 1);
  final label = '翌日（${next.month}/${next.day}）';
  final notes = <String>[];
  bool juggler(SlotRecord r) => foldForSearch(r.machine).contains('ジャグラー');
  if (const [5, 15, 25].contains(next.day) &&
      dayRows.any(
        (r) => foldForSearch(r.machine).contains('ゴーゴージャグラー3'),
      )) {
    notes.add(
      '$labelは5のつく日です。過去の記録では、5・15・25日のゴーゴージャグラー3は機種全体で当たりが多めでした'
      '（2026年4月〜11月7日の22回で、合算がほかの日の約1.10倍・RBが約1.18倍。22回中21回でその月の平均より上）。'
      '朝からよく回される日です。',
    );
  }
  if (next.day == 23) {
    final racks = [
      for (final r in dayRows)
        if (r.rack % 100 == 23 && juggler(r)) r,
    ]..sort((a, b) => a.rack.compareTo(b.rack));
    if (racks.isNotEmpty) {
      final names = racks
          .map((r) => '${r.rack}番・${displayMachineName(r.machine)}')
          .join('、');
      notes.add(
        '$labelは23日です。台番号の下2桁が23のジャグラー（$names）に注目。'
        '過去の記録では、23日の1323番（マイジャグラーV）は、同じ機種の全台より当たりが多めでした'
        '（2026年4月〜10月の7回すべてで1.10〜1.37倍）。毎回1万G前後回されています。',
      );
    }
  }
  return notes;
}

/// 注記の下に添える断り書き。
const pscubeCalendarNoteCaveat = '過去の記録からの注記です。指数・採点には入っていません。今後も続くとは限りません。';

/// 翌日候補のカードの上に置く部品。注記が無い日は何も置かない。
List<Widget> pscubeCalendarNoteWidgets(
  String store,
  String day,
  Iterable<SlotRecord> dayRows,
) {
  final notes = pscubeCalendarNotes(store, day, dayRows);
  if (notes.isEmpty) return const [];
  return [
    for (final (i, note) in notes.indexed)
      Notice(key: ValueKey('pscube-calendar-note-$i'), text: note),
    const Padding(
      padding: EdgeInsets.only(bottom: 10),
      child: Text(
        pscubeCalendarNoteCaveat,
        style: TextStyle(fontSize: 12, color: AppColors.ash),
      ),
    ),
  ];
}
