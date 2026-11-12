"""日次学習の見落としの修正（2026-11-12）。結果の記録・採用判定の失敗で予測の保存を止めない、
未記録の結果がある期間は判定を待つ、同じ日の新旧の名前を二重に数えない、分析用JSONを使えない晩を知らせる。"""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import daily_learning as d
import daily_learning_runtime as runtime
import test_daily_learning as base

row, group = base.row, base.LearningTests.group
PS = 'pscube:c740601:20'
OLD, NEW = 'L Vivy', 'L Vivy -Fluorite Eye’s Song-'


def frozen(journal, day, store, groups=()):
    """予測を1件、保存できる時刻（対象日の7:00）で固定保存する。"""
    journal.freeze(day, {'input_day': d.shift(day, -1), 'groups': list(groups)}, [],
                   datetime.fromisoformat(f'{day}T07:00:00+09:00'), store=store)


class RobustTests(unittest.TestCase):
    def test_adoption_waits_until_outcomes_of_the_period_are_recorded(self):
        # 判定は1回きり。原本を読めなかった晩に、期間の終わりの結果を欠いたまま確定させない。
        store = 'nagamachiminami'
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                with j.db:
                    j.state('start', '2026-01-01')
                    for i in range(111):
                        day = d.shift('2026-01-01', i)
                        j.append('outcomes', f'{day}|{store}', dict(target=day, store=store, groups=[
                            group(day, .4, .8, k=10, key=f'["{store}","","機種{n}"]') for n in range(3)]))
                last = d.shift('2026-01-01', 111)
                frozen(j, last, store)                       # 期間の最後の日：予測はあるが、結果はまだ記録していない
                today = d.shift('2026-01-01', 120)
                self.assertTrue(runtime.pending_outcomes(j, '2026-01-01', last))
                self.assertFalse(runtime.pending_outcomes(j, '2026-01-01', last, 'saiwaichou'))
                runtime.decisions(j, today)
                self.assertIsNone(j.get('decisions', 'adoption:1'))
                self.assertIsNone(j.get('state', 'store:' + store))
                with j.db:
                    j.append('outcomes', f'{last}|{store}', dict(target=last, store=store, groups=[
                        group(last, .4, .8, k=10, key=f'["{store}","","機種{n}"]') for n in range(3)]))
                runtime.decisions(j, today)
                self.assertEqual(j.get('decisions', 'adoption:1')['results'][store]['n'], 112)
                self.assertEqual(j.get('state', 'store:' + store)['active'], 'learned')
            finally:
                j.close()

    def test_rollback_waits_for_this_stores_outcomes_only(self):
        store, other = 'nagamachiminami', 'saiwaichou'
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                with j.db:
                    j.state('start', '2026-01-01')
                    j.state('store:' + store, {'active': 'learned', 'since': '2026-06-01', 'method': 'm1'})
                    for i in range(27):
                        day = d.shift('2026-06-01', i)
                        j.append('outcomes', f'{day}|{store}', dict(target=day, store=store, groups=[group(day, .8, .1, k=10)]))
                last = d.shift('2026-06-01', 27)
                frozen(j, last, store)
                frozen(j, last, other)                       # ほかの店舗の未記録は、この店舗の判定を待たせない
                today = d.shift('2026-06-01', 36)
                runtime.decisions(j, today)
                self.assertEqual(j.get('state', 'store:' + store)['active'], 'learned')
                self.assertFalse(j.has('decisions', f'rollback:{store}:2026-06-01:1'))
                with j.db:
                    j.append('outcomes', f'{last}|{store}', dict(target=last, store=store, groups=[group(last, .8, .1, k=10)]))
                runtime.decisions(j, today)
                self.assertTrue(j.get('decisions', f'rollback:{store}:2026-06-01:1')['rollback'])
                self.assertEqual(j.get('state', 'store:' + store), {'active': 'current', 'since': today})
            finally:
                j.close()

    def test_one_broken_outcome_does_not_stop_the_others(self):
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                ids = [list(d.identity(row(rack=i))) for i in range(1, 4)]
                good = dict(key='g', trained=True, pool=[{'id': k} for k in ids[:2]], current=ids[:1], learned=ids[2:])
                frozen(j, '2026-11-11', 'nagamachiminami', [good])    # learned の台（3番）は母集団の外。落とさずに正解を引く
                frozen(j, '2026-11-11', 'saiwaichou', [{'key': 'broken'}])
                rows = [row('2026-11-11', i) for i in (1, 2, 3)] + [row('2026-11-11', 1, store='saiwaichou')]
                failed = runtime.record_outcomes(j, rows, '2026-11-19')
                self.assertEqual([(k, type(e)) for k, e in failed], [('2026-11-11|saiwaichou', KeyError)])
                value = j.get('outcomes', '2026-11-11|nagamachiminami')['groups'][0]
                self.assertEqual((value['n_current'], value['n_learned'], len(value['labels'])), (1, 1, 3))
                self.assertFalse(j.has('outcomes', '2026-11-11|saiwaichou'))
                self.assertEqual(runtime.due_outcomes(j, '2026-11-19'), ['2026-11-11|saiwaichou'])   # 次の実行でやり直す
                # 同じ日・台・機種が重複した店舗（History が作れない）も、その店舗の鍵だけが失敗になる。
                frozen(j, '2026-11-12', 'nagamachiminami', [good])
                twice = rows + [row('2026-11-12', 1, store='saiwaichou')] * 2 + [row('2026-11-12', 1)]
                failed = runtime.record_outcomes(j, twice, '2026-11-20')
                self.assertEqual([k for k, _ in failed], ['2026-11-11|saiwaichou'])
                self.assertTrue(j.has('outcomes', '2026-11-12|nagamachiminami'))
            finally:
                j.close()

    def run_night(self, temp, stamp, *, archive_files=None, archive_error=None):
        at = datetime.fromisoformat

        def fake_load(data_dir, target, sources=('meruhen', 'pscube')):
            return [row(day=d.shift(target, -1), store=s) for s in runtime.STORES], {'records': [], 'machines': []}

        def fake_build(rows, pscube, target, journal, node=None, history_rows=None):
            g = dict(key='k', store=rows[0]['store'], name='試験機', current=[], learned=[], selected=[],
                     active='current', trained=False, status='学習データ不足・従来方式', pool=[])
            return dict(input_day=d.shift(target, -1), groups=[g], models={}, source_sha256={})

        def fake_merge(rows, store, target, folders=None):
            if archive_error and store in runtime.daily_learning_archive.FOLDERS:
                raise archive_error
            return rows
        with patch.object(runtime, 'load_inputs', side_effect=fake_load), patch.object(runtime, 'ready', return_value=[]), \
                patch.object(runtime, 'build_prediction', side_effect=fake_build), \
                patch.object(runtime.daily_learning_archive, 'merge', side_effect=fake_merge), \
                patch.object(runtime.daily_learning_archive, 'fingerprints',
                             side_effect=lambda store, folders=None: (archive_files or {}).get(store, {})):
            return runtime._run(Path(temp), clock=lambda: at(stamp), sync=False)

    def test_failed_outcomes_and_decisions_do_not_stop_tonights_predictions(self):
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'daily-learning' / 'journal.sqlite3')
            try:
                # 結果を記録できない予測（学習済みかの項目が無い）。表示用の項目はそろっている。
                frozen(j, '2026-11-11', 'saiwaichou', [dict(key='broken', store='saiwaichou', name='試験機', active='current',
                                                           status='x', selected=[], current=[], learned=[])])
                with j.db:
                    j.state('start', '2026-11-11')
            finally:
                j.close()
            files = {s: {'a.json': 'x'} for s in runtime.daily_learning_archive.FOLDERS}
            with patch.object(runtime, 'decisions', side_effect=RuntimeError('模擬の判定失敗')):
                doc = self.run_night(temp, '2026-11-19T23:40:00+09:00', archive_files=files)
            for name in ('長町南', '幸町', 'P-STATION'):
                self.assertIn(f'{name}：11/20の事前予測を固定保存しました', doc['status'])
            self.assertIn('結果の記録で処理失敗（1件。', doc['status'])
            self.assertIn('採用判定で処理失敗（RuntimeError: 模擬の判定失敗）。採用の状態は変えていません', doc['status'])
            self.assertEqual(len(doc['days'][0]['groups']), 3)
            log = (Path(temp) / 'errors.log').read_text(encoding='utf-8')
            self.assertIn('結果の記録 2026-11-11|saiwaichou', log)
            # 失敗は、どの店舗の画面でも重要な注意として出る（店舗の名前で始まらない文）。
            import daily_learning_view as view
            alerts = view.daily_view(doc, 'nagamachiminami', '2026-11-20', datetime.fromisoformat('2026-11-19T23:41:00+09:00'))['alerts']
            self.assertEqual(sum('処理失敗' in a for a in alerts), 2)

    def test_archive_unusable_is_shown_and_stays_after_saving(self):
        folders = list(runtime.daily_learning_archive.FOLDERS)
        self.assertEqual(sorted(folders), [PS, 'saiwaichou'])
        note = runtime.ARCHIVE_NOTE
        with tempfile.TemporaryDirectory() as temp:
            # 読めない（例外）とき：分析用JSONを使う2店舗にだけ出す。予測は原本DBだけで保存する。
            doc = self.run_night(temp, '2026-11-12T00:30:00+09:00', archive_error=ValueError('壊れたJSON'))
            self.assertIn('長町南：11/12の事前予測を固定保存しました／', doc['status'] + '／')
            self.assertIn('幸町：11/12の事前予測を固定保存しました' + note, doc['status'])
            self.assertIn('P-STATION：11/12の事前予測を固定保存しました' + note, doc['status'])
            j = d.Journal(Path(temp) / 'daily-learning' / 'journal.sqlite3')
            try:
                self.assertIn('壊れたJSON', j.get('predictions', '2026-11-12|saiwaichou')['archive_error'])
                self.assertNotIn('archive_error', j.get('predictions', '2026-11-12|nagamachiminami'))
            finally:
                j.close()
            # あとの実行（保存済み）でも出し続ける。
            doc = self.run_night(temp, '2026-11-12T07:40:00+09:00')
            self.assertIn('幸町：11/12の事前予測は保存済みです' + note, doc['status'])
            self.assertIn('長町南：11/12の事前予測は保存済みです／', doc['status'] + '／')
        with tempfile.TemporaryDirectory() as temp:
            # ファイルが1つも無い（フォルダーごと無い）とき：幸町は無い、P-STATIONは有る。
            doc = self.run_night(temp, '2026-11-12T00:30:00+09:00', archive_files={PS: {'a.json': 'x'}})
            self.assertIn('幸町：11/12の事前予測を固定保存しました' + note, doc['status'])
            self.assertIn('P-STATION：11/12の事前予測を固定保存しました／', doc['status'] + '／')
        import daily_learning_view as view
        self.assertTrue(view.IMPORTANT.search(note))

    def test_same_day_old_and_new_names_are_counted_once_in_training(self):
        rows = []
        for i in range(60):
            day = d.shift('2026-09-01', i)
            for rack in range(1, 5):
                name = OLD if i < 30 else NEW
                r = dict(day=day, rack=rack, store=PS, rate='20', machine=name, games=4000, bb=20, rb=10,
                         jo_net=100 if (i + rack) % 3 else -100)
                rows.append(r)
                if 30 <= i < 40:
                    rows.append(r | {'machine': OLD, 'games': 100})      # 同じ日に古い名前の行も残っている
        target = d.shift('2026-09-01', 70)
        model = d.train(d.History(rows), target)[(PS, '20', NEW)]
        clean = d.train(d.History([r for r in rows if not (r['machine'] == OLD and r['day'] >= d.shift('2026-09-01', 30))]),
                        target)[(PS, '20', NEW)]
        self.assertEqual(model['n'], clean['n'])
        self.assertEqual(model['weights'], clean['weights'])


