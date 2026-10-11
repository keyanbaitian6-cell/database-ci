"""確定が出た台の印🌈（2026-10-11 利用者「確定が出た台に簡単に🌈のマークつけられるようにしたい」
「ボタンワンタッチでつけられる感じ」「この虹マークがついてない期間（最終🌈の日付）を表示させる欄も」）。
PCで付け外しし、閲覧用ファイル・バックアップ・結果に出す。仕様は ../RAINBOW.md。"""
import json
import tempfile
import unittest
from pathlib import Path

from core import Store, export_backup, export_viewer, import_backup, rack_mark


def row(rack, day='2026-10-10', machine='Lモンキーターン5CE', store='nagamachiminami', **extra):
    return dict(store=store, kind_code=21, day=day, machine=machine, rack=rack,
                games=3000, bb=10, rb=5, max_hold=1500, **extra)


class RainbowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.db = Store(self.folder / 'database.sqlite3')
        self.addCleanup(self.db.close)
        self.db.save([row(660), row(661), row(660, day='2026-09-26'), row(660, day='2026-10-05'),
                      row(1279, machine='L聖闘士星矢海皇覚醒ED', store='saiwaichou')])

    def payload(self, rack, day='2026-10-10'):
        return json.loads(self.db.db.execute(
            'SELECT payload FROM days WHERE store=? AND day=? AND rack=?', ('nagamachiminami', day, rack)).fetchone()[0])

    def test_set_and_clear(self):
        self.assertEqual(self.db.set_rainbow('nagamachiminami', '2026-10-10', 660, True), 1)
        self.assertIs(self.payload(660)['rainbow'], True)
        self.assertEqual(self.db.rainbow_racks('nagamachiminami', '2026-10-10'), [660])
        self.db.set_rainbow('nagamachiminami', '2026-10-10', 660, False)
        self.assertNotIn('rainbow', self.payload(660))
        self.assertEqual(self.db.rainbow_racks('nagamachiminami', '2026-10-10'), [])

    def test_only_saved_racks_and_valid_input(self):
        with self.assertRaisesRegex(ValueError, '先に表を取り込んで'):
            self.db.set_rainbow('nagamachiminami', '2026-10-10', 999, True)
        for bad in (('other', '2026-10-10', 660, True), ('nagamachiminami', '2026-02-30', 660, True),
                    ('nagamachiminami', '2026-10-10', 660, 'yes')):
            with self.assertRaises(ValueError, msg=bad):
                self.db.set_rainbow(*bad)
        with self.assertRaises(ValueError, msg='表示しない機種（1279番台）には付けない'):
            self.db.set_rainbow('saiwaichou', '2026-10-10', 1279, True)

    def test_kept_when_the_table_is_captured_again_and_shown_in_files(self):
        self.db.set_rainbow('nagamachiminami', '2026-10-10', 660, True)
        self.db.save([dict(row(660), games=3500)])
        self.assertIs(self.payload(660)['rainbow'], True, '表を取り込み直しても残る')
        self.assertEqual(self.payload(660)['games'], 3500)
        viewer = self.folder / 'viewer.json'
        export_viewer(self.db, viewer)
        marked = [r for r in json.loads(viewer.read_text(encoding='utf-8'))['records'] if r.get('rainbow')]
        self.assertEqual([(r['day'], r['rack']) for r in marked], [('2026-10-10', 660)], '閲覧ページへ渡す')
        backup = self.folder / 'backup.json'
        export_backup(self.db, backup)
        self.assertIn('"rainbow": true', backup.read_text(encoding='utf-8'), '共有ページはバックアップを読む')
        self.assertEqual(rack_mark({'rainbow': True}), ' 🌈')
        self.assertEqual(rack_mark({}), '')

    def test_backup_from_another_device_adds_the_mark_and_android_backups_keep_it(self):
        backup = self.folder / 'other.json'
        record = dict(row(661), rainbow=True)
        backup.write_text(json.dumps({'format': 'database-backup', 'version': 1, 'records': [record]}), encoding='utf-8')
        plan = import_backup(self.db, backup)
        self.assertEqual(len(plan['setting_only']), 1)
        self.assertIs(self.payload(661)['rainbow'], True)
        # Androidのバックアップ（🌈を付けない端末。項目が無い）を読んでも外れない。
        backup.write_text(json.dumps({'format': 'database-backup', 'version': 1, 'records': [row(661)]}), encoding='utf-8')
        import_backup(self.db, backup)
        self.assertIs(self.payload(661)['rainbow'], True)

    def test_last_rainbow_days_and_the_calendar_rankings(self):
        from event_calendar import MeruhenEvents, last_rainbow_text
        self.db.set_rainbow('nagamachiminami', '2026-09-26', 660, True)
        self.assertEqual(self.db.last_rainbow_days('nagamachiminami', '2026-10-10'), {660: '2026-09-26'})
        self.db.set_rainbow('nagamachiminami', '2026-10-05', 660, True)
        self.assertEqual(self.db.last_rainbow_days('nagamachiminami', '2026-10-10'), {660: '2026-10-05'})
        self.assertEqual(self.db.last_rainbow_days('nagamachiminami', '2026-10-05'), {660: '2026-09-26'},
                         'その日より前だけ')
        events = MeruhenEvents(self.folder / 'database.sqlite3')
        rows = {r['rack']: r for r in events.day_records('nagamachiminami', '2026-10-10')}
        self.assertEqual(last_rainbow_text(rows[660]), '10/5（5日前）')
        self.assertEqual(last_rainbow_text(rows[661]), 'なし')
        events.set_rainbow('nagamachiminami', '2026-10-10', 661, True)
        rows = {r['rack']: r for r in events.day_records('nagamachiminami', '2026-10-10')}
        self.assertTrue(rows[661]['rainbow'])
        self.assertEqual(last_rainbow_text(rows[661]), '当日')
        changed = []
        MeruhenEvents(self.folder / 'database.sqlite3', changed.append).notify()
        self.assertEqual(len(changed), 1, '窓を閉じたときに1回だけバックアップ・閲覧用ファイルを作り直す')

    def test_capture_card_api(self):
        from browser_import import _Bridge
        bridge = _Bridge(self.folder / 'database.sqlite3', self.folder, 'x')
        ask = lambda **payload: json.loads(bridge.rainbow_racks(json.dumps(payload, ensure_ascii=False)))
        table = dict(store='nagamachiminami', day='2026-10-10', machine='Lモンキーターン5CE', rack=None)
        self.assertEqual(ask(**table)['racks'], [{'rack': 660, 'on': False}, {'rack': 661, 'on': False}])
        self.assertEqual(ask(**dict(table, machine='L モンキーターン 5CE'))['racks'][0]['rack'], 660,
                         '空白の違う機種名でも同じ機種')
        result = json.loads(bridge.set_rainbow(json.dumps(dict(store='nagamachiminami', day='2026-10-10', rack=661, on=True))))
        self.assertEqual((result['ok'], result['on']), (True, True))
        self.assertEqual(ask(**dict(table, machine=None, rack=661))['racks'], [{'rack': 661, 'on': True}], '個別台のページ')
        self.assertEqual(ask(store='x', day='2026-10-10')['racks'], [])
        bad = json.loads(bridge.set_rainbow(json.dumps(dict(store='nagamachiminami', day='2026-10-10', rack=999, on=True))))
        self.assertFalse(bad['ok'])
        self.assertIn('先に表を取り込んで', bad['message'])


    def test_marks_from_the_phone_are_pulled_and_the_newer_change_wins(self):
        """iPhoneの閲覧ページで付け外しした🌈（RAINBOW.md「iPhoneから付ける」）を同期フォルダから取り込む。"""
        from core import SHARED_RAINBOW_NAME, pull_shared_rainbow
        folder = self.folder / 'sync'
        folder.mkdir()
        write = lambda marks: (folder / SHARED_RAINBOW_NAME).write_text(
            json.dumps({'format': 'database-rainbow', 'version': 1, 'marks': marks}), encoding='utf-8')
        mark = lambda rack, on, at, **extra: dict(store='nagamachiminami', day='2026-10-10', rack=rack, on=on,
                                                  updated_at=at, **extra)
        self.assertEqual(pull_shared_rainbow(self.db, folder), 0, 'ファイルが無ければ何もしない')
        write([mark(660, True, '2026-10-11T13:00:00.000Z'), mark(999, True, '2026-10-11T13:00:00.000Z'),
               mark(661, True, 'bad'), {'store': 'other'}])
        self.assertEqual(pull_shared_rainbow(self.db, folder), 1, '記録の無い台・形の違う印は飛ばす')
        self.assertIs(self.payload(660)['rainbow'], True)
        self.assertEqual(self.payload(660)['rainbow_at'], '2026-10-11T13:00:00.000Z')
        self.assertEqual(pull_shared_rainbow(self.db, folder), 0, '同じ印は2回取り込まない')
        # PCで後から外した → iPhoneの古い印では付け直さない。
        self.db.set_rainbow('nagamachiminami', '2026-10-10', 660, False, at='2026-10-11T23:00:00+09:00')
        self.assertEqual(pull_shared_rainbow(self.db, folder), 0)
        self.assertNotIn('rainbow', self.payload(660))
        # iPhoneでさらに後から付けた → 付く。
        write([mark(660, True, '2026-10-11T15:00:00.000Z')])
        self.assertEqual(pull_shared_rainbow(self.db, folder), 1)
        self.assertIs(self.payload(660)['rainbow'], True)
        (folder / SHARED_RAINBOW_NAME).write_text('{broken', encoding='utf-8')
        self.assertEqual(pull_shared_rainbow(self.db, folder), 0, '読めないファイルは無視')

    def test_pc_changes_keep_their_time(self):
        self.db.set_rainbow('nagamachiminami', '2026-10-10', 661, True)
        at = self.payload(661)['rainbow_at']
        self.db.set_rainbow('nagamachiminami', '2026-10-10', 661, False)
        self.assertNotIn('rainbow', self.payload(661))
        self.assertGreaterEqual(self.payload(661)['rainbow_at'], at, '外しても時刻は残す（iPhoneの古い印に負けない）')


    def test_an_older_backup_does_not_bring_back_a_removed_mark(self):
        """自己点検で見つけたずれ（2026-10-11）：PCで外した🌈が、🌈の付いた古いバックアップ（グラフ追加など）を
        読み込むと付き直っていた。付け外しした時刻の新しい方を残す。"""
        self.db.set_rainbow('nagamachiminami', '2026-10-10', 660, True, at='2026-10-11T12:00:00+09:00')
        old = self.payload(660)
        self.db.set_rainbow('nagamachiminami', '2026-10-10', 660, False, at='2026-10-11T13:00:00+09:00')
        backup = self.folder / 'old.json'
        record = dict(old, graph_measurement=dict(baseline_y=200.5, peak_y=100, trough_y=210, end_y=150))
        backup.write_text(json.dumps({'format': 'database-backup', 'version': 1, 'records': [record]}), encoding='utf-8')
        plan = import_backup(self.db, backup)
        self.assertEqual(len(plan['graph_only']), 1, 'グラフは足す')
        self.assertIn('graph_measurement', self.payload(660))
        self.assertNotIn('rainbow', self.payload(660), '外した🌈は付き直らない')
        self.assertEqual(self.payload(660)['rainbow_at'], '2026-10-11T13:00:00+09:00')
        # ほかの端末で後から外した（🌈なし・時刻が新しい）バックアップは、外す方を取り込む。
        self.db.set_rainbow('nagamachiminami', '2026-10-10', 661, True, at='2026-10-11T12:00:00+09:00')
        removed = dict(self.payload(661), rainbow_at='2026-10-11T14:00:00+09:00')
        removed.pop('rainbow')
        backup.write_text(json.dumps({'format': 'database-backup', 'version': 1, 'records': [removed]}), encoding='utf-8')
        self.assertEqual(len(import_backup(self.db, backup)['setting_only']), 1)
        self.assertNotIn('rainbow', self.payload(661))
        # 表の取り込み直し（🌈の項目なし）では、どちらも変わらない。
        self.db.set_rainbow('nagamachiminami', '2026-10-10', 661, True)
        self.db.save([dict(row(661), games=3600)])
        self.assertIs(self.payload(661)['rainbow'], True)


if __name__ == '__main__':
    unittest.main()
