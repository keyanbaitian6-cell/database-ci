import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import error_log  # noqa: E402

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone(timedelta(hours=9)))


def raised(message='読めません'):
    try:
        raise ValueError(message)
    except ValueError as error:
        return error


class ErrorLogTests(unittest.TestCase):
    def setUp(self):
        error_log.forget()
        self.addCleanup(error_log.forget)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'errors.log'
        self.time = 0.0

    def record(self, where='pscube.auto.tick', error=None):
        return error_log.record(self.folder.name, where, error or raised(), clock=lambda: self.time, now=NOW)

    def lines(self):
        return self.path.read_text(encoding='utf-8').splitlines()

    def test_writes_time_place_error_and_origin(self):
        self.assertTrue(self.record(error=raised('一覧が\n読めません')))
        [line] = self.lines()
        stamp, where, error, origin = line.split('\t')
        self.assertEqual(stamp, '2026-11-01T12:00:00+09:00')
        self.assertEqual(where, 'pscube.auto.tick')
        self.assertEqual(error, 'ValueError: 一覧が 読めません')  # 改行は1行に畳む
        self.assertRegex(origin, r'^test_error_log\.py:\d+ raised$')

    def test_same_failure_is_written_once_per_minute(self):
        self.assertTrue(self.record())
        self.time = 59.9
        self.assertFalse(self.record())
        self.assertTrue(self.record(where='pscube.auto.close'))  # 場所が違えば書く
        self.assertTrue(self.record(error=raised('別の理由')))   # 内容が違えば書く
        self.time = 60.0
        self.assertTrue(self.record())
        self.assertEqual(len(self.lines()), 4)

    def test_large_log_keeps_one_previous_generation(self):
        self.path.write_text('古い記録\n' * 40000, encoding='utf-8')
        self.assertGreater(self.path.stat().st_size, error_log.MAX_BYTES)
        self.assertTrue(self.record())
        self.assertEqual(len(self.lines()), 1)
        self.assertTrue((Path(self.folder.name) / 'errors.log.1').read_text(encoding='utf-8').startswith('古い記録'))

    def test_failure_to_write_never_raises(self):
        blocker = Path(self.folder.name) / 'file'
        blocker.write_text('', encoding='utf-8')
        self.assertFalse(error_log.record(blocker / 'data', 'meruhen.overlay', raised(), clock=lambda: 0.0))

    def test_detail_follows_the_error_and_note_keeps_screen_text(self):
        self.assertTrue(error_log.record(self.folder.name, 'pscube.save', raised(), detail='https://example.test/a',
                                         clock=lambda: 0.0, now=NOW))
        self.assertTrue(error_log.note(self.folder.name, 'meruhen.save.table', '取り込みできません：表の見出しが違います',
                                       clock=lambda: 0.0, now=NOW))
        first, second = [line.split('\t') for line in self.lines()]
        self.assertEqual(first[2], 'ValueError: 読めません（https://example.test/a）')
        self.assertEqual(second[1:], ['meruhen.save.table', '取り込みできません：表の見出しが違います', ''])

    def test_meruhen_confirm_window_error_is_shown_and_kept(self):
        import browser_import
        shown = []
        messagebox = type('Box', (), {'showerror': staticmethod(lambda *a, **k: shown.append((a, k)))})
        root = type('Root', (), {'get': lambda self: 'root'})()
        browser_import._show_error(messagebox, root, '取り込みできません', '台番号が重複しています',
                                   Path(self.folder.name) / 'database.sqlite3', 'meruhen.save.table')
        self.assertEqual(shown, [(('取り込みできません', '台番号が重複しています'), {'parent': 'root'})])
        self.assertEqual(self.lines()[0].split('\t')[1:3], ['meruhen.save.table', '取り込みできません：台番号が重複しています'])

    def test_long_message_is_cut(self):
        self.record(error=raised('あ' * 2000))
        error = self.lines()[0].split('\t')[2]
        self.assertEqual(len(error), len('ValueError: ') + error_log.MESSAGE_LIMIT)


if __name__ == '__main__':
    unittest.main()