class WorkerTests(unittest.TestCase):
    def test_request_during_a_run_is_repeated_once_after_it(self):
        # 取り込み窓が続けて閉じたとき、動いている間の依頼を捨てない（終わったあとに1回だけやり直す）。
        import threading
        import daily_learning_ui as ui
        started, release, count = threading.Event(), threading.Event(), []

        def fake_run(data_dir):
            count.append(1)
            started.set()
            self.assertTrue(release.wait(10))
            if len(count) == 2:
                raise RuntimeError('模擬の失敗')
            return {'status': f'{len(count)}回目'}
        with tempfile.TemporaryDirectory() as temp, patch.object(ui, 'run', side_effect=fake_run):
            worker = ui.DailyLearningWorker(temp)
            self.assertTrue(worker.start())
            self.assertTrue(started.wait(10))
            self.assertFalse(worker.start())
            self.assertFalse(worker.start())                 # 何回頼まれても、やり直しは1回
            release.set()
            worker.thread.join(10)
            self.assertFalse(worker.thread.is_alive())
            self.assertEqual(len(count), 2)
            self.assertEqual(worker.results.get_nowait(), '1回目')
            self.assertIn('処理失敗', worker.results.get_nowait())   # 失敗しても係は止まらず、次の依頼を受ける
            self.assertTrue(worker.start())
            worker.thread.join(10)
            self.assertEqual(len(count), 3)
            self.assertFalse(worker.running)


if __name__ == '__main__':
    unittest.main()
