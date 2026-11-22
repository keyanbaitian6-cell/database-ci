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

  test('数値が同じでも、新しい差枚（ジャグラーオンライン）と🌈は取り込み、古いものでは戻さない（2026-11-22）', () {
    SlotRecord withExtra(Map<String, Object?> extra) =>
        sample(rack: 101).copyWith(extra: extra);
    const jo = {
      'jo_net': 1500,
      'jo_bb': 7,
      'jo_captured_at': '2026-09-14T01:00:00+09:00',
    };
    // 手元に差枚が無い：足す。
    final added = service.plan([withExtra(jo).toJson()], [sample(rack: 101)]);
    expect(added.extraOnly.single.extra['jo_net'], 1500);
    expect(added.extraOnly.single.extra['jo_bb'], 7);
    expect(added.unchanged, isEmpty);
    expect(added.toSave, hasLength(1));
    // 新しい時刻の差枚：置き換える。古い時刻の差枚：今のまま。
    final newer = service.plan(
      [
        withExtra({
          ...jo,
          'jo_net': 1800,
          'jo_captured_at': '2026-09-14T02:00:00+09:00',
        }).toJson(),
      ],
      [withExtra(jo)],
    );
    expect(newer.extraOnly.single.extra['jo_net'], 1800);
    final older = service.plan(
      [
        withExtra({
          ...jo,
          'jo_net': 900,
          'jo_captured_at': '2026-09-14T00:00:00+09:00',
        }).toJson(),
      ],
      [withExtra(jo)],
    );
    expect(older.extraOnly, isEmpty);
    expect(older.unchanged, hasLength(1));
    // 🌈：rainbow_at の新しい方。
    const mark = {'rainbow': true, 'rainbow_at': '2026-09-14T03:00:00+09:00'};
    final rainbow = service.plan(
      [withExtra(mark).toJson()],
      [sample(rack: 101)],
    );
    expect(rainbow.extraOnly.single.extra['rainbow'], true);
    final cleared = service.plan(
      [
        withExtra({'rainbow': false, 'rainbow_at': '2026-09-15T00:00:00+09:00'})
            .toJson(),
      ],
      [withExtra(mark)],
    );
    expect(cleared.extraOnly.single.extra['rainbow'], false);
    // 同じ内容は今までどおり「変わらない」。
    final same = service.plan(
      [
        withExtra({...jo, ...mark}).toJson(),
      ],
      [
        withExtra({...jo, ...mark}),
      ],
    );
    expect(same.unchanged, hasLength(1));
    expect(same.toSave, isEmpty);
    // グラフを足すときも、手元の新しい差枚は消さない。
    const graph = GraphMeasurement(
      baselineY: 100,
      peakY: 40,
      troughY: 140,
      endY: 60,
    );
    final graphPlan = service.plan(
      [sample(rack: 101, graph: graph).toJson()],
      [withExtra(jo)],
    );
    expect(graphPlan.graphOnly.single.extra['jo_net'], 1500);
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
