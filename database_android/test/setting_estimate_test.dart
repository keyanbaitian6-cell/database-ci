import 'package:database_android/models.dart';
import 'package:database_android/setting_estimate.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord record(String machine, int games, int bb, int rb) => SlotRecord(
  store: 'saiwaichou',
  day: '2026-09-23',
  machine: machine,
  rack: 123,
  games: games,
  bb: bb,
  rb: rb,
  confirmedSetting: '6',
);

void main() {
  test('保存済みの型式名は正しい機種表に対応する', () {
    expect(settingModelForMachine('SマイジャグラーVKD'), 'my_juggler_v');
    expect(settingModelForMachine('SネオアイムジャグラーEX−KK'), 'neo_im_juggler');
    expect(settingModelForMachine('Sハナハナホウオウ〜天翔〜EX−30'), 'houou_tensho');
    expect(settingModelForMachine('SｷﾝｸﾞﾊﾅﾊﾅSP-30'), 'king_2023');
    expect(settingModelForMachine('SBﾆｭｰｷﾝｸﾞﾊﾅﾊﾅVPA-30'), 'new_king_v');
    expect(settingModelForMachine('Sドラゴンハナハナ〜閃光〜SP−30'), 'dragon_senko');
    expect(settingModelForMachine('マイジャグラーⅥ'), isNull);
    expect(settingModelForMachine('キングハナハナ-30'), isNull);
    expect(settingModelForMachine('SBニューキングハナハナVIPA-30'), isNull);
    expect(settingModelForMachine('SマイジャグラーVXKD'), isNull);
    expect(settingModelForMachine('SネオアイムジャグラーEX2−KK'), isNull);
  });

  test('BBとRBを別々に比較し、低Gでは範囲が広がる', () {
    final high = estimateSetting(record('SマイジャグラーVKD', 10000, 44, 43))!;
    final low = estimateSetting(record('SマイジャグラーVKD', 100, 0, 0))!;
    expect(high.setting, '6');
    expect(high.support, 51.2); // PC版の同じ入力との照合値
    expect(high.range80, ['4', '5', '6']);
    expect(high.range80, contains('6'));
    expect(high.shortLabel, 'BB/RB候補 4・5・6');
    expect(high.detailLabel, contains('最多適合 6（均等仮定のモデル内相対重み 51.2%）'));
    expect(low.range80.length, greaterThan(high.range80.length));
    expect(low.range80, ['1', '2', '3', '4', '5', '6']);
    expect(low.shortLabel, 'BB/RBでは絞り込めず');
    expect(
      estimateSetting(record('SマイジャグラーVKD', 10000, 44, 20))!.support,
      isNot(high.support),
    );
  });

  test('ニューキングは設定Vを維持し、無効なデータでは推測しない', () {
    final row = record('SBニューキングハナハナVPA−30', 20000, 79, 54);
    expect(estimateSetting(row)!.setting, 'V');
    expect(estimateSetting(row)!.support, 46.9);
    expect(estimateSetting(row)!.range80, ['3', '4', 'V']);
    expect(estimateSetting(row)!.shortLabel, 'BB/RB候補 3・4・V');
    expect(row.confirmedSetting, '6');
    expect(estimateSetting(record(row.machine, 0, 0, 0)), isNull);
    expect(estimateSetting(record(row.machine, 10, 79, 54)), isNull);
  });
}
