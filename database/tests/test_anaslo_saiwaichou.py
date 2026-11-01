"""幸町店のアナスロ取り込み（2026-10-16）。P-STATIONと同じ部品で、変換先だけメルヘン用DB。"""
import gc
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
from urllib.parse import quote

from anaslo_converter import MeruhenCatalog, MeruhenTarget, analyze, make_meruhen_backup, save_backup
from anaslo_download import Client, OtherHall, cache_name, check_html, download, reject_access_check, AccessStopped
from anaslo_html import parse_html
from anaslo_index import (P_STATION, SAIWAICHOU, DayLink, canonical_url, extract_links, hall_of, link_day)
from core import Store, import_backup
from test_anaslo_download import fixture_html

STORE_NAME = 'スーパーメルヘンワールド幸町店'
# The real page writes its canonical URL percent-encoded in lower case.
DAILY = 'https://ana-slo.com/{day}-' + quote(STORE_NAME).lower() + '-data/'
COLUMNS = ['機種名', '台番号', 'G数', 'BB', 'RB', '合成確率', 'BB確率', 'RB確率']
ROWS = [('ネオアイムジャグラーEX', 779, '5,650', 17, 16), ('ネオアイムジャグラーEX', 781, '4,980', 19, 14),
        ('Sブラックボード', 598, '1,000', 2, 1), ('沖ドキ!DUO アンコール', 600, '2,000', 5, 3),
        ('マイジャグラーV', 900, '3,000', 10, 8)]


