import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/models.dart';
import 'package:database_android/normal_type.dart';

SlotRecord rec(int rack, String machine) => SlotRecord(
  store: 'saiwaichou',
  day: '2026-09-23',
  machine: machine,
  rack: rack,
  games: 3000,
  bb: 10,
  rb: 5,
);

void main() {
  test('機種名からノーマルタイプの系列を見分ける（半角カナの表記も）', () {
    expect(normalSeriesOf('SマイジャグラーVKD'), NormalSeries.juggler);
    expect(normalSeriesOf('SﾏｲｼﾞｬｸﾞﾗｰV'), NormalSeries.juggler);
    expect(normalSeriesOf('ファンキージャグラー2'), NormalSeries.juggler);
    expect(normalSeriesOf('SBニューキングハナハナVPA-30'), NormalSeries.hanahana);
    expect(normalSeriesOf('SBﾆｭｰｷﾝｸﾞﾊﾅﾊﾅVPA-30'), NormalSeries.hanahana);
    expect(normalSeriesOf('ドラゴンハナハナ〜閃光〜'), NormalSeries.hanahana);
    // ノーマルタイプ以外
    expect(normalSeriesOf('Lとある科学の超電磁砲2FV'), isNull);
    expect(normalSeriesOf('L 甲鉄城のｶﾊﾞﾈﾘ 海門決戦 XX'), isNull);
    expect(normalSeriesOf(null), isNull);
    expect(normalSeriesOf(''), isNull);
  });

  test('系列ごとに記録を絞り込む', () {
    final records = [
      rec(1, 'SマイジャグラーVKD'),
      rec(2, 'SBニューキングハナハナVPA-30'),
      rec(3, 'Lとある科学の超電磁砲2FV'),
      rec(4, 'ﾌｧﾝｷｰｼﾞｬｸﾞﾗｰ2'),
    ];
    racks(List<SlotRecord> rows) => [for (final r in rows) r.rack];

    expect(racks(recordsOfSeries(records, NormalSeries.juggler)), [1, 4]);
    expect(racks(recordsOfSeries(records, NormalSeries.hanahana)), [2]);
    // 系列を選ばなければ、そのまま全部
    expect(racks(recordsOfSeries(records, null)), [1, 2, 3, 4]);
    // ノーマルタイプだけ（ジャグラー・ハナハナ両方）
    expect(racks(normalTypeRecords(records)), [1, 2, 4]);
  });

  test('画面に出す名前', () {
    expect(NormalSeries.juggler.label, 'ジャグラーシリーズ');
    expect(NormalSeries.hanahana.label, 'ハナハナシリーズ');
  });
}
