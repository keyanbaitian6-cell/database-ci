"""差枚の分からない日の勝率（2026-10-17 利用者「差枚を出せないところについては勝率を書いてほしい
何台中何台プラスってところから割り出して」）。共有ページ tool/test_share_viewer.mjs・Flutter
test/win_rate_test.dart と同じ例で同じ答えになること。"""
from pathlib import Path
import tempfile
import unittest

from core import Store, rack_won, show_win_rate, win_rate_text
from event_calendar import meruhen_day_nets, net_color, net_text, ZERO_COLOR


def measurement(heights):
    curve = [[i * 10 + 0.5, 200.5 - h] for i, h in enumerate(heights)]
    ys = [p[1] for p in curve]
    return {'baseline_y': 200.5, 'peak_y': min(ys), 'trough_y': max(ys), 'end_y': curve[-1][1], 'curve': curve}


def rack(n, **extra):
    return {'store': 'saiwaichou', 'kind_code': 21, 'day': '2026-09-10', 'machine': 'M', 'rack': n,
            'games': 3000, 'bb': 5, 'rb': 2, **extra}


RACKS = [
    rack(1, graph_measurement=measurement([0, 80, 50])),   # 終点+50px → プラス
    rack(2, graph_measurement=measurement([0, 20, -30])),  # マイナス
    rack(3, graph_measurement=measurement([0, 40, 0.5])),  # 1px以内 → プラスにしない
    rack(4, games=2000, bb=0, rb=0),                       # 大当たり0回 → マイナス
    rack(5, games=0, bb=0, rb=0),                          # 未稼働 → 数えない
    rack(6),                                               # グラフ無し → 数えない
]


class WinRateTests(unittest.TestCase):
    def test_same_examples_as_android_and_share_page(self):
        self.assertEqual([rack_won(r) for r in RACKS], [True, False, False, False, None, None])
        self.assertEqual(win_rate_text(1, 4), '勝率25%')
        self.assertEqual(win_rate_text(255, 532), '勝率48%')
        self.assertEqual(win_rate_text(1, 8), '勝率13%')  # 0.5は切り上げ
        self.assertTrue(show_win_rate(1, 4))
        self.assertFalse(show_win_rate(2, 4))
        self.assertFalse(show_win_rate(0, 0))
        # 推定差枚を出さない店・日（長町南10/7）はグラフも信用しないので数えない。
        self.assertIsNone(rack_won(dict(RACKS[0], store='nagamachiminami', day='2026-10-07')))
        # 差枚があればその符号（ジャグラーオンラインの差枚）。
        self.assertFalse(rack_won(dict(RACKS[0], jo_net=-1)))

    def test_calendar_cell_shows_win_rate_only_when_most_nets_are_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Store(Path(folder) / 'database.sqlite3')
            try:
                db.save(RACKS + [dict(r, day='2026-09-11', jo_net=net) for r, net in
                                 zip(RACKS[:4], (500, -200, None, None))])
                nets = meruhen_day_nets(db, 'saiwaichou', '2026-09-10', '2026-09-11')
            finally:
                db.close()
        first = nets['2026-09-10']
        self.assertEqual((first['captured'], first['judged'], first['won']), (0, 4, 1))
        self.assertEqual(net_text(first), '勝率25%')
        self.assertEqual(net_color(first), ZERO_COLOR)
        # 4台中2台の差枚が分かる日は、今までどおり総差枚。
        second = nets['2026-09-11']
        self.assertEqual((second['captured'], second['judged']), (2, 4))
        self.assertEqual(net_text(second), '+300')


if __name__ == '__main__':
    unittest.main()