def saiwai_html(day='2026-09-01', rows=ROWS):
    def table(identity, cols, values):
        return (f'<table {identity}><tr>' + ''.join(f'<th>{c}</th>' for c in cols) + '</tr>'
                + ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>' for row in values) + '</table>')
    values = [(n, r, g, b, rb, '1/171.2', '1/332.4', '1/353.1') for n, r, g, b, rb in rows]
    graphs = ''.join(f'<script>var x_value = [0.5, 65.5];var y_value = [0, 134];'
                     f'var ctx = document.getElementById("{r}");if(context.tick.value == 0){{}}</script>'
                     for _, r, *_ in rows)
    return (f'<h1>{day.replace("-", "/")} {STORE_NAME} データまとめ</h1>'
            f'<link rel="canonical" href="{DAILY.format(day=day)}">'
            + table('id="all_data_table"', COLUMNS, values)
            + table('', COLUMNS[1:], [v[1:] for v in values]) + graphs).encode('utf-8')


def meruhen_row(day, rack, machine, games=3000):
    return dict(store='saiwaichou', kind_code=21, day=day, machine=machine, rack=rack,
                games=games, bb=12, rb=6, max_hold=None)


class HallUrlTests(unittest.TestCase):
    def test_saiwaichou_urls_are_recognised_and_kept_apart_from_p_station(self):
        url = DAILY.format(day='2026-09-01')
        self.assertEqual(link_day(url), '2026-09-01')
        self.assertIs(hall_of(url), SAIWAICHOU)
        self.assertEqual(canonical_url(url), canonical_url(f'https://ana-slo.com/2026-09-01-{STORE_NAME}-data/#top'))
        self.assertIs(hall_of(SAIWAICHOU.index_url, index=True), SAIWAICHOU)
        p_station = 'https://ana-slo.com/2026-09-01-p-stationiiスロット館-data/'
        self.assertNotEqual(canonical_url(url), canonical_url(p_station))
        with self.assertRaises(ValueError):
            canonical_url(url, hall=P_STATION)
        with self.assertRaises(ValueError):
            canonical_url(P_STATION.index_url, index=True, hall=SAIWAICHOU)

    def test_index_selects_only_its_own_halls_daily_links(self):
        raw = (f'<a href="{DAILY.format(day="2026-09-01")}">A</a>'
               f'<a href="/2026-09-02-{STORE_NAME}-data/">B</a>'
               '<a href="/2026-09-01-p-stationiiスロット館-data/">P</a>').encode('utf-8')
        links = extract_links(raw, SAIWAICHOU.index_url, '2026-09-01', '2026-09-30')
        self.assertEqual([l.day for l in links], ['2026-09-01', '2026-09-02'])
        self.assertTrue(all(hall_of(l.url) is SAIWAICHOU for l in links))
        self.assertEqual([l.day for l in extract_links(raw, P_STATION.index_url, '2026-09-01', '2026-09-30')],
                         ['2026-09-01'])

    def test_index_page_with_challenge_word_is_accepted_only_with_its_heading(self):
        raw = (f'<h1>{STORE_NAME} データ一覧</h1><a href="/2026-09-01-{STORE_NAME}-data/">A</a>'
               '<script>captcha</script>').encode('utf-8')
        reject_access_check(raw, SAIWAICHOU.index_url, index=True)
        with self.assertRaises(AccessStopped):
            reject_access_check(raw.replace('幸町店 データ一覧'.encode(), b'x'), SAIWAICHOU.index_url, index=True)


class SaiwaichouPageTests(unittest.TestCase):
    def test_table_without_art_columns(self):
        data = parse_html(saiwai_html(), '2026_09_01.html')
        self.assertEqual(data['store']['source_name'], STORE_NAME)
        first = data['records'][0]
        self.assertEqual((first['rack'], first['games'], first['bb'], first['rb']), (779, 5650, 17, 16))
        self.assertIsNone(first['at_art'])
        self.assertNotIn('at_art', first['probabilities'])
        self.assertEqual(data['validation']['detail_rows_checked'], len(ROWS))
        self.assertEqual(data['validation']['graphs'], len(ROWS))

    def test_check_html_is_per_hall(self):
        raw = saiwai_html()
        check_html(raw, '2026-09-01.html', '2026-09-01', SAIWAICHOU)
        with self.assertRaises(OtherHall):
            check_html(raw, '2026-09-01.html', '2026-09-01', P_STATION)
        with self.assertRaises(OtherHall):
            check_html(fixture_html(), '2026-09-15.html', '2026-09-15', SAIWAICHOU)
        with self.assertRaises(ValueError):
            check_html(raw, '2026-09-01.html', '2026-09-02', SAIWAICHOU)
        self.assertTrue(cache_name(DayLink('2026-09-01', canonical_url(DAILY.format(day='2026-09-01'))))
                        .startswith('2026-09-01-saiwaichou-'))

    def test_shared_folder_with_another_halls_page_of_same_date_still_downloads(self):
        with tempfile.TemporaryDirectory() as folder:
            other = Path(folder) / '2026_09_01 P-STATION.html'
            other.write_bytes(fixture_html().replace(b'2026/09/15', b'2026/09/01').replace(b'2026-09-15', b'2026-09-01'))
            item = DayLink('2026-09-01', canonical_url(DAILY.format(day='2026-09-01')))
            class Fake(Client):
                def get(self, url, *, index=False):
                    self.requested = url
                    return saiwai_html()
            client = Fake()
            result = download([item], '2026-09-01', '2026-09-01', folder, client)
            self.assertEqual((result.downloaded, result.failed, result.stopped), (1, 0, ''))
            self.assertEqual(client.requested, item.url)
            self.assertEqual(other.read_bytes()[:4], fixture_html()[:4])  # left untouched

    def test_one_hall_per_conversion(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / '2026_09_01.html'
            a.write_bytes(saiwai_html())
            b = Path(folder) / '2026_09_15.html'
            b.write_bytes(fixture_html())
            self.assertEqual(analyze([a])['hall'], 'saiwaichou')
            self.assertIsNone(analyze([a])['days'][0]['store']['rate'])
            self.assertEqual(analyze([b])['days'][0]['store']['rate'], '20')
            with self.assertRaises(ValueError):
                analyze([a, b])


class MeruhenBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.html = self.root / '2026_09_01.html'
        self.html.write_bytes(saiwai_html())
        self.staging = analyze([self.html])
        self.db = Store(self.root / 'database.sqlite3')
        self.addCleanup(self.db.close)
        self.db.save([meruhen_row('2026-09-15', 779, 'SネオアイムジャグラーEX−KK'),
                      meruhen_row('2026-09-15', 781, '★SネオアイムジャグラーEX−KK'),
                      meruhen_row('2026-09-15', 781, 'SネオアイムジャグラーEX−KK'),
                      meruhen_row('2026-09-15', 600, 'L／オキドキデュオ2／FR'),
                      meruhen_row('2026-09-01', 781, 'SネオアイムジャグラーEX−KK', games=4999)])
        from anaslo_converter import read_meruhen_catalog
        import input_versions
        input_versions.wait(self.root)
        before = (self.root / 'database.sqlite3').read_bytes()
        self.catalog = read_meruhen_catalog(self.root / 'database.sqlite3')
        self.assertEqual((self.root / 'database.sqlite3').read_bytes(), before)

    def test_automatic_name_needs_matching_name_and_rack(self):
        found = self.catalog.suggestions('ネオアイムジャグラーEX', {779, 781})
        self.assertEqual(found['automatic'], 'SネオアイムジャグラーEX−KK')
        self.assertIn('★SネオアイムジャグラーEX−KK', found['candidates'])
        # Same spelling rule, but never saved on these racks: only a candidate.
        self.assertIsNone(self.catalog.suggestions('ネオアイムジャグラーEX', {900})['automatic'])
        # Rack evidence alone (machine replaced on the rack) is never automatic.
        self.assertIsNone(self.catalog.suggestions('マイジャグラーV', {779})['automatic'])
        self.assertEqual(self.catalog.suggestions('マイジャグラーV', {779})['candidates'][0], 'SネオアイムジャグラーEX−KK')
        both = MeruhenCatalog('saiwaichou', [('2026-09-15', 'Lとある魔術の禁書目録JC', 1),
                                             ('2026-09-15', 'Lとある魔術の禁書目録2FA', 2)])
        self.assertIsNone(both.suggestions('とある魔術の禁書目録', {1, 2})['automatic'])
        self.assertEqual(both.suggestions('とある魔術の禁書目録2', {2})['automatic'], 'Lとある魔術の禁書目録2FA')

    def test_backup_fills_only_missing_known_racks_and_imports_once(self):
        mapping = {'ネオアイムジャグラーEX': 'SネオアイムジャグラーEX−KK', 'マイジャグラーV': 'マイジャグラーV'}
        payload = make_meruhen_backup(self.staging, mapping, self.catalog)
        self.assertEqual([(r['day'], r['rack']) for r in payload['records']], [('2026-09-01', 779)])
        self.assertEqual(payload['conversion_summary']['skipped'],
                         {'existing': 1, 'excluded': 2, 'unknown_rack': 1})
        saved = payload['records'][0]
        self.assertEqual((saved['kind_code'], saved['store'], saved['games']), (21, 'saiwaichou', 5650))
        self.assertIsNone(saved['max_hold'])
        self.assertEqual(saved['source_machine'], 'ネオアイムジャグラーEX')
        path = self.root / MeruhenTarget.file_name(None, '20260901')
        save_backup(path, payload)
        old = self.db.db.execute("SELECT payload FROM days WHERE day='2026-09-01' AND rack=781").fetchone()[0]
        plan = import_backup(self.db, path)
        self.assertEqual(len(plan['new']), 1)
        self.assertEqual(len(import_backup(self.db, path)['new']), 0)
        rows = {(r['day'], r['rack']): r for r in self.db.rows()}
        self.assertEqual(rows[('2026-09-01', 779)]['games'], 5650)
        self.assertEqual(rows[('2026-09-01', 779)]['source_site'], 'anaslo')
        self.assertEqual(self.db.db.execute("SELECT payload FROM days WHERE day='2026-09-01' AND rack=781").fetchone()[0], old)

    def test_mapping_is_required_and_excluded_targets_rejected(self):
        with self.assertRaises(ValueError):
            make_meruhen_backup(self.staging, {}, self.catalog)
        with self.assertRaises(ValueError):
            make_meruhen_backup(self.staging, {'ネオアイムジャグラーEX': 'L／オキドキデュオ2／FR', 'マイジャグラーV': None},
                                self.catalog)
        with self.assertRaises(ValueError):  # Nothing left to add.
            make_meruhen_backup(self.staging, {'ネオアイムジャグラーEX': None, 'マイジャグラーV': None}, self.catalog)

    def test_rack_keeps_meruhens_own_star_spelling(self):
        # 2026-10-17：海門決戦はメルヘンで1278番台だけ★付き。対応表の1つの名前を全台に付けると履歴が分かれた。
        catalog = MeruhenCatalog('saiwaichou', [('2026-09-15', '★SネオアイムジャグラーEX−KK', 779),
                                                ('2026-09-15', 'SネオアイムジャグラーEX−KK', 781),
                                                ('2026-09-14', '★SネオアイムジャグラーEX−KK', 781, 'anaslo')])
        payload = make_meruhen_backup(self.staging, {'ネオアイムジャグラーEX': 'SネオアイムジャグラーEX−KK',
                                                     'マイジャグラーV': None}, catalog)
        self.assertEqual({r['rack']: r['machine'] for r in payload['records']},
                         {779: '★SネオアイムジャグラーEX−KK', 781: 'SネオアイムジャグラーEX−KK'})
        # A different machine on the rack is never taken as a spelling.
        self.assertEqual(catalog.rack_spelling(779, 'マイジャグラーV'), 'マイジャグラーV')


class SavedNameFixTests(unittest.TestCase):
    """fix_anaslo_saved.py：対応表の誤りで保存した補完の機種名を付け直す（2026-10-17）。"""

    def setUp(self):
        from fix_anaslo_saved import apply_name_fixes, plan_name_fixes
        self.plan, self.apply = plan_name_fixes, apply_name_fixes
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = Store(self.root / 'database.sqlite3')
        self.addCleanup(self.db.close)
        anaslo = dict(source_site='anaslo', source_url=DAILY.format(day='2026-09-01'))
        self.db.save([
            # 初代を「Ⅱ」の名前で保存してしまった補完と、メルヘンが初代に付けている名前。
            dict(meruhen_row('2026-09-01', 518, 'L／ソードアート・オンラインⅡ'), source_machine='ソードアート・オンライン', **anaslo),
            meruhen_row('2026-09-21', 518, 'Lソードアート・オンラインB2'),
            # 正しい補完（Ⅱ）はそのまま。
            dict(meruhen_row('2026-09-01', 584, 'L／ソードアート・オンラインⅡ'), source_machine='ソードアート・オンラインII', **anaslo),
            meruhen_row('2026-09-18', 584, 'L／ソードアート・オンラインⅡ'),
            # ★の台。
            dict(meruhen_row('2026-09-01', 1278, 'L 甲鉄城のカバネリ 海門決戦 XX'), source_machine='甲鉄城のカバネリ 海門(うなと)決戦', **anaslo),
            meruhen_row('2026-09-22', 1278, '★L 甲鉄城のカバネリ 海門決戦 XX'),
            # メルヘンで取った行は、対応表と違っても変えない。
            dict(meruhen_row('2026-09-02', 518, 'L／ソードアート・オンラインⅡ'), source_machine='ソードアート・オンライン'),
        ])
        self.aliases = {'ソードアート・オンライン': 'Lソードアート・オンラインB2',
                        'ソードアート・オンラインII': 'L／ソードアート・オンラインⅡ',
                        '甲鉄城のカバネリ 海門(うなと)決戦': 'L 甲鉄城のカバネリ 海門決戦 XX'}

    def names(self):
        return {(r['day'], r['rack']): r['machine'] for r in self.db.rows() if r['store'] == 'saiwaichou'}

    def test_renames_only_wrong_anaslo_rows_and_old_backup_cannot_restore_them(self):
        fixes, _ = self.plan(self.db, self.aliases)
        self.assertEqual(sorted((old[3], new) for old, new, _ in fixes),
                         [(518, 'Lソードアート・オンラインB2'), (1278, '★L 甲鉄城のカバネリ 海門決戦 XX')])
        before = {k: v for k, v in self.names().items()}
        self.assertEqual(dict(self.apply(self.db, fixes)), {'renamed': 2})
        after = self.names()
        self.assertEqual(after[('2026-09-01', 518)], 'Lソードアート・オンラインB2')
        self.assertEqual(after[('2026-09-01', 1278)], '★L 甲鉄城のカバネリ 海門決戦 XX')
        self.assertEqual(after[('2026-09-01', 584)], before[('2026-09-01', 584)])
        self.assertEqual(after[('2026-09-02', 518)], 'L／ソードアート・オンラインⅡ')  # not anaslo
        moved = next(r for r in self.db.rows() if (r['day'], r['rack']) == ('2026-09-01', 518))
        self.assertEqual((moved['games'], moved['source_machine']), (3000, 'ソードアート・オンライン'))
        self.assertEqual(self.plan(self.db, self.aliases)[0], [])
        # The old-name row is marked deleted: re-reading the earlier anaslo JSON does not bring it back.
        old = self.root / 'old.json'
        old.write_text(json.dumps({'format': 'database-backup', 'version': 1, 'records': [
            dict(meruhen_row('2026-09-01', 518, 'L／ソードアート・オンラインⅡ'), source_machine='ソードアート・オンライン',
                 source_site='anaslo')]}, ensure_ascii=False), encoding='utf-8')
        self.assertEqual(len(import_backup(self.db, old)['new']), 0)
        self.assertEqual(sum(1 for k in self.names() if k == ('2026-09-01', 518)), 1)
        self.assertEqual(len([r for r in self.db.rows() if (r['day'], r['rack']) == ('2026-09-01', 518)]), 1)

    def test_existing_row_under_new_name_is_kept(self):
        self.db.save([dict(meruhen_row('2026-09-01', 518, 'Lソードアート・オンラインB2'), games=4321)])
        fixes, _ = self.plan(self.db, self.aliases)
        self.assertEqual(self.apply(self.db, [f for f in fixes if f[0][3] == 518])['kept_existing'], 1)
        rows = [r for r in self.db.rows() if (r['day'], r['rack']) == ('2026-09-01', 518)]
        self.assertEqual([(r['machine'], r['games']) for r in rows], [('Lソードアート・オンラインB2', 4321)])

    def test_unmapped_rows_are_left_alone(self):
        fixes, skipped = self.plan(self.db, {})
        self.assertEqual(fixes, [])
        self.assertEqual(skipped['no_mapping'], 3)


class AnasloGraphTests(unittest.TestCase):
    """アナスロのグラフ（片側1000に引き伸ばしたもの）→ メルヘンの座標の測定値（2026-10-17）。"""

    def graph(self, ys):
        return {'kind': 'source_coordinates', 'points': [[0.5 + 10 * i, y] for i, y in enumerate(ys)],
                'zero_y': 0.0, 'y_increases_downward': True}

    def test_shape_scores_and_variety_without_a_net_estimate(self):
        from anaslo_converter import graph_measurement_from_source
        from core import measurement_metrics, meruhen_net_estimate_detail, rack_net, variety_state
        up = graph_measurement_from_source(self.graph([0, 300, 1000, 500]))
        self.assertEqual((up['baseline_y'], up['peak_y'], up['end_y']), (200.5, 20.5, 110.5))
        self.assertEqual(up['curve'][2], [20.5, 20.5])
        metrics = measurement_metrics(up)
        self.assertEqual((metrics['positive_score'], metrics['retention_score']), (10.0, 5.0))
        down = graph_measurement_from_source(self.graph([0, 200, -400]))
        self.assertEqual(measurement_metrics(down)['positive_score'], 0.0)
        self.assertEqual(variety_state(dict(games=3500, bb=5, rb=5, graph_measurement=up)), 'plus')
        self.assertEqual(variety_state(dict(games=3500, bb=5, rb=5, graph_measurement=down)), 'dented')
        # No max_hold, so the scale (and the net) stays unknown on every platform's estimator.
        self.assertEqual(meruhen_net_estimate_detail(up, None, 3500), (None, False))
        self.assertEqual(rack_net(dict(store='saiwaichou', day='2026-09-01', games=3500, graph_measurement=up)),
                         (None, False, False))
        self.assertIsNone(graph_measurement_from_source(self.graph([0])))  # unplayed rack
        self.assertIsNone(graph_measurement_from_source(self.graph([0, 1500])))  # outside the frame
        self.assertIsNone(graph_measurement_from_source(None))

    def test_converter_and_saved_rows_get_the_measurement(self):
        from fix_anaslo_saved import apply_graph_fills, plan_graph_fills
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        html = Path(tmp.name) / '2026_09_01.html'
        html.write_bytes(saiwai_html())
        catalog = MeruhenCatalog('saiwaichou', [('2026-09-15', 'SネオアイムジャグラーEX−KK', 779)])
        payload = make_meruhen_backup(analyze([html]), {'ネオアイムジャグラーEX': 'SネオアイムジャグラーEX−KK',
                                                         'マイジャグラーV': None}, catalog)
        self.assertEqual(payload['records'][0]['graph_measurement']['method'], 'anaslo-source-graph')
        db = Store(Path(tmp.name) / 'database.sqlite3')
        self.addCleanup(db.close)
        old = dict(meruhen_row('2026-09-01', 779, 'SネオアイムジャグラーEX−KK'), source_site='anaslo',
                   source_graph=self.graph([0, 100, -50]))
        native = meruhen_row('2026-09-02', 779, 'SネオアイムジャグラーEX−KK')
        db.save([old, native])
        fills = plan_graph_fills(db)
        self.assertEqual([key[1] for key, _ in fills], ['2026-09-01'])
        self.assertEqual(apply_graph_fills(db, fills), 1)
        rows = {r['day']: r for r in db.rows()}
        self.assertEqual(rows['2026-09-01']['graph_measurement']['end_y'], 209.5)
        self.assertNotIn('graph_measurement', rows['2026-09-02'])
        self.assertEqual(plan_graph_fills(db), [])


class ConverterScreenTests(unittest.TestCase):
    def test_saiwaichou_html_uses_meruhen_target_and_own_alias_file(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        path = folder / '2026_09_01.html'
        path.write_bytes(saiwai_html())
        catalog = MeruhenCatalog('saiwaichou', [('2026-09-15', 'SネオアイムジャグラーEX−KK', 779)])
        root = tk.Tk()
        root.withdraw()
        # 壊したあと、このスレッド（メインスレッド）で片付ける。残すと後の試験の別スレッドのGCで片付けられ、
        # Tcl_AsyncDelete でプロセスごと落ちる（2026-10-18）。後片付けは逆順に動く。
        self.addCleanup(gc.collect)
        self.addCleanup(root.destroy)
        converter_dir = Path(__file__).resolve().parents[2] / 'html_converter'
        if str(converter_dir) not in sys.path:
            sys.path.append(str(converter_dir))
        spec = importlib.util.spec_from_file_location('converter_saiwai_test', converter_dir / 'app.py')
        ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ui)
        converter = ui.Converter(root)
        with patch('anaslo_converter.read_meruhen_catalog', return_value=catalog), \
                patch.object(MeruhenTarget, 'alias_file', str(folder / 'aliases.json')):
            converter.load_paths([path])
        self.assertIsInstance(converter.target, MeruhenTarget)
        self.assertEqual(converter.alias_file, folder / 'aliases.json')
        self.assertEqual(converter.mapping['ネオアイムジャグラーEX'], 'SネオアイムジャグラーEX−KK')
        self.assertIsNone(converter.mapping['Sブラックボード'])
        self.assertNotIn('マイジャグラーV', converter.mapping)
        self.assertIn('幸町', converter.hall_text.get())
        self.assertEqual(converter.target.file_name('20260901'), 'database-backup-anaslo-saiwaichou-20260901.json')
        self.assertFalse((folder / 'aliases.json').exists())


class NormalAnalysisTests(unittest.TestCase):
    """幸町のジャグラー・ハナハナだけの分析用ファイル（2026-10-17 利用者「ノーマルタイプのジャグラーシリーズ
    ハナハナシリーズしか作成せず、共有に載せない処理をしてほしい」）。databaseには読み込めない形式。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        html = self.folder / '2026_09_01.html'
        html.write_bytes(saiwai_html())
        self.staging = analyze([html])

    def test_only_juggler_and_hanahana_and_every_rack(self):
        from anaslo_converter import is_normal_type, make_normal_analysis
        payload = make_normal_analysis(self.staging, {'ネオアイムジャグラーEX': 'SネオアイムジャグラーEX−KK',
                                                      'Sブラックボード': None})
        self.assertEqual(payload['format'], 'database-normal-analysis')
        self.assertEqual([(r['rack'], r['machine'], r['source_machine']) for r in payload['records']],
                         [(779, 'SネオアイムジャグラーEX−KK', 'ネオアイムジャグラーEX'),
                          (781, 'SネオアイムジャグラーEX−KK', 'ネオアイムジャグラーEX'),
                          (900, 'マイジャグラーV', 'マイジャグラーV')])  # 対応を決めていない機種はHTMLの名前
        self.assertEqual(payload['summary'], {'records': 3, 'days': 1, 'other_machines': 2})
        first = payload['records'][0]
        self.assertEqual((first['day'], first['games'], first['bb'], first['rb']), ('2026-09-01', 5650, 17, 16))
        self.assertEqual(first['graph_measurement']['method'], 'anaslo-source-graph')
        self.assertTrue(all(is_normal_type(n) for n in ('ｷﾝｸﾞﾊﾅﾊﾅ-30', 'ゴーゴージャグラー3', 'SハナハナホウオウEX')))
        self.assertFalse(is_normal_type('沖ドキ!DUO アンコール'))

    def test_only_saiwaichou(self):
        from anaslo_converter import make_normal_analysis
        other = json.loads(json.dumps(self.staging))
        other['days'][0]['store']['source_name'] = P_STATION.source_name
        with self.assertRaises(ValueError):
            make_normal_analysis(other)

    def test_saved_file_is_never_read_as_a_backup(self):
        from anaslo_converter import make_normal_analysis, save_normal_analysis
        from core import latest_backup_file
        from pscube_import import is_pscube_backup
        payload = make_normal_analysis(self.staging)
        path = save_normal_analysis(self.folder / 'normal', payload)
        self.assertEqual(path.name, 'normal-analysis-saiwaichou-20260901.json')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['records'], payload['records'])
        self.assertEqual(save_normal_analysis(self.folder / 'normal', payload), path)  # 作り直しは上書き
        db = Store(self.folder / 'database.sqlite3')
        self.addCleanup(db.close)
        with self.assertRaises(ValueError):
            import_backup(db, path)
        self.assertEqual(db.rows(), [])
        self.assertIsNone(latest_backup_file(path.parent))
        self.assertFalse(is_pscube_backup(path))

    def test_converter_button_saves_without_resolving_names(self):
        root = tk.Tk()
        root.withdraw()
        # 壊したあと、このスレッド（メインスレッド）で片付ける。残すと後の試験の別スレッドのGCで片付けられ、
        # Tcl_AsyncDelete でプロセスごと落ちる（2026-10-18）。後片付けは逆順に動く。
        self.addCleanup(gc.collect)
        self.addCleanup(root.destroy)
        converter_dir = Path(__file__).resolve().parents[2] / 'html_converter'
        if str(converter_dir) not in sys.path:
            sys.path.append(str(converter_dir))
        spec = importlib.util.spec_from_file_location('converter_normal_test', converter_dir / 'app.py')
        ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ui)
        converter = ui.Converter(root)
        self.assertEqual(str(converter.normal_button['state']), 'disabled')
        catalog = MeruhenCatalog('saiwaichou', [('2026-09-15', 'SネオアイムジャグラーEX−KK', 779)])
        with patch('anaslo_converter.read_meruhen_catalog', return_value=catalog), \
                patch.object(MeruhenTarget, 'alias_file', str(self.folder / 'aliases.json')):
            converter.load_paths([self.folder / '2026_09_01.html'])
        self.assertEqual(str(converter.save_button['state']), 'disabled')  # マイジャグラーVが未確認
        self.assertEqual(str(converter.normal_button['state']), 'normal')
        with patch.object(ui, 'NORMAL_ANALYSIS_DIR', self.folder / 'normal'), \
                patch.object(ui.messagebox, 'showinfo') as shown:
            converter.save_normal()
        saved = self.folder / 'normal' / 'saiwaichou' / 'normal-analysis-saiwaichou-20260901.json'
        self.assertEqual(len(json.loads(saved.read_text(encoding='utf-8'))['records']), 3)
        self.assertIn('databaseに読み込みません', shown.call_args.args[1])
        self.assertFalse((self.folder / 'aliases.json').exists())  # 対応表は変えない


if __name__ == '__main__':
    unittest.main()
