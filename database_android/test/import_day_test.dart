import 'package:database_android/import_day.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('取り込み日の選択肢は、営業日の今日から7日前まで', () {
    final days = recentImportDays('2026-10-03');
    expect(
      (days.first, days[1], days.last, days.length),
      ('2026-10-03', '2026-10-02', '2026-09-27', 7),
    );
  });

  test('機種の表のURLに target_date を付ける（機種名の符号化は変えない）', () {
    const url =
        'https://meruhenworld.pt.teramoba2.com/nagamachiminami/standlist_slot/?kind_code=21&machine_name=L%2520%25E7%2594%25B2';
    expect(withTargetDate(url, '2026-10-03'), '$url&target_date=2026-10-03');
    expect(
      withTargetDate('$url&target_date=2026-10-04', '2026-10-03'),
      '$url&target_date=2026-10-03',
    );
    expect(
      withTargetDate('$url#x', '2026-10-03'),
      '$url&target_date=2026-10-03#x',
    );
    expect(
      withTargetDate('https://example.test/a', '2026-10-03'),
      'https://example.test/a?target_date=2026-10-03',
    );
  });

  test('取り込み日と違う日は理由を返し、指定なし・同じ日・日付不明は通す', () {
    expect(targetDayMismatch(null, '2026-10-04'), isNull);
    expect(targetDayMismatch('2026-10-03', '2026-10-03'), isNull);
    expect(targetDayMismatch('2026-10-03', null), isNull);
    expect(
      targetDayMismatch('2026-10-03', '2026-10-04'),
      contains('取り込み日は2026-10-03ですが、表示中は2026-10-04'),
    );
  });

  test('取り込みを始めた時刻が基準。営業が終わった日（翌日の午前2時以降）で頭打ち', () {
    expect(staleCaptureCutoff('2026-10-03', null), isNull);
    expect(
      staleCaptureCutoff(
        '2026-10-03',
        DateTime.parse('2026-10-03T22:00:00+09:00'),
      ),
      DateTime.parse('2026-10-03T19:00:00+09:00').millisecondsSinceEpoch,
    );
    expect(
      staleCaptureCutoff(
        '2026-10-03',
        DateTime.parse('2026-10-05T10:00:00+09:00'),
      ),
      DateTime.parse('2026-10-03T23:00:00+09:00').millisecondsSinceEpoch,
    );
  });

  test('手動のときは、済ませた機種の次から探し、先が無いときだけ最初へ戻る', () {
    const names = ['甲機', '乙機', 'L無職転生　NM', '丁機'];
    // 印が無い・一覧に無い：最初から1回だけ。
    for (final unknown in [null, '不明']) {
      final passes = machineSearchPasses(names, unknown);
      expect(passes, hasLength(1));
      expect(passes.single.$1, [0, 1, 2, 3]);
      expect(passes.single.$2, '');
    }
    // 乙機のあと：丙（無職転生）・丁から。次に、最初からの見直し（案内付き）。
    final after = machineSearchPasses(names, '乙機');
    expect(after[0].$1, [2, 3]);
    expect(after[0].$2, '');
    expect(after[1].$1, [0, 1, 2, 3]);
    expect(after[1].$2, contains('最後まで来たので'));
    // 空白の違い（全角・半角・連続）は同じ機種として探す。
    expect(machineSearchPasses(names, 'L無職転生 NM')[0].$1, [3]);
    // 一覧の最後の機種のあとは、先に探す機種が無いので、すぐ最初からの見直しになる。
    final last = machineSearchPasses(names, '丁機');
    expect(last[0].$1, isEmpty);
    expect(last[1].$1, [0, 1, 2, 3]);
  });

  test('グラフが残る機種も未取込の機種も、一覧の並び（選んだ向き）の順に選ぶ', () {
    // 2026-10-06：下から始めても、上に取りかけの機種があると、下の機種の次にいきなり上へ飛んでいた。
    // 一覧 [甲, 乙, 丙, 丁]：甲＝表は保存済みでグラフ1/3、乙・丙＝未取込、丁＝済み。
    final statuses = <Map<String, int>?>[
      {'done': 1, 'total': 3},
      null,
      null,
      {'done': 3, 'total': 3},
    ];
    int? firstOf(List<int> order) {
      for (final i in order) {
        if (machineNextStep(statuses[i], listedCount: 3, stale: false) !=
            null) {
          return i;
        }
      }
      return null;
    }

    expect(firstOf([3, 2, 1, 0]), 2, reason: '下から：丁の次は丙（上の甲へ飛ばない）');
    expect(firstOf([0, 1, 2, 3]), 0, reason: '上から：甲のグラフの続き');
    expect(
      machineNextStep(statuses[0], listedCount: 3, stale: false),
      'graphs',
    );
    expect(machineNextStep(null, listedCount: 3, stale: false), 'table');
    expect(machineNextStep(statuses[3], listedCount: 3, stale: false), isNull);
    expect(
      machineNextStep(statuses[3], listedCount: 4, stale: false),
      'table',
      reason: '台数が増えた',
    );
    expect(
      machineNextStep(statuses[3], listedCount: 2, stale: false),
      isNull,
      reason: '減台は取り直さない',
    );
    expect(
      machineNextStep(statuses[0], listedCount: 3, stale: true),
      'table',
      reason: '前に取った表のまま',
    );
  });
}
