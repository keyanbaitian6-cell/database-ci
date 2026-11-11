"""日次学習・採用中の候補の表示内容（PCの窓・結果ページ）。2026-11-12、4画面で同じ順・意味にそろえた。"""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

import daily_learning_display as display
import daily_learning_view as view

LONG = 'とても長い機種名の表示を確かめるための試験機・スーパーロングネームエディションｻﾝﾌﾞﾚｲｸ'


def doc():
    return {'format': 'daily-learning', 'version': 1, 'updated_at': '2026-11-12T00:30:00+09:00',
            'status': '長町南：11/12の事前予測は保存済みです／幸町：処理失敗（原本DBを読めません）。従来方式を使用してください'
                      '／P-STATION：取り込み待ち：P-STATIONの確定前データが残っています／同期先未設定または利用不可',
            'days': [{'target': '2026-11-12', 'input_day': '2026-11-11', 'saved_at': '2026-11-12T00:02:00+09:00', 'groups': [
                {'store': 'nagamachiminami', 'name': LONG, 'active': 'learned', 'status': '改善を確認して採用中',
                 'selected': [['nagamachiminami', '', LONG, n] for n in (1162, 1157, 1203)]},
                {'store': 'nagamachiminami', 'name': 'バラエティ', 'active': 'current', 'status': '学習データ不足・従来方式',
                 'selected': [['nagamachiminami', '', '機種A', 301], ['nagamachiminami', '', LONG, 305]]},
                {'store': 'saiwaichou', 'name': '試験機', 'active': 'current', 'status': 'x',
                 'selected': [['saiwaichou', '', '試験機', 1]]}]}]}


NOW = datetime.fromisoformat('2026-11-12T07:00:00+09:00')


class ViewTests(unittest.TestCase):
    def test_count_order_and_labels(self):
        v = view.daily_view(doc(), 'nagamachiminami', '2026-11-12', NOW)
        self.assertEqual(v['count'], 5)
        self.assertEqual(v['scope'], '1機種とバラエティ')
        self.assertEqual([[r for r, _ in g['racks']] for g in v['groups']], [[1162, 1157, 1203], [301, 305]])  # 保存した順
        self.assertEqual([m for _, m in v['groups'][1]['racks']], ['機種A', LONG])                           # バラエティだけ機種名
        self.assertEqual([g['learned'] for g in v['groups']], [True, False])
        self.assertEqual(v['alerts'], ['同期先未設定または利用不可'])           # ほかの店の失敗はこの店の注意にしない
        self.assertEqual(view.date_label('2026-11-12'), '11月12日（木）')
        self.assertEqual(view.time_label('2026-11-11T15:02:00Z'), '11月12日 0:02')

    def test_alerts_failure_past_stale_and_empty(self):
        self.assertTrue(view.daily_view(doc(), 'saiwaichou', '2026-11-12', NOW)['alerts'][0].startswith('処理失敗'))
        empty = view.daily_view(doc(), 'pscube:c740601:20', '2026-11-12', NOW)
        self.assertEqual(empty['count'], 0)
        self.assertTrue(any('取り込み待ち' in a for a in empty['alerts']))
        self.assertTrue(empty['alerts'][-1].startswith('この日の保存済み候補はありません'))
        later = ' '.join(view.daily_view(doc(), 'nagamachiminami', '2026-11-12',
                                         datetime.fromisoformat('2026-11-14T09:00:00+09:00'))['alerts'])
        self.assertIn('過去の対象日', later)
        self.assertIn('本日の処理結果は届いていません', later)

    def test_default_target_switches_at_2330(self):
        at = datetime.fromisoformat
        self.assertEqual(view.default_target(at('2026-11-11T23:29:59+09:00')), '2026-11-11')
        self.assertEqual(view.default_target(at('2026-11-11T23:30:00+09:00')), '2026-11-12')
        self.assertEqual(view.default_target(at('2026-11-11T14:30:00+00:00')), '2026-11-12')   # PCの時刻設定ではなく日本時間

    def test_report_panel_keeps_saved_order_and_machine_filter(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'daily-learning.json').write_text(json.dumps(doc(), ensure_ascii=False), encoding='utf-8')
            html = display.report_panel(temp, '2026-11-11', 'nagamachiminami', now=NOW)
            self.assertLess(html.index('>1162<'), html.index('>1157<'))
            self.assertLess(html.index('>1157<'), html.index('>1203<'))
            self.assertIn('採用中 日次学習版', html)
            self.assertIn('5台', html)
            only = display.report_panel(temp, '2026-11-11', 'nagamachiminami', LONG, now=NOW)
            self.assertIn('>305<', only)                     # バラエティの中でこの機種の台
            self.assertNotIn('>301<', only)
            self.assertIn('4台', only)
            none = display.report_panel(temp, '2026-11-11', 'pscube:c740601:20', now=NOW)
            self.assertIn('取り込み待ち', none)
            self.assertIn('保存済み事前予測はありません', none)
            self.assertIn('記録がまだ届いていません', display.report_panel(Path(temp) / 'none', '2026-11-11', 'saiwaichou'))


if __name__ == '__main__':
    unittest.main()
