"""幸町店のアナスロ取り込み（2026-10-16）。P-STATIONと同じ部品で、変換先だけメルヘン用DB。"""
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
        self.addCleanup(root.destroy)
        converter_dir = Path(__file__).resolve().parents[1] / 'html_converter'
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


if __name__ == '__main__':
    unittest.main()
