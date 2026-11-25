import 'dart:convert';

import 'package:database_android/calendar_day_net.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

/// 2026-11-26 点検①②④（DATABASE_REVIEW_20261126.md）：個人用閲覧ページが端末の履歴を失わないこと。
/// ① 手動の読み込みでPCの分けた書き出しの1つ（見出し・1店のファイル）を選んだら、保存の前に止める。
/// ② Driveの更新で端末の本文が壊れていたら、初回と同じ扱い（新着だけを保存）にしない。
/// ④ 差枚表の目印は、書き出しの時刻と件数が同じ別の本体を取り違えない。

Map<String, dynamic> row(String store, String day, int rack) => {
  'store': store,
  'day': day,
  'machine': 'テスト機種',
  'rack': rack,
  'games': 5000,
  'bb': 20,
  'rb': 10,
};

const exported = '2026-11-26T08:00:00+09:00';

/// PCの書き出し（database/core.py の export_viewer）と同じ外枠。
Map<String, dynamic> pcViewer(
  List<Map<String, dynamic>> records, {
  Map<String, dynamic> extra = const {},
}) => {
  'format': 'database-backup',
  'version': 1,
  'exported_at': exported,
  'source': 'pc-viewer',
  'days': 60,
  ...extra,
  'records': records,
};

/// 閲覧ページのファイル選択（web/index.html の pick → finish）が渡す形：外枠は `header` に入る。
String asPicked(Map<String, dynamic> doc) {
  final records = doc['records'];
  final header = {...doc}..remove('records');
  return jsonEncode({
    'header': header,
    'records': records,
    'candidates': const [],
    'date_events': doc['date_events'] ?? const [],
    'file': 'picked.json',
  });
}

void main() {
  final both = [
    row('nagamachiminami', '2026-07-01', 101),
    row('saiwaichou', '2026-11-25', 202),
  ];
  final previous = ViewerData.parse(jsonEncode(pcViewer(both)));

  group('① PCの分けた書き出しの1つは読み込まない', () {
    test('見出しのファイル（split_stores、台0件）', () {
      final header = pcViewer(
        const [],
        extra: {
          'split_stores': ['nagamachiminami', 'saiwaichou'],
          'date_events': const [],
        },
      );
      for (final text in [asPicked(header), jsonEncode(header)]) {
        expect(
          () => ViewerData.preparePicked(text, previous),
          throwsA(
            isA<PartialViewerFile>().having(
              (e) => e.message,
              'message',
              allOf(
                contains('見出しのファイル'),
                contains('database-backup-auto.json'),
              ),
            ),
          ),
        );
      }
    });

    test('1店のファイル（source=pc-viewer、stores）', () {
      final one = pcViewer(
        [row('saiwaichou', '2026-11-25', 202)],
        extra: {
          'stores': ['saiwaichou'],
          'record_deletions': const [],
        },
      );
      for (final text in [asPicked(one), jsonEncode(one)]) {
        expect(
          () => ViewerData.preparePicked(text, previous),
          throwsA(
            isA<PartialViewerFile>().having(
              (e) => e.toString(),
              'message',
              allOf(contains('1店分'), contains('幸町の台だけ')),
            ),
          ),
        );
      }
    });

    test('旧形式の完全な閲覧用・バックアップは今までどおり読む', () {
      for (final doc in [
        pcViewer(both),
        {...pcViewer(both), 'source': 'pc'},
        // 1店のファイルと見なすのは PCの閲覧用（source=pc-viewer）の stores だけ。
        {...pcViewer(both), 'source': 'pc', 'stores': 'x'},
      ]) {
        final picked = ViewerData.preparePicked(asPicked(doc), null);
        expect(picked.data.records.length, 2);
        expect(ViewerData.partialViewerFile(doc), isNull);
      }
    });
  });

  group('② Driveの更新：端末の本文の初回・壊れた本文を区別する', () {
    final fresh = jsonEncode(pcViewer([row('saiwaichou', '2026-11-26', 202)]))
        .replaceFirst(exported, '2026-11-27T08:00:00+09:00');

    test('初回（本文が無い・空）は、Driveの内容をそのまま使う', () {
      for (final stored in [null, '']) {
        final merged = ViewerData.prepareMerge(stored, fresh);
        expect(merged.data.records.length, 1);
        expect(merged.text, fresh);
      }
    });

    test('壊れた本文（JSONでない・途中で切れた・記録の一覧が無い）は止める', () {
      for (final stored in [
        '{"records":[',
        'not json',
        jsonEncode({'header': {}}),
        jsonEncode([1, 2]),
      ]) {
        expect(
          () => ViewerData.prepareMerge(stored, fresh),
          throwsA(isA<StoredBodyUnreadable>()),
          reason: stored,
        );
      }
    });

    test('読める本文なら、端末だけにあった古い日（7/1）を残して合わせる', () {
      final stored = jsonEncode(pcViewer(both));
      final merged = ViewerData.prepareMerge(stored, fresh);
      final days = {for (final r in merged.data.records) '${r.store}|${r.day}'};
      expect(days, contains('nagamachiminami|2026-07-01'));
      expect(days, contains('saiwaichou|2026-11-26'));
    });
  });

  group('④ 差枚表の目印は本体ごと', () {
    test('時刻・件数が同じ別の本体は目印が違う', () {
      final a = ViewerData.parse(asPicked(pcViewer(both)));
      final b = ViewerData.parse(
        asPicked(
          pcViewer([
            row('saiwaichou', '2026-07-01', 101),
            row('nagamachiminami', '2026-11-25', 202),
          ]),
        ),
      );
      expect(a.exportedAtText, b.exportedAtText);
      expect(a.records.length, b.records.length);
      expect(dayNetStamp(a, 'id-a'), isNot(dayNetStamp(b, 'id-b')));
      expect(dayNetStamp(a, 'id-a'), dayNetStamp(a, 'id-a'));
      expect(dayNetStamp(b, null), isNull);
    });
  });
}
