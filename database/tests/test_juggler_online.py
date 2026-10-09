"""ジャグラーオンラインの差枚（お試し、../JUGGLER_ONLINE.md）。Androidで足した jo_net などが、バックアップで
PCに入り、PCのカレンダー・閲覧用ファイルで推定差枚より優先されること。"""
import json
import tempfile
import unittest
from pathlib import Path

from core import Store, export_viewer, import_backup, plan_backup_import, rack_net


def record(rack=779, **extra):
    return dict(store='saiwaichou', kind_code=21, day='2026-10-06', machine='Sネオアイムジャグラー EX−KK',
                rack=rack, games=4827, bb=26, rb=11, max_hold=1883, **extra)


class JugglerOnlineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Store(Path(self.tmp.name) / 'database.sqlite3')
        self.addCleanup(self.db.close)
        self.db.save([record(779), record(780)])
        self.path = Path(self.tmp.name) / 'backup.json'

    def write(self, records):
        self.path.write_text(json.dumps(dict(format='database-backup', version=1, records=records),
                                        ensure_ascii=False), encoding='utf-8')

    def saved(self, rack):
        return next(r for r in self.db.rows(store='saiwaichou', day='2026-10-06') if r['rack'] == rack)

    def test_a_newer_juggler_online_net_comes_in_even_when_the_numbers_are_the_same(self):
        self.write([record(779, jo_net=1377, jo_games=4827, jo_captured_at='2026-10-09T23:10:00+09:00')])
        plan = import_backup(self.db, self.path)
        self.assertEqual(len(plan['jo_only']), 1)
        self.assertEqual(self.saved(779)['jo_net'], 1377)
        self.assertEqual(self.saved(779)['games'], 4827, '数値はそのまま')
        # 古い時刻の値では上書きしない。同じ値は「同じ内容」。
        self.write([record(779, jo_net=999, jo_captured_at='2026-10-09T20:00:00+09:00')])
        plan = import_backup(self.db, self.path)
        self.assertEqual((len(plan['jo_only']), len(plan['unchanged'])), (0, 1))
        self.assertEqual(self.saved(779)['jo_net'], 1377)
        # 新しい時刻の値は入る。
        self.write([record(779, jo_net=1380, jo_captured_at='2026-10-10T08:00:00+09:00')])
        self.assertEqual(len(plan_backup_import(self.db, [record(779, jo_net=1380, jo_captured_at='2026-10-10T08:00:00+09:00')])['jo_only']), 1)

    def test_a_rack_made_on_android_from_juggler_online_comes_in_as_new(self):
        # メルヘンで取り込めなかった日の台を、Androidがジャグラーオンラインの数字で作った（グラフ・最大持玉は無い）。
        made = dict(store='saiwaichou', kind_code=21, day='2026-10-07', machine='Sネオアイムジャグラー EX−KK',
                    rack=780, games=3299, bb=11, rb=7, jo_net=-844, jo_games=3299, jo_created=True,
                    jo_captured_at='2026-10-10T00:30:00+09:00', first_captured_at='2026-10-10T00:30:00+09:00')
        self.write([made])
        plan = import_backup(self.db, self.path)
        self.assertEqual(len(plan['new']), 1)
        row = next(r for r in self.db.rows(store='saiwaichou', day='2026-10-07'))
        self.assertEqual((row['games'], row['bb'], row['rb'], row.get('max_hold')), (3299, 11, 7, None))
        self.assertEqual((row['jo_net'], row['jo_created']), (-844, True))
        self.assertEqual(rack_net(row), (-844, False, True))

    def test_the_juggler_online_net_is_preferred_over_the_estimate(self):
        self.assertEqual(rack_net({'jo_net': -280, 'graph_measurement': None, 'max_hold': 10, 'games': 100}), (-280, False, True))
        self.assertEqual(rack_net({'graph_measurement': None, 'max_hold': 10, 'games': 100}), (None, False, False))
        self.assertEqual(rack_net({'jo_net': True})[2], False, '真偽値は差枚にしない')

    def test_the_calendar_and_the_viewer_file_use_it(self):
        from event_calendar import MeruhenEvents, meruhen_day_nets
        self.db.save([record(779, jo_net=1377, jo_captured_at='2026-10-09T23:10:00+09:00')])
        nets = meruhen_day_nets(self.db, 'saiwaichou', '2026-10-01', '2026-10-31')
        self.assertEqual((nets['2026-10-06']['total'], nets['2026-10-06']['captured']), (1377, 1), '推定できない台は足さない')
        rows = MeruhenEvents(self.db.path).day_records('saiwaichou', '2026-10-06')
        self.assertEqual(sorted((r['rack'], r['net']) for r in rows), [(779, 1377), (780, None)])
        out = Path(self.tmp.name) / 'viewer.json'
        export_viewer(self.db, out)
        viewer = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual({r['rack']: r.get('jo_net') for r in viewer['records']}, {779: 1377, 780: None})


if __name__ == '__main__':
    unittest.main()
