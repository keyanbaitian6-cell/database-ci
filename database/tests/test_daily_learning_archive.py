"""アナスロの分析用JSONを日次学習の過去の学習にだけ足す（daily_learning_archive.py、2026-11-12）。"""
import json
from pathlib import Path
import tempfile
import unittest

import daily_learning as d
import daily_learning_archive as archive
import daily_learning_runtime as runtime

STORE = 'pscube:c740601:20'


def record(day, rack, machine='ﾏｲｼﾞｬｸﾞﾗｰV', end=20, games=4000):
    return {'store': 'p-station', 'day': day, 'rack': rack, 'machine': machine, 'source_machine': machine,
            'games': games, 'bb': 20, 'rb': 10, 'rate': '20', 'at_art': 0, 'source_site': 'anaslo',
            'source_graph': {'kind': 'anaslo', 'zero_y': 50, 'points': [[0, 50], [10, end]]},
            'source_probabilities': {'combined': 1}}


def db_row(day, rack, site=None, machine='ﾏｲｼﾞｬｸﾞﾗｰV', end=20):
    r = {'store': STORE, 'rate': '20', 'day': day, 'rack': rack, 'machine': machine, 'games': 4000, 'bb': 20, 'rb': 10,
         'graph': {'kind': 'daily', 'zero_y': 50, 'points': [[0, 50], [10, end]]}}
    if site:
        r['source_site'] = site
    return r


