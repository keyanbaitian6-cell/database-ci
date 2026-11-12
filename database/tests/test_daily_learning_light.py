"""日次学習の軽量化（2026-11-12、A〜D）。どれも以前の書き方と同じ結果になることを確かめる。"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest

import daily_learning as d
import daily_learning_runtime as runtime


def rows_with_changes(seed):
    """機種の入れ替え・名前だけの変わり目（P-STATION）・欠けた日・同じ日の新旧の名前を混ぜた架空の履歴。"""
    rng = random.Random(seed)
    out = []
    for store in ('nagamachiminami', 'pscube:c740601:20'):
        rate = '20' if store.startswith('pscube:') else ''
        for rack in range(1, 9):
            machine = rng.choice(['機種A', '機種B'])
            for i in range(120):
                day = d.shift('2026-06-01', i)
                if rng.random() < .08:
                    continue                                          # 欠けた日
                if rng.random() < .03:
                    machine = rng.choice(['機種A', '機種B', '機種C'])    # 入れ替え（同じ名前に戻ることもある）
                name = machine
                if store.startswith('pscube:') and machine == '機種A':
                    name = 'L Vivy' if i < 60 else 'L Vivy -Fluorite Eye’s Song-'   # 名前だけの変わり目
                row = dict(day=day, rack=rack, store=store, rate=rate, machine=name, games=rng.choice([0, 300, 2500, 6000]),
                           bb=10, rb=5, jo_net=rng.choice([-500, 0, 400, None]))
                if row['jo_net'] is None:
                    row.pop('jo_net')
                    if rng.random() < .5:
                        row['graph_measurement'] = dict(baseline_y=50, end_y=rng.choice([20, 50, 51, 80]))
                out.append(row)
                if store.startswith('pscube:') and name == 'L Vivy -Fluorite Eye’s Song-' and i == 60:
                    out.append(row | {'machine': 'L Vivy'})          # 同じ日に古い名前と新しい名前の両方
    return out


class LightTests(unittest.TestCase):
    def test_a_indexed_features_equal_full_scan(self):
        for seed in range(3):
            history = d.History(rows_with_changes(seed))
            for row in history.rows:
                self.assertEqual(history.features(row), history._features_by_scan(row), (seed, row['day'], row['rack']))

    def test_b_c_freeze_same_fingerprint_compressed_and_readable(self):
        rows = rows_with_changes(1)[:400]
        expected = {}
        for r in rows:
            expected.setdefault((str(r['store']), r['day']), []).append(r)
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'j.sqlite3')
            try:
                at = datetime.fromisoformat('2026-11-11T07:00:00+09:00')
                self.assertTrue(j.freeze('2026-11-11', {'groups': []}, rows, at, store='nagamachiminami'))
                p = j.get('predictions', '2026-11-11|nagamachiminami')
                # 指紋は以前の書き方（encoded(sorted(行, key=encoded)) の sha256）と同じ。
                old = sorted(d.digest(sorted(v, key=d.encoded)) for v in expected.values())
                self.assertEqual(sorted(p['inputs']['rows']), old)
                stored = j.db.execute('SELECT body FROM inputs LIMIT 1').fetchone()[0]
                self.assertIsInstance(stored, bytes)                         # 圧縮して保存
                self.assertEqual(sorted(j.input_rows(p), key=d.encoded), sorted(rows, key=d.encoded))
                # 以前の形式（圧縮していない文字）の記録もそのまま読める。
                with j.db:
                    j.db.execute('INSERT INTO inputs VALUES (?,?,?)', ('old', d.encoded([{'a': 1}]), d.digest([{'a': 1}])))
                    j.db.execute('INSERT INTO inputs VALUES (?,?,?)', ('bad', d.encoded([{'a': 2}]), d.digest([{'a': 1}])))
                self.assertEqual(j.get('inputs', 'old'), [{'a': 1}])
                with self.assertRaises(ValueError):                         # 指紋の照合は弱めない
                    j.get('inputs', 'bad')
                with self.assertRaises(sqlite3.IntegrityError):             # 書き換え・削除の拒否もそのまま
                    j.db.execute('DELETE FROM inputs')
                j.db.rollback()
                total = j.db.execute('SELECT SUM(LENGTH(body)) FROM inputs').fetchone()[0]
                raw = sum(len(d.encoded(sorted(v, key=d.encoded)).encode()) for v in expected.values())
                self.assertLess(total, raw / 2)
            finally:
                j.close()

    def test_d_decode_equals_compact(self):
        samples = [
            {'a': 1, 'preview_image': 'x' * 100, 'graph_measurement': {'end_y': 2, 'preview_image': 'y', 'curve': [[1, 2], [3, 4]]}},
            {'list': [{'screenshot': 1, 'k': [{'raw_html': '<p>', 'v': 3}]}, 5, 'image_base64'], 'image_base64': None},
            {'machine': 'ﾏｲｼﾞｬｸﾞﾗｰ', 'nested': {'deeper': {'preview_image': 1, 'keep': True}}},
            [], {}, 'text', 3,
        ]
        for value in samples:
            text = json.dumps(value, ensure_ascii=False)
            self.assertEqual(runtime.decode(text), runtime.compact(json.loads(text)))

    def test_append_text_matches_append(self):
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'j.sqlite3')
            try:
                body = {'b': [1, 2], 'a': '日本語'}
                with j.db:
                    j.append('decisions', 'x', body)
                sha = j.db.execute("SELECT sha FROM decisions WHERE key='x'").fetchone()[0]
                self.assertEqual(sha, d.digest(body))
                self.assertEqual(sha, hashlib.sha256(d.encoded(body).encode('utf-8')).hexdigest())
                self.assertEqual(j.get('decisions', 'x'), body)
            finally:
                j.close()


if __name__ == '__main__':
    unittest.main()
