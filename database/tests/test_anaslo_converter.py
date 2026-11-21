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


class PstationNormalAnalysisTests(unittest.TestCase):
    """P-STATIONのジャグラー・ハナハナだけの分析用JSON（2026-11-11 利用者「ジャグラーハナハナだけに絞って
    分析用JSON作ろう」）。databaseには読み込まない別の形式。幸町の分析用とはフォルダも分ける。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        a, b = self.folder / '2026_09_15.html', self.folder / '2026_09_16.html'
        a.write_bytes(html('2026/09/15', 'マイジャグラーV'))
        b.write_bytes(html('2026/09/16', 'ジャックポットアット'))
        self.staging = analyze([a, b])

    def test_only_juggler_and_hanahana_without_dropping_native_racks(self):
        from anaslo_converter import make_normal_analysis
        payload = make_normal_analysis(self.staging, {'マイジャグラーV': '#マイジャグラーV'})
        self.assertEqual((payload['format'], payload['store'], payload['days']),
                         ('database-normal-analysis', 'p-station', ['2026-09-15', '2026-09-16']))
        self.assertEqual(payload['summary'], {'records': 1, 'days': 2, 'other_machines': 1})
        row = payload['records'][0]
        self.assertEqual((row['day'], row['rack'], row['source_machine'], row['games'], row['bb'], row['rb']),
                         ('2026-09-15', 101, 'マイジャグラーV', 3000, 8, 4))
        self.assertEqual((row['rate'], row['at_art'], row['source_site']), ('20', 0, 'anaslo'))
        self.assertEqual(row['source_graph']['points'][-1], [1, 80])
        self.assertNotIn('graph_measurement', row)  # メルヘン座標の測定値は幸町だけ
        self.assertNotIn('my', row)
        self.assertNotIn('net_medals', row)

    def test_unresolved_names_are_allowed_and_non_juggler_is_dropped(self):
        from anaslo_converter import make_normal_analysis
        payload = make_normal_analysis(self.staging)
        self.assertEqual([r['machine'] for r in payload['records']], ['マイジャグラーV'])

    def test_saved_file_is_never_read_as_a_backup(self):
        from anaslo_converter import make_normal_analysis, save_normal_analysis
        payload = make_normal_analysis(self.staging)
        path = save_normal_analysis(self.folder / 'out', payload)
        self.assertEqual(path.name, 'normal-analysis-p-station-20260915-20260916.json')
        self.assertEqual(save_normal_analysis(self.folder / 'out', payload), path)  # 作り直しは上書き
        self.assertFalse(is_pscube_backup(path))
        store = PscubeStore(self.folder / 'test.sqlite3')
        self.addCleanup(store.close)
        with self.assertRaises(ValueError):
            store.import_backup(json.loads(path.read_text(encoding='utf-8')))
        self.assertEqual(store.db.execute('SELECT count(*) FROM records').fetchone()[0], 0)

    def test_converter_button_saves_into_its_own_folder(self):
        import gc
        import importlib.util
        import sys
        import tkinter as tk
        from unittest.mock import patch
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(gc.collect)  # Tcl_AsyncDelete 対策（test_anaslo_saiwaichou と同じ）
        self.addCleanup(root.destroy)
        converter_dir = Path(__file__).resolve().parents[2] / 'html_converter'
        if str(converter_dir) not in sys.path:
            sys.path.append(str(converter_dir))
        spec = importlib.util.spec_from_file_location('converter_pstation_normal_test', converter_dir / 'app.py')
        ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ui)
        converter = ui.Converter(root)
        self.assertEqual(str(converter.normal_button['state']), 'disabled')
        with patch('anaslo_converter.read_catalog', return_value=[]), \
                patch('anaslo_converter.read_native_occupied', return_value=frozenset({('2026-09-15', 101)})), \
                patch.object(ui.PscubeTarget, 'alias_file', str(self.folder / 'aliases.json')):
            converter.load_paths([self.folder / '2026_09_15.html', self.folder / '2026_09_16.html'])
        self.assertEqual(str(converter.save_button['state']), 'disabled')  # 機種名が未確認
        self.assertEqual(str(converter.normal_button['state']), 'normal')
        self.assertEqual(str(converter.other_button['state']), 'disabled')  # その他機種用は幸町だけ
        with patch.object(ui, 'PSTATION_ANALYSIS_DIR', self.folder / 'pstation'), \
                patch.object(ui.messagebox, 'showinfo') as shown:
            converter.save_normal()
        saved = self.folder / 'pstation' / 'normal-analysis-p-station-20260915-20260916.json'
        rows = json.loads(saved.read_text(encoding='utf-8'))['records']
        self.assertEqual([(r['day'], r['rack']) for r in rows], [('2026-09-15', 101)])  # P’s CUBEの実データがある台も残る
        self.assertIn('databaseに読み込みません', shown.call_args.args[1])
        self.assertFalse((self.folder / 'aliases.json').exists())  # 対応表は変えない

    def test_no_juggler_is_an_error(self):
        from anaslo_converter import make_normal_analysis
        only_other = self.folder / '2026_09_17.html'
        only_other.write_bytes(html('2026/09/17', 'ジャックポットアット'))
        with self.assertRaises(ValueError):
            make_normal_analysis(analyze([only_other]))


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


class OldGraphZeroLineTests(unittest.TestCase):
    """2026-11-21：P-STATIONの古い形式（2026-01〜08前半）は赤い線の値が0のまま、点は y=312 から始まる。
    最初の点をゼロ線にし、印（zero_from）を残す。推定差枚には使わない（目盛りの倍率が未確認、2026-11-06の判断）。"""

    @staticmethod
    def graph(zero, ys, xs=(0, 100, 300)):
        data = html().replace(b'var x_value = [0, 1];var y_value = [100, 80];', f'var x_value = {list(xs)};var y_value = {list(ys)};'.encode())
        data = data.replace(b'context.tick.value == 100', f'context.tick.value == {zero}'.encode())
        return parse_html(data, '2026_09_15.html')['records'][0]['graph']

    def test_old_format_takes_the_first_point_and_new_format_is_unchanged(self):
        import anaslo_net
        import daily_learning as dl
        old = self.graph(0, [312, 300, 250])
        self.assertEqual((old['zero_y'], old['zero_from']), (312., 'first-point'))
        new = self.graph(312, [312, 300, 250])
        self.assertEqual(new['zero_y'], 312.)
        self.assertNotIn('zero_from', new)
        same_start = self.graph(0, [0, -10, -40])           # 点の座標がゼロ線と合っている形は変えない
        self.assertEqual(same_start['zero_y'], 0.)
        self.assertNotIn('zero_from', same_start)
        late_start = self.graph(0, [312, 300, 250], xs=(5, 100, 300))
        self.assertNotIn('zero_from', late_start)
        # 終点が始点より上（yが小さい）ならプラス。直す前は古い形式がすべて「プラスでない」と読まれた。
        row = lambda g: dict(store='pscube:c740601:20', rate='20', day='2026-03-01', rack=1, machine='m', games=4000,
                             bb=20, rb=10, graph=g)
        self.assertEqual((dl.outcome(row(old)), dl.outcome(row(new))), (1, 1))
        self.assertIsNone(anaslo_net.pixels(old))
        self.assertIsNotNone(anaslo_net.pixels(new))
