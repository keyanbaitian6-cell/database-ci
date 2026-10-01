import json
import tempfile
import unittest
from pathlib import Path

from core import Store, import_backup, plan_backup_import, read_backup_file
from pscube_import import PscubeStore, ROOT_URL


def record(rack=1):
    return dict(store='nagamachiminami', kind_code=21, day='2026-10-01',
                machine='試験機種', rack=rack, games=3000, bb=12, rb=6)


def payload(**extra):
    return dict(format='database-backup', version=1, records=[record()], **extra)


def lines(doc):
    head = {k: v for k, v in doc.items() if k != 'records'}
    return json.dumps(head, ensure_ascii=False)[:-1] + ', "records": [\n' + ',\n'.join(
        json.dumps(r, ensure_ascii=False) for r in doc['records']) + '\n]}'


class BackupIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'backup.json'
        self.db = Store(Path(self.tmp.name) / 'database.sqlite3')
        self.addCleanup(self.db.close)
        self.db.save([record(999)])

    def assert_rejected_without_changes(self, text):
        self.path.write_text(text, encoding='utf-8')
        before = self.db.db.iterdump()
        before = list(before)
        with self.assertRaises(ValueError):
            import_backup(self.db, self.path)
        self.assertEqual(list(self.db.db.iterdump()), before)

    def test_incomplete_or_extra_document_never_changes_any_table(self):
        text = lines(payload())
        for broken in (text[:-1], text[:-2], text + '\n{}', text + 'junk',
                       text.replace('\n]}', ',\n]}'),
                       text.replace('\n]}', '\n' + json.dumps(record(2)) + '\n]}')):
            with self.subTest(broken=broken[-40:]):
                self.assert_rejected_without_changes(broken)

    def test_header_validation_is_the_same_in_all_layouts(self):
        for patch in ({'format': 'other'}, {'version': 99}, {'version': True},
                      {'source': 'pc-viewer'}, {'date_events': {}},
                      {'candidate_snapshots': {}}, {'recovery_required': 1},
                      {'unreadable_date_events': '{broken'},
                      {'date_events': [{'name': 'invalid'}]},
                      {'candidate_snapshots': [{'unreadable_candidate_snapshot': '{broken'}]}):
            for serialize in (json.dumps, lambda d: json.dumps(d, indent=2), lines):
                with self.subTest(patch=patch, layout=serialize):
                    self.assert_rejected_without_changes(serialize({**payload(), **patch}))

    def test_duplicate_fields_are_rejected(self):
        text = lines(payload())
        for broken in (text.replace('\n]}', '\n], "records": []}'),
                       text.replace('"version": 1', '"version": 99, "version": 1'),
                       text.replace('"games": 3000', '"games": 2000, "games": 3000')):
            self.assert_rejected_without_changes(broken)

    def test_trailing_events_and_candidates_are_kept(self):
        event = dict(store='nagamachiminami', day='2026-10-01', name='試験イベント')
        snapshot = dict(store='nagamachiminami', day='2026-10-01', machine='試験機種',
                        taken_at='2026-10-01T23:00:00+09:00', total=1, eligible=0, candidates=[])
        for text in (lines(payload())[:-1] + ', "date_events": ' + json.dumps([event]) +
                     ', "candidate_snapshots": ' + json.dumps([snapshot]) + '}',
                     lines(payload())[:-1] + '\n, "candidate_snapshots": [\n' +
                     json.dumps(snapshot) + '\n], "date_events": ' + json.dumps([event]) + '}'):
            self.path.write_text(text, encoding='utf-8')
            import_backup(self.db, self.path)
            self.assertIn(event, self.db.date_events())
            self.assertEqual(len(self.db.candidate_snapshots()), 2)  # existing + imported

    def test_bom_and_blank_prefix_and_empty_backup_are_supported(self):
        for text in ('\ufeff\n' + lines(payload()), json.dumps(payload(), indent=2),
                     lines({**payload(), 'records': []})):
            self.path.write_text(text, encoding='utf-8')
            records, _ = read_backup_file(self.path)
            self.assertIn(len(records), (0, 1))

    def test_missing_fractional_negative_and_non_numeric_values_are_skipped(self):
        for key in ('games', 'bb', 'rb', 'rack'):
            for value in (None, '3', True, -1, 1.5):
                with self.subTest(key=key, value=value):
                    plan = plan_backup_import(self.db, [{**record(), key: value}])
                    self.assertEqual(len(plan['skipped']), 1)
                    self.assertEqual(plan['new'], [])
        for key in ('games', 'bb', 'rb'):
            raw = record()
            del raw[key]
            self.assertEqual(len(plan_backup_import(self.db, [raw])['skipped']), 1)

    def test_real_zero_values_are_not_missing(self):
        self.path.write_text(lines({**payload(), 'records': [{**record(), 'games': 0, 'bb': 0, 'rb': 0}]}), encoding='utf-8')
        plan = import_backup(self.db, self.path)
        self.assertEqual(len(plan['new']), 1)
        self.assertEqual(plan['skipped'], [])


class PscubeBackupTimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = PscubeStore(Path(self.tmp.name) / 'pscube.sqlite3')
        self.addCleanup(self.db.close)
        self.machine = dict(store='c740601', rate='20', machine='試験機種', expected_count=1,
                            url=ROOT_URL + 'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20')

    def backup(self, time, games):
        row = {**self.machine, 'rack': 1, 'day': '2026-10-01', 'games': games,
               'bb': 12, 'rb': 6, 'at_art': 0, 'my': 1000, 'observed_at': time,
               'detail_url': ROOT_URL + 'cgi-bin/nc-v06-001.php?cd_dai=1#20261001'}
        row.pop('url')
        return dict(format='pscube-viewer', version=1, kind='backup', machines=[self.machine], records=[row])

    def test_newer_instant_wins_even_with_a_different_offset_and_fewer_games(self):
        self.db.import_backup(self.backup('2026-10-01T12:00:00+09:00', 3000))
        result = self.db.import_backup(self.backup('2026-10-01T04:00:00Z', 2000))
        self.assertEqual(result['updated'], 1)
        self.assertEqual(self.db.export_payload()['records'][0]['games'], 2000)

    def test_older_instant_cannot_overwrite_even_with_more_games(self):
        self.db.import_backup(self.backup('2026-10-01T04:00:00Z', 2000))
        result = self.db.import_backup(self.backup('2026-10-01T12:00:00+09:00', 3000))
        self.assertEqual(result['kept_local'], 1)
        self.assertEqual(self.db.export_payload()['records'][0]['games'], 2000)

    def test_invalid_timestamp_rejects_the_whole_backup(self):
        self.db.import_backup(self.backup('2026-10-01T04:00:00Z', 2000))
        for time in ('bad time', 123):
            before = self.db.export_payload()['records']
            with self.assertRaises(ValueError):
                self.db.import_backup(self.backup(time, 3000))
            self.assertEqual(self.db.export_payload()['records'], before)


if __name__ == '__main__':
    unittest.main()
