import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/backup_service.dart';
import 'package:database_android/models.dart';

SlotRecord sample({
  int rack = 128,
  int games = 3500,
  int bb = 20,
  int rb = 10,
  int? maxHold = 2000,
  GraphMeasurement? graph,
  String? confirmedSetting,
}) => SlotRecord(
  store: 'nagamachiminami',
  day: '2026-09-13',
  machine: 'テスト',
  rack: rack,
  games: games,
  bb: bb,
  rb: rb,
  maxHold: maxHold,
  graph: graph,
  confirmedSetting: confirmedSetting,
);

void main() {
  final service = BackupService();

  test('新しい台番号はそのまま追加される', () {
    final plan = service.plan(
      [sample(rack: 101).toJson(), sample(rack: 202).toJson()],
      [sample(rack: 101)],
    );
    expect(plan.added.map((r) => r.rack), [202]);
    expect(plan.unchanged.length, 1);
    expect(plan.conflicts, isEmpty);
  });

  test('数値が食い違う記録は自動で上書きされず競合として残る', () {
    final plan = service.plan(
      [sample(rack: 101, games: 9999).toJson()],
      [sample(rack: 101, games: 3500)],
    );
    expect(plan.conflicts.length, 1);
    expect(plan.conflicts.single.local.games, 3500);
    expect(plan.conflicts.single.incoming.games, 9999);
    expect(plan.added, isEmpty);
    expect(plan.toSave, isEmpty);
  });

  test('最大持玉が片方だけ無い記録は競合として扱わない', () {
    // saiwaichouは一覧に最大持玉が無いため、保存済み側がnullで
    // 取り込み側に値があるだけでは「食い違い」として扱わない。
    final plan = service.plan(
      [sample(rack: 101, maxHold: 2000).toJson()],
      [sample(rack: 101, maxHold: null)],
    );
    expect(plan.conflicts, isEmpty);
    expect(plan.unchanged.length, 1);
  });

  test('数値が一致しグラフだけ追加できる場合はそのまま取り込む', () {
    const graph = GraphMeasurement(
      baselineY: 100,
      peakY: 40,
      troughY: 140,
      endY: 60,
    );
    final plan = service.plan(
      [sample(rack: 101, graph: graph).toJson()],
      [sample(rack: 101)],
    );
    expect(plan.graphOnly.length, 1);
    expect(plan.toSave.length, 1);
  });

  test('設定情報だけが新しい場合は安全に追加し、異なる設定情報は競合にする', () {
    final withSetting = service.plan(
      [sample(rack: 101, confirmedSetting: '5以上').toJson()],
      [sample(rack: 101)],
    );
    expect(withSetting.settingOnly.single.confirmedSetting, '5以上');
    expect(withSetting.conflicts, isEmpty);
    final conflict = service.plan(
      [sample(rack: 101, confirmedSetting: '6').toJson()],
      [sample(rack: 101, confirmedSetting: '5以上')],
    );
    expect(conflict.conflicts, hasLength(1));
  });

  test('対象外の店舗・区分・壊れた行はスキップされる', () {
    final plan = service.plan([
      {...sample(rack: 101).toJson(), 'kind_code': 10},
      {...sample(rack: 102).toJson(), 'store': 'otherstore'},
      {...sample(rack: 103).toJson(), 'confirmed_setting': '3以上'},
      {'not': 'valid'},
    ], []);
    expect(plan.skipped, 4);
    expect(plan.added, isEmpty);
  });

  test('planFromJson はPC版と同じバックアップ形式を読み取れる', () {
    final json = jsonEncode({
      'format': 'database-backup',
      'version': 1,
      'source': 'pc',
      'records': [sample(rack: 303).toJson()],
    });
    final plan = service.planFromJson(json, []);
    expect(plan.added.single.rack, 303);
  });
}
