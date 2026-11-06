"""HTML変換アプリの動作改善（2026-11-06）の再発防止。

- P-STATION のHTMLを1回だけ解析する（以前は店舗の見分けと貸玉付けで2回）。
- 解析結果の控え（同じHTMLの2回目以降は解析しない。規則が変われば使わない）。
- 「補完用JSONを保存」の変換・書き込みを別のスレッドで行う。
- P’s CUBE に実データがある台・日は JSON に入れない（アナスロの補完どうしは入れる）。
- 取得期間の初期値（DBの台数が足りない日のいちばん新しい連続範囲）。
- 取得ブラウザで日付リンクを押したら、その場で開始を聞く。
- PC版の「バックアップを読み込む」は、変換アプリの保存から3時間はその保存先を開く。
"""
from datetime import date
import gc
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import anaslo_converter
import anaslo_html
from anaslo_converter import analyze, make_backup, read_native_occupied, suggest_period
from anaslo_html import convert, parse_cached, prune_cache
from pscube_import import PscubeStore
from test_anaslo_converter import html
from test_pscube_sync import machine, put, record

CONVERTER = Path(__file__).resolve().parents[2] / 'html_converter'
if str(CONVERTER) not in sys.path:
    sys.path.append(str(CONVERTER))


def two_rack_html(day='2026/09/15'):
    """101番台と102番台の2台。"""
    columns = ['機種名', '台番号', 'G数', 'BB', 'RB', 'ART', '合成確率', 'BB確率', 'RB確率', 'ART確率']
    rows = [['マイジャグラーV', str(rack), '3,000', '8', '4', '0', '1/250.0', '1/375.0', '1/750.0', '1/0.0'] for rack in (101, 102)]

    def table(identity):
        return (f'<table {identity}><tr>' + ''.join(f'<th>{v}</th>' for v in columns) + '</tr>'
                + ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>' for row in rows) + '</table>')
    graphs = ''.join(f'<script>var x_value = [0, 1];var y_value = [100, 80];document.getElementById("{r}");'
                     'if(context.tick.value == 100){}</script>' for r in (101, 102))
    return (f'<h1>{day} P-STATION&amp;IIスロット館 データまとめ</h1>'
            f'<link rel="canonical" href="https://ana-slo.com/{day.replace("/", "-")}-p-stationii-data/">'
            + table('id="all_data_table"') + table('') + graphs).encode('utf-8')


class ParseOnceAndCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paths = []
        for day in ('2026/09/15', '2026/09/16'):
            path = self.root / f'{day.replace("/", "_")}.html'
            path.write_bytes(html(day=day))
            self.paths.append(path)

    def test_p_station_is_parsed_once_with_the_same_result(self):
        expected = convert(self.paths, '20')
        expected['hall'] = 'p-station'
        real = anaslo_html.parse_html
        calls = []
        with patch.object(anaslo_html, 'parse_html', side_effect=lambda *a: calls.append(a[1]) or real(*a)):
            staging = analyze(self.paths)
        self.assertEqual(sorted(calls), sorted(p.name for p in self.paths), '1ファイル1回だけ解析する')
        self.assertEqual(staging, expected)
        self.assertEqual({d['store']['rate'] for d in staging['days']}, {'20'})

    def test_cache_gives_the_same_result_and_skips_parsing(self):
        cache = self.root / 'cache'
        cold = analyze(self.paths, cache_dir=cache)
        self.assertEqual(len(list(cache.glob('*.json'))), 2)
        with patch.object(anaslo_html, 'parse_html', side_effect=AssertionError('控えがあれば解析しない')):
            warm = analyze(self.paths, cache_dir=cache)
        self.assertEqual(cold, warm)
        self.assertEqual(cold, analyze(self.paths))
        # 控えの中で貸玉を付けても、控えそのものは変わらない（別の店舗の扱いに漏れない）
        stored = json.loads(next(cache.glob('*.json')).read_text(encoding='utf-8'))
        self.assertIsNone(stored['day']['store']['rate'])

    def test_cache_is_ignored_when_the_parser_changes_or_the_file_is_broken(self):
        cache = self.root / 'cache'
        raw = self.paths[0].read_bytes()
        parse_cached(raw, self.paths[0].name, cache)
        stored = next(cache.glob('*.json'))
        stored.write_text('{broken', encoding='utf-8')
        self.assertEqual(parse_cached(raw, self.paths[0].name, cache), anaslo_html.parse_html(raw, self.paths[0].name))
        with patch.object(anaslo_html, '_PARSER_REVISION', 'other'):
            calls = []
            real = anaslo_html.parse_html
            with patch.object(anaslo_html, 'parse_html', side_effect=lambda *a: calls.append(1) or real(*a)):
                parse_cached(raw, self.paths[0].name, cache)
            self.assertEqual(calls, [1], '解析の規則が変わったら控えを使わない')

    def test_same_html_under_a_wrong_date_name_still_fails(self):
        cache = self.root / 'cache'
        raw = self.paths[0].read_bytes()
        parse_cached(raw, self.paths[0].name, cache)
        with self.assertRaises(ValueError):
            parse_cached(raw, '2026_09_20.html', cache)  # ファイル名の日付の検査は控えでも省かない

    def test_unreadable_html_is_not_cached(self):
        cache = self.root / 'cache'
        with self.assertRaises(ValueError):
            parse_cached(b'<html></html>', 'x.html', cache)
        self.assertFalse(cache.exists() and any(cache.iterdir()))

    def test_prune_keeps_the_most_recently_used(self):
        cache = self.root / 'cache'
        cache.mkdir()
        for i in range(5):
            f = cache / f'{i}.json'
            f.write_text('{}', encoding='utf-8')
            os.utime(f, (1000 + i, 1000 + i))
        self.assertEqual(prune_cache(cache, keep=2), 3)
        self.assertEqual(sorted(f.name for f in cache.iterdir()), ['3.json', '4.json'])


class NativeRecordsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / 'pscube.sqlite3'
        self.store = PscubeStore(self.db_path)
        self.addCleanup(self.store.close)
        self.m = machine()

    def test_racks_with_real_pscube_data_are_left_out_but_anaslo_fills_stay(self):
        put(self.store, self.m, [record(self.m, 101, '2026-09-15'),
                                 record(self.m, 102, '2026-09-16', source_site='anaslo')])
        native = read_native_occupied(self.db_path)
        self.assertEqual(native, {('2026-09-15', 101)})
        paths = []
        for day in ('2026/09/15', '2026/09/16'):
            path = self.root / f'{day.replace("/", "_")}.html'
            path.write_bytes(two_rack_html(day))
            paths.append(path)
        payload = make_backup(analyze(paths), {'マイジャグラーV': self.m['machine']}, [self.m], native)
        kept = sorted((r['day'], r['rack']) for r in payload['records'])
        self.assertEqual(kept, [('2026-09-15', 102), ('2026-09-16', 101), ('2026-09-16', 102)])
        self.assertEqual(payload['conversion_summary']['skipped'], {'existing': 1})

    def test_only_real_data_gives_a_clear_error(self):
        put(self.store, self.m, [record(self.m, 101, '2026-09-15')])
        path = self.root / '2026_09_15.html'
        path.write_bytes(html())
        with self.assertRaisesRegex(ValueError, 'P’s CUBEに実データ'):
            make_backup(analyze([path]), {'マイジャグラーV': self.m['machine']}, [self.m], read_native_occupied(self.db_path))

    def test_target_reads_real_data_read_only(self):
        put(self.store, self.m, [record(self.m, 101, '2026-09-15')])
        target = anaslo_converter.PscubeTarget(self.root)
        self.assertEqual(target.native, {('2026-09-15', 101)})
        self.assertEqual(read_native_occupied(self.root / 'missing.sqlite3'), frozenset())


class SuggestPeriodTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'downloads'
        self.folder.mkdir()
        self.store = PscubeStore(self.root / 'pscube.sqlite3')
        self.addCleanup(self.store.close)
        self.m = machine()

    def fill(self, counts):
        rows = []
        for day, count in counts.items():
            rows += [record(self.m, 100 + i, day) for i in range(count)]
        put(self.store, self.m, rows)

    def test_latest_contiguous_short_days_without_saved_html(self):
        # 11/6 に開く：直近14日（10/23〜11/5）のうち 10/30・11/3・11/4 が足りない。11/1 はHTML保存済み。
        counts = {f'2026-10-{d:02d}': 10 for d in range(23, 32)}
        counts.update({'2026-11-01': 3, '2026-11-02': 10, '2026-11-03': 2, '2026-11-04': 0, '2026-11-05': 10,
                       '2026-10-30': 4})
        self.fill({d: c for d, c in counts.items() if c})
        (self.folder / '2026-11-01-p-station-abc.html').write_bytes(b'x')
        found = suggest_period('p-station', self.root, self.folder, date(2026, 11, 6))
        self.assertEqual((found['start'], found['end']), ('2026-11-03', '2026-11-04'))
        self.assertIn('2026-11-01', found['note'])   # 変換だけで補える日
        self.assertIn('2026-10-30', found['note'])   # ほかの足りない日（範囲に入れない）

    def test_a_few_racks_less_are_not_short(self):
        # 直近14日（10/23〜11/5）がそろっていて、10/31 だけ2台少ない（台の入替くらいの差）。
        self.fill({f'2026-10-{d:02d}': 100 for d in range(23, 31)} | {f'2026-11-{d:02d}': 100 for d in range(1, 6)}
                  | {'2026-10-31': 98})
        self.assertIsNone(suggest_period('p-station', self.root, self.folder, date(2026, 11, 6)))

    def test_days_without_any_record_are_short(self):
        self.fill({f'2026-10-{d:02d}': 10 for d in range(23, 32)} | {f'2026-11-{d:02d}': 10 for d in range(1, 4)})
        found = suggest_period('p-station', self.root, self.folder, date(2026, 11, 6))
        self.assertEqual((found['start'], found['end']), ('2026-11-04', '2026-11-05'))

    def test_no_data_gives_no_suggestion(self):
        self.assertIsNone(suggest_period('p-station', self.root, self.folder, date(2026, 11, 6)))
        self.assertIsNone(suggest_period('saiwaichou', self.root, self.folder, date(2026, 11, 6)))


class DialogSuggestionTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        gc.collect()

    def setUp(self):
        gc.collect()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_dialog_fills_the_suggestion_and_keeps_typed_dates(self):
        from download_dialog import DownloadDialog
        answers = {'p-station': {'start': '2026-11-03', 'end': '2026-11-04', 'note': '初期値はP’s CUBEの台数が足りない日'},
                   'saiwaichou': None}
        with patch('anaslo_converter.suggest_period', side_effect=lambda key, *a: answers[key]):
            dialog = DownloadDialog(self.root, lambda paths: None, suggest=True)
            dialog.withdraw()
            self.assertEqual((dialog.start_day.get(), dialog.end_day.get()), ('2026-11-03', '2026-11-04'))
            self.assertIn('台数が足りない日', dialog.status.get())
            dialog.hall.set('saiwaichou')
            dialog.choose_hall()
            self.assertEqual((dialog.start_day.get(), dialog.end_day.get()), ('', ''), '店舗に合わせて出し直す')
            dialog.start_day.set('2026-09-01')
            dialog.end_day.set('2026-09-02')
            dialog.hall.set('p-station')
            dialog.choose_hall()
            self.assertEqual((dialog.start_day.get(), dialog.end_day.get()), ('2026-09-01', '2026-09-02'), '手で入れた日付は変えない')
            dialog.destroy()

    def test_tests_and_default_open_without_suggestion(self):
        from download_dialog import DownloadDialog
        with patch('anaslo_converter.suggest_period', side_effect=AssertionError('呼ばない')):
            dialog = DownloadDialog(self.root, lambda paths: None)
            dialog.withdraw()
            self.assertEqual(dialog.start_day.get(), '')
            dialog.destroy()


class BackgroundSaveTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        gc.collect()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        gc.collect()
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        spec = importlib.util.spec_from_file_location('converter_save_test', CONVERTER / 'app.py')
        self.ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ui)

    def test_save_builds_the_json_in_the_background(self):
        ui = self.ui
        converter = ui.Converter(self.root)
        converter.parse_cache = None
        converter.aliases = {}
        path = self.folder / '2026-09-15.html'
        path.write_bytes(html())
        with patch('anaslo_converter.read_catalog', return_value=[]), \
                patch('anaslo_converter.read_native_occupied', return_value=frozenset()):
            converter.load_paths([path])
        converter.keep_remaining()
        converter.alias_file = self.folder / 'names.json'
        out = self.folder / 'out.json'
        import threading
        release = threading.Event()
        real = converter.target.make_backup

        def slow(staging, mapping):
            release.wait(5)
            return real(staging, mapping)
        # 同期フォルダが無いとき（あれば P-STATION はそこが初期値。test_anaslo_net.SyncFolderTests、2026-11-06）。
        with patch.object(ui, 'JSON_DIR', self.folder / 'json'), patch.object(ui, 'sync_folder', return_value=None), \
                patch.object(ui.filedialog, 'asksaveasfilename', return_value=str(out)) as choose, \
                patch.object(converter.target, 'make_backup', slow), \
                patch.object(ui.messagebox, 'showinfo') as shown:
            converter.save(background=True)
            self.assertEqual(choose.call_args.kwargs['initialdir'], str(self.folder / 'json'))
            self.assertTrue(converter.loading)
            self.assertEqual(str(converter.save_button.cget('state')), 'disabled', '途中は保存を押せない')
            ticks = []
            self.root.after(10, lambda: ticks.append(1))
            deadline = time.monotonic() + 1
            while not ticks and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.005)
            self.assertEqual(ticks, [1], '変換の途中でも画面のイベントが処理される')
            release.set()
            deadline = time.monotonic() + 5
            while converter.loading and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.005)
        self.assertFalse(converter.loading)
        self.assertTrue(out.is_file())
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['records'][0]['rack'], 101)
        self.assertIn('保存しました', shown.call_args.args[0])
        self.assertEqual(self.root.clipboard_get(), str(out))
        self.assertEqual(str(converter.save_button.cget('state')), 'normal')

    def test_save_error_is_shown_and_buttons_come_back(self):
        ui = self.ui
        converter = ui.Converter(self.root)
        converter.parse_cache = None
        converter.aliases = {}
        path = self.folder / '2026-09-15.html'
        path.write_bytes(html())
        with patch('anaslo_converter.read_catalog', return_value=[]), \
                patch('anaslo_converter.read_native_occupied', return_value=frozenset()):
            converter.load_paths([path])
        converter.keep_remaining()
        with patch.object(ui, 'JSON_DIR', self.folder / 'json'), \
                patch.object(ui.filedialog, 'asksaveasfilename', return_value=str(self.folder / 'out.json')), \
                patch.object(converter.target, 'make_backup', side_effect=ValueError('テストの失敗')), \
                patch.object(ui.messagebox, 'showerror') as error:
            converter.save(background=True)
            deadline = time.monotonic() + 5
            while converter.loading and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.005)
        self.assertIn('テストの失敗', error.call_args.args[1])
        self.assertEqual(str(converter.save_button.cget('state')), 'normal')
        self.assertFalse((self.folder / 'out.json').exists())


