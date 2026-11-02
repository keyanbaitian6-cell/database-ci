"""採点と翌日候補が、PC（core.py）とAndroid・閲覧ページ（scoring.dart・list_views.dart）で同じになること（2026-11-01）。

同じ計算が2つの言語で書かれている。片方だけ直すと、PCと閲覧ページで点数・候補が食い違っても気づきにくい。
以前の照合（audit_scoring.py → tool/check_scoring_parity.dart、check_candidate_parity.py）は実データを
使う手動の道具で、毎回の試験には入っていなかった。

ここでは乱数の種を固定した合成データ（実データではない）を作り、PCで計算した点数・候補を
`database_android/test/fixtures/scoring_parity.json` に保存しておく。
- この試験（PC）：保存した合成データからPCで計算し直し、保存した期待値と一致すること。
- `database_android/test/scoring_parity_test.dart`（Android）：同じ合成データからDartで計算し、同じ期待値と一致すること。

採点・候補の仕様を意図して変えたときは、`database/` で
`python tests/test_scoring_parity.py --write` を実行して期待値を作り直し、Dart側も同じ結果になるよう直す。
"""
import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest_candidates import Rows  # noqa: E402
from core import NEW_MACHINE_SCORING_VERSION, VERSION, day_candidates, score  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[2] / 'database_android' / 'test' / 'fixtures' / 'scoring_parity.json'
SCORE_FIELDS = ('games', 'max_hold', 'hits', 'positive', 'retention', 'total',
                'reference_count', 'reference_days', 'hold_reference_count', 'coverage',
                'missing_low', 'missing_high', 'provisional')
# 4台以上の機種（機種ごとの候補）と、1〜3台の機種（バラエティ）を両方含める。
MACHINES = (('マイジャグラーV', 6), ('試験機種A', 5), ('試験機種B', 4), ('少数機種C', 2), ('少数機種D', 1))
STORES = (('nagamachiminami', 100), ('saiwaichou', 500))
DAYS = 16


def synthetic_rows(seed=20261101):
    """実データを使わない合成の記録。採点の分かれ道（未稼働・500G以下・異常値・グラフ無し・最大持ち玉無し）を含む。"""
    rng = random.Random(seed)
    rows = []
    for store, first_rack in STORES:
        rack = first_rack
        racks = []
        for machine, count in MACHINES:
            racks += [(machine, rack + i) for i in range(count)]
            rack += 10
        for d in range(DAYS):
            day = f'2026-10-{d + 1:02d}'
            for machine, number in racks:
                roll = rng.random()
                games = (0 if roll < .04 else rng.randint(1, 500) if roll < .12
                         else rng.randint(501, 9000))
                rate = rng.uniform(1 / 400, 1 / 120)
                hits = round(games * rate)
                bb = rng.randint(0, hits)
                row = dict(store=store, day=day, machine=machine, rack=number, games=games,
                           bb=bb, rb=hits - bb, captured_at=f'{day}T23:00:00+09:00')
                if rng.random() < .85:
                    row['max_hold'] = rng.randint(0, 4000)
                if games and rng.random() < .8:
                    up, down = rng.randint(0, 80), rng.randint(0, 80)
                    row['graph_measurement'] = dict(baseline_y=100.0, peak_y=100.0 - up, trough_y=100.0 + down,
                                                    end_y=round(rng.uniform(100.0 - up, 100.0 + down), 2))
                if rng.random() < .01:
                    row.update(games=88888888, bb=888, rb=888)  # サイトの整備中表示（採点しない）
                rows.append(row)
    return rows


def expected(rows):
    scores = [{k: s[k] for k in SCORE_FIELDS} for s in (score(r, rows) for r in rows)]
    # 画面に出す点数（2026-11-03、新台は同じ日の同じ機種のほかの台と比べる。合成データの初日は全機種が新台）。
    by_day = {}
    for r in rows:
        by_day.setdefault((r['store'], r['day']), []).append(r)
    display = [{k: s[k] for k in SCORE_FIELDS} for s in
               (score(r, rows, same_day=by_day[(r['store'], r['day'])]) for r in rows)]
    data = Rows(rows)
    candidates = []
    for store, day in sorted({(r['store'], r['day']) for r in rows}):
        for c in day_candidates(data, day, store):
            candidates.append(dict(store=store, day=day, machine=c['row']['machine'], rack=int(c['row']['rack']),
                                   index=c['index'], days=c['days']))
    return scores, candidates, display


