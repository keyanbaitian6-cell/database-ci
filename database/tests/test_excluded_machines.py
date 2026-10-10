"""対象外の機種（2026-10-11 利用者「1279番台の聖闘士星矢ってずっと稼働停止なので取り込まない、表示しないように」）。
幸町の聖闘士星矢 海皇覚醒は保存せず、以前に保存した記録も消さずに、読み出し・閲覧用ファイル・
バックアップ・カレンダー・機種の選択肢から外す。"""
import json
import tempfile
import unittest
from pathlib import Path

from core import Store, export_backup, export_viewer, is_excluded_machine, is_hidden_machine, plan_backup_import

SEIYA = 'L聖闘士星矢海皇覚醒ED'


def row(machine, rack, store='saiwaichou', day='2026-10-09', **extra):
    return dict(store=store, kind_code=21, day=day, machine=machine, rack=rack,
                games=300, bb=1, rb=0, max_hold=100, jo_net=-250, **extra)


class ExcludedMachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Store(Path(self.tmp.name) / 'database.sqlite3')
        self.addCleanup(self.db.close)
        self.db.save([row('Lモンキーターン5CE', 722)])
        # 以前に保存した1279番台（対象外にする前の記録）。保存の入口を通さずに置く。
        with self.db.db:
            self.db.db.execute('INSERT INTO days VALUES (?,?,?,?,?)',
                               ('saiwaichou', '2026-10-09', SEIYA, 1279, json.dumps(row(SEIYA, 1279), ensure_ascii=False)))

    def test_which_names_are_excluded(self):
        for name in (SEIYA, 'L 聖闘士星矢 海皇覚醒 ED', 'Ｌ聖闘士星矢海皇覚醒ＥＤ'):
            self.assertTrue(is_excluded_machine('saiwaichou', name), name)
        self.assertFalse(is_excluded_machine('nagamachiminami', SEIYA), '幸町だけ')
        self.assertFalse(is_excluded_machine('saiwaichou', 'S聖闘士星矢 冥王復活'), '別の聖闘士星矢は対象のまま')
        self.assertTrue(is_excluded_machine('saiwaichou', 'L／沖ドキ！DUO'), 'これまでの対象外もそのまま')
        # 表示しないのは聖闘士星矢だけ。沖ドキなど、対象外にする前に取り込んだ記録は今までどおり出す。
        self.assertTrue(is_hidden_machine('saiwaichou', 'L 聖闘士星矢 海皇覚醒 ED'))
        self.assertFalse(is_hidden_machine('saiwaichou', 'L／オキドキデュオ2／FR'))
        self.assertFalse(is_hidden_machine('nagamachiminami', 'S/沖ﾄﾞｷ!GOLD/LS'))

    def test_old_okidoki_rows_are_still_shown(self):
        okidoki = 'L／オキドキデュオ2／FR'
        with self.db.db:
            self.db.db.execute('INSERT INTO days VALUES (?,?,?,?,?)',
                               ('saiwaichou', '2026-10-09', okidoki, 900, json.dumps(row(okidoki, 900), ensure_ascii=False)))
        self.assertEqual([r['rack'] for r in self.db.rows(store='saiwaichou')], [722, 900])
        self.assertIn(okidoki, self.db.machines_for('saiwaichou', '2026-10-09'))

    def test_saved_rows_stay_but_are_not_read(self):
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM days').fetchone()[0], 2, '記録は消さない')
        self.assertEqual([r['rack'] for r in self.db.rows(store='saiwaichou')], [722])
        self.assertEqual(len(self.db.raw_payloads(store='saiwaichou')), 1)
        self.assertEqual(self.db.machines_for('saiwaichou', '2026-10-09'), ['Lモンキーターン5CE'])

    def test_not_saved_again(self):
        self.db.save([row(SEIYA, 1279, day='2026-10-10'), row('Lモンキーターン5CE', 722, day='2026-10-10')])
        self.assertEqual(self.db.db.execute("SELECT COUNT(*) FROM days WHERE day='2026-10-10'").fetchone()[0], 1)
        plan = plan_backup_import(self.db, [row(SEIYA, 1279, day='2026-10-08')])
        self.assertEqual(sum(len(v) for v in plan.values() if isinstance(v, list)), 0,
                         'Androidのバックアップに残っていても、新規・重複などにしない')

    def test_viewer_backup_and_calendar_leave_it_out(self):
        out = Path(self.tmp.name) / 'viewer.json'
        export_viewer(self.db, out)
        self.assertEqual([r['rack'] for r in json.loads(out.read_text(encoding='utf-8'))['records']], [722])
        backup = Path(self.tmp.name) / 'backup.json'
        export_backup(self.db, backup)
        self.assertEqual([r['rack'] for r in json.loads(backup.read_text(encoding='utf-8'))['records']], [722])
        from event_calendar import MeruhenEvents, meruhen_day_nets
        nets = meruhen_day_nets(self.db, 'saiwaichou', '2026-10-01', '2026-10-31')
        self.assertEqual((nets['2026-10-09']['total'], nets['2026-10-09']['captured']), (-250, 1))
        self.assertEqual([r['rack'] for r in MeruhenEvents(self.db.path).day_records('saiwaichou', '2026-10-09')], [722])


if __name__ == '__main__':
    unittest.main()
