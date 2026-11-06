"""アナスロで補った台の推定差枚（anaslo_net.py、2026-11-06）。サイトには接続しない。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anaslo_net  # noqa: E402
import pscube_import  # noqa: E402

JUG = 'ﾏｲｼﾞｬｸﾞﾗｰV'
AT = 'L東京喰種'
# 段1（1000枚を90px）しか出ない表・式。ずれ σ=s√G。
MODEL = {'method': anaslo_net.METHOD, 'days': [], 'tv': [0, 0, 0, 0, 0],
         'counts': {JUG: [240, 100, -1.2, 10.0], AT: [240, 100, -1.2, 10.0]},
         'prior': {}, 'prior_coarse': {str(b): {'1': 50, '2': 50} for b in range(0, 45)}}
SHA = 'a' * 64


def graph(heights):
    return {'kind': 'source_coordinates', 'points': [[i * 25, 312 - h] for i, h in enumerate(heights)],
            'zero_y': 312.0, 'y_increases_downward': True, 'medals_per_y_unit': None, 'games_per_x_unit': None}


def record(machine=JUG, heights=(0, -10, -20, -36), bb=5, rb=3, games=1500, **extra):
    return {'store': 'c740601', 'rate': '20', 'machine': machine, 'rack': 1235, 'day': '2026-11-04',
            'games': games, 'bb': bb, 'rb': rb, 'at_art': 0, 'my': None, 'detail_url': None, 'observed_at': None,
            'net_medals': None, 'graph': None, 'source_site': 'anaslo',
            'source_url': 'https://ana-slo.com/2026-11-04-p-stationiiスロット館-data/', 'source_sha256': SHA,
            'source_machine': 'マイジャグラーV', 'source_probabilities': {}, 'source_graph': graph(heights), **extra}


class EstimateTests(unittest.TestCase):
    def test_tier_rule_matches_the_measured_pixel_ranges(self):
        self.assertEqual([round(anaslo_net.upper(k)) for k in (1, 2, 3, 4)], [90, 120, 135, 144])
        self.assertEqual([round(anaslo_net.lower(k)) for k in (1, 2, 3, 4)], [0, 60, 90, 108])
        self.assertAlmostEqual(anaslo_net.ratio(1), 1000 / 90)
        self.assertAlmostEqual(anaslo_net.ratio(2), 1500 / 90)

    def test_a_small_swing_can_only_be_the_first_tier_and_is_sure(self):
        # 見えている山36px：段2（下限60px）は隠れた山が24px以上必要で、ありにくい。推定 240×5+100×3−1.2×1500＝−300。
        e = anaslo_net.estimate(record(), MODEL)
        self.assertEqual(e, {'value': -400, 'sure': True, 'method': anaslo_net.METHOD})   # −36px × 1000/90
        self.assertTrue(anaslo_net.valid(e))

    def test_an_ambiguous_swing_is_marked_for_normal_and_omitted_for_other_machines(self):
        # 見えている山75px：段1なら −833、段2なら −1250。BB・RB・G数の推定（−1050 付近）はどちらとも言えない。
        heights = (0, -30, -60, -75)
        normal = anaslo_net.estimate(record(heights=heights, bb=2, rb=1, games=1300), MODEL)
        self.assertIsNotNone(normal)
        self.assertFalse(normal['sure'])
        self.assertIsNone(anaslo_net.estimate(record(machine=AT, heights=heights, bb=2, rb=1, games=1300), MODEL),
                          'AT機などは確かな台だけ')

    def test_a_single_remaining_candidate_or_a_high_tier_is_never_sure(self):
        # 見えている山 169px：段14より下は上限で消え、候補が段14以上だけになる。上限が14だった頃は1つだけ残り、
        # 確からしさ1.0で2510枚外れた（Codex の独立検証 2026-11-06）。
        heights = (0, 40, 90, 140, 169)
        self.assertIsNone(anaslo_net.estimate(record(machine=AT, heights=heights, bb=20, rb=5, games=8000), MODEL))
        normal = anaslo_net.estimate(record(heights=heights, bb=20, rb=5, games=8000), MODEL)
        self.assertIsNotNone(normal)
        self.assertFalse(normal['sure'], '段が12より上は確かと言わない')
        self.assertGreaterEqual(anaslo_net.MAX_TIER, 40)

    def test_no_estimate_without_a_source_graph_a_known_machine_or_when_the_real_net_exists(self):
        self.assertIsNone(anaslo_net.estimate(record(source_graph=None), MODEL))
        self.assertIsNone(anaslo_net.estimate(record(machine='知らない機種'), MODEL))
        self.assertIsNone(anaslo_net.estimate({**record(), 'net_medals': 100}, MODEL))
        self.assertIsNone(anaslo_net.estimate({**record(), 'source_site': None}, MODEL))
        broken = record()
        broken['source_graph']['zero_y'] = 300.0
        self.assertIsNone(anaslo_net.estimate(broken, MODEL), 'ゼロ線が違うグラフは目盛りの規則が当てはまらない')

    def test_the_saved_model_file_loads(self):
        model = anaslo_net.load_model()
        self.assertEqual(model['method'], anaslo_net.METHOD)
        self.assertIn(JUG, model['counts'])
        self.assertEqual(len(model['tv']), 5)

    def test_shape_check(self):
        good = {'value': -400, 'sure': True, 'method': anaslo_net.METHOD}
        self.assertTrue(anaslo_net.valid(good))
        for bad in ({**good, 'value': 1.5}, {**good, 'sure': 1}, {**good, 'method': 'x'}, {**good, 'extra': 1},
                    {**good, 'value': 2000000}, None, [], {'value': 1}):
            self.assertFalse(anaslo_net.valid(bad), bad)


class StoreRuleTests(unittest.TestCase):
    def test_only_anaslo_records_may_carry_an_estimate(self):
        e = {'value': -400, 'sure': True, 'method': anaslo_net.METHOD}
        pscube_import._validate_record(record(net_estimate=e))
        with self.assertRaises(ValueError):
            pscube_import._validate_record(record(net_estimate={'value': 'x'}))
        real = {'store': 'c740601', 'rate': '20', 'machine': JUG, 'rack': 1235, 'day': '2026-11-04', 'games': 1500,
                'bb': 5, 'rb': 3, 'at_art': 0, 'my': 100, 'net_medals': -300, 'observed_at': None, 'graph': None,
                'detail_url': 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=1235#20261104',
                'net_estimate': e}
        with self.assertRaises(ValueError):
            pscube_import._validate_record(real)

    def test_merge_moves_a_later_estimate_onto_the_same_anaslo_page_only(self):
        e = {'value': -400, 'sure': True, 'method': anaslo_net.METHOD}
        old = record()
        merged = pscube_import._merge(old, record(net_estimate=e, games=9999))
        self.assertEqual(merged['net_estimate'], e)
        self.assertEqual(merged['games'], 1500, '数値・出典は先にある方のまま')
        other_page = record(net_estimate=e, source_sha256='b' * 64)
        self.assertNotIn('net_estimate', pscube_import._merge(old, other_page))
        real = {**record(), 'source_site': None, 'net_medals': -321}
        self.assertEqual(pscube_import._merge(record(net_estimate=e), real), real, '本当の取り込みが来たら置き換わる')
        self.assertEqual(pscube_import._merge(real, record(net_estimate=e)), real)


    def test_import_moves_the_estimate_onto_an_existing_supplement(self):
        import tempfile
        from test_pscube_sync import machine
        m = machine()
        base = {**record(), 'machine': m['machine']}
        e = {'value': -400, 'sure': True, 'method': anaslo_net.METHOD}
        payload = lambda r: {'format': 'pscube-viewer', 'version': 1, 'kind': 'backup', 'machines': [m], 'records': [r]}
        with tempfile.TemporaryDirectory() as tmp:
            store = pscube_import.PscubeStore(Path(tmp) / 't.sqlite3')
            try:
                self.assertEqual(store.import_backup(payload(base))['added'], 1)
                self.assertEqual(store.import_backup(payload({**base, 'net_estimate': e, 'source_sha256': 'b' * 64}))['updated'], 0)
                summary = store.import_backup(payload({**base, 'net_estimate': e}))
                self.assertEqual(summary['updated'], 1)
                saved = json.loads(store.db.execute('SELECT payload FROM records').fetchone()[0])
                self.assertEqual(saved['net_estimate'], e)
                self.assertEqual(store.import_backup(payload({**base, 'net_estimate': e}))['updated'], 0, '同じなら変えない')
            finally:
                store.close()


class ConverterTests(unittest.TestCase):
    def test_backup_records_carry_the_estimate_only_when_one_can_be_made(self):
        import tempfile
        from unittest import mock
        import anaslo_converter
        from test_pscube_sync import machine

        def page(zero):
            columns = ['機種名', '台番号', 'G数', 'BB', 'RB', 'ART', '合成確率', 'BB確率', 'RB確率', 'ART確率']
            values = ['マイジャグラーV', '101', '1,500', '5', '3', '0', '1/187.5', '1/300.0', '1/500.0', '1/0.0']
            table = lambda identity: (f'<table {identity}><tr>' + ''.join(f'<th>{v}</th>' for v in columns) + '</tr><tr>'
                                      + ''.join(f'<td>{v}</td>' for v in values) + '</tr></table>')
            return ('<h1>2026/09/15 P-STATION&amp;IIスロット館 データまとめ</h1>'
                    '<link rel="canonical" href="https://ana-slo.com/2026-09-15-p-stationii-data/">'
                    + table('id="all_data_table"') + table('')
                    + f'<script>var x_value = [0, 25, 50, 75];var y_value = [{zero}, {zero + 10}, {zero + 20}, {zero + 36}];'
                    + f'document.getElementById("101");if(context.tick.value == {zero}){{}}</script>').encode('utf-8')
        m = machine()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(anaslo_net, '_MODEL', {**MODEL, 'counts': {m['machine']: [240, 100, -1.2, 10.0]}}):
            path = Path(tmp) / '2026_09_15.html'
            path.write_bytes(page(312))
            payload = anaslo_converter.make_backup(anaslo_converter.analyze([path]), {'マイジャグラーV': m['machine']}, [m])
            self.assertEqual(payload['records'][0]['net_estimate'], {'value': -400, 'sure': True, 'method': anaslo_net.METHOD})
            path.write_bytes(page(100))   # ゼロ線が違う（規則が当てはまらない）グラフには付けない
            payload = anaslo_converter.make_backup(anaslo_converter.analyze([path]), {'マイジャグラーV': m['machine']}, [m])
            self.assertNotIn('net_estimate', payload['records'][0])
        store_dir = tempfile.TemporaryDirectory()
        self.addCleanup(store_dir.cleanup)


class SyncFolderTests(unittest.TestCase):
    """取ったら毎回、処理してドライブへ（2026-11-06 利用者「Aにして」）：変換アプリが同期フォルダに保存した補完を、
    起動中のPC版が数分おきに自動で読み込む。"""

    def test_the_pc_poll_picks_up_converter_supplements_but_not_its_own_exports(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            names = ['pscube-backup-anaslo-20261104-20261105.json', 'pscube-backup-anaslo-20261106.json',
                     'pscube-day-android-2026-11-06.json', 'pscube-backup-auto.json', 'pscube-viewer-drive.json',
                     'pscube-backup-anaslo-2026.json']
            for i, name in enumerate(names):
                (Path(tmp) / name).write_text('{}', encoding='utf-8')
                os.utime(Path(tmp) / name, (1000 + i, 1000 + i))
            found = [name for name, _mtime, _path in pscube_import.android_sync_files(tmp)]
            self.assertEqual(found, names[:3])
            due, initial = pscube_import.android_sync_due(pscube_import.android_sync_files(tmp), {}, 10_000)
            self.assertIsNone(initial)
            self.assertEqual([name for name, _m, _p in due], names[:3], '書き込みが落ち着いたものを古い順に読む')

    def test_the_converter_saves_p_station_supplements_into_the_sync_folder(self):
        import importlib.util
        import tempfile
        from unittest import mock
        converter_dir = Path(__file__).resolve().parents[2] / 'html_converter'
        sys.path.append(str(converter_dir))
        spec = importlib.util.spec_from_file_location('converter_sync_test', converter_dir / 'app.py')
        ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ui)
        pscube = ui.PscubeTarget.__new__(ui.PscubeTarget)
        meruhen = ui.MeruhenTarget.__new__(ui.MeruhenTarget)
        with tempfile.TemporaryDirectory() as tmp, mock.patch('core.load_settings', return_value={'sync_dir': tmp}):
            self.assertEqual(ui.json_folder(pscube), Path(tmp))
            self.assertEqual(ui.json_folder(meruhen), ui.JSON_DIR, '幸町は今まで通り')
            self.assertTrue(pscube_import.ANDROID_SYNC_NAME.fullmatch(pscube.file_name('20261104-20261105')))
        with mock.patch('core.load_settings', return_value={'sync_dir': str(Path(tmp) / 'gone')}):
            self.assertEqual(ui.json_folder(pscube), ui.JSON_DIR, '同期フォルダが見つからなければ今まで通り')


if __name__ == '__main__':
    unittest.main()