def write():
    rows = synthetic_rows()
    scores, candidates, display = expected(rows)
    fixture = dict(note='合成データ（実データではない）。database/tests/test_scoring_parity.py --write で作る。',
                   version=VERSION, new_machine_version=NEW_MACHINE_SCORING_VERSION, rows=rows, scores=scores,
                   candidates=candidates, display_scores=display)
    FIXTURE.write_text(json.dumps(fixture, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f'{FIXTURE.name}: {len(rows)}台×日, 採点あり {sum(s["total"] is not None for s in scores)}, 候補 {len(candidates)}')


class ScoringParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def test_fixture_is_the_current_version_and_synthetic_rows(self):
        self.assertEqual(self.fixture['version'], VERSION, '採点版が変わった：--write で作り直し、Dart側も確かめる')
        self.assertEqual(self.fixture['rows'], synthetic_rows())

    def test_fixture_covers_every_branch(self):
        scores, rows = self.fixture['scores'], self.fixture['rows']
        self.assertTrue(any(s['total'] is not None and not s['provisional'] for s in scores))
        self.assertTrue(any(s['total'] is not None and s['provisional'] for s in scores))
        self.assertTrue(any(r['games'] == 0 for r in rows))
        self.assertTrue(any(0 < r['games'] <= 500 for r in rows))
        self.assertTrue(any(r['games'] == 88888888 for r in rows))
        self.assertTrue(any('graph_measurement' not in r and r['games'] > 500 for r in rows))
        self.assertTrue(any('max_hold' not in r and r['games'] > 500 for r in rows))
        machines = {c['machine'] for c in self.fixture['candidates']}
        self.assertTrue({'少数機種C', '少数機種D'} & machines, 'バラエティの候補が無い')
        self.assertTrue({'マイジャグラーV', '試験機種A', '試験機種B'} & machines, '機種ごとの候補が無い')
        # 新台の扱い：初日は画面の点数だけ同じ日のほかの台と比べ、候補・検証用の点数（scores）は今までどおり。
        changed = [i for i, (a, b) in enumerate(zip(scores, self.fixture['display_scores'])) if a != b]
        self.assertTrue(changed)
        self.assertTrue(all(rows[i]['day'] == '2026-10-01' for i in changed), '新台（過去の記録なし）の日だけ変わる')

    def test_pc_matches_saved_scores_and_candidates(self):
        scores, candidates, display = expected(self.fixture['rows'])
        self.assertEqual(len(scores), len(self.fixture['scores']))
        self.assertEqual(self.fixture['new_machine_version'], NEW_MACHINE_SCORING_VERSION)
        for row, actual, wanted in [*zip(self.fixture['rows'], scores, self.fixture['scores']),
                                    *zip(self.fixture['rows'], display, self.fixture['display_scores'])]:
            for key in SCORE_FIELDS:
                if isinstance(wanted[key], float) or isinstance(actual[key], float):
                    self.assertAlmostEqual(actual[key], wanted[key], places=8, msg=(row['store'], row['day'], row['rack'], key))
                else:
                    self.assertEqual(actual[key], wanted[key], (row['store'], row['day'], row['rack'], key))
        self.assertEqual(len(candidates), len(self.fixture['candidates']))
        for actual, wanted in zip(candidates, self.fixture['candidates']):
            self.assertEqual({k: v for k, v in actual.items() if k != 'index'},
                             {k: v for k, v in wanted.items() if k != 'index'})
            self.assertAlmostEqual(actual['index'], wanted['index'], places=8, msg=wanted)


if __name__ == '__main__':
    if '--write' in sys.argv:
        write()
    else:
        unittest.main()
