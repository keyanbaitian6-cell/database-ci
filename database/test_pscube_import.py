import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from pscube_import import PscubeStore, ROOT_URL


class PscubeImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = PscubeStore(Path(self.tmp.name) / 'pscube.sqlite3')
        self.addCleanup(self.store.close)
        self.day = '2026-10-01'
        self.index_url = ROOT_URL + 'cgi-bin/nc-v03-001.php?cd_ps=2'
        self.machines = [
            {'store': 'c740601', 'rate': '20', 'machine': name,
             'expected_count': 1,
             'url': ROOT_URL + f'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu={name}'}
            for name in ('L東京喰種', 'ﾏｲｼﾞｬｸﾞﾗｰV')
        ]

    def page(self, url, machines, records=()):
        return {'format': 'pscube-viewer', 'version': 1, 'source_url': url,
                'machines': machines, 'records': list(records)}

    def record(self, machine, rack, day=None):
        day = day or self.day
        return {'store': 'c740601', 'rate': '20', 'machine': machine['machine'],
                'rack': rack, 'day': day, 'bb': 13, 'rb': 5, 'at_art': 0,
                'games': 1854, 'my': 1921, 'observed_at': '2026-10-01T12:00:00+09:00',
                'detail_url': ROOT_URL + f'cgi-bin/nc-v06-001.php?cd_dai={rack}#{day.replace("-", "")}',
                'graph': {'kind': 'overview', 'zero_y': 10, 'points': [[0, 10], [1, 8]]}}

    def test_index_table_rack_cycle_and_export(self):
        index = self.page(self.index_url, self.machines)
        first = self.store.import_page(index, self.index_url)
        self.assertEqual(first['next_url'], self.machines[0]['url'])
        for i, machine in enumerate(self.machines):
            record = self.record(machine, 1526 + i)
            table = self.page(machine['url'], [dict(machine, expected_count=None)], [record])
            result = self.store.import_page(table, machine['url'])
            self.assertEqual(result['next_url'], record['detail_url'])
            history = []
            for ago in range(7):
                day = (date.fromisoformat(self.day) - timedelta(days=ago)).isoformat()
                row = self.record(machine, 1526 + i, day)
                row['graph'] = {'kind': 'daily', 'zero_y': 10, 'points': [[0, 10], [1, 6]]} if ago == 0 else None
                history.append(row)
            rack = self.page(record['detail_url'], [dict(machine, expected_count=None)], history)
            result = self.store.import_page(rack, record['detail_url'])
            self.assertEqual(result['next_url'], self.machines[1]['url'] if i == 0 else None)
            # Re-reading a saved rack is safe and does not make it pending again.
            self.store.import_page(rack, record['detail_url'])
        export = self.store.export_viewer(Path(self.tmp.name) / 'viewer.json')
        data = json.loads(export.read_text())
        self.assertEqual(data['format'], 'pscube-viewer')
        self.assertEqual(len(data['records']), 14)
        self.assertEqual(data['records'][0]['my'], 1921)

    def test_incomplete_table_and_mismatched_page_are_rejected(self):
        self.store.import_page(self.page(self.index_url, self.machines), self.index_url)
        self.machines[0]['expected_count'] = 2
        self.store.import_page(self.page(self.index_url, self.machines), self.index_url)
        record = self.record(self.machines[0], 1526)
        table = self.page(self.machines[0]['url'], [dict(self.machines[0], expected_count=None)], [record])
        with self.assertRaisesRegex(ValueError, '全台を表示'):
            self.store.import_page(table, self.machines[0]['url'])
        with self.assertRaisesRegex(ValueError, '表示中のページ'):
            self.store.import_page(table, self.machines[1]['url'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
