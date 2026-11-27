import copy
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import daily_learning as d
import daily_learning_runtime as runtime


def row(day='2026-11-10', rack=1, win=True, store='nagamachiminami', machine='試験機'):
    return dict(day=day, rack=rack, store=store, machine=machine, games=4000, bb=20, rb=10,
                max_hold=2000, jo_net=100 if win else -100,
                graph_measurement=dict(baseline_y=50, end_y=25 if win else 75, peak_y=20, trough_y=80))


class LearningTests(unittest.TestCase):
    def test_node_resolves_without_codex_path(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = 'node.exe' if runtime.os.name == 'nt' else 'node'
            cached = Path(temp) / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin' / executable
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b'fixture')
            with patch.object(runtime.shutil, 'which', return_value=None):
                self.assertEqual(runtime.resolve_node(environ={'PATH': ''}, home=temp), str(cached))
                self.assertEqual(runtime.resolve_node('explicit-node', environ={}, home=temp), 'explicit-node')
                self.assertEqual(runtime.resolve_node(environ={'NODE': 'configured-node'}, home=temp), 'configured-node')
            with patch.object(runtime.shutil, 'which', return_value='path-node'):
                self.assertEqual(runtime.resolve_node(environ={'PATH': 'fixture'}, home=temp), 'path-node')

    def test_missing_zero_and_source(self):
        r = row()
        self.assertEqual(d.outcome(r), 1)
        r['jo_net'] = 0
        self.assertEqual(d.outcome(r), 0)
        r.pop('jo_net')
        r.pop('graph_measurement')
        self.assertIsNone(d.outcome(r))
        r['games'] = 0
        self.assertIsNone(d.outcome(r))
        r = row(store='pscube:c740601:20') | {'source_site': 'anaslo'}
        self.assertIsNone(d.outcome(r))

    def test_graph_tolerance_and_my_not_net(self):
        r = row()
        r.pop('jo_net')
        r['graph_measurement']['end_y'] = 49
        self.assertIsNone(d.outcome(r))
        r.pop('graph_measurement')
        r['my'] = 10000
        self.assertIsNone(d.outcome(r))

    def training_rows(self):
        return [row(d.shift('2026-08-01', i), rack, (i + rack) % 3 == 0)
                for i in range(100) for rack in range(1, 7)]

    def test_training_all_racks_and_future_independence(self):
        rows = self.training_rows()
        before = copy.deepcopy(rows)
        model = d.train(d.History(rows), '2026-10-10')
        changed = [r | {'jo_net': 9999} if r['day'] > '2026-10-02' else r for r in rows]
        self.assertEqual(model, d.train(d.History(changed), '2026-10-10'))
        key = d.identity(rows[0])[:3]
        self.assertEqual(model[key]['n'], 62 * 6)
        self.assertEqual(rows, before)

    def test_store_isolation_and_missing_models(self):
        rows = self.training_rows()
        other = [r | {'store': 'saiwaichou', 'jo_net': 999} for r in rows]
        a = d.train(d.History(rows), '2026-11-10')
        b = d.train(d.History(rows + other), '2026-11-10')
        self.assertEqual(a[d.identity(rows[0])[:3]], b[d.identity(rows[0])[:3]])
        self.assertIsNone(d.rank_pool([row(machine='新機種')], d.History(rows), a))

    def test_machine_change_resets_history(self):
        old = row('2026-11-01')
        changed = row('2026-11-05', machine='別機種')
        new = row('2026-11-10', win=False)
        a = d.History([old, changed, new]).features(new)
        b = d.History([changed, new]).features(new)
        self.assertEqual(a, b)

    def test_exact_next_calendar_day_not_next_record(self):
        rows = [row('2026-10-01'), row('2026-10-03')]
        self.assertEqual(d.train(d.History(rows), '2026-11-10'), {})

    @staticmethod
    def group(day, current, learned, k=2, missing_current=0., missing_learned=0., key='["nagamachiminami","","試験機"]',
              method='m1'):
        n_c, n_l = round(k * (1 - missing_current)), round(k * (1 - missing_learned))
        return dict(key=key, day=day, trained=True, method=method, current=current, learned=learned,
                    n_current=n_c, n_learned=n_l, k_current=k, k_learned=k,
                    plus_current=None if current is None else current * n_c,
                    plus_learned=None if learned is None else learned * n_l,
                    missing_current=missing_current, missing_learned=missing_learned)

    def test_fixed_period_adoption(self):
        days = [d.store_day(d.shift('2026-01-01', i), [self.group(d.shift('2026-01-01', i), .2, .8, k=1)])
                for i in range(112)]
        result = d.comparison(days, .025)
        self.assertTrue(result['adopt'])
        self.assertAlmostEqual(result['p'], 1 / 65536)          # 16週すべて正：符号反転の全組合せで最小
        self.assertFalse(d.comparison(days[:30], .025)['adopt'])
        missing = [d.store_day(x['day'], [self.group(x['day'], .2, .8, k=10, missing_learned=.1)]) for x in days]
        self.assertFalse(d.comparison(missing, .025)['adopt'])     # 欠測の悪化が2ポイント超
        self.assertFalse(d.comparison([d.store_day(x['day'], [self.group(x['day'], .2, .2)]) for x in days], .025)['adopt'])

    def test_flip_p_exact(self):
        # 全組合せを直接数えた値と一致する（半分ずつ数える方法の検算）。
        import itertools
        values = [.3, -.1, .2, .05, -.4, .25, .1]
        observed = sum(values)
        brute = sum(sum(s * v for s, v in zip(signs, values)) >= observed - 1e-12
                    for signs in itertools.product((1, -1), repeat=len(values))) / 2 ** len(values)
        self.assertAlmostEqual(d.flip_p(values), brute)
        self.assertEqual(d.flip_p([]), 1.)

    def test_store_day_equal_group_weight_and_missing_sensitivity(self):
        groups = [self.group('2027-01-01', .0, 1., k=1), self.group('2027-01-01', .5, .5, k=10)]
        day = d.store_day('2027-01-01', groups)
        self.assertAlmostEqual(day['diff'], .5)                  # 組を等しく重み付け（台数の多い組だけが効かない）
        # 学習版の候補だけが回されず判定不能になる例：除いた差は正でも、非プラスとみなすと負。
        g = self.group('2027-01-01', .4, .6, k=10, missing_learned=.5)
        day = d.store_day('2027-01-01', [g])
        self.assertGreater(day['diff'], 0)
        self.assertLess(day['diff_nonplus'], 0)
        days = [d.store_day(d.shift('2027-01-01', i), [self.group(d.shift('2027-01-01', i), .4, .6, k=10,
                                                                  missing_learned=.01 * (i % 2))]) for i in range(112)]
        self.assertTrue(d.comparison(days, .01)['adopt'])
        biased = [d.store_day(x['day'], [self.group(x['day'], .4, .6, k=10, missing_learned=.5)]) for x in days]
        self.assertFalse(d.comparison(biased, .01)['adopt'])

    def test_rollback_rule(self):
        def days(diff, missing=0.):
            return [d.store_day(d.shift('2027-01-01', i), [self.group(d.shift('2027-01-01', i), .5, .5 + diff, k=10,
                                                                      missing_learned=missing)]) for i in range(28)]
        self.assertTrue(d.rollback_needed(days(-.1)))
        self.assertFalse(d.rollback_needed(days(-.01)))
        self.assertTrue(d.rollback_needed(days(0, missing=.1)))
        self.assertFalse(d.rollback_needed(days(-.1)[:13]))      # 14日未満では判断しない

    def test_net_medals_sign_and_source(self):
        r = row(store='pscube:c740601:20')
        r.pop('graph_measurement')
        r.pop('jo_net')
        r['net_medals'] = -20
        self.assertEqual((d.outcome(r), d.outcome_source(r)), (0, 'net_medals'))
        r['net_medals'] = 30
        self.assertEqual(d.outcome(r), 1)
        r = row()
        self.assertEqual(d.outcome_source(r), 'jo_net')
        r.pop('jo_net')
        self.assertEqual(d.outcome_source(r), 'graph')
        r['net_estimate'] = {'value': 500}                       # 推定は使わない
        r['graph_measurement']['end_y'] = 50
        self.assertIsNone(d.outcome(r))

    def test_cutoff_and_immutable_predictions(self):
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                at = datetime.fromisoformat
                now = at('2026-11-11T07:59:59+09:00')
                self.assertTrue(j.freeze('2026-11-11', {'groups': []}, [row()], now))
                self.assertFalse(j.freeze('2026-11-11', {'groups': ['changed']}, [], now))
                self.assertEqual(j.get('predictions', '2026-11-11')['groups'], [])
                with self.assertRaises(sqlite3.IntegrityError):
                    j.db.execute("UPDATE predictions SET body='{}'")
                j.db.rollback()
                # 8時締切は完全撤廃（2026-11-25）。当日08:00〜23:29も当日分を保存でき、既保存は上書きしない。
                self.assertFalse(j.freeze('2026-11-11', {'groups': ['late']}, [], at('2026-11-11T08:00:00+09:00')))
                self.assertTrue(j.freeze('2026-11-11', {'groups': ['daytime']}, [row()], at('2026-11-11T15:00:00+09:00'), store='saiwaichou'))
                with self.assertRaises(ValueError):
                    j.freeze('2026-11-10', {}, [], now)
                # 保存できるのは対象日の前日23:30〜当日23:30未満（2026-11-25に8時締切を完全撤廃）。
                self.assertEqual(d.prediction_target(at('2026-11-11T23:29:59+09:00')), '2026-11-11')
                self.assertEqual(d.prediction_target(at('2026-11-11T23:30:00+09:00')), '2026-11-12')
                self.assertEqual(d.prediction_target(at('2026-11-12T00:00:00+09:00')), '2026-11-12')
                self.assertEqual(d.prediction_target(at('2026-11-12T07:59:59+09:00')), '2026-11-12')
                self.assertEqual(d.prediction_target(at('2026-11-12T08:00:00+09:00')), '2026-11-12')
                self.assertEqual(d.prediction_target(at('2026-11-12T12:00:00+09:00')), '2026-11-12')
                self.assertEqual(d.prediction_target(at('2026-11-12T23:29:59+09:00')), '2026-11-12')
                self.assertEqual(d.prediction_target(at('2026-11-12T23:30:00+09:00')), '2026-11-13')
                # PCの時刻設定ではなく日本時間で決める（UTCの14:30は日本時間の23:30）。
                self.assertEqual(d.prediction_target(at('2026-11-11T14:30:00+00:00')), '2026-11-12')
                with self.assertRaises(ValueError):          # 23:30より前は、翌日の分をまだ保存しない
                    j.freeze('2026-11-12', {}, [], at('2026-11-11T23:29:59+09:00'))
                with self.assertRaises(ValueError):          # 23:30以降は、今日の分は対象日切替後
                    j.freeze('2026-11-11', {'late': True}, [], at('2026-11-11T23:30:00+09:00'))
                self.assertTrue(j.freeze('2026-11-12', {'groups': ['night']}, [row()], at('2026-11-11T23:30:00+09:00')))
                # 前の晩に保存した予測は、翌朝・日中に動いても上書きしない。
                self.assertFalse(j.freeze('2026-11-12', {'groups': ['morning']}, [], at('2026-11-12T07:00:00+09:00')))
                self.assertFalse(j.freeze('2026-11-12', {'groups': ['noon']}, [], at('2026-11-12T12:00:00+09:00')))
                self.assertEqual(j.get('predictions', '2026-11-12')['groups'], ['night'])
                self.assertTrue(j.get('predictions', '2026-11-12')['saved_at'].startswith('2026-11-11T23:30:00'))
            finally:
                j.close()

    def test_read_only_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input.db'
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE days(payload TEXT)')
            db.execute('INSERT INTO days VALUES (?)', (json.dumps(row()),))
            db.commit()
            db.close()
            before = path.read_bytes()
            self.assertEqual(runtime.read_database(path, 'days'), [row()])
            self.assertEqual(path.read_bytes(), before)

    def test_input_decoding_does_not_block_capture_commit(self):
        # 複数行を走査中のcursorはDELETE journalの読取ロックを持つ。
        # JSON解析中も原本を読み続ける実装では、別接続の保存確定が失敗する。
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input.db'
            writer = sqlite3.connect(path, timeout=.05)
            try:
                writer.execute('CREATE TABLE days(payload TEXT)')
                originals = [row(rack=i) for i in range(1, 5)]
                writer.executemany('INSERT INTO days VALUES (?)', [(json.dumps(r),) for r in originals])
                writer.commit()
                original_decode = runtime.decode
                committed = []
                def decode_and_save(value):
                    if not committed:
                        changed = row(rack=1, win=False)
                        with writer:
                            writer.execute('UPDATE days SET payload=? WHERE rowid=1', (json.dumps(changed),))
                        committed.append(True)
                    return original_decode(value)
                with patch.object(runtime, 'decode', side_effect=decode_and_save):
                    result = runtime.read_database(path, 'days')
                self.assertEqual(committed, [True])
                self.assertEqual(result, originals)  # 一貫したコピーを読む。途中の更新は混ぜない。
                self.assertEqual(json.loads(writer.execute('SELECT payload FROM days WHERE rowid=1').fetchone()[0])['jo_net'], -100)
            finally:
                writer.close()

    def test_baseline_same_candidates_and_pool(self):
        rows = [row(d.shift('2026-11-01', i), rack, rack % 2 == 0) for i in range(10) for rack in range(1, 9)]
        groups = runtime.baseline_groups(rows, {'records': [], 'machines': []}, '2026-11-10')
        current = runtime.core.provisional_next_day_candidates(runtime.MemoryStore(rows), '2026-11-10', '試験機')
        self.assertEqual(groups[0]['current'], [d.identity(v['row']) for v in current['candidates']])
        self.assertEqual(len(groups[0]['pool']), 8)
        self.assertEqual(len(groups[0]['current']), 2)

    def test_one_store_ready_independently(self):
        rows = [row()]
        self.assertEqual(runtime.ready(rows, '2026-11-11', ('nagamachiminami',)), [])
        self.assertTrue(runtime.ready(rows, '2026-11-11', ('saiwaichou',)))

    def test_ready_counts_site777_racks_skipped_under_500_games(self):
        # 2026-11-10 から P-STATION は500G未満の台を保存しない。控え（site777-staging/日付-low.json）を数えないと、
        # 保存台数がふだんの90%未満になって、毎日「取り込み待ち」のままになる（11/10：295台中258台）。
        store = 'pscube:c740601:20'
        rows = [row(day=f'2026-11-0{n}', rack=rack, store=store) for n in range(3, 10) for rack in range(1, 101)]
        rows += [row(day='2026-11-10', rack=rack, store=store) for rack in range(1, 88)]          # 87台だけ保存（13台は500G未満）
        self.assertTrue(runtime.ready(rows, '2026-11-11', (store,)))
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'site777-staging'
            folder.mkdir()
            (folder / '2026-11-10-low.json').write_text(json.dumps({'120001': list(range(88, 95)), '120002': list(range(95, 101))}), encoding='utf-8')
            (folder / '2026-11-09-low.json').write_text('{broken', encoding='utf-8')                    # 読めない控えは無視
            (folder / '2026-11-11-low.json').write_text(json.dumps({'120001': [1]}), encoding='utf-8')  # 対象日より前の日だけ読む
            low = runtime.skipped_low_racks(temp, '2026-11-11')
            self.assertEqual(sorted(low), ['2026-11-10'])
            self.assertEqual(len(low['2026-11-10']), 13)
            self.assertEqual(runtime.ready(rows, '2026-11-11', (store,), low), [])
            # 控えは P-STATION だけに足す。保存した台と同じ番号は二重に数えない。取り込みの無い日を取り込み済みにしない。
            self.assertTrue(runtime.ready([dict(r, store='saiwaichou') for r in rows], '2026-11-11', ('saiwaichou',), low))
            self.assertTrue(runtime.ready(rows, '2026-11-11', (store,), {'2026-11-10': set(range(1, 14))}))
            self.assertTrue(runtime.ready([r for r in rows if r['day'] != '2026-11-10'], '2026-11-11', (store,), low))

    def test_failed_freeze_rolls_back_input(self):
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                original = j.append
                def failing(table, key, body):
                    if table == 'predictions':
                        raise OSError('模擬保存失敗')
                    return original(table, key, body)
                with patch.object(j, 'append', side_effect=failing), self.assertRaises(OSError):
                    j.freeze('2026-11-11', {}, [row()], datetime.fromisoformat('2026-11-11T07:00:00+09:00'))
                self.assertEqual(j.db.execute('SELECT COUNT(*) FROM inputs').fetchone()[0], 0)
                self.assertEqual(j.db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0], 0)
            finally:
                j.close()

    def test_adoption_once_rollback_and_no_reuse(self):
        store = 'nagamachiminami'
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            def add(first, count, learned, method='m1'):
                with j.db:
                    for i in range(count):
                        day = d.shift(first, i)
                        groups = [self.group(day, .4, learned, k=10, method=method, key=f'["{store}","","機種{n}"]')
                                  for n in range(3)]
                        j.append('outcomes', f'{day}|{store}', dict(target=day, store=store, groups=groups))
            try:
                with j.db:
                    j.state('start', '2026-01-01')
                add('2026-01-01', 112, .8)
                now = d.shift('2026-01-01', 120)
                runtime.decisions(j, now)
                state = j.get('state', 'store:' + store)
                self.assertEqual((state['active'], state['method']), ('learned', 'm1'))
                self.assertIsNone(j.get('state', 'store:saiwaichou'))   # 結果の無い店舗は採用しない
                first = j.get('decisions', 'adoption:1')
                self.assertEqual(first['rule'], d.RULE_VERSION)
                runtime.decisions(j, now)
                self.assertEqual(j.get('decisions', 'adoption:1'), first)
                add(now, 28, .1)
                # 28日目の成熟日（27 + MATURITY = 35日後）の1日前ではまだ判定せず、35日目ちょうどで切り戻す。
                runtime.decisions(j, d.shift(now, 34))
                self.assertEqual(j.get('state', 'store:' + store)['active'], 'learned')
                later = d.shift(now, 35)
                runtime.decisions(j, later)
                self.assertEqual(j.get('state', 'store:' + store), {'active': 'current', 'since': later})
                runtime.decisions(j, later)
                self.assertEqual(j.get('state', 'store:' + store)['active'], 'current')
                # 切り戻し前の期間（adoption:2 は120日目から）は再採用に使わない。
                add(d.shift('2026-01-01', 148), 200, .8)
                runtime.decisions(j, d.shift('2026-01-01', 247))
                self.assertEqual(j.get('state', 'store:' + store)['active'], 'current')
            finally:
                j.close()

    def test_method_change_days_are_not_mixed(self):
        # 期間の途中で方式の版が変わったら、最後の版の日だけで判定する（日数が足りなければ改善未確認）。
        store = 'saiwaichou'
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                with j.db:
                    j.state('start', '2027-01-01')
                    for i in range(112):
                        day = d.shift('2027-01-01', i)
                        g = self.group(day, .2, .8, k=10, method='v1' if i < 56 else 'v2', key=f'["{store}","","機種"]')
                        j.append('outcomes', f'{day}|{store}', dict(target=day, store=store, groups=[g]))
                runtime.decisions(j, d.shift('2027-01-01', 120))
                result = j.get('decisions', 'adoption:1')['results'][store]
                self.assertEqual((result['method'], result['other_method_days'], result['adopt']), ('v2', 56, False))
                self.assertIsNone(j.get('state', 'store:' + store))
            finally:
                j.close()

    def test_adopted_state_needs_same_method(self):
        # 採用したときと従来候補・学習の版が違えば、採用中にしない（根拠が無いため）。
        rows = [row(d.shift('2026-08-01', i), rack, (i + rack) % 3 == 0) for i in range(100) for rack in range(1, 9)]
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                method = runtime.method_signature('nagamachiminami')
                for stored, expected in ((method, 'learned'), ('古い版', 'current')):
                    with j.db:
                        j.state('store:nagamachiminami', {'active': 'learned', 'since': '2026-11-01', 'method': stored})
                    p = runtime.build_prediction(rows, {'records': [], 'machines': []}, d.shift('2026-08-01', 100), j)
                    trained = [g for g in p['groups'] if g['trained']]
                    self.assertTrue(trained)
                    self.assertEqual({g['active'] for g in trained}, {expected}, stored)
                    self.assertTrue(all(g['method'] == method for g in p['groups']))
            finally:
                j.close()

    def test_inputs_stored_once_per_store_day(self):
        # 2026-11-12：以前は210日分を毎晩まるごと保存し、1晩で約132MB増えた。塊ごとに1回だけ保存する。
        at = datetime.fromisoformat
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                history = [row(d.shift('2026-10-01', i), rack) for i in range(40) for rack in range(1, 6)]
                j.freeze('2026-11-10', {'groups': []}, history, at('2026-11-10T07:00:00+09:00'), store='nagamachiminami')
                first = j.db.execute('SELECT COUNT(*) FROM inputs').fetchone()[0]
                self.assertEqual(first, 40)
                extra = history + [row('2026-11-10', rack) for rack in range(1, 6)]
                extra[0] = extra[0] | {'jo_net': -5}                    # 過去の日の訂正は、その日の新しい塊として残る
                raw = [{'day': '2026-11-10', 'store': 'c740601', 'rack': 1, 'games': 10}]
                j.freeze('2026-11-11', {'groups': []}, {'rows': extra, 'pscube_records': raw},
                         at('2026-11-11T07:00:00+09:00'), store='nagamachiminami')
                self.assertEqual(j.db.execute('SELECT COUNT(*) FROM inputs').fetchone()[0], first + 3)
                p = j.get('predictions', '2026-11-11|nagamachiminami')
                rebuilt = j.input_rows(p)
                self.assertEqual(sorted(rebuilt, key=d.encoded), sorted(extra, key=d.encoded))
                self.assertEqual(j.input_rows(p, 'pscube_records'), raw)
                self.assertEqual(p['input_sha256'], d.digest(p['inputs']))
                # 11/12以前の形式（1つの塊）も読める。
                with j.db:
                    j.append('inputs', d.digest([row()]), [row()])
                self.assertEqual(j.input_rows({'input_sha256': d.digest([row()])}), [row()])
            finally:
                j.close()

    def test_ready_only_waits_for_count_and_usable_racks(self):
        # 2026-11-25 利用者の決定で、閉店前／確定前・前日機種の丸ごと欠落1%超・符号不明10%超の停止ルールを撤廃。
        # 直近7日中央値の90%未満と使える台0台だけを取り込み待ちにする。
        def rows_for(day, cap, machines=range(10), graph=True):
            out = []
            for rack in range(1, 101):
                if rack % 10 not in machines:
                    continue
                r = row(day, rack, machine=f'機種{rack % 10}') | {'captured_at': cap}
                r.pop('jo_net')
                if not graph:
                    r.pop('graph_measurement')
                out.append(r)
            return out
        base = [r for n in range(1, 8) for r in rows_for(d.shift('2026-11-11', -n), d.shift('2026-11-11', -n) + 'T23:10:00+09:00')]
        good = rows_for('2026-11-11', '2026-11-11T23:20:00+09:00')
        target = '2026-11-12'
        self.assertEqual(runtime.ready(base + good, target, ('nagamachiminami',)), [])
        # 閉店前時刻・前日機種の丸ごと欠落（90%以上残存）・グラフ無し多数でも止めずに保存へ進む。
        early = rows_for('2026-11-11', '2026-11-11T15:00:00+09:00')
        self.assertEqual(runtime.ready(base + early, target, ('nagamachiminami',)), [])
        partial = rows_for('2026-11-11', '2026-11-11T23:20:00+09:00', machines=range(9))
        self.assertEqual(runtime.ready(base + partial, target, ('nagamachiminami',)), [])
        nograph = good[:20] + [r for r in rows_for('2026-11-11', '2026-11-11T23:20:00+09:00', graph=False)][20:]
        self.assertEqual(runtime.ready(base + nograph, target, ('nagamachiminami',)), [])
        # 直近7日中央値の90%未満（100台→80台）は従来どおり取り込み待ち。
        too_few = rows_for('2026-11-11', '2026-11-11T23:20:00+09:00', machines=range(8))
        self.assertIn('前日データが不足しています', ''.join(runtime.ready(base + too_few, target, ('nagamachiminami',))))
        # 取り込み時刻の無い行（アナスロの保存ページなど）も通る。
        stamped = [{k: v for k, v in r.items() if k != 'captured_at'} for r in good]
        self.assertEqual(runtime.ready(base + stamped, target, ('nagamachiminami',)), [])

    def run_with(self, temp, stamp, *, build=None, load=None, sync=None):
        at = datetime.fromisoformat
        calls = []

        def fake_load(data_dir, target, sources=('meruhen', 'pscube')):
            calls.append(tuple(sources))
            if load:
                load(sources)
            return [row(day=d.shift(target, -1), store=s) for s in runtime.STORES], {'records': [], 'machines': []}

        def fake_build(rows, pscube, target, journal, node=None, history_rows=None):
            if build:
                build(rows[0]['store'])
            group = dict(key='k', store=rows[0]['store'], name='試験機', current=[], learned=[], selected=[],
                         active='current', trained=False, status='学習データ不足・従来方式', pool=[])
            return dict(input_day=d.shift(target, -1), groups=[group], models={}, source_sha256={})
        with patch.object(runtime, 'load_inputs', side_effect=fake_load), patch.object(runtime, 'ready', return_value=[]), \
                patch.object(runtime, 'build_prediction', side_effect=fake_build), \
                patch.object(runtime.core, 'resolve_sync_dir', return_value=sync):
            clock = stamp if callable(stamp) else (lambda: at(stamp))
            doc = runtime._run(Path(temp), clock=clock, sync=sync is not None)
        return doc, calls

    def test_one_store_failure_does_not_hide_others(self):
        with tempfile.TemporaryDirectory() as temp:
            sync = Path(temp) / 'sync'
            sync.mkdir()
            def fail(store):
                if store.startswith('pscube:'):
                    raise RuntimeError('P-STATIONの従来候補を計算するNode.jsがありません')
            doc, _ = self.run_with(temp, '2026-11-12T00:30:00+09:00', build=fail, sync=sync)
            self.assertIn('長町南：11/12の事前予測を固定保存しました', doc['status'])
            self.assertIn('P-STATION：処理失敗（Node.jsが見つかりません', doc['status'])
            self.assertEqual(len(doc['days'][0]['groups']), 2)
            self.assertEqual(json.loads((sync / runtime.FILE_NAME).read_text(encoding='utf-8')), doc)
            # 次の確認では失敗した店だけ作り直す。
            doc, calls = self.run_with(temp, '2026-11-12T00:40:00+09:00', sync=sync)
            self.assertEqual(calls, [('pscube',)])
            self.assertIn('P-STATION：11/12の事前予測を固定保存しました', doc['status'])

    def test_unreadable_source_only_stops_its_stores(self):
        with tempfile.TemporaryDirectory() as temp:
            def broken(sources):
                if 'pscube' in sources:
                    raise FileNotFoundError('pscube.sqlite3 がありません')
            doc, _ = self.run_with(temp, '2026-11-12T00:30:00+09:00', load=broken)
            self.assertIn('幸町：11/12の事前予測を固定保存しました', doc['status'])
            self.assertIn('P-STATION：処理失敗（pscube.sqlite3 がありません。データフォルダーを確認してください）', doc['status'])

    def test_saved_does_not_open_originals(self):
        with tempfile.TemporaryDirectory() as temp:
            _, calls = self.run_with(temp, '2026-11-12T00:30:00+09:00')
            self.assertEqual(sorted(calls), [('meruhen',), ('pscube',)])
            _, calls = self.run_with(temp, '2026-11-12T07:50:00+09:00')       # 全店保存済み
            self.assertEqual(calls, [])
            _, calls = self.run_with(temp, '2026-11-12T12:00:00+09:00')       # 日中でも全店保存済みなら原本を開かない
            self.assertEqual(calls, [])

    def test_crossing_0800_saves_normally_and_crossing_2330_is_not_failure(self):
        at = datetime.fromisoformat
        # 8時締切撤廃により、計算中に08:00をまたいでもそのまま固定保存する。
        morning_ticks = iter([at('2026-11-12T07:58:00+09:00')] + [at('2026-11-12T08:00:30+09:00')] * 10)
        with tempfile.TemporaryDirectory() as temp:
            doc, _ = self.run_with(temp, lambda: next(morning_ticks))
            self.assertIn('11/12の事前予測を固定保存しました', doc['status'])
            self.assertNotIn('処理失敗', doc['status'])
            self.assertEqual([x['target'] for x in doc['days']], ['2026-11-12'])
        # 23:30の対象日切替をまたいだ場合は保存せず、処理失敗にしない。
        rollover_ticks = iter([at('2026-11-12T23:29:00+09:00')] + [at('2026-11-12T23:30:30+09:00')] * 10)
        with tempfile.TemporaryDirectory() as temp:
            doc, _ = self.run_with(temp, lambda: next(rollover_ticks))
            self.assertIn('計算中に23:30（対象日の切替）を過ぎたため', doc['status'])
            self.assertNotIn('処理失敗', doc['status'])
            self.assertEqual(doc['days'], [])

    def test_result_labels_keep_non_candidates_and_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                ids = [list(d.identity(row(rack=i))) for i in range(1, 5)]
                group = dict(key='group', trained=True, pool=[{'id': k} for k in ids],
                             current=ids[:2], learned=ids[2:])
                now = datetime.fromisoformat('2026-11-11T07:00:00+09:00')
                j.freeze('2026-11-11', {'groups': [group]}, [], now, store='nagamachiminami')
                rows = [row('2026-11-11', i) for i in (1, 3, 4)]
                runtime.record_outcomes(j, rows, '2026-11-18')
                self.assertIsNone(j.get('outcomes', '2026-11-11|nagamachiminami'))
                runtime.record_outcomes(j, rows, '2026-11-19')
                value = j.get('outcomes', '2026-11-11|nagamachiminami')['groups'][0]
                self.assertEqual(len(value['labels']), 4)
                self.assertEqual(value['missing_current'], .5)
                self.assertEqual(value['current'], 1)
                runtime.record_outcomes(j, [], '2026-11-20')
                self.assertEqual(j.get('outcomes', '2026-11-11|nagamachiminami')['groups'][0], value)
            finally:
                j.close()

    def test_old_outcome_waits_for_its_day_then_uses_original_data(self):
        from daily_learning_view import status_parts

        day, target = '2024-01-01', '2024-09-01'
        nagamachi, saiwai, pstation = runtime.STORES
        old_row = row(day, store=nagamachi)
        candidate = list(d.identity(old_row))
        group = dict(key='group', store=nagamachi, name='試験機', active='current', status='試験',
                     trained=True, pool=[{'id': candidate}], current=[candidate], learned=[], selected=[candidate])
        yesterday = row(d.shift(target, -1), store=nagamachi) | {
            'games': 0, 'captured_at': f'{d.shift(target, -1)}T12:00:00+09:00',
        }
        clock = lambda: datetime.fromisoformat(f'{target}T12:00:00+09:00')
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            journal_path = base / 'daily-learning' / 'journal.sqlite3'
            journal = d.Journal(journal_path)
            try:
                journal.freeze(day, {'input_day': d.shift(day, -1), 'groups': [group]}, [],
                               datetime.fromisoformat(f'{day}T07:00:00+09:00'), store=nagamachi)
            finally:
                journal.close()
            with closing(sqlite3.connect(base / 'database.sqlite3')) as db:
                with db:
                    db.execute('CREATE TABLE days(payload TEXT)')
                    db.executemany('INSERT INTO days VALUES (?)', [(json.dumps(r),) for r in
                                   (yesterday, row(day, store=saiwai))])
                first = runtime.run(base, clock=clock, sync=False, skip_sources=(runtime.SOURCES[pstation],))
                self.assertIn('結果の記録で処理失敗', first['status'])
                self.assertIn('使える台がありません', status_parts(first['status'], nagamachi)[0][0])
                self.assertNotIn('長町南の前日データ', ' '.join(status_parts(first['status'], saiwai)[1]))
                with db:
                    db.execute('INSERT INTO days VALUES (?)', (json.dumps(old_row),))
                rows, _ = runtime.load_inputs(base, target, ('meruhen',))
                self.assertEqual(rows, [yesterday])
                runtime.run(base, clock=clock, sync=False, skip_sources=(runtime.SOURCES[pstation],))
            # 結果を見るのは上で作った架空の記録DBだけ。
            with closing(d.Journal(journal_path, readonly=True)) as journal:
                saved = journal.get('outcomes', f'{day}|{nagamachi}')['groups'][0]
                self.assertEqual((saved['current'], saved['missing_current']), (1, 0))

    def test_same_day_per_store_and_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'journal.sqlite3'
            j = d.Journal(path)
            now = datetime.fromisoformat('2026-11-11T07:00:00+09:00')
            try:
                for store in runtime.STORES:
                    self.assertTrue(j.freeze('2026-11-11', {'groups': []}, [], now, store=store))
                self.assertEqual(j.db.execute('SELECT COUNT(*) FROM predictions').fetchone()[0], 3)
            finally:
                j.close()
            j = d.Journal(path)
            try:
                self.assertFalse(j.freeze('2026-11-11', {}, [], now, store=runtime.STORES[0]))
            finally:
                j.close()

    def test_run_saves_daytime_and_switches_to_next_day_at_2330(self):
        # 2026-11-25 利用者の決定で当日8時締切を完全撤廃。前日23:30〜当日23:30未満は未保存ならいつでも保存でき、23:30で翌日に切り替わる。
        at = datetime.fromisoformat
        built, loaded = [], []

        def fake_load(data_dir, target, sources=('meruhen', 'pscube')):
            loaded.append(target)
            return [row(day=d.shift(target, -1), store=s) for s in runtime.STORES], {'records': [], 'machines': []}

        def fake_build(rows, pscube, target, journal, node=None, history_rows=None):
            built.append((target, rows[0]['store'], rows[0]['day']))
            group = dict(key='k', store=rows[0]['store'], name='試験機', current=[], learned=[], selected=[],
                         active='current', trained=False, status='学習データ不足・従来方式', pool=[])
            return dict(input_day=d.shift(target, -1), groups=[group], models={}, source_sha256={})

        with tempfile.TemporaryDirectory() as temp, patch.object(runtime, 'load_inputs', side_effect=fake_load), \
                patch.object(runtime, 'ready', return_value=[]), patch.object(runtime, 'build_prediction', side_effect=fake_build):
            run = lambda stamp: runtime._run(Path(temp), clock=lambda: at(stamp), sync=False)
            doc = run('2026-11-11T12:00:00+09:00')              # 日中でも未保存なら当日分を固定保存する
            self.assertEqual(built, [('2026-11-11', s, '2026-11-10') for s in runtime.STORES])
            self.assertIn('11/11の事前予測を固定保存しました', doc['status'])
            self.assertTrue(doc['days'][0]['saved_at'].startswith('2026-11-11T12:00:00'))
            doc = run('2026-11-11T23:29:00+09:00')              # 23:30の直前は当日分が保存済み（翌日はまだ作らない）
            self.assertEqual(len(built), 3)
            self.assertIn('11/11の事前予測は保存済みです', doc['status'])
            doc = run('2026-11-11T23:35:00+09:00')              # 23:30以降：対象日は明日、前日データは今日
            self.assertEqual(loaded[-1], '2026-11-12')
            self.assertEqual(built[3:], [('2026-11-12', s, '2026-11-11') for s in runtime.STORES])
            self.assertIn('11/12の事前予測を固定保存しました', doc['status'])
            self.assertEqual([(x['target'], x['input_day']) for x in doc['days']],
                             [('2026-11-12', '2026-11-11'), ('2026-11-11', '2026-11-10')])
            self.assertTrue(doc['days'][0]['saved_at'].startswith('2026-11-11T23:35:00'))
            for stamp in ['2026-11-12T00:10:00+09:00', '2026-11-12T07:40:00+09:00',
                          '2026-11-12T09:00:00+09:00', '2026-11-12T20:00:00+09:00']:
                doc = run(stamp)                                # 翌朝・日中に動いても作り直さない
                self.assertEqual(len(built), 6, stamp)
                self.assertIn('11/12の事前予測は保存済みです', doc['status'], stamp)
            self.assertTrue(doc['days'][0]['saved_at'].startswith('2026-11-11T23:35:00'))

    def test_zero_usable_racks_is_not_frozen_rebuilds_in_daytime_and_misses_after_2330(self):
        # G12（2026-11-23 利用者の決定）：使える台が0台の店・日は予測を固定しない。
        # 当日23:30（対象日切替）までに有効な台の取り込みが入れば作り直す。0台のまま23:30を過ぎたら未保存（missed）。
        at = datetime.fromisoformat
        target, prev_day = '2026-11-12', '2026-11-11'
        base_naga = [row(d.shift(prev_day, -n), r, store='nagamachiminami') | {'captured_at': f'{d.shift(prev_day, -n)}T23:20:00+09:00'}
                     for n in range(1, 5) for r in range(1, 11)]
        zero_naga = [row(prev_day, r, store='nagamachiminami') | {'games': 0, 'captured_at': f'{prev_day}T23:20:00+09:00'}
                     for r in range(1, 11)]
        valid_naga = [row(prev_day, r, store='nagamachiminami') | {'games': 2000, 'captured_at': f'{prev_day}T23:20:00+09:00'}
                      for r in range(1, 11)]
        # ready()：全行あっても使える台が0台なら理由を返す（0Gの店休日等、およびP-STATIONのアナスロ補完行のみ）
        reasons = runtime.ready(base_naga + zero_naga, target, ('nagamachiminami',))
        self.assertEqual(len(reasons), 1)
        self.assertIn('使える台がありません', reasons[0])
        ps_store = 'pscube:c740601:20'
        ps_anaslo_only = [row(prev_day, r, store=ps_store) | {'games': 2000, 'source_site': 'anaslo'} for r in range(1, 11)]
        ps_reasons = runtime.ready(ps_anaslo_only, target, (ps_store,))
        self.assertEqual(len(ps_reasons), 1)
        self.assertIn('使える台がありません', ps_reasons[0])

        # _run()：0台の店は固定保存せず取り込み待ちにし、8時を過ぎた日中（12:00）でも有効データが入れば作り直して固定保存する
        valid_saiwai = [row(prev_day, r, store='saiwaichou') | {'games': 2000, 'captured_at': f'{prev_day}T23:20:00+09:00'}
                        for r in range(1, 11)]
        valid_ps = [row(prev_day, r, store=ps_store) | {'games': 2000} for r in range(1, 11)]

        def fake_build(rows, pscube, t, journal, node=None, history_rows=None):
            g = dict(key='k', store=rows[0]['store'], name='試験機', current=[list(d.identity(rows[0]))],
                     learned=[list(d.identity(rows[0]))], selected=[list(d.identity(rows[0]))],
                     active='current', trained=False, status='学習データ不足・従来方式', pool=[])
            return dict(input_day=d.shift(t, -1), groups=[g], models={}, source_sha256={})

        state_rows = [base_naga + zero_naga + valid_saiwai + valid_ps]

        def fake_load(data_dir, t, sources=('meruhen', 'pscube')):
            picked = [r for r in state_rows[0] if runtime.SOURCES.get(r['store']) in sources]
            return picked, {'records': [], 'machines': []}

        with tempfile.TemporaryDirectory() as temp, \
                patch.object(runtime, 'load_inputs', side_effect=fake_load), \
                patch.object(runtime, 'build_prediction', side_effect=fake_build):
            doc1 = runtime._run(Path(temp), clock=lambda: at('2026-11-12T00:30:00+09:00'), sync=False)
            self.assertIn('長町南：取り込み待ち：長町南の前日データに使える台がありません', doc1['status'])
            self.assertIn('幸町：11/12の事前予測を固定保存しました', doc1['status'])
            self.assertIn('P-STATION：11/12の事前予測を固定保存しました', doc1['status'])
            self.assertEqual(runtime.unsaved_stores(temp, target), ['nagamachiminami'])
            trace_text = (Path(temp) / 'daily-learning' / runtime.TRACE_NAME).read_text(encoding='utf-8')
            self.assertIn('長町南：取り込み待ち：長町南の前日データに使える台がありません', trace_text)
            text_wait, level_wait = runtime.night_status(temp, at('2026-11-12T00:35:00+09:00'))
            self.assertEqual(level_wait, 'wait')
            self.assertIn('長町南 取り込み待ち', text_wait)
            # 当日12:00（従来の8:00締切後）でも有効な台の取り込みが入れば作り直して固定保存する
            state_rows[0] = base_naga + valid_naga + valid_saiwai + valid_ps
            doc2 = runtime._run(Path(temp), clock=lambda: at('2026-11-12T12:00:00+09:00'), sync=False)
            self.assertIn('長町南：11/12の事前予測を固定保存しました', doc2['status'])
            self.assertEqual(runtime.unsaved_stores(temp, target), [])

        # 0台のまま当日23:30（翌日の対象日切替）を過ぎたときは、11/12は未保存（checkup は missed）になる
        state_rows[0] = base_naga + zero_naga + valid_saiwai + valid_ps
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(runtime, 'load_inputs', side_effect=fake_load), \
                patch.object(runtime, 'build_prediction', side_effect=fake_build):
            runtime._run(Path(temp), clock=lambda: at('2026-11-12T00:30:00+09:00'), sync=False)
            doc_next = runtime._run(Path(temp), clock=lambda: at('2026-11-12T23:35:00+09:00'), sync=False)
            self.assertEqual(runtime.unsaved_stores(temp, target), ['nagamachiminami'])
            cells = {c['target']: c['state'] for c in doc_next['checkup']['stores']['nagamachiminami']}
            self.assertEqual(cells['2026-11-12'], 'missed')
            self.assertEqual(cells['2026-11-13'], 'pending')

    def test_v5_no_hits_without_graph_and_site777_guard(self):
        # メルヘン v12：大当たり0回・グラフ省略台は非プラス(0)として欠測バイアス（MNAR）を防ぐ。
        meruhen_zero = dict(store='nagamachiminami', day='2026-11-28', machine='試験機', rack=1,
                            games=900, bb=0, rb=0)
        self.assertEqual((d.outcome(meruhen_zero), d.outcome_source(meruhen_zero)), (0, 'no_hits'))
        # 0Gは未稼働なので判定不能のまま。
        self.assertEqual((d.outcome(meruhen_zero | {'games': 0}), d.outcome_source(meruhen_zero | {'games': 0})), (None, None))
        # P’s CUBE は at_art==0 も明示のときだけ no_hits。サイトセブン補完（at_art=None）はAT当たりの可能性があるため None。
        ps_zero = dict(store='pscube:c740601:20', rate='20', day='2026-11-28', machine='AT機', rack=1,
                       games=900, bb=0, rb=0, at_art=0)
        self.assertEqual((d.outcome(ps_zero), d.outcome_source(ps_zero)), (0, 'no_hits'))
        s777_zero = ps_zero | {'at_art': None, 'source_site': 'site777'}
        self.assertEqual((d.outcome(s777_zero), d.outcome_source(s777_zero)), (None, None))

    def test_v5_standardized_ridge_is_scale_invariant_and_picks_small_variance_signal(self):
        # 特徴量1のスケールを100倍しても予測値が一致する（標準化リッジ回帰のスケール不変性）。
        base_examples = []
        scaled_examples = []
        for day_i in range(25):
            day = d.shift('2026-10-01', day_i)
            for rack in range(1, 7):
                signal = 0.02 if rack <= 3 else -0.02  # 分散が非常に小さい特徴（plus7 / dry_streak 相当）
                y = 1 if (rack <= 3 and day_i % 5 != 0) or (rack > 3 and day_i % 5 == 0) else 0
                base_examples.append(([1., signal, 0.], y, day))
                scaled_examples.append(([1., signal * 100., 0.], y, day))
        w_base, _ = d._fit(base_examples)
        w_scaled, _ = d._fit(scaled_examples)
        self.assertGreater(w_base[1], 1.0)
        for (xb, _, _), (xs, _, _) in zip(base_examples[:6], scaled_examples[:6]):
            pb = sum(a * b for a, b in zip(xb, w_base))
            ps = sum(a * b for a, b in zip(xs, w_scaled))
            self.assertAlmostEqual(pb, ps, places=9)

    def test_v5_comparison_manski_bounds_14d_block_and_paired_counts(self):
        # ペア比較可能な112日＋片側全欠測（diff is None）の日を混ぜても、counts は paired のみで数え、
        # Manski 最悪/最良境界と 14暦日ブロック符号反転 p 値（p_14d）が正しく算出される。
        days = [d.store_day(d.shift('2026-01-01', i), [self.group(d.shift('2026-01-01', i), .4, .6, k=10,
                                                                  missing_current=.05, missing_learned=.05)])
                for i in range(112)]
        unpaired = d.store_day('2026-05-01', [self.group('2026-05-01', .5, None, k=10,
                                                         missing_current=0., missing_learned=1.)])
        self.assertIsNone(unpaired['diff'])
        res_clean = d.comparison(days, .01)
        res_with_unpaired = d.comparison(days + [unpaired], .01)
        self.assertEqual(res_with_unpaired['counts'], res_clean['counts'])
        self.assertEqual(res_clean['weeks14'], 8)
        self.assertAlmostEqual(res_clean['p_14d'], 1 / 256)
        self.assertLessEqual(res_clean['manski_worst_difference'], res_clean['nonplus_difference'] + 1e-12)
        self.assertLessEqual(res_clean['manski_worst_difference'], res_clean['plus_difference'] + 1e-12)
        self.assertLessEqual(res_clean['nonplus_difference'], res_clean['manski_best_difference'] + 1e-12)
        self.assertLessEqual(res_clean['plus_difference'], res_clean['manski_best_difference'] + 1e-12)


if __name__ == '__main__':
    unittest.main()