class BrowserStartTests(unittest.TestCase):
    def test_link_click_sets_the_notice_that_asks_to_start(self):
        from anaslo_browser_host import LINK_NOTICE, NavigationState
        state = NavigationState()
        from test_anaslo_download import link
        state.target(link('2026-09-15').url, False)
        self.assertFalse(state.starting(link('2026-09-16').url, 1))
        self.assertIs(state.notice, LINK_NOTICE)

    def test_ask_start(self):
        from anaslo_browser_host import ask_start

        class Window:
            def __init__(self, answer):
                self.answer = answer

            def create_confirmation_dialog(self, title, message):
                if isinstance(self.answer, Exception):
                    raise self.answer
                self.asked = (title, message)
                return self.answer
        yes = Window(True)
        self.assertTrue(ask_start(yes))
        self.assertIn('表示を確認して自動取得を開始', yes.asked[1])
        self.assertFalse(ask_start(Window(False)))
        self.assertFalse(ask_start(Window(None)))
        self.assertFalse(ask_start(Window(RuntimeError('no dialog'))))


class PcImportFolderTests(unittest.TestCase):
    def test_converter_folder_is_opened_only_soon_after_a_save(self):
        import app
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            self.assertEqual(app.recent_converter_folder(folder, now=10_000), {})
            f = folder / 'pscube-backup-anaslo-20261101.json'
            f.write_text('{}', encoding='utf-8')
            os.utime(f, (10_000, 10_000))
            self.assertEqual(app.recent_converter_folder(folder, now=10_000 + 3600), {'initialdir': str(folder)})
            self.assertEqual(app.recent_converter_folder(folder, now=10_000 + 4 * 3600), {})
        self.assertEqual(app.recent_converter_folder(Path(name) / 'gone'), {})
        self.assertEqual(app.CONVERTER_JSON_DIR, CONVERTER / 'data' / 'backup_json')


if __name__ == '__main__':
    unittest.main()
