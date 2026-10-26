import copy
import json
from pathlib import Path
import tempfile
import unittest

from anaslo_converter import analyze, make_backup, read_catalog, save_backup, suggestions
from anaslo_html import parse_html, probability
from pscube_import import PscubeStore, _record_key, _validate_record, is_pscube_backup, installation_count
from test_pscube_sync import machine, record, put


def html(day='2026/09/15', name='マイジャグラーV', games='3,000'):
    columns = ['機種名', '台番号', 'G数', 'BB', 'RB', 'ART', '合成確率', 'BB確率', 'RB確率', 'ART確率']
    values = [name, '101', games, '8', '4', '0', '1/250.0', '1/375.0', '1/750.0', '1/0.0']
    def table(identity):
        return f'<table {identity}><tr>' + ''.join(f'<th>{v}</th>' for v in columns) + '</tr><tr>' + ''.join(f'<td>{v}</td>' for v in values) + '</tr></table>'
    return (f'<h1>{day} P-STATION&amp;IIスロット館 データまとめ</h1>'
            f'<link rel="canonical" href="https://ana-slo.com/{day.replace("/", "-")}-p-stationii-data/">'
            + table('id="all_data_table"') + table('')
            + '<script>var x_value = [0, 1];var y_value = [100, 80];document.getElementById("101");if(context.tick.value == 100){}</script>').encode('utf-8')


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / '2026_09_15.html'
        self.input.write_bytes(html())
        self.staging = analyze([self.input])
        self.m = machine()
        self.payload = make_backup(self.staging, {'マイジャグラーV': self.m['machine']}, [self.m])
        self.store = PscubeStore(self.root / 'test.sqlite3')
        self.addCleanup(self.store.close)

    def test_import_and_repeat_are_fill_only(self):
        summary = self.store.import_backup(self.payload)
        self.assertEqual(summary['added'], 1)
        saved = json.loads(self.store.db.execute('SELECT payload FROM records').fetchone()[0])
        self.assertIsNone(saved['my'])
        self.assertIsNone(saved['detail_url'])
        self.assertEqual(saved['games'], 3000)
        self.assertEqual(saved['source_graph']['points'][-1], [1, 80])
        self.assertEqual(self.store.import_backup(self.payload)['added'], 0)
        exported = self.store.export_payload()
        self.store.import_backup(exported)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM records').fetchone()[0], 1)

    def test_existing_native_rack_day_wins_even_with_different_alias(self):
        other = machine('別表記')
        old = record(other, 101, '2026-09-15', games=1000, my=5000)
        put(self.store, other, [old])
        before = self.store.db.execute('SELECT payload FROM records').fetchone()[0]
        summary = self.store.import_backup(self.payload)
        self.assertEqual(summary['added'], 0)
        self.assertEqual(summary['kept_local'], 1)
        self.assertEqual(self.store.db.execute('SELECT payload FROM records').fetchone()[0], before)

    def test_native_capture_replaces_unknown_my_even_with_fewer_games(self):
        self.store.import_backup(self.payload)
        native = record(self.m, 101, '2026-09-15', games=1000, my=1200)
        self.store.import_backup({'format': 'pscube-viewer', 'version': 1, 'machines': [self.m], 'records': [native]})
        saved = self.store._read('records', _record_key(native))
        self.assertEqual(saved, native)
        self.store.import_backup(self.payload)
        self.assertEqual(self.store._read('records', _record_key(native)), native)

    def test_native_missing_my_still_rejected(self):
        r = record(self.m, 101, '2026-09-15')
        r['my'] = None
        with self.assertRaises(ValueError):
            _validate_record(r)

    def test_invalid_source_and_partial_file_roll_back(self):
        bad = copy.deepcopy(self.payload)
        bad['records'].append({**bad['records'][0], 'rack': 102, 'source_url': 'https://example.com'})
        with self.assertRaises(ValueError):
            self.store.import_backup(bad)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM records').fetchone()[0], 0)

    def test_external_fake_my_rejected(self):
        r = dict(self.payload['records'][0], my=0)
        with self.assertRaises(ValueError):
            _validate_record(r)

    def test_missing_required_null_rejected(self):
        r = dict(self.payload['records'][0])
        del r['my']
        with self.assertRaises(ValueError):
            _validate_record(r)

    def test_source_only_machine_is_not_auto_capture_target(self):
        payload = make_backup(self.staging, {'マイジャグラーV': '未知の機種'}, [])
        self.store.import_backup(payload)
        url, remaining = self.store.next_target('2026-09-15')
        self.assertEqual(remaining, 0)
        self.assertIn('nc-v03-001.php', url)

    def test_source_only_machine_does_not_block_native_installation_count(self):
        put(self.store, self.m, [record(self.m, 102, '2026-09-16')])
        payload = make_backup(self.staging, {'マイジャグラーV': '未知の機種'}, [])
        self.store.import_backup(payload)
        external = next(m for m in self.store.export_payload()['machines']
                        if m.get('source_site') == 'anaslo')
        self.assertIsNone(external['url'])
        import input_versions
        input_versions.wait(self.store.path.parent)
        before = self.store.path.read_bytes()
        self.assertEqual(installation_count(self.store.path, self.m['url']), self.m['expected_count'])
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_source_only_catalog_does_not_supply_native_installation_count(self):
        payload = make_backup(self.staging, {'マイジャグラーV': '未知の機種'}, [])
        self.store.import_backup(payload)
        import input_versions
        input_versions.wait(self.store.path.parent)
        before = self.store.path.read_bytes()
        self.assertIsNone(installation_count(self.store.path, self.m['url']))
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_existing_machine_settings_kept(self):
        put(self.store, {**self.m, 'expected_count': 100, 'machine_type': 'normal'}, [])
        self.store.import_backup(self.payload)
        m = json.loads(self.store.db.execute('SELECT payload FROM machines').fetchone()[0])
        self.assertEqual(m['expected_count'], 100)
        self.assertEqual(m['machine_type'], 'normal')

    def test_normalized_and_ambiguous_names(self):
        self.assertEqual(suggestions('マイジャグラーV', [self.m])['automatic'], self.m['machine'])
        self.assertEqual(suggestions('スマスロ北斗の拳', [machine('L北斗の拳')])['automatic'], 'L北斗の拳')
        self.assertIsNone(suggestions('マイジャグラーV', [self.m, machine('マイジャグラーV')])['automatic'])
        self.assertIsNone(suggestions('マイジャグラーVI', [self.m])['automatic'])

    def test_mapping_required_and_no_overwrite(self):
        with self.assertRaises(ValueError):
            make_backup(self.staging, {}, [])
        target = self.root / 'pscube-backup-anaslo-test.json'
        save_backup(target, self.payload)
        self.assertTrue(is_pscube_backup(target))
        before = target.read_bytes()
        with self.assertRaises(FileExistsError):
            save_backup(target, self.payload)
        self.assertEqual(target.read_bytes(), before)

    def test_catalog_readonly(self):
        put(self.store, self.m, [])
        import input_versions
        input_versions.wait(self.store.path.parent)
        before = self.store.path.read_bytes()
        self.assertEqual(read_catalog(self.store.path), [self.m])
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_source_validation(self):
        self.assertEqual(probability('1/0.0')['denominator'], None)
        for data, name in [(html(), '2026_09_25.html'), (html(games=''), '2026_09_15.html')]:
            with self.assertRaises(ValueError):
                parse_html(data, name)
        with self.assertRaises(ValueError):
            analyze([self.input, self.input])


if __name__ == '__main__':
    unittest.main()
