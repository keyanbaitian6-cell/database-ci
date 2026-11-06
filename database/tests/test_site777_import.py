"""表示資料の変換・日付/台番の取り違え・不明値の保護。通信と実DBは使わない。"""
import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path
import sys
import unittest
import tempfile
import copy

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import site777_import as capture

NOW = datetime.fromisoformat('2026-11-07T01:50:00+09:00')
URL = 'https://m.site777.jp/f/D3300.do?pmc=04034001&urt=2000&mdc=123&dtdd=0&pan=1'


def bitmap():
    image = Image.new('RGB', (260, 226), '#191e18')
    draw = ImageDraw.Draw(image)
    draw.line([(8, 111), (243, 111)], fill='white', width=2)
    draw.line([(9, 111), (30, 98), (45, 123), (66, 116)], fill='yellow', width=2)
    stream = BytesIO()
    image.save(stream, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()


class ImportTest(unittest.TestCase):
    def table(self):
        return {'url': URL, 'machine': '試験ジャグラー3', 'model_id': '123', 'selected_md': '11/6',
                'count': 2, 'headers': ['', '台番', '累計ゲーム', 'BB回数', 'RB回数', '最高出玉', 'ART回数'],
                'rows': [['', '101', '3000', '10', '8', '900', '--'], ['', '102', '2800', '9', '5', '1,234', '0']]}

    def test_table_keeps_unknown_art_and_real_zero_distinct(self):
        rows = capture.table_records(self.table(), '2026-11-06', NOW)
        self.assertEqual(rows[0]['at_art'], None)
        self.assertEqual(rows[1]['at_art'], 0)
        self.assertEqual(rows[1]['my'], 1234)
        self.assertEqual(rows[0]['games'], 3000)
        missing=self.table()
        missing['rows'][1][5]='--'
        self.assertIsNone(capture.table_records(missing,'2026-11-06',NOW)[1]['my'])

    def test_bad_scope_or_incomplete_table_is_not_accepted(self):
        for change in ({'selected_md': '11/5'}, {'count': 3},
                       {'headers': ['', '台番', '累計ゲーム', 'BB回数', 'RB回数', '合成確率', 'ART回数']}):
            with self.assertRaises(ValueError):
                capture.table_records({**self.table(), **change}, '2026-11-06', NOW)
        for url in (URL.replace('2000', '500'), URL.replace('04034001', '12345678'),
                    URL.replace('m.site777.jp', 'example.com'), URL + '&dtdd=1'):
            with self.assertRaises(ValueError):
                capture.table_records({**self.table(), 'url': url}, '2026-11-06', NOW)
        for rows in ([self.table()['rows'][0]] * 2, [['', '101', '--', '1', '0', '0', '0']] * 2):
            with self.assertRaises(ValueError):
                capture.table_records({**self.table(), 'rows': rows}, '2026-11-06', NOW)

    def test_year_boundary_and_page_identity(self):
        self.assertEqual(capture.day_from_label('12/31', datetime.fromisoformat('2027-01-01T01:00:00+09:00')), '2026-12-31')
        self.assertTrue(capture.same_page(URL, URL.replace('pmc=04034001&urt=2000', 'urt=2000&pmc=04034001') + '#scroll'))
        self.assertFalse(capture.same_page(URL, URL.replace('dtdd=0', 'dtdd=1')))
        self.assertFalse(capture.same_page(URL, URL.replace('pan=1', 'pan=2')))

    def test_graph_is_pixel_curve_without_inventing_exact_net(self):
        graph, source = capture.trace_graph(bitmap())
        self.assertAlmostEqual(graph['zero_y'], 111.5)
        self.assertGreater(len(graph['points']), 45)
        self.assertLess(graph['points'][10][1], graph['zero_y'])
        self.assertGreater(graph['points'][-1][1], graph['zero_y'])
        self.assertNotIn('net_medals', source)
        self.assertEqual(len(source['image_sha256']), 64)

    def test_graph_pages_must_match_date_model_and_rack_scope(self):
        payload = {'url': URL.replace('D3300', 'D4300'), 'model_id': '123', 'selected_md': '11/6',
                   'graphs': [{'rack': 101, 'png': bitmap()}]}
        got = capture.graph_records(payload, '2026-11-06', '123', {101, 102}, NOW)
        self.assertEqual(set(got), {101})
        for change in ({'selected_md': '11/5'}, {'model_id': '999'},
                       {'graphs': payload['graphs'] * 2}, {'graphs': [{'rack': 103, 'png': bitmap()}]}):
            with self.assertRaises(ValueError):
                capture.graph_records({**payload, **change}, '2026-11-06', '123', {101, 102}, NOW)

    def test_complete_backup_preserves_provenance_and_unknown_net(self):
        table = self.table()
        rows = capture.table_records(table, '2026-11-06', NOW)
        curve, source = capture.trace_graph(bitmap())
        graphs = {r['rack']: {'graph': curve, 'source_graph': source} for r in rows}
        backup = capture.make_backup(table, rows, graphs, '2026-11-06', '試験ジャグラー3', now=NOW)
        self.assertEqual(backup['import_mode'], 'fill_missing')
        for record in backup['records']:
            capture.validate_record(record)
            self.assertIsNone(record['net_medals'])
            self.assertIsNone(record['detail_url'])
            with self.assertRaises(ValueError):
                capture.validate_record({**record, 'source_day_label': '11/5'})
        del graphs[102]
        with self.assertRaises(ValueError):
            capture.make_backup(table, rows, graphs, '2026-11-06', '試験ジャグラー3', now=NOW)

    def backup(self):
        table = self.table()
        rows = capture.table_records(table, '2026-11-06', NOW)
        curve, source = capture.trace_graph(bitmap())
        graphs = {r['rack']: {'graph': curve, 'source_graph': source} for r in rows}
        return capture.make_backup(table, rows, graphs, '2026-11-06', '試験ジャグラー3', now=NOW)

    def test_existing_rack_day_is_preserved_across_different_machine_aliases(self):
        from pscube_import import PscubeStore, _record_key
        from test_pscube_sync import machine, record, put
        with tempfile.TemporaryDirectory() as tmp:
            store = PscubeStore(Path(tmp) / 'test.sqlite3', recording=False)
            try:
                m = machine('別表記')
                original = record(m, 101, '2026-11-06', games=123, my=678)
                put(store, m, [original])
                result = store.import_backup(self.backup())
                self.assertEqual(result['added'], 1)
                self.assertEqual(result['kept_local'], 1)
                self.assertEqual(store._read('records', _record_key(original)), original)
                snapshot = store.export_payload()
                self.assertEqual(store.import_backup(snapshot)['added'], 0)
                self.assertEqual(len(store.export_payload()['records']), 2)
            finally:
                store.close()

    def test_native_capture_can_replace_site777_but_site777_never_replaces_it(self):
        from pscube_import import PscubeStore, _record_key
        from test_pscube_sync import machine, record
        with tempfile.TemporaryDirectory() as tmp:
            store = PscubeStore(Path(tmp) / 'test.sqlite3', recording=False)
            try:
                store.import_backup(self.backup())
                m = machine('試験ジャグラー3')
                fresh = record(m, 101, '2026-11-06', games=100, my=123)
                store.import_backup({'format': 'pscube-viewer', 'version': 1, 'machines': [m], 'records': [fresh]})
                self.assertEqual(store._read('records', _record_key(fresh)), fresh)
                store.import_backup(self.backup())
                self.assertEqual(store._read('records', _record_key(fresh)), fresh)
            finally:
                store.close()

    def test_bad_provenance_rolls_back_whole_backup(self):
        from pscube_import import PscubeStore
        with tempfile.TemporaryDirectory() as tmp:
            store = PscubeStore(Path(tmp) / 'test.sqlite3', recording=False)
            try:
                bad = copy.deepcopy(self.backup())
                bad['records'][1]['source_url'] = URL.replace('04034001', '1234')
                with self.assertRaises(ValueError):
                    store.import_backup(bad)
                self.assertEqual(store.export_payload()['records'], [])
            finally:
                store.close()
