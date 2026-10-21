"""その他機種の分析専用保存。実DB・共有へ入らず、元の数値と欠測を保つ。"""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import anaslo_converter as service
from core import Store, import_backup, latest_backup_file
from pscube_import import is_pscube_backup
from test_anaslo_saiwaichou import saiwai_html, MeruhenCatalog, MeruhenTarget


class OtherAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.html = self.folder / '2026_09_01.html'
        self.html.write_bytes(saiwai_html())
        self.staging = service.analyze([self.html])

    def test_partition_keeps_every_other_rack_despite_omitted_mapping(self):
        mapping = {'ネオアイムジャグラーEX': 'SネオアイムジャグラーEX−KK',
                   'Sブラックボード': None, '沖ドキ!DUO アンコール': 'L／オキドキデュオ2／FR'}
        normal = service.make_normal_analysis(self.staging, mapping)
        other = service.make_other_analysis(self.staging, mapping)
        normal_keys = {(r['day'], r['rack']) for r in normal['records']}
        other_keys = {(r['day'], r['rack']) for r in other['records']}
        source_keys = {(d['day'], r['rack']) for d in self.staging['days'] for r in d['records']}
        self.assertFalse(normal_keys & other_keys)
        self.assertEqual(normal_keys | other_keys, source_keys)
        self.assertEqual({r['rack'] for r in other['records']}, {598, 600})
        self.assertEqual(other['format'], 'database-other-analysis')
        self.assertFalse(other['import_ready'])
        self.assertEqual(other['summary']['records'], 2)

    def test_source_values_and_unknowns_survive_without_mutating_input(self):
        source = self.staging['days'][0]['records'][3]
        source['at_art'] = 7
        source['graph']['points'][1][1] = 1500  # 測定値へ変換できなくても原座標を捨てない。
        before = copy.deepcopy(self.staging)
        payload = service.make_other_analysis(self.staging)
        r = next(r for r in payload['records'] if r['rack'] == 600)
        self.assertEqual((r['games'], r['bb'], r['rb'], r['at_art']), (2000, 5, 3, 7))
        self.assertEqual(r['source_probabilities'], source['probabilities'])
        self.assertEqual(r['source_graph'], source['graph'])
        self.assertNotIn('graph_measurement', r)
        self.assertIsNone(r['my'])
        self.assertIsNone(r['net_medals'])
        self.assertIsNone(r['max_hold'])
        self.assertIsNone(r['rate'])
        self.assertIsNone(r['observed_at'])
        blackboard = next(r for r in payload['records'] if r['rack'] == 598)
        self.assertIsNone(blackboard['at_art'])
        self.assertEqual(blackboard['graph_measurement']['method'], 'anaslo-source-graph')
        self.assertEqual(payload['sources'][0]['sha256'], self.staging['days'][0]['source']['sha256'])
        self.assertEqual(self.staging, before)

    def test_juggler_alias_and_half_width_names_stay_out_but_other_a_types_stay(self):
        self.staging['days'][0]['records'][0]['machine'] = 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3'
        self.staging['days'][0]['records'][1]['machine'] = 'ｷﾝｸﾞﾊﾅﾊﾅ-30'
        self.staging['days'][0]['records'][-1]['machine'] = '新ハナビ'
        payload = service.make_other_analysis(self.staging)
        self.assertEqual({r['rack'] for r in payload['records']}, {598, 600, 900})
        payload = service.make_other_analysis(self.staging, {'新ハナビ': 'SマイジャグラーVKD'})
        self.assertNotIn(900, {r['rack'] for r in payload['records']})

    def test_wrong_hall_and_empty_partition_are_rejected(self):
        bad = copy.deepcopy(self.staging)
        bad['days'][0]['store']['source_name'] = '別店舗'
        with self.assertRaises(ValueError):
            service.make_other_analysis(bad)
        self.staging['days'][0]['records'] = self.staging['days'][0]['records'][:2]
        with self.assertRaises(ValueError):
            service.make_other_analysis(self.staging)

    def test_saving_is_separate_and_regular_import_rejects_it_before_writing(self):
        payload = service.make_other_analysis(self.staging)
        path = service.save_other_analysis(self.folder / 'other', payload)
        self.assertEqual(path.name, 'other-analysis-saiwaichou-20260901.json')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), payload)
        self.assertEqual(service.save_other_analysis(path.parent, payload), path)
        self.assertIsNone(latest_backup_file(path.parent))
        self.assertFalse(is_pscube_backup(path))
        db = Store(self.folder / 'isolated.sqlite3')
        self.addCleanup(db.close)
        before = db.path.read_bytes()
        with self.assertRaises(ValueError):
            import_backup(db, path)
        self.assertEqual(db.rows(), [])
        self.assertEqual(db.path.read_bytes(), before)

    def test_period_filename_and_wrong_format_cannot_overwrite_an_archive(self):
        payload = service.make_other_analysis(self.staging)
        payload['days'] = ['2026-09-03', '2026-09-01', '2026-09-03']
        path = service.save_other_analysis(self.folder, payload)
        self.assertEqual(path.name, 'other-analysis-saiwaichou-20260901-20260903.json')
        before = path.read_bytes()
        payload['format'] = 'database-backup'
        with self.assertRaises(ValueError):
            service.save_other_analysis(self.folder, payload)
        self.assertEqual(path.read_bytes(), before)

    def test_converter_button_saves_unresolved_names_without_regular_save(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        converter_dir = Path(__file__).resolve().parents[1] / 'html_converter'
        if str(converter_dir) not in sys.path:
            sys.path.append(str(converter_dir))
        spec = importlib.util.spec_from_file_location('converter_other_test', converter_dir / 'app.py')
        ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ui)
        converter = ui.Converter(root)
        self.assertEqual(str(converter.other_button['state']), 'disabled')
        catalog = MeruhenCatalog('saiwaichou', [('2026-09-15', 'SネオアイムジャグラーEX−KK', 779)])
        with patch('anaslo_converter.read_meruhen_catalog', return_value=catalog), \
                patch.object(MeruhenTarget, 'alias_file', str(self.folder / 'aliases.json')):
            converter.load_paths([self.html])
        self.assertEqual(str(converter.save_button['state']), 'disabled')
        self.assertEqual(str(converter.other_button['state']), 'normal')
        with patch.object(ui, 'OTHER_ANALYSIS_DIR', self.folder / 'other'), \
                patch.object(ui.messagebox, 'showinfo') as shown, \
                patch.object(converter.target, 'make_backup') as regular_save:
            converter.save_other()
        path = self.folder / 'other/saiwaichou/other-analysis-saiwaichou-20260901.json'
        self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))['records']), 2)
        self.assertIn('databaseに読み込みません', shown.call_args.args[1])
        regular_save.assert_not_called()
        self.assertFalse((self.folder / 'aliases.json').exists())
        root.geometry('800x600')
        root.update_idletasks()
        row = converter.other_button.master
        self.assertLessEqual(row.winfo_reqwidth(), 800 - 44)
        from test_anaslo_converter import html as p_station_html
        other_hall = self.folder / '2026_09_15.html'
        other_hall.write_bytes(p_station_html())
        with patch('anaslo_converter.read_catalog', return_value=[]), \
                patch.object(service.PscubeTarget, 'alias_file', str(self.folder / 'p_aliases.json')):
            converter.load_paths([other_hall])
        self.assertEqual(str(converter.other_button['state']), 'disabled')


if __name__ == '__main__':
    unittest.main()
