import 'dart:convert';
import 'dart:io';

import 'package:database_android/calendar_day_page.dart';
import 'package:database_android/daily_net_page.dart';
import 'package:database_android/date_events.dart';
import 'package:database_android/event_calendar_page.dart';
import 'package:database_android/main.dart';
import 'package:database_android/models.dart';
import 'package:database_android/pscube_viewer_data.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/real_database.dart';

/// イベントカレンダー（EVENT_CALENDAR.md、2026-10-07）。PC `tests/test_event_calendar.py` と同じ規則。
DateEvent ev(String name, [String? at, String day = '2026-10-10']) =>
    DateEvent(store: 'nagamachiminami', day: day, name: name, updatedAt: at);

void main() {
  group('形式', () {
    test('時刻の無い以前のイベント・時刻つき・消した印を読み書きする', () {
      final legacy = DateEvent.tryFromJson({
        'store': 'nagamachiminami',
        'day': '2026-09-14',
        'name': '4台構成',
      })!;
      expect((legacy.updatedAt, legacy.removed), (null, false));
      expect(legacy.toJson().containsKey('updated_at'), isFalse);
      final removed = DateEvent.tryFromJson({
        'store': 'saiwaichou',
        'day': '2026-10-10',
        'name': null,
        'updated_at': '2026-10-07T13:00:00.000Z',
      })!;
      expect(removed.removed, isTrue);
      expect(removed.toJson()['name'], isNull);
      expect(
        DateEvent.tryFromJson({
          'store': 'saiwaichou',
          'day': '2026-10-10',
          'name': null,
        }),
        isNull,
        reason: '時刻の無い消した印は読まない',
      );
      expect(
        DateEvent.tryFromJson({
          'store': 'saiwaichou',
          'day': '2026-10-10',
          'name': '華の日',
          'updated_at': '2026-10-07T22:00:00',
        }),
        isNull,
        reason: '時差の無い時刻は読まない',
      );
    });

    test('前日までに入力＝その日の02:00（日本時間）より前', () {
      expect(ev('華の日', '2026-10-10T01:59:59+09:00').enteredInAdvance, isTrue);
      expect(ev('華の日', '2026-10-09T16:59:59Z').enteredInAdvance, isTrue);
      expect(ev('華の日', '2026-10-10T02:00:00+09:00').enteredInAdvance, isFalse);
      expect(ev('華の日').enteredInAdvance, isFalse);
    });

    test('入力時刻は前の時刻より必ず後', () {
      expect(
        eventStamp(DateTime.utc(2026, 10, 7, 12), '2026-10-07T22:00:00+09:00'),
        '2026-10-07T13:00:00.001Z',
      );
      expect(
        eventStamp(DateTime.utc(2026, 10, 7, 14), null),
        '2026-10-07T14:00:00.000Z',
      );
    });
  });

  group('統合（PC core.merge_date_events と同じ）', () {
    Map<String, DateEvent> one(DateEvent e) => {e.key: e};
    test('両方に時刻：新しい方、同じなら読み込んだ方', () {
      var r = mergeDateEvents(one(ev('A', '2026-10-07T22:00:00+09:00')), [
        ev('B', '2026-10-07T13:00:01Z'),
      ]);
      expect((r.events.values.single.name, r.changed), ('B', 1));
      r = mergeDateEvents(one(ev('A', '2026-10-07T22:00:00+09:00')), [
        ev('B', '2026-10-07T12:59:59Z'),
      ]);
      expect((r.events.values.single.name, r.changed), ('A', 0));
      r = mergeDateEvents(one(ev('A', '2026-10-07T22:00:00+09:00')), [
        ev('B', '2026-10-07T13:00:00Z'),
      ]);
      expect(r.events.values.single.name, 'B');
    });
    test('時刻のある方が、時刻の無い方に勝つ', () {
      expect(
        mergeDateEvents(one(ev('古い')), [
          ev('新', '2026-10-07T22:00:00+09:00'),
        ]).events.values.single.name,
        '新',
      );
      expect(
        mergeDateEvents(one(ev('新', '2026-10-07T22:00:00+09:00')), [
          ev('古い'),
        ]).events.values.single.name,
        '新',
      );
    });
    test('どちらも時刻なし：手元を残し不一致を数える', () {
      final r = mergeDateEvents(one(ev('A')), [ev('B')]);
      expect(
        (r.events.values.single.name, r.changed, r.conflicts),
        ('A', 0, 1),
      );
    });
    test('消した印は古いバックアップで戻らない', () {
      final r = mergeDateEvents(one(ev('', '2026-10-08T09:00:00+09:00')), [
        ev('半列'),
        ev('半列', '2026-10-07T22:00:00+09:00'),
      ]);
      expect((r.events.values.single.removed, r.changed), (true, 0));
    });
  });

  group('Android：入力', () {
    test('先の日・期間に入れる、同じ名前は時刻を変えない、消すと印が残り画面には出ない', () async {
      final path = await newDatabasePath();
      final db = realDatabase(path);
      final c = AppController(database: db);
      await c.initialize();
      await c.setDateEventDays(
        store: 'saiwaichou',
        days: ['2026-12-30', '2026-12-31'],
        name: ' 華の日 ',
        now: DateTime.utc(2026, 10, 7, 13),
      );
      expect(c.dateEventFor('saiwaichou', '2026-12-31')!.name, '華の日');
      expect(
        c.dateEventFor('saiwaichou', '2026-12-31')!.updatedAt,
        '2026-10-07T13:00:00.000Z',
      );
      await c.setDateEventDays(
        store: 'saiwaichou',
        days: ['2026-12-31'],
        name: '華の日',
        now: DateTime.utc(2026, 12, 31, 12),
      );
      expect(
        c.dateEventFor('saiwaichou', '2026-12-31')!.updatedAt,
        '2026-10-07T13:00:00.000Z',
        reason: '前日までに入力した印を消さない',
      );
      await c.setDateEvent(store: 'saiwaichou', day: '2026-12-30', name: null);
      expect(c.dateEventFor('saiwaichou', '2026-12-30'), isNull);
      expect(c.dateEvents['saiwaichou|2026-12-30']!.removed, isTrue);
      expect(c.dateEventNamesFor('saiwaichou').take(5), dateEventOptions);
      // 開き直しても、時刻と消した印が残っている。
      final again = AppController(database: db);
      await again.initialize();
      expect(again.dateEvents['saiwaichou|2026-12-30']!.removed, isTrue);
      expect(
        again.dateEventFor('saiwaichou', '2026-12-31')!.updatedAt,
        '2026-10-07T13:00:00.000Z',
      );
      await db.close();
    });

    test('閲覧ページのイベントだけのファイルを取り込み、新しい方が残る', () async {
      final db = realDatabase(await newDatabasePath());
      final c = AppController(database: db);
      await c.initialize();
      await c.setDateEventDays(
        store: 'saiwaichou',
        days: ['2026-10-10'],
        name: '仮',
        now: DateTime.utc(2026, 10, 7, 11),
      );
      final dir = await Directory.systemTemp.createTemp('event_import');
      final file = File('${dir.path}/database-backup-browser-events.json');
      await file.writeAsString(
        ViewerData.eventsOnlyBackup([
          const DateEvent(
            store: 'saiwaichou',
            day: '2026-10-10',
            name: '華の日',
            updatedAt: '2026-10-07T13:10:00.000Z',
          ),
          ev('', '2026-10-07T13:10:00.000Z', '2026-09-15'),
        ], DateTime.utc(2026, 10, 7, 13, 11)),
      );
      final result = await c.importBackup(file);
      expect(result.dateEventsAdded, 2);
      expect(c.dateEventFor('saiwaichou', '2026-10-10')!.name, '華の日');
      expect(
        c.dateEventFor('nagamachiminami', '2026-09-15'),
        isNull,
        reason: '時刻の無い初期のイベントは、時刻つきの消した印で消える',
      );
      await db.close();
    });
  });

  group('閲覧ページ', () {
    String data({List<Map<String, Object?>> events = const []}) => jsonEncode({
      'header': {'format': 'database-backup', 'source': 'pc'},
      'records': [
        {
          'store': 'nagamachiminami',
          'day': '2026-10-05',
          'machine': '北斗',
          'rack': 1,
          'games': 3000,
          'bb': 10,
          'rb': 5,
        },
      ],
      'date_events': events,
    });

    test('入れる・消す：入力時刻を残し、消した印は画面に出さない', () {
      final now = DateTime.utc(2026, 10, 7, 13);
      final text = ViewerData.setEvents(
        data(),
        'nagamachiminami',
        ['2026-10-20', '2026-10-21'],
        '超探す楽しみ',
        now,
      );
      final parsed = ViewerData.parse(text);
      expect(
        parsed.dateEventFor('nagamachiminami', '2026-10-20')!.updatedAt,
        '2026-10-07T13:00:00.000Z',
      );
      expect(
        identical(
          ViewerData.setEvents(
            text,
            'nagamachiminami',
            ['2026-10-20'],
            '超探す楽しみ',
            now,
          ),
          text,
        ),
        isTrue,
        reason: '変わらなければ保存し直さない',
      );
      final removed = ViewerData.setEvents(
        text,
        'nagamachiminami',
        ['2026-10-20'],
        null,
        now.add(const Duration(minutes: 1)),
      );
      final again = ViewerData.parse(removed);
      expect(again.dateEventFor('nagamachiminami', '2026-10-20'), isNull);
      expect(again.dateEvents['nagamachiminami|2026-10-20']!.removed, isTrue);
    });

    test('Driveの自動読み込み：端末で入れた新しいイベントを残し、PCの新しい入力も入る', () {
      final stored = data(
        events: [
          {
            'store': 'nagamachiminami',
            'day': '2026-10-20',
            'name': '端末で入力',
            'updated_at': '2026-10-07T13:00:00.000Z',
          },
          {
            'store': 'nagamachiminami',
            'day': '2026-10-06',
            'name': 'PCで外した古いイベント',
          },
        ],
      );
      final fresh = data(
        events: [
          {
            'store': 'nagamachiminami',
            'day': '2026-10-21',
            'name': 'PCで入力',
            'updated_at': '2026-10-07T12:00:00+09:00',
          },
        ],
      );
      final merged = ViewerData.parse(ViewerData.merge(stored, fresh).text);
      expect(
        merged.dateEventFor('nagamachiminami', '2026-10-20')!.name,
        '端末で入力',
      );
      expect(
        merged.dateEventFor('nagamachiminami', '2026-10-21')!.name,
        'PCで入力',
      );
      expect(
        merged.dateEventFor('nagamachiminami', '2026-10-06'),
        isNull,
        reason: '時刻の無いイベントは、Driveの対象期間ではDriveの内容に合わせる',
      );
    });

    test('端末の内容の方が新しくて置き換えないときも、Driveの時刻つきの入力だけは入る', () {
      String withHeader(String text, String at) {
        final doc = Map<String, dynamic>.from(jsonDecode(text) as Map);
        return jsonEncode({
          ...doc,
          'header': {'format': 'database-backup', 'exported_at': at},
        });
      }

      final stored = withHeader(data(), '2026-10-07T23:00:00+09:00');
      final fresh = withHeader(
        data(
          events: [
            {
              'store': 'nagamachiminami',
              'day': '2026-10-22',
              'name': 'PCで入力',
              'updated_at': '2026-10-07T12:00:00+09:00',
            },
            {'store': 'nagamachiminami', 'day': '2026-09-01', 'name': '時刻なし'},
          ],
        ),
        '2026-10-07T20:00:00+09:00',
      );
      final result = ViewerData.merge(stored, fresh);
      expect(result.note, contains('置き換えていません'));
      final merged = ViewerData.parse(result.text);
      expect(
        merged.dateEventFor('nagamachiminami', '2026-10-22')!.name,
        'PCで入力',
      );
      expect(merged.dateEventFor('nagamachiminami', '2026-09-01'), isNull);
    });

    test('イベントだけの書き出し：台の記録は空、消した印と時刻つき', () {
      final events = [
        ev('周年', '2026-10-07T13:00:00.000Z', '2026-10-25'),
        ev('', '2026-10-07T13:01:00.000Z', '2026-10-03'),
      ];
      final doc = jsonDecode(
        ViewerData.eventsOnlyBackup(events, DateTime.utc(2026, 10, 7, 13, 5)),
      ) as Map;
      expect(doc['format'], 'database-backup');
      expect(doc['records'], isEmpty);
      expect(doc['exported_at'], matches(RegExp(r'[+-]\d{2}:\d{2}$')));
      expect(doc['date_events'], [
        {
          'store': 'nagamachiminami',
          'day': '2026-10-03',
          'name': null,
          'updated_at': '2026-10-07T13:01:00.000Z',
        },
        {
          'store': 'nagamachiminami',
          'day': '2026-10-25',
          'name': '周年',
          'updated_at': '2026-10-07T13:00:00.000Z',
        },
      ]);
      expect(
        ViewerData.eventsBackupFileName(DateTime(2026, 10, 7, 22, 5, 9)),
        'database-backup-browser-events-20261007-220509.json',
      );
    });
  });

  group('共有カレンダー（2026-10-08）', () {
    final stored = jsonEncode({
      'header': {
        'format': 'database-backup',
        'exported_at': '2026-10-08T09:00:00+09:00',
      },
      'records': [
        {
          'store': 'nagamachiminami',
          'day': '2026-10-05',
          'machine': '北斗',
          'rack': 1,
          'games': 3000,
          'bb': 10,
          'rb': 5,
        },
      ],
      'date_events': [
        {
          'store': 'nagamachiminami',
          'day': '2026-10-20',
          'name': '端末の新しい入力',
          'updated_at': '2026-10-08T05:00:00.000Z',
        },
      ],
    });

    test('共有ファイルの時刻つきイベントだけを足し、新しい方が残る', () {
      final shared = jsonEncode({
        'format': 'database-events',
        'version': 1,
        'kind': 'meruhen',
        'events': [
          {
            'store': 'nagamachiminami',
            'day': '2026-10-20',
            'name': '古い共有',
            'updated_at': '2026-10-08T04:00:00.000Z',
          },
          {
            'store': 'saiwaichou',
            'day': '2026-10-21',
            'name': 'ほかの端末',
            'updated_at': '2026-10-08T04:00:00.000Z',
          },
        ],
      });
      final merged = ViewerData.parse(
        ViewerData.withSharedEvents(stored, shared)!,
      );
      expect(
        merged.dateEventFor('nagamachiminami', '2026-10-20')!.name,
        '端末の新しい入力',
      );
      expect(merged.dateEventFor('saiwaichou', '2026-10-21')!.name, 'ほかの端末');
      expect(ViewerData.withSharedEvents(stored, '{broken'), isNull);
      expect(
        ViewerData.withSharedEvents(stored, jsonEncode({'error': '見つかりません'})),
        isNull,
        reason: '古いスクリプト・ファイル無しの返事では何も変えない',
      );
      expect(
        ViewerData.withSharedEvents(
          stored,
          jsonEncode({'format': 'database-events', 'events': []}),
        ),
        isNull,
      );
    });

    test('送る中身：入力時刻つきだけ、合言葉は入れない', () {
      final body = jsonDecode(
        ViewerData.sharedEventsBody([
          ev('周年', '2026-10-08T05:00:00.000Z', '2026-10-25'),
          ev('時刻なし', null, '2026-09-14'),
          ev('', '2026-10-08T05:01:00.000Z', '2026-10-03'),
        ]),
      ) as Map;
      expect(body.keys.toSet(), {'file', 'events'});
      expect(body['file'], 'events');
      expect(
        [for (final e in body['events'] as List) e['day']],
        ['2026-10-03', '2026-10-25'],
      );
    });

    test('スクリプトの返事を知らせにする', () {
      expect(ViewerData.sharedResult('{"ok":true,"changed":1}').ok, isTrue);
      final error = ViewerData.sharedResult('{"error":"イベントの形式が不正です。"}');
      expect((error.ok, error.message), (false, 'イベントの形式が不正です。'));
      expect(ViewerData.sharedResult('<html>').message, contains('更新したか確認'));
    });
  });

  group('カレンダー画面', () {
    test('日曜始まりの週、期間の日、＊の付け方', () {
      final weeks = monthWeeks(2026, 10);
      expect(weeks.first.take(4), everyElement(isNull));
      expect(weeks.first[4], DateTime.utc(2026, 10, 1));
      expect(weeks.last.whereType<DateTime>().last, DateTime.utc(2026, 10, 31));
      expect(monthWeeks(2026, 2).length, 4, reason: '2026年2月は日曜始まりで4週');
      expect(eventRangeDays('2026-10-31', '2026-10-29'), [
        '2026-10-29',
        '2026-10-30',
        '2026-10-31',
      ]);
      expect(eventCellLabel(ev('華の日', '2026-10-09T22:00:00+09:00')), '華の日');
      expect(eventCellLabel(ev('華の日', '2026-10-10T12:00:00+09:00')), '華の日＊');
      expect(eventCellLabel(ev('華の日')), '華の日＊');
      expect(eventCellLabel(ev('', '2026-10-10T12:00:00+09:00')), '');
    });

    testWidgets('日を押して入れる・期間でまとめて入れる', (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 852));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final events = <String, DateEvent>{};
      final saved = <(String, List<String>, String?)>[];
      await tester.pumpWidget(
        MaterialApp(
          home: StatefulBuilder(
            builder: (context, setState) => EventCalendarPage(
              stores: storeNames,
              initialStore: 'saiwaichou',
              today: DateTime(2026, 10, 7),
              eventFor: (store, day) => events['$store|$day'],
              namesFor: (_) => dateEventOptions,
              onSave: (store, days, name) async {
                saved.add((store, days, name));
                setState(() {
                  for (final day in days) {
                    events['$store|$day'] = DateEvent(
                      store: store,
                      day: day,
                      name: name ?? '',
                      updatedAt: '2026-10-07T13:00:00.000Z',
                    );
                  }
                });
              },
            ),
          ),
        ),
      );
      expect(find.text('2026年10月'), findsOneWidget);
      await tester.ensureVisible(
        find.byKey(const ValueKey('event-day-2026-10-30')),
      );
      await tester.tap(find.byKey(const ValueKey('event-day-2026-10-30')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '華の日');
      await tester.pump();
      await tester.tap(find.text('保存'));
      await tester.pumpAndSettle();
      expect((saved.single.$1, saved.single.$3), ('saiwaichou', '華の日'));
      expect(saved.single.$2, ['2026-10-30']);
      expect(find.text('華の日'), findsWidgets);
      await tester.ensureVisible(find.text('期間でまとめて入力'));
      await tester.tap(find.text('期間でまとめて入力'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const ValueKey('event-day-2026-10-20')),
      );
      await tester.tap(find.byKey(const ValueKey('event-day-2026-10-20')));
      await tester.pump();
      await tester.tap(find.byKey(const ValueKey('event-day-2026-10-22')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '半列');
      await tester.pump();
      await tester.tap(find.text('保存'));
      await tester.pumpAndSettle();
      expect(saved.last.$2, ['2026-10-20', '2026-10-21', '2026-10-22']);
      await tester.ensureVisible(find.byTooltip('次の月'));
      await tester.tap(find.byTooltip('次の月'));
      await tester.pumpAndSettle();
      expect(find.text('2026年11月'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('カレンダーの差枚（2026-10-08）', () {
    const base =
        'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/';
    Map<String, Object?> rec(String day, int rack, int? net, {int games = 3000}) => {
      'store': 'c740601',
      'rate': '20',
      'machine': 'マイジャグラーV',
      'rack': rack,
      'day': day,
      'bb': 10,
      'rb': 5,
      'games': games,
      'my': 1000,
      'at_art': 0,
      'net_medals': ?net,
      'observed_at': '2026-10-05T23:00:00+09:00',
      'detail_url': '${base}nc-v06-001.php?cd_dai=$rack#${day.replaceAll('-', '')}',
    };
    Map<String, Object?> doc(List<Map<String, Object?>> records) => {
      'format': 'pscube-viewer',
      'version': 1,
      'machines': [
        {
          'store': 'c740601',
          'rate': '20',
          'machine': 'マイジャグラーV',
          'machine_type': 'normal',
          'expected_count': 4,
          'url': '${base}nc-v05-011.php?cd_ps=2&bai=20',
        },
      ],
      'records': records,
      'date_events': [
        {
          'store': 'c740601',
          'rate': '20',
          'day': '2026-10-06',
          'name': '業火の極',
          'updated_at': '2026-10-05T12:00:00.000Z',
        },
      ],
    };
    const scope = 'pscube:c740601:20';

    test('その日の総差枚：差枚のある台だけ足し、無い台・数値異常の台は数えない', () {
      final records = pscubeViewerRecords(
        doc([
          rec('2026-10-04', 1, 1200),
          rec('2026-10-04', 2, -300),
          rec('2026-10-04', 3, null),
          rec('2026-10-04', 4, 99999, games: 88888888),
          rec('2026-10-05', 1, null),
        ]),
      );
      final lookup = dailyNetLookup(records);
      final day = lookup(scope, '2026-10-04')!;
      expect((day.total, day.captured, day.racks), (900, 2, 3));
      expect(dayNetCellLabel(day), '+900');
      expect(lookup(scope, '2026-10-05')!.total, isNull, reason: '差枚が1台も無い日は0にしない');
      expect(dayNetCellLabel(lookup(scope, '2026-10-05')), isNull);
      expect(lookup(scope, '2026-10-20'), isNull, reason: '記録の無い日');
      expect(lookup('nagamachiminami', '2026-10-04'), isNull, reason: '別の店は混ぜない');
      expect(
        dayNetCellLabel(
          const DayNet(day: 'x', total: -1500, captured: 2, racks: 2, needsCheck: 1),
        ),
        '-1,500',
        reason: 'マスには※を付けない',
      );
      expect(dailyNetNote('saiwaichou'), contains('推定'));
      expect(dailyNetNote(scope), isNot(contains('推定')));
    });

    test('P’s CUBEのイベントは入力時刻を持ち、前日までの入力は＊が付かない', () {
      final events = pscubeDateEvents(doc(const []));
      final event = events.single.event;
      expect((event.store, event.updatedAt), (scope, '2026-10-05T12:00:00.000Z'));
      expect(eventCellLabel(event), '業火の極');
    });

    for (final width in [320.0, 393.0]) {
      testWidgets('マスに差枚を出す（プラスは青・マイナスは赤、${width.toInt()}px）', (tester) async {
        await tester.binding.setSurfaceSize(Size(width, 900));
        addTearDown(() => tester.binding.setSurfaceSize(null));
        final nets = {
          '2026-10-04': const DayNet(
            day: '2026-10-04',
            total: 138200,
            captured: 20,
            racks: 20,
            needsCheck: 1,
          ),
          '2026-10-05': const DayNet(
            day: '2026-10-05',
            total: -4300,
            captured: 20,
            racks: 20,
          ),
        };
        await tester.pumpWidget(
          MaterialApp(
            home: EventCalendarPage(
              stores: storeNames,
              initialStore: 'nagamachiminami',
              today: DateTime(2026, 10, 8),
              eventFor: (store, day) => day == '2026-10-04'
                  ? ev('半列', '2026-10-03T12:00:00+09:00', '2026-10-04')
                  : null,
              namesFor: (_) => const [],
              onSave: (_, _, _) async {},
              netFor: (store, day) => store == 'nagamachiminami' ? nets[day] : null,
              netNote: dailyNetNote('nagamachiminami'),
            ),
          ),
        );
        final plus = tester.widget<Text>(
          find.byKey(const ValueKey('event-net-2026-10-04')),
        );
        expect(plus.data, '+138,200');
        expect(plus.style!.color, AppColors.linkBlue);
        final minus = tester.widget<Text>(
          find.byKey(const ValueKey('event-net-2026-10-05')),
        );
        expect(minus.data, '-4,300');
        expect(minus.style!.color, const Color(0xFFC62828));
        expect(find.byKey(const ValueKey('event-net-2026-10-06')), findsNothing);
        expect(find.text('半列'), findsOneWidget);
        expect(find.textContaining('推定'), findsWidgets);
        expect(tester.takeException(), isNull, reason: '狭い画面でもはみ出さない');
      });
    }
  });

  group('日付を押したときのTOP10・強かった機種5選（2026-10-09）', () {
    const base =
        'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/';
    const scope = 'pscube:c740601:20';
    const day = '2026-10-04';
    // 機種Aは5台、機種Bは2台、機種Cは1台（5選に入らない）。
    final racks = <(String, int, int?, int)>[
      ('機種A', 1, 1200, 3000),
      ('機種A', 2, -300, 4000),
      ('機種A', 3, null, 5000),
      ('機種A', 4, 800, 2000),
      ('機種A', 5, 800, 2500),
      ('機種B', 11, 50, 9000),
      ('機種B', 12, 60, 8000),
      ('機種C', 21, 9999, 12000),
      ('機種B', 13, 70000, 88888888),
    ];
    for (var i = 30; i < 40; i++) {
      racks.add(('機種A', i, -i, 1000));
    }
    List<SlotRecord> records() => pscubeViewerRecords({
      'format': 'pscube-viewer',
      'version': 1,
      'machines': [
        for (final m in ['機種A', '機種B', '機種C'])
          {
            'store': 'c740601',
            'rate': '20',
            'machine': m,
            'machine_type': 'normal',
            'expected_count': 20,
            'url': '${base}nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=$m',
          },
      ],
      'records': [
        for (final (machine, rack, net, games) in racks)
          {
            'store': 'c740601',
            'rate': '20',
            'machine': machine,
            'rack': rack,
            'day': day,
            'bb': 10,
            'rb': 5,
            'games': games,
            'my': 1000,
            'at_art': 0,
            'net_medals': ?net,
            'observed_at': '2026-10-05T23:00:00+09:00',
            'detail_url': '${base}nc-v06-001.php?cd_dai=$rack#20261004',
          },
      ],
    });

    test('TOP10は差枚の多い順（同じ差枚は回転数の多い方）、5選は2台以上の機種の平均回転数', () {
      final summary = calendarDaySummary(records());
      expect(summary.top.map((r) => r.rack).take(5), [21, 1, 5, 4, 12]);
      expect(summary.top.length, 10);
      expect(summary.top.any((r) => r.rack == 13), isFalse, reason: '数値異常の台は入れない');
      expect(summary.top.any((r) => r.rack == 3), isFalse, reason: '差枚の無い台は入れない');
      expect(
        summary.machines.map((m) => (m.machine, m.racks, m.average)),
        [('機種B', 2, 8500), ('機種A', 15, 1767)],
        reason: '1台だけの機種Cは入れない、数値異常の台は数えない',
      );
    });

    testWidgets('記録のある日はまとめを開き、そこからイベント編集・台の詳細へ。先の日は入力', (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 852));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final all = records();
      final events = <String, DateEvent>{};
      final opened = <int>[];
      await tester.pumpWidget(
        MaterialApp(
          home: StatefulBuilder(
            builder: (context, setState) => EventCalendarPage(
              stores: const {scope: 'P’s CUBE（20スロ）'},
              initialStore: scope,
              today: DateTime(2026, 10, 9),
              eventFor: (store, d) => events['$store|$d'],
              namesFor: (_) => const [],
              onSave: (store, days, name) async => setState(() {
                for (final d in days) {
                  events['$store|$d'] = DateEvent(
                    store: store,
                    day: d,
                    name: name ?? '',
                    updatedAt: '2026-10-03T12:00:00.000Z',
                  );
                }
              }),
              netFor: dailyNetLookup(all),
              recordsFor: (store, d) => [
                for (final r in all)
                  if (r.store == store && r.day == d) r,
              ],
              onOpenRecord: (r) => opened.add(r.rack),
            ),
          ),
        ),
      );
      await tester.tap(find.byKey(const ValueKey('event-day-$day')));
      await tester.pumpAndSettle();
      expect(find.text('TOP10（差枚の多い順）'), findsOneWidget);
      expect(find.text('21番　機種C'), findsOneWidget);
      expect(find.text('イベント：なし'), findsOneWidget);
      await tester.tap(find.text('イベントを編集'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '華の日');
      await tester.pump();
      await tester.tap(find.text('保存'));
      await tester.pumpAndSettle();
      expect(find.text('イベント：華の日'), findsOneWidget, reason: '編集した名前がすぐ出る');
      await tester.tap(find.byKey(const ValueKey('calendar-top-21')));
      await tester.pump();
      expect(opened, [21]);
      await tester.scrollUntilVisible(
        find.text('8,500G（2台）'),
        300,
        scrollable: find.byType(Scrollable).last,
      );
      expect(find.text('強かった機種5選（1台あたりの平均回転数）'), findsOneWidget);
      expect(find.text('1,767G（15台）'), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('華の日'), findsOneWidget, reason: 'カレンダーにも出る');
      // 記録の無い先の日は、今までどおりイベント名の入力。
      await tester.ensureVisible(find.byKey(const ValueKey('event-day-2026-10-30')));
      await tester.tap(find.byKey(const ValueKey('event-day-2026-10-30')));
      await tester.pumpAndSettle();
      expect(find.byType(TextField), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}
