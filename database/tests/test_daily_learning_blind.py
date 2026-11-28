"""日次学習 v6（2026-11-28）：完全盲検モデル blind-hbma-condrank-v1 の導入・先行採用・28日切り戻し監視の試験。"""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import daily_learning as d
import daily_learning_blind as blind
import daily_learning_runtime as runtime
import daily_learning_view as view

SAI = 'saiwaichou'
NAGA = 'nagamachiminami'
PS = 'pscube:c740601:20'
SEALED_SHA256 = 'fc3f40cfd4b87951966ec9867c3453493371e1158afeef8fbd4501d60b767523'


def make_row(day, rack, machine, *, win=True, store=SAI, rate='', games=4000, net=None):
    val = (1200 if win else -800) if net is None else net
    row = dict(
        day=day,
        rack=rack,
        store=store,
        machine=machine,
        games=games,
        bb=22 if win else 10,
        rb=14 if win else 6,
        max_hold=2400 if win else 600,
        graph_measurement=dict(baseline_y=100, end_y=40 if win else 160, peak_y=20, trough_y=180),
    )
    if store.startswith('pscube:'):
        row['rate'] = rate or '20'
        row['net_medals'] = val
        row['at_art'] = 0
    else:
        row['jo_net'] = val
    return row


def synthetic_store_rows(store=SAI, *, start='2026-09-15', days=75):
    """通常機種 A（6台）・新台 N（4台）・バラエティ V1（1台）・V2（2台）の合成履歴。"""
    rows = []
    for i in range(days):
        day = d.shift(start, i)
        for rack in range(1, 7):
            # 前日高稼働・好調台が翌日に出やすい強い合成パターンを入れて重みが非ゼロになるようにする
            prev_signal = ((i + rack) % 3 == 0)
            games = 6500 if prev_signal else 2200
            win = ((i - 1 + rack) % 3 == 0) if i > 0 else prev_signal
            rows.append(make_row(day, rack, 'A', win=win, store=store, games=games))
        for rack in range(101, 105):
            machine = 'Old' if i < days - 5 else 'N'
            win = ((i + rack) % 2 == 0)
            rows.append(make_row(day, rack, machine, win=win, store=store, games=5000 if win else 2000))
        if not store.startswith('pscube:'):
            rows.append(make_row(day, 201, 'V1', win=((i * 3) % 5 < 2), store=store, games=3200))
            for rack in (202, 203):
                rows.append(make_row(day, rack, 'V2', win=((i * 5 + rack) % 5 < 2), store=store, games=3000))
    return rows


def groups_for_day(rows, input_day, store=SAI):
    daily = [r for r in rows if r['day'] == input_day and r['store'] == store]
    rate = '20' if store.startswith('pscube:') else ''
    pick = lambda names: [r for r in daily if r['machine'] in names]
    groups = [
        dict(store=store, rate=rate, name='A', pool=pick(('A',)), current=[d.identity(r) for r in pick(('A',))][:2]),
        dict(store=store, rate=rate, name='N', pool=pick(('N',)), current=[d.identity(r) for r in pick(('N',))][:1]),
    ]
    if not store.startswith('pscube:'):
        vpool = pick(('V1', 'V2'))
        groups.append(dict(store=store, rate=rate, name='バラエティ', pool=vpool,
                           current=[d.identity(pick(('V1',))[0])]))
    return groups


class EmptyJournal:
    @staticmethod
    def get(table, key):
        return None