class ArchiveTests(unittest.TestCase):
    def folder(self, temp, docs):
        path = Path(temp) / 'pst'
        path.mkdir()
        for i, records in enumerate(docs):
            (path / f'normal-analysis-p-station-{i}.json').write_text(json.dumps(
                {'format': 'database-normal-analysis', 'version': 1, 'records': records}, ensure_ascii=False), encoding='utf-8')
        return {STORE: path}

    def test_load_normalizes_graph_and_dedupes(self):
        with tempfile.TemporaryDirectory() as temp:
            folders = self.folder(temp, [[record('2026-10-01', 1), record('2026-10-01', 1), record('2026-10-02', 2)],
                                         [record('2026-10-02', 2, end=80), record('2026-12-01', 3)]])
            rows = archive.load(STORE, '2026-09-01', '2026-11-30', folders)
            self.assertEqual([(r['day'], r['rack']) for r in rows], [('2026-10-01', 1)])   # 矛盾する重複は両方使わない・範囲外は読まない
            r = rows[0]
            self.assertEqual((r['store'], r['rate'], r['archive']), (STORE, '20', 'normal-analysis'))
            self.assertNotIn('source_graph', r)
            self.assertTrue(d.valid(r))
            self.assertEqual(d.outcome(r), 1)                     # グラフの終点がゼロ線より上
            self.assertFalse(d.valid(db_row('2026-10-01', 1, 'anaslo')))   # 原本DBのアナスロ行は今までどおり使わない
            self.assertEqual(archive.load(STORE, '2026-09-01', '2026-11-30', {STORE: Path(temp) / 'none'}), [])

    def test_old_format_zero_line_is_the_first_point(self):
        """2026-11-21：P-STATIONの古い形式（1〜8月前半）は zero_y が 0 のまま。最初の点（x=0）をゼロ線にする。
        直す前は、ゼロ線より上（yが312より小さい）で終わった台も「プラスでない」と読まれていた。"""
        def old(day, rack, end, first=(0, 312)):
            r = record(day, rack)
            r['source_graph'] = {'kind': 'source_coordinates', 'zero_y': 0.0, 'y_increases_downward': True,
                                 'points': [list(first), [100, 300], [300, end]]}
            return r
        new = record('2026-10-03', 9)
        new['source_graph'] = {'kind': 'source_coordinates', 'zero_y': 312.0, 'points': [[0, 312], [300, 250]]}
        with tempfile.TemporaryDirectory() as temp:
            folders = self.folder(temp, [[old('2026-03-01', 1, 250), old('2026-03-01', 2, 400),
                                          old('2026-03-01', 3, 312.5), old('2026-03-01', 4, 250, first=(0, 0)),
                                          old('2026-03-01', 5, 250, first=(5, 312)), new]])
            rows = {r['rack']: r for r in archive.load(STORE, '2026-01-01', '2026-12-31', folders)}
        self.assertEqual({k: d.outcome(r) for k, r in rows.items()}, {1: 1, 2: 0, 3: None, 4: 0, 5: 0, 9: 1})
        self.assertEqual((rows[1]['graph']['zero_y'], rows[1]['graph']['zero_from']), (312., 'first-point'))
        for rack in (4, 5, 9):           # 最初の点が0・x=0でない・新しい形式は、そのまま
            self.assertNotIn('zero_from', rows[rack]['graph'])
        self.assertIn('+' + archive.ZERO_FIX, runtime.method_signature(STORE))
        self.assertNotIn(archive.ZERO_FIX, runtime.method_signature('saiwaichou'))
        self.assertNotIn(archive.ZERO_FIX, runtime.method_signature('nagamachiminami'))

    def test_merge_prefers_database_and_never_touches_input_day(self):
        with tempfile.TemporaryDirectory() as temp:
            folders = self.folder(temp, [[record('2026-10-01', 1, end=80), record('2026-10-01', 2), record('2026-10-02', 3),
                                          record('2026-11-11', 4), record('2026-11-12', 5)]])
            rows = [db_row('2026-10-01', 1),                        # 有効な原本DBの行を優先
                    db_row('2026-10-01', 2, 'anaslo'),              # 無効なアナスロ行はJSONで置き換える
                    db_row('2026-11-12', 6, 'site777')]             # 前日データ（入力の日）
            merged = archive.merge(rows, STORE, '2026-11-13', folders)
            by = {(r['day'], r['rack']): r for r in merged}
            self.assertNotIn('archive', by[('2026-10-01', 1)])
            self.assertEqual(by[('2026-10-01', 1)]['graph']['points'][-1][1], 20)
            self.assertEqual(by[('2026-10-01', 2)]['archive'], 'normal-analysis')
            self.assertEqual(sum(1 for r in merged if (r['day'], r['rack']) == ('2026-10-01', 2)), 1)
            self.assertIn(('2026-11-11', 4), by)                    # 対象日の2日前まで
            self.assertNotIn(('2026-11-12', 5), by)                 # 前日（入力の日）には足さない
            self.assertIn(('2026-11-12', 6), by)
            d.History(merged)                                       # 同じ日・台の重複が無い
            self.assertEqual(archive.merge(rows, 'nagamachiminami', '2026-11-13', folders), rows)

    def test_candidates_use_database_rows_only(self):
        # 従来候補（baseline）は原本DBの行だけで作り、学習だけが分析用JSONを使う。
        rows = [{'store': 'saiwaichou', 'rate': '', 'day': d.shift('2026-11-01', i), 'rack': rack, 'machine': '試験機',
                 'games': 4000, 'bb': 20, 'rb': 10, 'jo_net': 100 if (i + rack) % 2 else -100,
                 'graph_measurement': {'baseline_y': 50, 'end_y': 25, 'peak_y': 20, 'trough_y': 80}}
                for i in range(10) for rack in range(1, 9)]
        extra = [r | {'day': d.shift('2026-06-01', i), 'archive': 'normal-analysis'} for i in range(100) for r in rows[:8]]
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'j.sqlite3')
            try:
                a = runtime.build_prediction(rows, {'records': [], 'machines': []}, '2026-11-11', j)
                b = runtime.build_prediction(rows, {'records': [], 'machines': []}, '2026-11-11', j,
                                             history_rows=sorted(extra + rows, key=lambda r: (r['day'], d.identity(r))))
            finally:
                j.close()
        self.assertEqual([g['current'] for g in a['groups']], [g['current'] for g in b['groups']])
        self.assertEqual([[p['id'] for p in g['pool']] for g in a['groups']], [[p['id'] for p in g['pool']] for g in b['groups']])
        self.assertFalse(any(g['trained'] for g in a['groups']))   # 原本DBの10日分だけでは学習不足
        self.assertTrue(all(g['trained'] for g in b['groups']))    # 足すと学習できる


if __name__ == '__main__':
    unittest.main()
