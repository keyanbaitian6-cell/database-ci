import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from core import (AUTO_BACKUP_NAME, list_snapshots, restore_backup, snapshot_backup, snapshot_dir, slump_days, slump_strip_html, captured_note, missing_graphs, next_day_index, provisional_next_day_candidates, reliability_label, signed_index, Store, auto_backup, latest_backup_file, load_settings,
                 save_settings, summary_report, export_backup, history_report, import_backup, plan_backup_import,
                 report, score, spin_score, graph_metrics, measurement_metrics)
from collector import HEADERS, HEADERS_NO_MAX_HOLD, parse_table, check_url, store_from_url, DEFAULT_URL
from screenshot_import import encode_preview_image, find_headers, graph_auto_points, graph_stats_from_tokens
from app import GRAPH_DOWNLOAD_RE, LIST_DOWNLOAD_RE, decode_machine_token
from browser_import import (GraphExtractionError, graph_auto_save_blockers, graph_measurement_result, TableExtractionError, _Bridge, auto_four_points,
                            build_graph_context, build_table_rows, is_allowed_url,
                            normalize_machine_name, render_curve_image, resolve_day)


def row(day='2026-09-13', rack=128):
    return dict(store='nagamachiminami',kind_code=21,day=day,machine='テスト',rack=rack,games=3500,bb=20,rb=10,max_hold=2000)