class BlindV6Tests(unittest.TestCase):
    def test_blind_module_matches_sealed_sha256(self):
        # Windows チェックアウトの CRLF 変換に依らず、封印済み原本（LF）との内容一致を検証する
        raw = Path(blind.__file__).read_bytes()
        actual_lf = hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()
        self.assertEqual(blind.VERSION, 'blind-hbma-condrank-v1')
        self.assertEqual(actual_lf, SEALED_SHA256)

    def test_method_signature_updates_only_blind_stores_and_keeps_nagamachiminami(self):
        self.assertEqual(runtime.method_signature(NAGA).split('|')[0], d.VERSION)
        self.assertEqual(runtime.method_signature(SAI).split('|')[0], f'{d.VERSION}+{blind.VERSION}')
        self.assertEqual(
            runtime.method_signature(PS).split('|')[0],
            f'{d.VERSION}+{blind.VERSION}+{runtime.daily_learning_archive.ZERO_FIX}',
        )

    def test_saiwaichou_adopts_blind_for_normal_and_protects_variety(self):
        target = '2026-11-29'
        input_day = d.shift(target, -1)
        rows = synthetic_store_rows(SAI, start=d.shift(target, -75), days=75)
        groups = groups_for_day(rows, input_day, SAI)
        with patch.object(runtime, 'baseline_groups', return_value=groups):
            pred = runtime.build_prediction(rows, {'records': [], 'machines': []}, target, EmptyJournal())

        by = {g['name']: g for g in pred['groups']}
        self.assertEqual({n: g['model'] for n, g in by.items()}, {'A': 'blind', 'N': 'blind', 'バラエティ': 'variety'})
        # 通常機種は盲検先行採用中
        for name in ('A', 'N'):
            self.assertTrue(by[name]['trained'])
            self.assertEqual(by[name]['active'], 'learned')
            self.assertEqual(by[name]['selected'], by[name]['learned'])
            self.assertEqual(by[name]['status'], runtime.BLIND_STATUS)
        # バラエティは v5 学習継続・従来方式維持で保護
        self.assertTrue(by['バラエティ']['trained'])
        self.assertEqual(by['バラエティ']['active'], 'current')
        self.assertEqual(by['バラエティ']['selected'], by['バラエティ']['current'])
        self.assertEqual(by['バラエティ']['status'], '学習済み・将来成績を比較中')

        # 直接 BlindModel を呼んだ順位と完全一致する
        bm = blind.BlindModel(SAI)
        by_day = {}
        for r in rows:
            by_day.setdefault(r['day'], []).append(r)
        for day in sorted(by_day):
            bm.ingest_day(day, by_day[day])
        for g in groups[:2]:
            direct = bm.rank(target, g['name'], g['pool'], is_variety=False)
            self.assertEqual(by[g['name']]['learned'], [list(d.identity(r)) for r in direct[:len(g['current'])]])

        self.assertEqual(
            pred['source_sha256']['daily_learning_blind.py'],
            hashlib.sha256(Path(blind.__file__).read_bytes()).hexdigest(),
        )
        self.assertEqual(pred['blind'][SAI]['version'], blind.VERSION)
        self.assertGreater(pred['blind'][SAI]['trained_days'], 0)

        # 2026-11-29 より前の対象日では自動先行採用しない
        before_target = '2026-11-28'
        before_rows = [r for r in rows if r['day'] <= d.shift(before_target, -1)]
        before_groups = groups_for_day(before_rows, d.shift(before_target, -1), SAI)
        with patch.object(runtime, 'baseline_groups', return_value=before_groups):
            before_pred = runtime.build_prediction(before_rows, {'records': [], 'machines': []}, before_target, EmptyJournal())
        self.assertTrue(all(g['active'] == 'current' and g['selected'] == g['current'] for g in before_pred['groups']))

    def test_pstation_adopts_blind_and_aligns_renamed_machines(self):
        target = '2026-11-29'
        input_day = d.shift(target, -1)
        rows = []
        start = d.shift(target, -60)
        for i in range(60):
            day = d.shift(start, i)
            machine = 'ﾏｲｼﾞｬｸﾞﾗｰVI' if i < 35 else 'SマイジャグラーVI'
            for rack in range(1, 7):
                win = ((i + rack) % 3 == 0)
                rows.append(make_row(day, rack, machine, win=win, store=PS, rate='20', games=6000 if win else 2200))
        daily = [r for r in rows if r['day'] == input_day]
        groups = [dict(store=PS, rate='20', name='SマイジャグラーVI', pool=daily,
                       current=[d.identity(r) for r in daily[:2]])]
        with patch.object(runtime, 'baseline_groups', return_value=groups):
            pred = runtime.build_prediction(rows, {'records': [], 'machines': []}, target, EmptyJournal())

        g = pred['groups'][0]
        self.assertEqual(g['model'], 'blind')
        self.assertTrue(g['trained'])
        self.assertEqual(g['active'], 'learned')
        self.assertEqual(g['selected'], g['learned'])
        self.assertEqual(g['status'], runtime.BLIND_STATUS)
        self.assertTrue(all(item[2] == 'SマイジャグラーVI' for item in g['selected']))
        # P-STATION は全組盲検のため不要な v5 リッジ学習を行わない
        self.assertEqual(pred['models'], {})
        self.assertGreaterEqual(pred['blind'][PS]['trained_days'], 40)

    def test_nagamachiminami_remains_v5_and_current(self):
        target = '2026-11-29'
        input_day = d.shift(target, -1)
        rows = synthetic_store_rows(NAGA, start=d.shift(target, -75), days=75)
        groups = groups_for_day(rows, input_day, NAGA)
        with patch.object(runtime, 'baseline_groups', return_value=groups):
            pred = runtime.build_prediction(rows, {'records': [], 'machines': []}, target, EmptyJournal())
        by = {g['name']: g for g in pred['groups']}
        self.assertEqual({n: g['model'] for n, g in by.items()}, {'A': 'machine', 'N': 'store', 'バラエティ': 'variety'})
        self.assertTrue(all(g['active'] == 'current' and g['selected'] == g['current'] for g in pred['groups']))
        self.assertNotIn('blind', pred)

    def test_nightly_continuous_learning_progresses_while_adopted(self):
        start = '2026-09-15'
        rows_full = synthetic_store_rows(SAI, start=start, days=82)
        t1, t2 = '2026-11-29', '2026-12-05'
        r1 = [r for r in rows_full if r['day'] <= d.shift(t1, -1)]
        r2 = [r for r in rows_full if r['day'] <= d.shift(t2, -1)]
        with patch.object(runtime, 'baseline_groups', return_value=groups_for_day(r1, d.shift(t1, -1), SAI)):
            p1 = runtime.build_prediction(r1, {'records': [], 'machines': []}, t1, EmptyJournal())
        with patch.object(runtime, 'baseline_groups', return_value=groups_for_day(r2, d.shift(t2, -1), SAI)):
            p2 = runtime.build_prediction(r2, {'records': [], 'machines': []}, t2, EmptyJournal())
        self.assertGreater(p2['blind'][SAI]['trained_days'], p1['blind'][SAI]['trained_days'])
        self.assertGreater(p2['blind'][SAI]['trained_obs'], p1['blind'][SAI]['trained_obs'])

    def test_insufficient_data_falls_back_to_current_even_after_adopt_since(self):
        target = '2026-11-29'
        rows = synthetic_store_rows(SAI, start=d.shift(target, -2), days=2)
        groups = groups_for_day(rows, d.shift(target, -1), SAI)
        with patch.object(runtime, 'baseline_groups', return_value=groups):
            pred = runtime.build_prediction(rows, {'records': [], 'machines': []}, target, EmptyJournal())
        self.assertTrue(all(not g['trained'] and g['active'] == 'current'
                            and g['selected'] == g['current']
                            and g['status'] == '学習データ不足・従来方式' for g in pred['groups']))

    def test_28day_rollback_excludes_variety_and_never_auto_readopts(self):
        method = runtime.method_signature(SAI)

        def group_outcome(day, name, current_rate, learned_rate):
            return dict(
                key=d.encoded([SAI, '', name]),
                day=day,
                trained=True,
                method=method,
                current=current_rate,
                learned=learned_rate,
                n_current=10,
                n_learned=10,
                k_current=10,
                k_learned=10,
                plus_current=round(10 * current_rate),
                plus_learned=round(10 * learned_rate),
                missing_current=0.0,
                missing_learned=0.0,
            )

        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                with j.db:
                    j.state('start', '2026-11-12')
                    # 第1ブロック（2026-11-29〜2026-12-26）：通常機種は互角（差 0）、バラエティだけ大敗（-50pt）
                    for i in range(28):
                        day = d.shift('2026-11-29', i)
                        groups = [
                            group_outcome(day, 'A', 0.4, 0.4),
                            group_outcome(day, 'バラエティ', 0.6, 0.1),
                        ]
                        j.append('outcomes', f'{day}|{SAI}', dict(target=day, store=SAI, groups=groups))
                # 35日目（2027-01-03）で第1ブロック成熟 → バラエティ除外のため切り戻されない
                runtime.decisions(j, '2027-01-03')
                dec1 = j.get('decisions', f'rollback:{SAI}:2026-11-29:1')
                self.assertIsNotNone(dec1)
                self.assertFalse(dec1['rollback'])
                self.assertEqual(dec1['basis'], runtime.BLIND_ADOPT_BASIS)
                self.assertEqual(runtime.effective_state(j, SAI, method, as_of='2027-01-04')['active'], 'learned')

                # 第2ブロック（2026-12-27〜2027-01-23）：通常機種が -10pt 悪化、バラエティは +50pt 好調
                with j.db:
                    for i in range(28):
                        day = d.shift('2026-12-27', i)
                        groups = [
                            group_outcome(day, 'A', 0.5, 0.4),
                            group_outcome(day, 'バラエティ', 0.1, 0.6),
                        ]
                        j.append('outcomes', f'{day}|{SAI}', dict(target=day, store=SAI, groups=groups))
                # 成熟1日前（2027-01-30）はまだ切り戻さない
                runtime.decisions(j, '2027-01-30')
                self.assertEqual(runtime.effective_state(j, SAI, method, as_of='2027-01-30')['active'], 'learned')
                # 成熟日（2027-01-31）で通常機種の悪化により自動切り戻し
                runtime.decisions(j, '2027-01-31')
                dec2 = j.get('decisions', f'rollback:{SAI}:2026-11-29:2')
                self.assertTrue(dec2['rollback'])
                self.assertEqual(j.get('state', 'store:' + SAI), {'active': 'current', 'since': '2027-01-31'})
                # 切り戻し後は自動再採用されない
                self.assertEqual(runtime.effective_state(j, SAI, method, as_of='2027-02-01')['active'], 'current')
                rows = synthetic_store_rows(SAI, start=d.shift('2027-02-01', -60), days=60)
                groups = groups_for_day(rows, '2027-01-31', SAI)
                with patch.object(runtime, 'baseline_groups', return_value=groups):
                    after = runtime.build_prediction(rows, {'records': [], 'machines': []}, '2027-02-01', j)
                self.assertTrue(all(g['active'] == 'current' and g['selected'] == g['current'] for g in after['groups']))
                self.assertTrue(all(g['status'] == '学習済み・将来成績を比較中' for g in after['groups']))
                # 切り戻し前に始まった adoption:1（2026-11-12〜2027-03-03）では再採用しない
                with j.db:
                    for i in range(39):
                        day = d.shift('2027-01-24', i)
                        j.append('outcomes', f'{day}|{SAI}',
                                 dict(target=day, store=SAI, groups=[group_outcome(day, 'A', 0.2, 0.8)]))
                runtime.decisions(j, '2027-03-11')
                self.assertEqual(runtime.effective_state(j, SAI, method, as_of='2027-03-12')['active'], 'current')
            finally:
                j.close()

    def test_pstation_28day_rollback_and_future_row_cutoff(self):
        # 1) P-STATION も 2026-11-29 起算の 28日自動切り戻しで監視され、切り戻し後は再採用されない
        method = runtime.method_signature(PS)
        with tempfile.TemporaryDirectory() as temp:
            j = d.Journal(Path(temp) / 'journal.sqlite3')
            try:
                with j.db:
                    j.state('start', '2026-11-12')
                    for i in range(28):
                        day = d.shift('2026-11-29', i)
                        g = dict(
                            key=d.encoded([PS, '20', 'SマイジャグラーVI']),
                            day=day, trained=True, method=method,
                            current=0.45, learned=0.35, n_current=10, n_learned=10,
                            k_current=10, k_learned=10, plus_current=5, plus_learned=4,
                            missing_current=0.0, missing_learned=0.0,
                        )
                        j.append('outcomes', f'{day}|{PS}', dict(target=day, store=PS, groups=[g]))
                runtime.decisions(j, '2027-01-03')
                dec = j.get('decisions', f'rollback:{PS}:2026-11-29:1')
                self.assertTrue(dec['rollback'])
                self.assertEqual(dec['basis'], runtime.BLIND_ADOPT_BASIS)
                self.assertEqual(j.get('state', 'store:' + PS), {'active': 'current', 'since': '2027-01-03'})
                self.assertEqual(runtime.effective_state(j, PS, method, as_of='2027-01-04')['active'], 'current')
            finally:
                j.close()

        # 2) history_rows に target 以降の未来行が混じっても runtime 側で遮断され予測が不変
        target = '2026-11-29'
        rows = synthetic_store_rows(SAI, start=d.shift(target, -60), days=60)
        groups = groups_for_day(rows, d.shift(target, -1), SAI)
        future = [make_row(target, rack, 'A', win=True, store=SAI, games=19000, net=99999) for rack in range(1, 7)]
        with patch.object(runtime, 'baseline_groups', return_value=groups):
            p_clean = runtime.build_prediction(rows, {'records': [], 'machines': []}, target, EmptyJournal(), history_rows=rows)
            p_with_future = runtime.build_prediction(rows, {'records': [], 'machines': []}, target, EmptyJournal(), history_rows=rows + future)
        self.assertEqual(p_clean['groups'], p_with_future['groups'])
        self.assertEqual(p_clean['blind'], p_with_future['blind'])

    def test_four_screen_method_text_consistency(self):
        root = Path(__file__).resolve().parents[2]
        learned_text = view.METHOD_TEXT[True]
        current_text = view.METHOD_TEXT[False]
        summary_text = ('幸町（通常機種）・P-STATIONは完全盲検の過去検証に基づき日次学習版を採用し、'
                        '28日ごとの自動切り戻しで監視しています。幸町バラエティと長町南は将来の成績で改善を確認するまで従来方式を維持します。')
        for rel in (
            'database/daily_learning_ui.py',
            'database_android/lib/daily_learning_page.dart',
            'share_viewer/daily_learning.mjs',
        ):
            content = (root / rel).read_text(encoding='utf-8')
            self.assertIn(summary_text, content, rel)
            if rel != 'database/daily_learning_ui.py':
                self.assertIn(learned_text, content, rel)
                self.assertIn(current_text, content, rel)


if __name__ == '__main__':
    unittest.main()