class ScoringTests(unittest.TestCase):
    def test_machine_name_token_from_extension(self):
        self.assertEqual(decode_machine_token('TOaIpuWbveS5meWlszVMOA'), 'L戦国乙女5L8')
        self.assertIsNone(decode_machine_token('%%%'))
        list_match = LIST_DOWNLOAD_RE.fullmatch(
            'database-list-2026-09-15~ssaiwaichou~mTOaIpuWbveS5meWlszVMOA~-stamp.png')
        self.assertEqual(list_match.groups(), ('2026-09-15', 'saiwaichou', 'TOaIpuWbveS5meWlszVMOA'))
        graph_match = GRAPH_DOWNLOAD_RE.fullmatch(
            'database-graph-rack-285-2026-09-15~snagamachiminami~mTOaIpuWbveS5meWlszVMOA~-stamp.png')
        self.assertEqual(graph_match.groups(), ('285', '2026-09-15', 'nagamachiminami', 'TOaIpuWbveS5meWlszVMOA'))

    def test_boundaries(self):
        self.assertEqual([spin_score(g) for g in (0,499,500,1500,2000,2500,3000,3500,8000)], [None,0,0,0,0,0,0,0,0])  # v7: 回転数は20点満点（500G→4点、3500G→20点）

    def test_graph_linear_ratio_and_quantization(self):
        # 終点5点・維持5点（2026-09-18-v6での配点見直し：設定示唆が主目的のため、
        # 単日の結果でしかない終点・維持の比重を回転数・当たり頻度より下げている）。
        m = graph_metrics('M0,200 L10,100 L20,150',200)
        self.assertEqual((m['positive_score'],m['retention_score']),(10,5))
        n = graph_metrics('M0,400 L10,200 L20,300',400)
        self.assertEqual(n['retention_score'],5)
        self.assertIsNone(graph_metrics('M0,200 L10,100 L20,199.5',200)['positive_score'])
        self.assertEqual(graph_metrics('M0,200 L10,250',200)['retention_score'],0)
        with self.assertRaises(ValueError):
            graph_metrics('M0,200 C1,2 3,4 5,6',200)
        m = measurement_metrics(dict(baseline_y=200,peak_y=100,end_y=150))
        self.assertEqual((m['positive_score'],m['retention_score']),(10,5))

    def test_missing_is_neutral_and_not_a_zero_or_a_probability(self):
        result = score(row(), [])
        self.assertEqual(result['total'], 50)
        self.assertIsNone(result['hits'])
        self.assertIsNone(result['max_hold'])
        self.assertEqual(result['coverage'], 0)
        self.assertEqual((result['missing_low'], result['missing_high']), (0, 100))
        self.assertIsNone(result['confidence'])
        self.assertTrue(result['provisional'])

    def test_zero_events_are_shrunk_in_a_short_session(self):
        r = dict(row(), games=600, bb=0, rb=0, max_hold=0,
                 graph_measurement=dict(baseline_y=100, peak_y=80, end_y=120))
        refs = [dict(row('2026-09-12', i), games=500, bb=1, rb=1, max_hold=1)
                for i in range(20)]
        # 600Gで当たり0・持玉0でも、自動的に0点にはせず中間へ寄せる
        # （v9の相乗平均で 20.13 + 6.71 + 0 + 0 = 26.8。500G以下は採点しない）。
        result = score(r, refs)
        self.assertGreater(result['total'], 20)
        self.assertLess(result['total'], 40)
        self.assertEqual(result['positive'], 0)
        self.assertIn('グラフ終点がゼロ線以下', result['reasons'])

    def test_same_day_fallback_cannot_change_a_historical_score(self):
        r = dict(row(), graph_measurement=dict(baseline_y=200, peak_y=100, end_y=100))
        extra = [dict(row(rack=i), bb=999, max_hold=999999) for i in range(10)]
        before = score(r, [])
        self.assertEqual(before, score(r, extra, extra))
        self.assertEqual(before['total'], 60)
        self.assertEqual(before['coverage'], 20)

    def test_history_survives_and_reference_excludes_today(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db=Store(Path(folder)/'test.db')
            old=row('2026-08-01'); prior=row('2026-09-12'); current=row()
            current['graph']=dict(path='M0,200 L10,100',baseline=200)
            db.save([old,prior,current]); db.save([dict(row(),graph=None)])
            self.assertEqual(len(db.rows()),3)
            self.assertIsNotNone(db.rows('2026-09-13')[0]['graph'])
            self.assertEqual([r['day'] for r in db.references(current)],['2026-09-12'])
            self.assertEqual([r['day'] for r in db.provisional_references(current)],
                             ['2026-09-12', '2026-09-13'])
            self.assertEqual(db.db.execute('SELECT count(*) FROM observations').fetchone()[0],4)
            db.save([dict(row(),games=3600,graph=None)])
            self.assertNotIn('graph',db.rows('2026-09-13')[0])
            with self.assertRaises(ValueError): db.save([dict(row(),kind_code=10)])
            db.close()

    def test_history_report_groups_saved_dates_and_machines(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            first = dict(row('2026-09-12', 128),
                         graph_measurement=dict(baseline_y=200, peak_y=100, end_y=150))
            second = dict(row('2026-09-13', 129), machine='別機種',
                          graph_measurement=dict(baseline_y=200, peak_y=100, end_y=150))
            db.save([first, second])
            output = history_report(db, Path(folder) / 'reports')
            text = output.read_text(encoding='utf-8')
            self.assertIn('2026年9月13日', text)
            self.assertIn('別機種', text)
            self.assertIn('暫定', text)
            self.assertIn('date-filter', text)
            self.assertIn('store-filter', text)
            self.assertIn('補完・注意の理由', text)
            db.close()

    def test_report_handles_a_row_with_no_max_hold_at_all(self):
        # saiwaichou rows can be saved with max_hold=None (its list page has
        # no such column); Store.save() then drops the key entirely rather
        # than keeping an explicit None, so report() must not assume the key
        # exists on every row.
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            saved = dict(row('2026-09-17', 637), store='saiwaichou')
            saved.pop('max_hold')
            db.save([saved])
            self.assertNotIn('max_hold', db.rows('2026-09-17', 'テスト', 'saiwaichou')[0])
            output, results = report(db, '2026-09-17', 'テスト', Path(folder) / 'reports', 'saiwaichou')
            self.assertIsNone(results[0]['score']['max_hold'])
            self.assertIn('—', output.read_text(encoding='utf-8'))
            db.close()

    def test_two_stores_are_saved_and_compared_separately(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            naga = row(rack=100)
            saiwai = dict(naga, store='saiwaichou', max_hold=9999)
            db.save([naga, saiwai])
            self.assertEqual(len(db.rows()), 2)
            self.assertEqual(len(db.rows(store='nagamachiminami')), 1)
            self.assertEqual(len(db.rows(store='saiwaichou')), 1)
            self.assertEqual(db.references(saiwai), [])
            db.close()

    def test_delete_removes_only_the_selected_record(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            first = row('2026-09-12', 128)
            second = row('2026-09-12', 129)
            db.save([first, second])
            self.assertTrue(db.delete('nagamachiminami', '2026-09-12', first['machine'], 128))
            self.assertFalse(db.delete('nagamachiminami', '2026-09-12', first['machine'], 128))
            self.assertEqual([item['rack'] for item in db.rows()], [129])
            db.close()

    def test_confirmed_setting_is_manual_metadata_and_can_be_cleared(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            saved = row('2026-09-12', 128)
            db.save([saved])
            db.set_confirmed_setting('nagamachiminami', saved['day'], saved['machine'], 128, '5以上')
            self.assertEqual(db.rows()[0]['confirmed_setting'], '5以上')
            self.assertEqual(score(saved, []), score(db.rows()[0], []))
            # A following table import must not erase the manually entered note.
            db.save([dict(saved, games=3600)])
            self.assertEqual(db.rows()[0]['confirmed_setting'], '5以上')
            with self.assertRaises(ValueError):
                db.set_confirmed_setting('nagamachiminami', saved['day'], saved['machine'], 128, '設定4')
            db.set_confirmed_setting('nagamachiminami', saved['day'], saved['machine'], 128, None)
            self.assertNotIn('confirmed_setting', db.rows()[0])
            db.close()

    def test_backup_setting_only_is_safe_and_setting_mismatch_needs_review(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            saved = row('2026-09-12', 128)
            db.save([saved])
            incoming = dict(saved, confirmed_setting='4以上')
            plan = plan_backup_import(db, [incoming])
            self.assertEqual(plan['setting_only'], [incoming])
            db.save(plan['setting_only'])
            self.assertEqual(db.rows()[0]['confirmed_setting'], '4以上')
            conflict = plan_backup_import(db, [dict(saved, confirmed_setting='6')])
            self.assertEqual(len(conflict['conflicts']), 1)
            self.assertFalse(plan_backup_import(db, [dict(saved, confirmed_setting='3以上')])['new'])
            self.assertEqual(len(plan_backup_import(db, [dict(saved, confirmed_setting='3以上')])['skipped']), 1)
            db.close()

    def test_legacy_database_is_migrated_with_backup(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            path = Path(folder) / 'legacy.sqlite3'
            legacy = sqlite3.connect(path)
            legacy.execute('CREATE TABLE days (day TEXT, machine TEXT, rack INTEGER, payload TEXT NOT NULL, PRIMARY KEY(day,machine,rack))')
            item = row()
            legacy.execute('INSERT INTO days VALUES(?,?,?,?)',
                           (item['day'], item['machine'], item['rack'], json.dumps(item, ensure_ascii=False)))
            legacy.commit()
            legacy.close()
            db = Store(path)
            columns = [value[1] for value in db.db.execute('PRAGMA table_info(days)')]
            self.assertIn('store', columns)
            self.assertEqual(db.rows(store='nagamachiminami')[0]['rack'], 128)
            self.assertTrue(Path(folder, 'legacy.pre-store-migration.sqlite3').exists())
            db.close()

    def test_parse_real_observed_table_and_wrong_date(self):
        matrix=[HEADERS,['128','61','24','5072','1/59.7','1','2825']]
        url='https://meruhenworld.pt.teramoba2.com/nagamachiminami/standgraph/?rack_no=128&target_date=2026-09-13'
        r=parse_table(matrix,[url],'2026-09-13','L戦国乙女5L8',DEFAULT_URL,'2026/09/13 23:04')[0]
        self.assertEqual((r['games'],r['max_hold']),(5072,2825))
        with self.assertRaises(ValueError): parse_table(matrix,[url],'2026-09-12','x',DEFAULT_URL,'')
        self.assertEqual(check_url(DEFAULT_URL),'L戦国乙女5L8')
        saiwai = DEFAULT_URL.replace('/nagamachiminami/', '/saiwaichou/')
        self.assertEqual(store_from_url(saiwai), 'saiwaichou')
        self.assertEqual(check_url(saiwai), 'L戦国乙女5L8')
        with self.assertRaises(ValueError): check_url(DEFAULT_URL.replace('kind_code=21','kind_code=10'))

    def test_table_without_max_hold_column_is_accepted(self):
        # saiwaichou's own list page never shows 最大持玉 at all; max_hold
        # must come back None rather than the row being rejected outright.
        matrix = [HEADERS_NO_MAX_HOLD, ['637', '7', '3', '1170', '1/117.0', '342']]
        url = 'https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph/?rack_no=637&target_date=2026-09-17'
        r = parse_table(matrix, [url], '2026-09-17', 'L パチスロ北斗の拳AD XR', DEFAULT_URL, '', 'saiwaichou')[0]
        self.assertEqual((r['games'], r['previous_start'], r['max_hold']), (1170, 342, None))
        with self.assertRaises(ValueError):
            parse_table([HEADERS_NO_MAX_HOLD, ['637', '7', '3', '1170', '1/117.0']], [url],
                        '2026-09-17', 'x', DEFAULT_URL, '', 'saiwaichou')

    def test_screenshot_header_detection(self):
        labels=['台番号','BB','RB','総回転数','合成確率','前日最終スタート','最大持玉']
        tokens=[dict(text=t,confidence=.99,x0=i*100,x1=i*100+60,y0=10,y1=30,
                     cx=i*100+30,cy=20) for i,t in enumerate(labels)]
        self.assertEqual(set(find_headers(tokens)),
                         {'rack','bb','rb','games','combined','previous_start','max_hold'})

    def test_graph_stats_are_read_from_current_graph_tooltip(self):
        def token(text, x0, x1, cy):
            return dict(text=text, confidence=.99, x0=x0, x1=x1,
                        y0=cy-6, y1=cy+6, cx=(x0+x1)/2, cy=cy)
        tokens = [
            token('504', 130, 157, 78),
            token('BIG', 61, 89, 92), token('2', 145, 156, 93),
            token('REG', 61, 91, 107), token('1', 145, 155, 107),
            token('ART', 61, 90, 122), token('0', 145, 156, 122),
            token('最大持玉171', 61, 155, 138),
        ]
        self.assertEqual(graph_stats_from_tokens(tokens),
                         {'games': 504, 'bb': 2, 'rb': 1, 'max_hold': 171})

    def test_graph_points_are_detected_from_filled_shape(self):
        image = Image.new('RGB', (300, 200), 'black')
        draw = ImageDraw.Draw(image)
        draw.line((10, 100, 290, 100), fill=(255, 0, 0))
        curve = [(20, 100), (80, 100), (110, 60), (145, 90), (180, 130)]
        draw.polygon(curve + [(180, 160), (20, 160)], fill=(90, 90, 90))
        draw.line(curve, fill=(220, 220, 220), width=2)
        points = graph_auto_points(image, 100)
        self.assertIsNotNone(points)
        self.assertEqual(points[0][1], 100)
        self.assertLessEqual(abs(points[1][1] - 60), 2)
        self.assertLessEqual(abs(points[2][1] - 130), 3)
        self.assertLessEqual(abs(points[3][0] - 180), 2)
        self.assertLessEqual(abs(points[3][1] - 130), 3)

        # A graph can touch the lower edge and then continue horizontally.
        # Its endpoint must not jump to a later isolated time tick.
        lower = Image.new('RGB', (300, 200), 'black')
        draw = ImageDraw.Draw(lower)
        draw.line((10, 100, 290, 100), fill=(255, 0, 0))
        curve = [(20, 100), (80, 100), (105, 160), (180, 160)]
        draw.polygon(curve + [(20, 160)], fill=(90, 90, 90))
        draw.line(curve, fill=(220, 220, 220), width=2)
        draw.line((230, 160, 230, 170), fill=(220, 220, 220), width=2)
        points = graph_auto_points(lower, 100)
        self.assertEqual(points[1][1], 100)
        self.assertLessEqual(abs(points[2][1] - 160), 3)
        self.assertLessEqual(abs(points[3][0] - 180), 2)
        self.assertLessEqual(abs(points[3][1] - 160), 3)

    def test_graph_endpoint_ignores_overlapping_statistics_box(self):
        image = Image.new('RGB', (300, 220), 'black')
        draw = ImageDraw.Draw(image)
        draw.line((10, 110, 290, 110), fill=(255, 0, 0))
        curve = [(20, 110), (70, 125), (120, 70), (180, 55), (230, 65)]
        draw.polygon(curve + [(230, 190), (20, 190)], fill=(90, 90, 90))
        draw.line(curve, fill=(220, 220, 220), width=2)
        # Mimic the site's information panel immediately after the graph.
        draw.rectangle((231, 155, 255, 195), fill=(25, 25, 25),
                       outline=(230, 230, 230), width=2)

        points = graph_auto_points(image, 110)

        self.assertIsNotNone(points)
        self.assertLessEqual(abs(points[1][1] - 55), 3)
        self.assertLessEqual(abs(points[3][0] - 230), 3)
        self.assertLessEqual(abs(points[3][1] - 65), 3)


def _table_payload(rows, target_date='2026-09-13', store='nagamachiminami',
                    machine='L戦国乙女5L8', kind_code='21'):
    matrix = [HEADERS] + [
        [str(r['rack']), str(r['bb']), str(r['rb']), str(r['games']), '1/59.7',
         str(r['previous_start']), str(r['max_hold'])]
        for r in rows
    ]
    links = [
        f'https://meruhenworld.pt.teramoba2.com/{store}/standgraph/'
        f'?rack_no={r["rack"]}&target_date={target_date}'
        for r in rows
    ]
    return dict(matrix=matrix, links=links, store=store, machine=machine,
               target_date=target_date, kind_code=kind_code,
               source_url=DEFAULT_URL, updated_display='2026/09/13 23:04')


class BrowserImportTests(unittest.TestCase):
    def test_target_date_from_url_wins_over_page_text_date(self):
        self.assertEqual(resolve_day(dict(target_date='2026-09-10', day='2026-09-11')), '2026-09-10')
        self.assertEqual(resolve_day(dict(day='2026-09-11')), '2026-09-11')
        with self.assertRaises(ValueError):
            resolve_day({})

    def test_normalize_machine_name_matches_android_rule(self):
        self.assertEqual(normalize_machine_name('L戦国乙女5+L8'), 'L戦国乙女5 L8')
        self.assertEqual(normalize_machine_name('  a   b  '), 'a b')
        self.assertEqual(normalize_machine_name(None), '')

    def test_is_allowed_url_restricts_to_the_two_shops(self):
        self.assertTrue(is_allowed_url('https://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info'))
        self.assertTrue(is_allowed_url('https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph?rack_no=1'))
        self.assertFalse(is_allowed_url('https://example.com/nagamachiminami/rack_info'))
        self.assertFalse(is_allowed_url('https://meruhenworld.pt.teramoba2.com/otherstore/rack_info'))
        self.assertFalse(is_allowed_url('http://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info'))

    def test_next_ungraphed_rack_skips_graphed_racks_and_wraps_around(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db_path = Path(folder) / 'test.db'
            db = Store(db_path)
            db.save([
                dict(row(rack=1), detail_url='https://example.com/rack1'),
                dict(row(rack=2), detail_url='https://example.com/rack2',
                     graph=dict(path='M0,0 L1,1', baseline=0)),
                dict(row(rack=3), detail_url='https://example.com/rack3'),
            ])
            # A second, fully-graphed machine/day, so "all done" can be told
            # apart from "the list was never imported" below -- both leave
            # no target, but need a different message.
            db.save([dict(row(day='2026-09-14', rack=9), machine='完了機',
                          detail_url='https://example.com/rack9',
                          graph=dict(path='M0,0 L1,1', baseline=0))])
            db.close()
            bridge = _Bridge(db_path, folder, 'browser_import.py')
            query = lambda rack, machine='テスト', day='2026-09-13': json.loads(bridge.next_ungraphed_rack(json.dumps(
                dict(store='nagamachiminami', day=day, machine=machine, rack=rack))))
            self.assertEqual(query(None)['rack'], 1)
            self.assertEqual(query(1)['rack'], 3)
            self.assertEqual(query(3)['rack'], 1, 'should wrap back to the first pending rack')

            # An individual rack's own graph page often has no machine_name in
            # its own URL at all -- resolving it from the rack number (as
            # build_graph_context() already does) must still find the target.
            resolved = query(1, machine='')
            self.assertEqual(resolved['rack'], 3)
            unresolvable = query(999, machine='')
            self.assertEqual(unresolvable['reason'], 'unknown_machine')

            no_rows = query(None, machine='存在しない')
            self.assertIsNone(no_rows['url'])
            self.assertEqual(no_rows['reason'], 'no_rows')

            all_done = query(None, machine='完了機', day='2026-09-14')
            # 機種が全部済んだら、機種一覧ページへ案内する（サイト自身のページ）。
            self.assertTrue(all_done['url'].endswith(
                '/nagamachiminami/rack_info_kt/?kind_code=21'
                '#database_next_machine=1&database_day=2026-09-14'))
            self.assertEqual(all_done['reason'], 'all_done')
            self.assertIn('機種一覧', all_done['message'])

            # 旧スクリーンショット由来の記録には、個別台へのURLがない。
            # 未取り込み台が残っていても「全台済み」とは返さない。
            db = Store(db_path)
            db.save([row(day='2026-09-15', rack=10)])
            db.close()
            no_link = query(None, day='2026-09-15')
            self.assertIsNone(no_link['url'])
            self.assertEqual(no_link['rack'], 10)
            self.assertEqual(no_link['reason'], 'no_link')

    def test_machine_list_opens_missing_graph_before_new_machine(self):
        host = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami'
        graph = dict(baseline_x=1, baseline_y=200, peak_x=2, peak_y=100,
                     trough_x=3, trough_y=250, end_x=4, end_y=150)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            db = Store(folder / 'test.db')
            db.save([
                dict(row(rack=101), machine='途中機',
                     detail_url=f'{host}/standgraph/?rack_no=101&target_date=2026-09-13'),
                dict(row(rack=102), machine='途中機',
                     detail_url=f'{host}/standgraph/?rack_no=102&target_date=2026-09-13',
                     graph_measurement=graph),
            ])
            db.close()
            bridge = _Bridge(folder / 'test.db', folder, 'x')
            machines = [
                dict(name='途中機', url=f'{host}/standlist_slot?machine_name=途中機', count=2),
                dict(name='新規機', url=f'{host}/standlist_slot?machine_name=新規機', count=3),
            ]
            query = lambda: json.loads(bridge.next_unimported_machine(json.dumps(
                dict(store='nagamachiminami', day='2026-09-13', machines=machines))))
            pending = query()
            self.assertEqual(pending['reason'], 'graph')
            self.assertIn('rack_no=101', pending['url'])

            db = Store(folder / 'test.db')
            db.save([dict(row(rack=101), machine='途中機',
                          detail_url=f'{host}/standgraph/?rack_no=101&target_date=2026-09-13',
                          graph_measurement=graph)])
            db.close()
            new_machine = query()
            self.assertEqual(new_machine['reason'], 'table')
            self.assertIn('machine_name=新規機', new_machine['url'])

    def test_machine_list_does_not_loop_when_fewer_racks_are_listed_than_saved(self):
        """保存台数が一覧の台数より多いときに、同じ機種へ戻し続けないこと。

        一覧の台数は「今の設置台数」。入替で台数が減った後に前日分を取り込むと、
        保存した台数（前日）が一覧（今日）より多くなる。取り込み直しても台は
        上書きされるだけで消えないため、ここで「台数が変わった」と案内すると
        何度押しても同じ機種に戻され、後ろの機種へ進めなくなっていた。
        """
        host = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami'
        graph = dict(baseline_x=1, baseline_y=200, peak_x=2, peak_y=100,
                     trough_x=3, trough_y=250, end_x=4, end_y=150)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            db = Store(folder / 'test.db')
            db.save([dict(row(rack=r), machine='減台機', graph_measurement=graph,
                          detail_url=f'{host}/standgraph/?rack_no={r}&target_date=2026-09-13')
                     for r in range(101, 111)])     # 10台保存・全台グラフ済み
            db.close()
            bridge = _Bridge(folder / 'test.db', folder, 'x')
            machines = [
                dict(name='減台機', url=f'{host}/standlist_slot?machine_name=減台機', count=8),
                dict(name='後ろの機種', url=f'{host}/standlist_slot?machine_name=後ろの機種', count=3),
            ]
            result = json.loads(bridge.next_unimported_machine(json.dumps(
                dict(store='nagamachiminami', day='2026-09-13', machines=machines))))
            self.assertIn('machine_name=後ろの機種', result['url'] or '')

    def test_machine_list_reimports_when_more_racks_are_listed_than_saved(self):
        """一覧の台数の方が多い（増台・取りこぼし）ときは、取り込み直しを案内する。"""
        host = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami'
        graph = dict(baseline_x=1, baseline_y=200, peak_x=2, peak_y=100,
                     trough_x=3, trough_y=250, end_x=4, end_y=150)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            db = Store(folder / 'test.db')
            db.save([dict(row(rack=r), machine='増台機', graph_measurement=graph)
                     for r in range(101, 109)])     # 8台保存
            db.close()
            bridge = _Bridge(folder / 'test.db', folder, 'x')
            result = json.loads(bridge.next_unimported_machine(json.dumps(dict(
                store='nagamachiminami', day='2026-09-13',
                machines=[dict(name='増台機', url=f'{host}/standlist_slot?machine_name=増台機', count=10)]))))
            self.assertEqual(result['reason'], 'table')
            self.assertIn('設置台数が変わっています', result['message'])

    def test_machine_list_refuses_non_46mai_kind_code(self):
        """低貸し（kind_code=10・5）の機種一覧や機種へは移動しない。"""
        host = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami'
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            bridge = _Bridge(folder / 'test.db', folder, 'x')
            ask = lambda **payload: json.loads(bridge.next_unimported_machine(json.dumps(
                dict(dict(store='nagamachiminami', day='2026-09-13'), **payload))))
            # 画面そのものが低貸しの一覧なら、何も選ばずに理由を伝える
            for kind in ('10', '5'):
                refused = ask(kind_code=kind, machines=[
                    dict(name='低貸し機', url=f'{host}/standlist_slot/?kind_code={kind}&machine_name=x', count=3)])
                self.assertIsNone(refused['url'])
                self.assertIn('1000円46枚', refused['message'])
            # 46枚の一覧に紛れた低貸しの機種は飛ばし、46枚の機種を選ぶ
            mixed = ask(kind_code='21', machines=[
                dict(name='低貸し機', url=f'{host}/standlist_slot/?kind_code=10&machine_name=a', count=3),
                dict(name='46枚機', url=f'{host}/standlist_slot/?kind_code=21&machine_name=b', count=3)])
            self.assertIn('kind_code=21', mixed['url'])
            # 日付確認のための移動でも、低貸しの機種は選ばない
            need_day = ask(day=None, kind_code='21', machines=[
                dict(name='低貸し機', url=f'{host}/standlist_slot/?kind_code=10&machine_name=a', count=3),
                dict(name='46枚機', url=f'{host}/standlist_slot/?kind_code=21&machine_name=b', count=3)])
            self.assertEqual(need_day['reason'], 'need_day')
            self.assertIn('kind_code=21', need_day['url'])

    def test_machine_list_empty_result_says_it_may_still_be_loading(self):
        """一覧が空のとき、壊れたページと決めつけず「表示を待って再度」と案内する。"""
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            bridge = _Bridge(folder / 'test.db', folder, 'x')
            for day in (None, '2026-09-13'):
                result = json.loads(bridge.next_unimported_machine(json.dumps(
                    dict(store='nagamachiminami', day=day, machines=[]))))
                self.assertIsNone(result['url'])
                self.assertIn('表示されるのを待って', result['message'])

    def test_machine_list_header_row_is_not_chosen_as_next_machine(self):
        """実サイトの見出し行「機種名 台数 通常順 ピックアップ順」を機種として選ばない。"""
        host = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami'
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            bridge = _Bridge(folder / 'test.db', folder, 'x')
            machines = [
                dict(name='機種名 台数 通常順 ピックアップ順',
                     url=f'{host}/standlist_slot/?kind_code=21&machine_name=h', count=None),
                dict(name='SBﾆｭｰｷﾝｸﾞﾊﾅﾊﾅVPA-30', url=f'{host}/standlist_slot/?kind_code=21&machine_name=n', count=16),
            ]
            ask = lambda day, items: json.loads(bridge.next_unimported_machine(json.dumps(
                dict(store='nagamachiminami', day=day, kind_code='21', machines=items))))
            self.assertEqual(ask('2026-09-21', machines)['machine'], 'SBﾆｭｰｷﾝｸﾞﾊﾅﾊﾅVPA-30')
            self.assertEqual(ask(None, machines)['machine'], 'SBﾆｭｰｷﾝｸﾞﾊﾅﾊﾅVPA-30')
            # 見出し行しか無ければ、まだ読み込み中として案内する
            self.assertIsNone(ask('2026-09-21', machines[:1])['url'])
            self.assertNotEqual(ask('2026-09-21', machines[:1]).get('reason'), 'table')

    def test_juggler_is_excluded_only_at_nagamachiminami(self):
        """長町南店はジャグラーシリーズのデータを公開していない。半角カナの表記も含めて除外する。"""
        from browser_import import is_excluded_machine
        self.assertTrue(is_excluded_machine('nagamachiminami', 'SﾏｲｼﾞｬｸﾞﾗｰV'))      # 半角カナ
        self.assertTrue(is_excluded_machine('nagamachiminami', 'ファンキージャグラー2'))  # 全角
        self.assertTrue(is_excluded_machine('nagamachiminami', 'S+ｱｲﾑｼﾞｬｸﾞﾗｰEX'))
        self.assertFalse(is_excluded_machine('nagamachiminami', 'L 甲鉄城のｶﾊﾞﾈﾘ 海門決戦 XX'))
        self.assertFalse(is_excluded_machine('saiwaichou', 'SマイジャグラーVKD'))     # 幸町は対象のまま
        # 幸町はブラックボードを公開していない（長町南は対象のまま・別機種は巻き込まない）
        self.assertTrue(is_excluded_machine('saiwaichou', 'Sブラックボード'))
        self.assertTrue(is_excluded_machine('saiwaichou', 'Sﾌﾞﾗｯｸﾎﾞｰﾄﾞ'))
        self.assertFalse(is_excluded_machine('nagamachiminami', 'Sブラックボード'))
        self.assertFalse(is_excluded_machine('nagamachiminami', 'LｽｰﾊﾟｰﾌﾞﾗｯｸｼﾞｬｯｸSLDC'))
        self.assertFalse(is_excluded_machine('saiwaichou', 'LスーパーブラックジャックSLDC'))
        self.assertFalse(is_excluded_machine('nagamachiminami', None))

    def test_machine_list_skips_juggler_at_nagamachiminami(self):
        host = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami'
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            bridge = _Bridge(folder / 'test.db', folder, 'x')
            machines = [
                dict(name='SﾏｲｼﾞｬｸﾞﾗｰV', url=f'{host}/standlist_slot/?kind_code=21&machine_name=j', count=20),
                dict(name='L 普通機', url=f'{host}/standlist_slot/?kind_code=21&machine_name=n', count=5),
            ]
            ask = lambda store, day, items: json.loads(bridge.next_unimported_machine(json.dumps(
                dict(store=store, day=day, kind_code='21', machines=items))))
            # 未取込の機種を探すとき、ジャグラーは飛ばす
            self.assertEqual(ask('nagamachiminami', '2026-09-13', machines)['machine'], 'L 普通機')
            # 日付を確かめるために最初の機種を開くときも、ジャグラーは選ばない
            need_day = ask('nagamachiminami', None, machines)
            self.assertEqual((need_day['reason'], need_day['machine']), ('need_day', 'L 普通機'))
            # 残りがジャグラーだけなら「すべて取り込み済み」
            self.assertEqual(ask('nagamachiminami', '2026-09-13', machines[:1])['reason'], 'all_done')
            # 幸町ではジャグラーも対象
            saiwai = [dict(m, url=m['url'].replace('/nagamachiminami/', '/saiwaichou/')) for m in machines]
            self.assertEqual(ask('saiwaichou', '2026-09-13', saiwai)['machine'], 'SﾏｲｼﾞｬｸﾞﾗｰV')
            # 取り込み状況の印は「対象外」
            status = json.loads(bridge.machine_status(json.dumps(dict(
                store='nagamachiminami', day='2026-09-13', machines=[m['name'] for m in machines]))))['status']
            self.assertEqual(status[0], {'excluded': True})
            self.assertIsNone(status[1])

    def test_machine_list_without_day_opens_first_table_to_resolve_day(self):
        host = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami'
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            bridge = _Bridge(folder / 'test.db', folder, 'x')
            result = json.loads(bridge.next_unimported_machine(json.dumps(dict(
                store='nagamachiminami', day=None,
                machines=[dict(name='先頭機', url=f'{host}/standlist_slot?machine_name=先頭機', count=2)],
            ))))
            self.assertEqual(result['reason'], 'need_day')
            self.assertIn('machine_name=先頭機', result['url'])
            self.assertIn('対象日を確認', result['message'])

    def test_build_table_rows_reads_the_live_table_directly(self):
        rows = [dict(rack=128, bb=61, rb=24, games=5072, previous_start=1, max_hold=2825)]
        result, day, machine = build_table_rows(_table_payload(rows))
        self.assertEqual(day, '2026-09-13')
        self.assertEqual(machine, 'L戦国乙女5L8')
        self.assertEqual((result[0]['games'], result[0]['max_hold']), (5072, 2825))

    def test_build_table_rows_rejects_non_46mai_kind_code(self):
        rows = [dict(rack=128, bb=1, rb=1, games=1000, previous_start=0, max_hold=100)]
        with self.assertRaises(TableExtractionError):
            build_table_rows(_table_payload(rows, kind_code='10'))

    def test_build_table_rows_never_silently_merges_duplicate_racks(self):
        rows = [dict(rack=128, bb=1, rb=1, games=1000, previous_start=0, max_hold=100),
                dict(rack=128, bb=9, rb=9, games=9999, previous_start=0, max_hold=999)]
        with self.assertRaises(ValueError):
            build_table_rows(_table_payload(rows))

    def test_build_table_rows_keeps_idle_and_identical_value_racks(self):
        # Two different, consecutive racks with identical (including zero) numbers
        # must both survive -- neither an idle-rack pass nor a value-based dedupe
        # may drop either one.
        rows = [dict(rack=200, bb=0, rb=0, games=0, previous_start=0, max_hold=0),
                dict(rack=201, bb=0, rb=0, games=0, previous_start=0, max_hold=0)]
        result, _day, _machine = build_table_rows(_table_payload(rows))
        self.assertEqual(sorted(r['rack'] for r in result), [200, 201])
        self.assertEqual([r['games'] for r in result], [0, 0])

    def test_build_graph_context_requires_prior_list_import(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            payload = dict(store='nagamachiminami', target_date='2026-09-13', rack=128,
                          points=[[0, 50], [10, 10]], baseline_y=50)
            with self.assertRaises(GraphExtractionError):
                build_graph_context(payload, db)
            db.close()

    def test_build_graph_context_inherits_machine_name_and_numbers(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            db.save([row()])  # machine='テスト', games=3500, bb=20, rb=10, max_hold=2000, rack=128
            payload = dict(store='nagamachiminami', target_date='2026-09-13', rack=128,
                          points=[[0, 50], [10, 10], [20, 80], [30, 40]], baseline_y=50,
                          width=30, height=100, machine=None)
            context = build_graph_context(payload, db)
            self.assertEqual(context['machine'], 'テスト')
            self.assertEqual((context['games'], context['bb'], context['rb'], context['max_hold']),
                             (3500, 20, 10, 2000))
            self.assertAlmostEqual(context['auto']['peak_y'], 10)
            self.assertAlmostEqual(context['auto']['trough_y'], 80)
            self.assertAlmostEqual(context['auto']['end_x'], 30)
            db.close()

    def test_build_graph_context_uses_newer_detail_page_numbers(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            db.save([row()])
            payload = dict(store='nagamachiminami', target_date='2026-09-13', rack=128,
                          points=[[0, 50], [10, 10]], baseline_y=50, games=999)
            context = build_graph_context(payload, db)
            self.assertEqual(context['games'], 999)
            self.assertEqual(context['updated_fields'], {'games': (3500, 999)})
            db.close()

    def test_auto_four_points_from_svg_style_coordinates(self):
        points = [(0, 50), (10, 10), (20, 80), (30, 40)]
        auto = auto_four_points(points, baseline_y=50, width=30)
        self.assertAlmostEqual(auto['baseline_x'], 25.5)
        self.assertEqual((auto['peak_x'], auto['peak_y']), (10, 10))
        self.assertEqual((auto['trough_x'], auto['trough_y']), (20, 80))
        self.assertEqual((auto['end_x'], auto['end_y']), (30, 40))

    def test_render_curve_image_matches_requested_size(self):
        image = render_curve_image([(0, 50), (10, 10), (20, 80)], baseline_y=50, width=40, height=100)
        self.assertEqual(image.size, (40, 100))

    def test_encode_preview_image_downscales_and_round_trips(self):
        image = Image.new('RGB', (800, 400), 'white')
        encoded, width, height = encode_preview_image(image, max_width=420)
        self.assertLessEqual(width, 420)
        self.assertEqual(height, round(400 * 420 / 800))
        self.assertTrue(encoded)


class BackupSharingTests(unittest.TestCase):
    def test_export_backup_writes_a_readable_round_trip_file(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            db.save([row(rack=101), row(rack=102)])
            out = Path(folder) / 'backup.json'
            count = export_backup(db, out)
            self.assertEqual(count, 2)
            payload = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(payload['format'], 'database-backup')
            self.assertEqual(payload['source'], 'pc')
            self.assertEqual(len(payload['records']), 2)
            db.close()

    def test_sync_folder_auto_backup_latest_file_and_summary(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            db = Store(folder / 'test.db')
            db.save([row(rack=101), row(rack=102)])
            # No folder configured -> silently does nothing.
            self.assertIsNone(auto_backup(db, folder))
            sync = folder / 'sync'
            sync.mkdir()
            save_settings(folder, sync_dir=str(sync), last_day='2026-09-13')
            self.assertEqual(load_settings(folder)['last_day'], '2026-09-13')
            written = auto_backup(db, folder)
            self.assertEqual(written.name, AUTO_BACKUP_NAME)
            # The app's own auto copy is never offered as "the latest to import".
            self.assertIsNone(latest_backup_file(sync))
            other = sync / 'from-phone.json'
            export_backup(db, other)
            (sync / 'notes.json').write_text('{"hello": 1}', encoding='utf-8')
            self.assertEqual(latest_backup_file(sync), other)
            output = summary_report(db, folder / 'reports', '2026-09-13')
            text = output.read_text(encoding='utf-8')
            self.assertIn('2026-09-13', text)
            self.assertIn('function showDetail', text)
            with self.assertRaises(ValueError):
                summary_report(db, folder / 'reports', '2020-01-01')
            db.close()

    def _observed_graph_payloads(self):
        """Real captures (observed_graphs.json), as the browser would send them."""
        data = json.loads((Path(__file__).parents[1] / 'observed_graphs.json').read_text(encoding='utf-8'))
        for record in data['records']:
            numbers = [float(v) for v in record['xy'].split(',')]
            yield dict(store='nagamachiminami', target_date=data['day'], rack=record['rack'],
                       points=[[x, y] for x, y in zip(numbers[::2], numbers[1::2])],
                       baseline_y=record['baseline'], width=682, height=400)

    def test_auto_save_gate_accepts_real_captures_and_rejects_doubtful_ones(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            payloads = list(self._observed_graph_payloads())
            db.save([dict(row(day='2026-09-13', rack=p['rack'])) for p in payloads])
            for payload in payloads:
                context = build_graph_context(payload, db)
                self.assertEqual(graph_auto_save_blockers(context), [], payload['rack'])
            base = dict(payloads[0])

            def blockers(**changes):
                return graph_auto_save_blockers(build_graph_context({**base, **changes}, db))

            self.assertTrue(blockers(points=base['points'][:5]))              # too few points
            self.assertTrue(blockers(baseline_y=150.0))                       # does not start on zero line
            self.assertTrue(blockers(width=2000))                             # stops before the right edge
            self.assertTrue(blockers(points=base['points'][:-1] + [[682, 200.5]]))  # ends on the zero line
            self.assertTrue(blockers(games=999))                              # detail page disagrees with the list
            db.save([dict(row(day='2026-09-13', rack=128), graph_measurement=dict(
                baseline_x=1, baseline_y=200, peak_x=2, peak_y=100, trough_x=3, trough_y=250,
                end_x=4, end_y=150))])
            self.assertTrue(blockers())                                       # graph already saved
            db.close()

    def test_graph_measurement_result_matches_dialog_shape(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            payload = next(self._observed_graph_payloads())
            db.save([row(day='2026-09-13', rack=payload['rack'])])
            context = build_graph_context(payload, db)
            curve = render_curve_image(context['points'], context['baseline_y'],
                                       context['width'], context['height'])
            result = graph_measurement_result(context, curve)
            for key in ('baseline_x', 'baseline_y', 'peak_x', 'peak_y', 'trough_x', 'trough_y',
                        'end_x', 'end_y', 'preview_image', 'preview_width', 'preview_height', 'method'):
                self.assertIn(key, result)
            self.assertEqual(result['peak_y'], 35.0)
            db.close()

    def test_confirm_graph_always_saves_without_a_review_dialog(self):
        import browser_import
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            db_path = folder / 'data' / 'database.sqlite3'
            db_path.parent.mkdir()
            db = Store(db_path)
            payload = next(self._observed_graph_payloads())
            db.save([row(day='2026-09-13', rack=payload['rack'])])
            db.close()
            payload_file = folder / 'payload.json'
            signals = []
            original_signal = browser_import._write_advance_signal
            browser_import._write_advance_signal = lambda message, next_url=None: signals.append(message)
            try:
                # 一覧と数値が食い違っても確認画面を出さず、詳細画面の値とグラフを保存する。
                payload_file.write_text(json.dumps({**payload, 'games': 999}), encoding='utf-8')
                browser_import._confirm_graph(str(payload_file), db_path, folder / 'reports')
                self.assertIn('保存しました', signals[-1])
                check = Store(db_path)
                try:
                    saved_row = check.rows('2026-09-13', None, 'nagamachiminami')[0]
                finally:
                    check.close()
                # 保存時刻と、グラフの線そのもの（後から新しい指標を作るための生データ）も残る
                self.assertRegex(saved_row['captured_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')
                self.assertGreater(len(saved_row['graph_measurement']['curve']), 10)
                self.assertEqual(saved_row['graph_measurement']['curve'][0], [0.0, 200.0])
            finally:
                browser_import._write_advance_signal = original_signal

    def test_missing_graphs_lists_racks_per_machine_and_flags_missing_links(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            with_graph = dict(row(rack=101), graph_measurement=dict(
                baseline_x=1, baseline_y=200, peak_x=2, peak_y=100, trough_x=3, trough_y=250,
                end_x=4, end_y=150))
            db.save([with_graph, dict(row(rack=102), detail_url='https://example.test/102'), row(rack=103)])
            self.assertEqual(missing_graphs(db, '2026-09-13', 'nagamachiminami'), [('テスト', [102, 103], 1)])
            self.assertEqual(missing_graphs(db, '2026-09-13', 'saiwaichou'), [])
            page = summary_report(db, Path(folder) / 'r', '2026-09-13').read_text(encoding='utf-8')
            self.assertIn('グラフ未取得の台（2台）', page)
            self.assertIn('個別台リンクが保存されていません', page)
            db.close()

    def test_saved_table_keeps_detail_links_so_next_ungraphed_can_jump(self):
        import tkinter
        from tkinter import messagebox
        import browser_import
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            db_path = folder / 'data' / 'database.sqlite3'
            db_path.parent.mkdir()
            rows = [dict(rack=r, bb=1, rb=1, games=3000, previous_start=10, max_hold=500) for r in (301, 302)]
            payload_file = folder / 'payload.json'
            payload_file.write_text(json.dumps(_table_payload(rows)), encoding='utf-8')
            errors, signals = [], []
            originals = (browser_import._write_advance_signal, browser_import._bring_to_front, messagebox.showerror)
            browser_import._write_advance_signal = lambda message, next_url=None: signals.append((message, next_url))
            browser_import._bring_to_front = lambda window: None
            messagebox.showerror = lambda *args, **kwargs: errors.append(args)
            try:
                browser_import._confirm_table(str(payload_file), db_path, folder / 'reports')
            finally:
                browser_import._write_advance_signal, browser_import._bring_to_front, messagebox.showerror = originals
            self.assertEqual(errors, [])
            # 表を保存したら、そのまま最初の未取り込み台へ移動する。
            self.assertIn('rack_no=301', signals[-1][1])
            self.assertIn('最初の未取り込み台', signals[-1][0])
            db = Store(db_path)
            saved = db.rows('2026-09-13', 'L戦国乙女5L8', 'nagamachiminami')
            self.assertEqual([r['rack'] for r in saved], [301, 302])
            self.assertTrue(all('rack_no=' in (r.get('detail_url') or '') for r in saved))
            answer = json.loads(_Bridge(db_path, folder / 'reports', 'x').next_ungraphed_rack(json.dumps(
                dict(store='nagamachiminami', day='2026-09-13', machine='L戦国乙女5L8', rack=None))))
            self.assertIn('rack_no=301', answer['url'])
            db.close()

    def test_backup_fills_in_missing_detail_link_without_touching_numbers(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            db.save([row(rack=101)])
            incoming = dict(row(rack=101), detail_url='https://example.test/101')
            plan = plan_backup_import(db, [incoming])
            self.assertEqual([r['rack'] for r in plan['link_only']], [101])
            self.assertEqual(plan['unchanged'], [])
            path = Path(folder) / 'b.json'
            path.write_text(json.dumps(dict(format='database-backup', version=1, records=[incoming])), encoding='utf-8')
            import_backup(db, path)
            self.assertEqual(db.rows()[0]['detail_url'], 'https://example.test/101')
            self.assertEqual(db.rows()[0]['games'], 3500)
            db.close()

    def test_progress_duplicates_and_undo(self):
        from core import (day_fully_graphed, duplicate_warning, progress_text, remember_for_undo,
                          suspicious_duplicates, undo_last_save)
        graph = dict(baseline_x=1, baseline_y=200, peak_x=2, peak_y=100, trough_x=3, trough_y=250,
                     end_x=4, end_y=150)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            db = Store(folder / 'test.db')
            db.save([row(rack=285), dict(row(rack=286), graph_measurement=graph), row(rack=287)])
            self.assertEqual(progress_text(db, '2026-09-13'), '2026-09-13　長町南 1/3台')
            self.assertFalse(day_fully_graphed(db, '2026-09-13'))
            # 回転・BIG・REGがすべて同じ台 = 台番号ずれの疑い（row()は全台同じ数値）
            self.assertEqual(suspicious_duplicates(db, '2026-09-13', 'nagamachiminami'), [('テスト', [285, 286, 287])])
            self.assertIn('286', duplicate_warning(db, '2026-09-13', 'nagamachiminami', 'テスト', 286))
            db.save([dict(row(rack=285), games=100), dict(row(rack=287), games=200)])
            self.assertEqual(duplicate_warning(db, '2026-09-13', 'nagamachiminami', 'テスト'), '')
            # 取り消し：既存行は保存前の内容に戻り、新規行は消える
            new_row = dict(row(rack=288), graph_measurement=graph)
            edit = dict(row(rack=285), games=555, graph_measurement=graph)
            remember_for_undo(db, folder, 'テスト保存', [new_row, edit])
            db.save([new_row, edit])
            self.assertEqual(len(db.rows()), 4)
            self.assertEqual(undo_last_save(db, folder), 'テスト保存')
            racks = {r['rack']: r for r in db.rows()}
            self.assertEqual(sorted(racks), [285, 286, 287])
            self.assertEqual(racks[285]['games'], 100)
            self.assertNotIn('graph_measurement', racks[285])
            with self.assertRaises(ValueError):
                undo_last_save(db, folder)   # 1回だけ
            db.close()

    def test_delete_records_by_machine_store_day_and_undo(self):
        """取り込みミスを機種ごと・店舗の日付ごと・両店舗の日付ごとに消せる。1回分は元に戻せる。"""
        from core import delete_records, undo_last_save
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            db = Store(folder / 'test.db')
            db.save([
                row(rack=1), row(rack=2),
                dict(row(rack=3), machine='別機種'),
                dict(row(rack=4), store='saiwaichou'),
                dict(row(rack=5), day='2026-09-12'),
            ])
            key = lambda: sorted((r['rack'], r['store'], r['day'], r['machine']) for r in db.rows())
            racks = lambda: [k[0] for k in key()]
            before = key()
            # 機種ごと：同じ店舗・日付の別機種、別店舗、別日は残る
            self.assertEqual(delete_records(db, folder, '2026-09-13', 'nagamachiminami', 'テスト'), 2)
            self.assertEqual(racks(), [3, 4, 5])
            # 取り消すと元どおり
            self.assertIn('テスト', undo_last_save(db, folder))
            self.assertEqual(key(), before)
            # 店舗の日付ごと：その店舗のその日だけ
            self.assertEqual(delete_records(db, folder, '2026-09-13', 'nagamachiminami'), 3)
            self.assertEqual(racks(), [4, 5])
            undo_last_save(db, folder)
            # 両店舗の日付ごと：その日の両店舗すべて。別日は残る
            self.assertEqual(delete_records(db, folder, '2026-09-13'), 4)
            self.assertEqual(racks(), [5])
            undo_last_save(db, folder)
            self.assertEqual(key(), before)
            # 該当なし・機種だけの指定は消さない
            with self.assertRaises(ValueError):
                delete_records(db, folder, '2026-09-01', 'nagamachiminami')
            with self.assertRaises(ValueError):
                db.delete_group('2026-09-13', None, 'テスト')
            self.assertEqual(key(), before)
            db.close()

    def test_confirm_graph_reports_progress_and_heads_to_machine_list_without_opening_a_window(self):
        import tkinter
        from tkinter import messagebox
        import browser_import
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            db_path = folder / 'data' / 'database.sqlite3'
            db_path.parent.mkdir()
            db = Store(db_path)
            payload = next(self._observed_graph_payloads())
            db.save([row(day='2026-09-13', rack=payload['rack'])])
            db.close()
            (folder / 'payload.json').write_text(json.dumps(payload), encoding='utf-8')
            signals, opened = [], []
            originals = (browser_import._write_advance_signal, browser_import._bring_to_front,
                         messagebox.showerror, browser_import.os if hasattr(browser_import, 'os') else None)
            browser_import._write_advance_signal = lambda message, next_url=None: signals.append((message, next_url))
            browser_import._bring_to_front = lambda window: None
            messagebox.showerror = lambda *args, **kwargs: opened.append(('error', args))
            import os
            real_startfile = getattr(os, 'startfile', None)
            os.startfile = lambda path: opened.append(('open', str(path)))
            try:
                browser_import._confirm_graph(str(folder / 'payload.json'), db_path, folder / 'reports')
            finally:
                (browser_import._write_advance_signal, browser_import._bring_to_front, messagebox.showerror, _) = originals
                if real_startfile:
                    os.startfile = real_startfile
            self.assertEqual([o for o in opened if o[0] == 'error'], [])
            message, next_url = signals[-1]
            self.assertIn('保存しました', message)
            self.assertIn('機種一覧へ移動', message)                 # 機種が終わったので一覧ページへ
            self.assertTrue(next_url.endswith(
                '/nagamachiminami/rack_info_kt/?kind_code=21'
                '#database_next_machine=1&database_day=2026-09-13'))
            self.assertIn('すべて完了しました', message)              # 日の全グラフが揃ったことは案内する
            self.assertFalse([o for o in opened if o[0] == 'open'])   # が、まとめのウィンドウは開かない
            # 取り消せる（グラフだけが外れて、一覧の行は残る）
            bridge = _Bridge(db_path, folder / 'reports', 'x')
            self.assertIn('取り消しました', json.loads(bridge.undo_last_save())['message'])
            check = Store(db_path)
            saved = check.rows('2026-09-13')[0]
            self.assertFalse(saved.get('graph_measurement') or saved.get('graph'))
            self.assertIn('1', json.loads(bridge.progress(json.dumps(dict(store='nagamachiminami', day='2026-09-13'))))['text'] + '1')
            check.close()

    def test_rack_trend_and_machine_status_badges(self):
        from core import machine_progress, rack_trend
        graph = dict(baseline_x=1, baseline_y=200, peak_x=2, peak_y=100, trough_x=3, trough_y=250,
                     end_x=4, end_y=150)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            db = Store(folder / 'test.db')
            for day, machine, games in (('2026-09-10', 'テスト', 3000), ('2026-09-11', 'ほか機', 2000),
                                        ('2026-09-12', 'テスト', 3500), ('2026-09-13', 'テスト', 4000)):
                db.save([dict(row(day=day, rack=128), machine=machine, games=games)])
            today = db.rows('2026-09-13')[0]
            trend = rack_trend(db, today)
            # 新しい順・同じ機種だけ（9/11は別機種なので含めない）
            self.assertEqual([t['day'] for t in trend], ['2026-09-13', '2026-09-12', '2026-09-10'])
            self.assertEqual(trend[0]['hits'], 30)
            self.assertAlmostEqual(trend[0]['rate'], 4000 / 30)
            self.assertEqual(len(rack_trend(db, today, limit=2)), 2)
            page = summary_report(db, folder / 'r', '2026-09-13').read_text(encoding='utf-8')
            # 合計点確定台が無い日でも落ちない（推移はまとめの詳細モーダル用）
            self.assertIn('2026-09-13', page)
            # 機種一覧ページの印：済/途中/未取込を決めるための集計（空白の違いは無視）
            db.save([dict(row(day='2026-09-13', rack=129), machine='L 別 機', graph_measurement=graph),
                     dict(row(day='2026-09-13', rack=130), machine='L 別 機')])
            self.assertEqual(machine_progress(db, 'nagamachiminami', '2026-09-13'),
                             {'テスト': (0, 1), 'L別機': (1, 2)})
            answer = json.loads(_Bridge(folder / 'test.db', folder, 'x').machine_status(json.dumps(dict(
                store='nagamachiminami', day='2026-09-13', machines=['L+別+機', 'テスト', '存在しない']))))
            self.assertEqual(answer['status'], [dict(done=1, total=2), dict(done=0, total=1), None])
            db.close()

    def test_preview_image_is_stored_small_but_keeps_its_coordinate_size(self):
        """保存する画像は画素を半分・32色にして小さくする。返す幅・高さは座標の大きさのまま。

        幅・高さは4点や曲線と同じ座標系で、表示側はこの大きさに引き伸ばして描く。
        画像の画素数を返すと、点の位置が半分ずれてしまう。
        """
        import base64
        import io
        from PIL import Image
        from screenshot_import import encode_preview_image
        source = Image.new('RGB', (400, 300), 'white')
        draw = ImageDraw.Draw(source)
        draw.line([(0, 150), (399, 150)], fill=(220, 45, 45))
        draw.line([(0, 250), (200, 60), (399, 180)], fill=(30, 30, 30))
        encoded, width, height = encode_preview_image(source)
        self.assertEqual((width, height), (400, 300))          # 座標の大きさ
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as stored:
            self.assertEqual(stored.size, (200, 150))          # 画素は半分
            self.assertLessEqual(len(stored.convert('RGB').getcolors(65536) or []), 32)
        # 大きすぎる画像は、これまでどおり幅420にそろえてから半分にする
        _, wide_w, wide_h = encode_preview_image(Image.new('RGB', (840, 600), 'white'))
        self.assertEqual((wide_w, wide_h), (420, 300))

    def test_overlay_hides_youtube_with_the_same_script_as_android(self):
        """内部ブラウザにYouTubeを表示しない。PC版とAndroid版で同じスクリプトを使う。"""
        import re
        from browser_import import HIDE_YOUTUBE_JS, OVERLAY_JS
        dart = Path(__file__).parents[2] / 'database_android' / 'lib' / 'web_import_page.dart'
        if dart.exists():   # Android版が無い環境でも落とさない
            quotes = chr(39) * 3
            pattern = 'const _hideYouTubeScript = r' + quotes + '(.*?)' + quotes
            android = re.search(pattern, dart.read_text(encoding='utf-8'), re.S).group(1).strip()
            self.assertEqual(HIDE_YOUTUBE_JS.strip(), android)
        self.assertIn('ytimg', OVERLAY_JS)                 # サムネイル形式も隠す
        self.assertIn('MutationObserver', OVERLAY_JS)      # 後から差し込まれる分も
        self.assertIn('table, select, input, textarea', OVERLAY_JS)  # 表や日付選択は隠さない
        self.assertEqual(OVERLAY_JS.count('{'), OVERLAY_JS.count('}'))
        self.assertEqual(OVERLAY_JS.count('('), OVERLAY_JS.count(')'))

    def test_business_day_changes_at_2am(self):
        """深夜2時までは前日扱い（9/22の26時＝9/23 1:59 までは9/22）。"""
        from datetime import datetime
        from browser_import import today_iso
        self.assertEqual(today_iso(datetime(2026, 9, 22, 12, 0)), '2026-09-22')
        self.assertEqual(today_iso(datetime(2026, 9, 23, 0, 30)), '2026-09-22')
        self.assertEqual(today_iso(datetime(2026, 9, 23, 1, 59, 59)), '2026-09-22')
        self.assertEqual(today_iso(datetime(2026, 9, 23, 2, 0)), '2026-09-23')
        # 月・年の変わり目
        self.assertEqual(today_iso(datetime(2026, 10, 1, 1, 0)), '2026-09-30')
        self.assertEqual(today_iso(datetime(2027, 1, 1, 1, 0)), '2026-12-31')

    def test_machine_list_without_date_is_judged_by_today(self):
        """機種一覧ページには日付が無い。印・進み具合・日付確認で開く機種は「今日」で判定する。
        （以前は保存済みの最新日だったため、今日の分を消すと前日の「済」が出ていた）"""
        import browser_import
        from unittest import mock
        host = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami'
        graph = dict(baseline_x=1, baseline_y=200, peak_x=2, peak_y=100, trough_x=3, trough_y=250,
                     end_x=4, end_y=150)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            db = Store(folder / 'test.db')
            # 前日（9/21）は「済」、今日（9/22）は別機種を途中まで
            db.save([dict(row(day='2026-09-21', rack=1), machine='沖ドキ', graph_measurement=graph),
                     dict(row(day='2026-09-22', rack=2), machine='ハナハナ', graph_measurement=graph)])
            db.close()
            bridge = _Bridge(folder / 'test.db', folder, 'x')
            ask = lambda method, **payload: json.loads(getattr(bridge, method)(json.dumps(payload)))
            with mock.patch.object(browser_import, 'today_iso', return_value='2026-09-22'):
                status = ask('machine_status', store='nagamachiminami', day=None,
                             machines=['沖ドキ', 'ハナハナ'])
                self.assertEqual(status['day'], '2026-09-22')
                self.assertEqual(status['status'], [None, dict(done=1, total=1)])   # 前日の「済」は出さない
                self.assertIn('2026-09-22', ask('progress', store='nagamachiminami', day=None)['text'])
                # 日付確認で開く機種：今日済んでいる「ハナハナ」より、未取込の「沖ドキ」を先に
                machines = [dict(name='ハナハナ', url=f'{host}/standlist_slot/?kind_code=21&machine_name=h', count=1),
                            dict(name='沖ドキ', url=f'{host}/standlist_slot/?kind_code=21&machine_name=o', count=1)]
                need_day = ask('next_unimported_machine', store='nagamachiminami', day=None,
                               kind_code='21', machines=machines)
                self.assertEqual((need_day['reason'], need_day['machine']), ('need_day', '沖ドキ'))
            with mock.patch.object(browser_import, 'today_iso', return_value='2026-09-23'):
                # 今日の分がまだ無ければ、進み具合はそう表示する
                self.assertEqual(ask('progress', store='nagamachiminami', day=None)['text'],
                                 '2026-09-23　まだ取り込みがありません')

    def test_reliability_capture_note_and_next_day_index(self):
        self.assertEqual([reliability_label(g) for g in (None, 800, 1500, 3499, 3500)], ['少', '少', '中', '中', '多'])
        self.assertEqual(captured_note({}), '')
        self.assertEqual(captured_note({'captured_at': '2026-09-18T23:48:10+09:00'}), '取得 09/18 23:48')
        self.assertIn('早めの取得', captured_note({'captured_at': '2026-09-18T15:05:00+09:00'}))
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            # 台301は毎日、同機種の他の3台より明らかに高い回転・当たり（3日）
            for i, day in enumerate(('2026-09-10', '2026-09-11', '2026-09-12')):
                db.save([dict(row(day=day, rack=301), games=3000, bb=60, rb=20, max_hold=5000),
                         dict(row(day=day, rack=302), games=2000, bb=8, rb=2, max_hold=500),
                         dict(row(day=day, rack=303), games=2100, bb=9, rb=2, max_hold=600),
                         dict(row(day=day, rack=304), games=1900, bb=7, rb=2, max_hold=400)])
            graph = dict(baseline_y=200, peak_y=100, trough_y=210, end_y=120)
            for r in db.rows():
                db.save([dict(r, graph_measurement=graph)])
            last = [r for r in db.rows('2026-09-12') if r['rack'] == 301][0]
            forecast = next_day_index(db, last)
            self.assertEqual(forecast['days'], 3)
            self.assertGreater(forecast['index'], 50)          # 平均より高い傾向
            self.assertLessEqual(forecast['index'], 100)
            self.assertEqual(forecast['confidence'], '少')
            first = [r for r in db.rows('2026-09-10') if r['rack'] == 301][0]
            self.assertIsNone(next_day_index(db, first)['index'])   # 1日分しかない → データ不足
            candidates = provisional_next_day_candidates(db, '2026-09-12', 'テスト', 'nagamachiminami')
            self.assertEqual((candidates['total'], candidates['eligible'], candidates['count']), (4, 4, 1))
            self.assertEqual([item['row']['rack'] for item in candidates['candidates']], [301])
            # 表示は「63 / 100」ではなく「平均より +13」。50が中立であることも、
            # 上下どちらが良いのかも、素の指数だけでは画面から読めないため。
            self.assertEqual(signed_index(63.0), '平均より +13')
            self.assertEqual(signed_index(41.0), '平均より -9')
            self.assertEqual(signed_index(50.0), '平均より +0')
            page = summary_report(db, Path(folder) / 'r', '2026-09-12').read_text(encoding='utf-8')
            self.assertIn('この台の当たりの軽さ（過去傾向）', page)
            self.assertIn('平均より +', page)
            result_page = report(db, '2026-09-12', 'テスト', Path(folder) / 'r')[0].read_text(encoding='utf-8')
            self.assertIn('翌日候補（仮）', result_page)
            self.assertIn('当たりの軽さ 平均より +', result_page)
            db.close()

    def test_five_day_slump_strip_needs_five_days_of_graphs(self):
        graph = dict(baseline_x=1, baseline_y=200, peak_x=2, peak_y=100, trough_x=3, trough_y=250,
                     end_x=4, end_y=150)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            for i in range(1, 7):
                db.save([dict(row(day=f'2026-09-{10 + i}', rack=128), graph_measurement=graph)])
            # 別機種の日は数えない
            db.save([dict(row(day='2026-09-10', rack=128), machine='別機', graph_measurement=graph)])
            latest = db.rows('2026-09-16')[0]
            days = slump_days(db, latest)
            self.assertEqual([r['day'] for r in days],
                             ['2026-09-12', '2026-09-13', '2026-09-14', '2026-09-15', '2026-09-16'])  # 古い順・直近5日
            html_text = slump_strip_html(db, latest)
            self.assertIn('5日間のスランプグラフ', html_text)
            self.assertEqual(html_text.count('<figure>'), 5)
            # 4日分しかない日は表示しない
            self.assertEqual(slump_strip_html(db, db.rows('2026-09-14')[0]), '')
            db.close()

    def test_daily_snapshots_keep_seven_days_and_restore_forces_the_old_state(self):
        from datetime import date, timedelta
        graph_old = dict(baseline_x=1, baseline_y=200, peak_x=2, peak_y=100, trough_x=3, trough_y=250,
                         end_x=4, end_y=150)
        graph_bad = dict(graph_old, end_y=290)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            folder = Path(folder)
            db = Store(folder / 'test.db')
            db.save([dict(row(rack=101), graph_measurement=graph_old), row(rack=102)])
            base = date(2026, 9, 20)
            # 同期フォルダ未設定なら data 側の backups/ に、日付つきで作られる
            for offset in (12, 9, 8, 7, 3):
                snapshot_backup(db, folder, today=base - timedelta(days=offset))
            snapshot_backup(db, folder, today=base)
            (snapshot_dir(folder) / 'database-backup-notes.json').write_text('{}', encoding='utf-8')  # 対象外の名前は触らない
            kept = [stamp for stamp, _path in list_snapshots(folder)]
            # 7日より古いもの（8日前・9日前・12日前）は消え、7日前・3日前・今日が残る
            self.assertEqual(kept, [base, base - timedelta(days=3), base - timedelta(days=7)])
            self.assertTrue((snapshot_dir(folder) / 'database-backup-notes.json').exists())
            # 間違ったデータが保存された後に、3日前の状態へ戻す
            newest_good = [path for stamp, path in list_snapshots(folder) if stamp == base - timedelta(days=3)][0]
            db.save([dict(row(rack=101), games=999, graph_measurement=graph_bad), row(rack=103)])
            result = restore_backup(db, newest_good)
            rows = {r['rack']: r for r in db.rows()}
            self.assertEqual(rows[101]['games'], 3500)                       # 数値が元に戻る
            self.assertEqual(rows[101]['graph_measurement']['end_y'], 150)   # グラフも元に戻る
            self.assertIn(103, rows)                                         # その後に追加した台は消えない
            self.assertTrue(result['forced'])
            db.close()

    def test_machine_row_cache_never_serves_stale_rows(self):
        """比較用の行はまとめて復号して使い回すので、書き込み後に古い行が残らないこと。"""
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            db.save([row(rack=101), row(day='2026-09-12', rack=101)])
            current = db.rows('2026-09-13')[0]
            self.assertEqual(len(db.references(current)), 1)      # ここでキャッシュが作られる
            db.save([row(day='2026-09-11', rack=101)])            # 追加
            self.assertEqual(len(db.references(current)), 2)
            db.save([dict(row(day='2026-09-12', rack=101), games=7777)])   # 上書き
            self.assertIn(7777, [r['games'] for r in db.references(current)])
            db.set_confirmed_setting('nagamachiminami', '2026-09-12', 'テスト', 101, '6')
            self.assertIn('6', [r.get('confirmed_setting') for r in db.references(current)])
            db.delete('nagamachiminami', '2026-09-12', 'テスト', 101)      # 削除
            self.assertEqual(len(db.references(current)), 1)
            db.close()

    def test_new_record_from_another_device_is_added(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            db.save([row(rack=101)])
            incoming = [row(rack=101), row(rack=202)]
            plan = plan_backup_import(db, incoming)
            self.assertEqual([r['rack'] for r in plan['new']], [202])
            self.assertEqual(len(plan['unchanged']), 1)
            self.assertEqual(plan['conflicts'], [])
            db.close()

    def test_conflicting_numbers_are_never_silently_overwritten(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            db.save([row(rack=101)])  # games=3500
            incoming = [dict(row(rack=101), games=9999)]
            plan = plan_backup_import(db, incoming)
            self.assertEqual(len(plan['conflicts']), 1)
            local, remote = plan['conflicts'][0]
            self.assertEqual((local['games'], remote['games']), (3500, 9999))
            self.assertEqual(plan['new'], [])
            # import_backup must not apply the conflicting record.
            import_backup(db, self._write(folder, incoming))
            self.assertEqual(db.rows('2026-09-13', 'テスト', 'nagamachiminami')[0]['games'], 3500)
            db.close()

    def test_graph_only_update_is_merged_when_numbers_match(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            db.save([row(rack=101)])
            incoming = [dict(row(rack=101),
                            graph_measurement=dict(baseline_y=100, peak_y=40, end_y=60))]
            plan = plan_backup_import(db, incoming)
            self.assertEqual(len(plan['graph_only']), 1)
            backup_path = self._write(folder, incoming)
            applied = import_backup(db, backup_path)
            self.assertEqual(len(applied['graph_only']), 1)
            saved = db.rows('2026-09-13', 'テスト', 'nagamachiminami')[0]
            self.assertIn('graph_measurement', saved)
            db.close()

    def test_out_of_scope_records_are_skipped_not_imported(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            incoming = [dict(row(rack=101), kind_code=10),
                       dict(row(rack=102), store='otherstore'),
                       {'not': 'a valid record'}]
            plan = plan_backup_import(db, incoming)
            self.assertEqual(len(plan['skipped']), 3)
            self.assertEqual(plan['new'], [])
            db.close()

    def test_import_backup_applies_new_and_graph_only_via_a_file(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            incoming = [row(rack=303)]
            backup_path = self._write(folder, incoming)
            plan = import_backup(db, backup_path)
            self.assertEqual([r['rack'] for r in plan['new']], [303])
            self.assertEqual(db.rows('2026-09-13', 'テスト', 'nagamachiminami')[0]['rack'], 303)
            db.close()

    @staticmethod
    def _write(folder, records):
        path = Path(folder) / f'backup-{len(records)}-{id(records)}.json'
        path.write_text(json.dumps(dict(format='database-backup', version=1, records=records),
                                   ensure_ascii=False), encoding='utf-8')
        return path


class FirstCapturedTests(unittest.TestCase):
    def test_first_capture_time_is_kept_and_only_moves_earlier(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            db.save([row(rack=1)])
            first = db.payload_map([('nagamachiminami', '2026-09-13', 'テスト', 1)])[0]['first_captured_at']
            self.assertRegex(first, r'[+-]\d\d:\d\d$')
            db.save([dict(row(rack=1), games=3600)])
            again = db.payload_map([('nagamachiminami', '2026-09-13', 'テスト', 1)])[0]
            self.assertEqual(again['first_captured_at'], first)
            # A backup that saw the rack earlier (on the phone) wins; a later one never does.
            db.save([dict(row(rack=1), first_captured_at='2026-09-13T22:00:00+09:00')])
            db.save([dict(row(rack=1), first_captured_at='2030-01-01T00:00:00+09:00')])
            kept = db.payload_map([('nagamachiminami', '2026-09-13', 'テスト', 1)])[0]
            self.assertEqual(kept['first_captured_at'], '2026-09-13T22:00:00+09:00')
            db.close()

    def test_rows_saved_before_first_capture_existed_stay_unknown(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[1]) as folder:
            db = Store(Path(folder) / 'test.db')
            key = ('nagamachiminami', '2026-09-13', 'テスト', 2)
            db.restore_payloads([(key, row(rack=2))])
            db.save([dict(row(rack=2), games=3600)])
            self.assertNotIn('first_captured_at', db.payload_map([key])[0])
            db.close()


if __name__ == '__main__': unittest.main()
