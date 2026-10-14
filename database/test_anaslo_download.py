import io
import json
from email.message import Message
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from anaslo_index import DayLink, INDEX_URL, canonical_url, date_range, extract_links
from anaslo_download import AccessStopped, Client, NoRedirect, cache_name, download, folder_lock, write_atomic
from test_anaslo_converter import html as fixture_html


def html(**kwargs):
    return fixture_html(**kwargs).replace(b'p-stationii-data/', 'p-stationiiスロット館-data/'.encode('utf-8'))


def link(day):
    return DayLink(day, canonical_url(f'https://ana-slo.com/{day}-p-stationiiスロット館-data/'))


class FakeCancel:
    def __init__(self, clock):
        self.clock = clock
        self.stopped = False
        self.waits = []

    def is_set(self):
        return self.stopped

    def wait(self, delay):
        self.waits.append(delay)
        self.clock[0] += delay
        return self.stopped


class Response(io.BytesIO):
    def __init__(self, raw, url, content_type='text/html'):
        super().__init__(raw)
        self.url = url
        self.status = 200
        self.headers = Message()
        self.headers['Content-Type'] = content_type
        self.headers['Content-Length'] = str(len(raw))

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request.full_url, timeout))
        result = self.outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, Response):
            return result
        return result(request.full_url) if callable(result) else Response(result, request.full_url)


def client(outputs):
    clock = [0.0]
    cancel = FakeCancel(clock)
    opener = Opener(outputs)
    return Client(cancel, opener, lambda: clock[0], lambda: 6.0), opener


def http_error(code, **headers):
    message = Message()
    for k, v in headers.items():
        message[k] = v
    return HTTPError(link('2026-09-15').url, code, 'test', message, io.BytesIO())


class IndexTests(unittest.TestCase):
    def test_default_redirect_handler_cannot_follow_an_unchecked_url(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com/'))

    def test_relative_duplicates_encoded_variants_and_date_filter(self):
        raw = ('<a href="/2026-09-15-p-stationiiスロット館-data/#top">A</a>'
               f'<a href="{link("2026-09-15").url.upper().replace("HTTPS", "https").replace("ANA-SLO.COM", "ana-slo.com").replace("P-STATIONII", "p-stationii").replace("-DATA/", "-data/")}">A</a>'
               '<a href="/2026-09-25-p-stationiiスロット館-data/">B</a>'
               '<a href="/2026-09-14-p-stationiiスロット館-data/">C</a>'
               '<a href="https://example.com/2026-09-15-p-stationiiスロット館-data/">D</a>'
               '<a href="/2026-09-15-other-data/">E</a>').encode('utf-8')
        self.assertEqual(extract_links(raw, INDEX_URL, '2026-09-15', '2026-09-25'), [link('2026-09-15'), link('2026-09-25')])

    def test_required_range_and_invalid_dates(self):
        for start, end in [('', ''), ('2026-02-30', '2026-03-01'), ('2026-09-25', '2026-09-15')]:
            with self.assertRaises(ValueError):
                date_range(start, end)

    def test_unwanted_schemes_hosts_queries_and_paths(self):
        for url in ['http://ana-slo.com/', 'https://ana-slo.com.evil.example/', 'https://x@ana-slo.com/',
                    link('2026-09-15').url + '?other=1', 'file:///tmp/file', 'https://ana-slo.com/2026-02-30-p-stationiiスロット館-data/']:
            with self.assertRaises(ValueError):
                canonical_url(url)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.a, self.b, self.c, self.d = map(link, ['2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18'])

    def run_download(self, links, engine):
        return download(links, '2026-09-15', '2026-09-18', self.folder, engine)

    def test_download_resume_and_manual_saved_file_skip(self):
        engine, opener = client([html(), html(day='2026/09/16')])
        first = self.run_download([self.a, self.b], engine)
        self.assertEqual((first.downloaded, first.failed), (2, 0))
        self.assertEqual(engine.cancel.waits, [0, 6.0])
        second = self.run_download([self.a, self.b], engine)
        self.assertEqual((second.downloaded, second.skipped), (0, 2))
        self.assertEqual(len(opener.calls), 2)
        self.assertFalse(list(self.folder.glob('*.part')))
        self.assertEqual(len(json.loads((self.folder / 'download-manifest.json').read_text(encoding='utf-8'))['entries']), 2)

    def test_manual_file(self):
        path = self.folder / '2026_09_15 manual.html'
        path.write_bytes(html())
        engine, opener = client([])
        result = self.run_download([self.a], engine)
        self.assertEqual(result.paths, [path])
        self.assertEqual(opener.calls, [])

    def test_range_is_enforced_before_any_request_or_file_creation(self):
        engine, opener = client([])
        with self.assertRaises(ValueError):
            download([self.a, self.b], '2026-09-15', '2026-09-15', self.folder / 'must-not-exist', engine)
        self.assertEqual(opener.calls, [])
        self.assertFalse((self.folder / 'must-not-exist').exists())

    def test_invalid_existing_file_never_overwritten_or_downloaded(self):
        path = self.folder / cache_name(self.a)
        path.write_bytes(b'broken')
        engine, opener = client([])
        result = self.run_download([self.a], engine)
        self.assertEqual(result.failed, 1)
        self.assertEqual(opener.calls, [])
        self.assertEqual(path.read_bytes(), b'broken')

    def test_wrong_day_response_not_saved(self):
        engine, opener = client([html(day='2026/09/16')])
        result = self.run_download([self.a], engine)
        self.assertEqual(result.failed, 1)
        self.assertFalse(list(self.folder.glob('*.html')))

    def test_403_and_429_stop_entire_queue(self):
        for code in (401, 403, 429):
            engine, opener = client([http_error(code, **{'Retry-After': '120'}), html(day='2026/09/16')])
            result = self.run_download([self.a, self.b], engine)
            self.assertIn(str(code), result.stopped)
            self.assertEqual(len(opener.calls), 1)
            self.assertEqual(result.paths, [])

    def test_404_skips_only_one_day(self):
        engine, opener = client([http_error(404), html(day='2026/09/16')])
        result = self.run_download([self.a, self.b], engine)
        self.assertEqual((result.failed, result.downloaded), (1, 1))
        self.assertEqual(len(opener.calls), 2)

    def test_three_errors_stop_without_retry(self):
        engine, opener = client([URLError('offline')] * 4)
        result = self.run_download([self.a, self.b, self.c, self.d], engine)
        self.assertTrue(result.stopped)
        self.assertEqual(len(opener.calls), 3)

    def test_redirect_is_rejected_before_target_request(self):
        for target in ['https://example.com/page', self.b.url]:
            engine, opener = client([http_error(302, Location=target)])
            result = self.run_download([self.a, self.b], engine)
            self.assertTrue(result.stopped)
            self.assertEqual(len(opener.calls), 1)

    def test_same_identity_redirect_is_paced_and_capped(self):
        engine, opener = client([http_error(301, Location=self.a.url)] * 4)
        with self.assertRaises(AccessStopped):
            engine.get(self.a.url)
        self.assertEqual(len(opener.calls), 4)
        self.assertEqual(engine.cancel.waits, [0, 6.0, 6.0, 6.0])

    def test_cancel_keeps_successful_file_and_resumes(self):
        engine, opener = client([html(), html(day='2026/09/16')])
        def progress(message):
            engine.cancel.stopped = True
        first = download([self.a, self.b], self.a.day, self.b.day, self.folder, engine, progress)
        self.assertEqual(first.downloaded, 1)
        self.assertTrue(first.stopped)
        self.assertEqual(len(opener.calls), 1)
        engine.cancel.stopped = False
        resumed = self.run_download([self.a, self.b], engine)
        self.assertEqual((resumed.skipped, resumed.downloaded), (1, 1))

    def test_200_challenge_not_saved_and_stops(self):
        engine, opener = client([b'<html>Just a moment...</html>'])
        result = self.run_download([self.a, self.b], engine)
        self.assertTrue(result.stopped)
        self.assertFalse(list(self.folder.glob('*.html')))

    def test_bad_content_type_or_length_not_saved(self):
        for response in [Response(b'x', self.a.url, 'image/png'), Response(html(), self.a.url)]:
            if response.headers.get_content_type() == 'text/html':
                response.headers.replace_header('Content-Length', '1')
            engine, opener = client([response])
            result = self.run_download([self.a], engine)
            self.assertEqual(result.failed, 1)
            self.assertFalse(list(self.folder.glob('*.html')))

    def test_cache_hash_mismatch_is_not_forgotten_after_failure(self):
        engine, opener = client([html()])
        self.run_download([self.a], engine)
        path = self.folder / cache_name(self.a)
        path.write_bytes(html(games='3,100'))
        for i in range(2):
            result = self.run_download([self.a], engine)
            self.assertEqual((result.failed, result.skipped), (1, 0))
        self.assertEqual(len(opener.calls), 1)

    def test_atomic_no_overwrite_and_lock_released(self):
        path = self.folder / 'existing.html'
        path.write_bytes(b'original')
        with self.assertRaises(FileExistsError):
            write_atomic(path, b'new')
        self.assertEqual(path.read_bytes(), b'original')
        self.assertFalse(list(self.folder.glob('*.part')))
        with folder_lock(self.folder):
            with self.assertRaises(ValueError):
                with folder_lock(self.folder):
                    pass
        with folder_lock(self.folder):
            pass

    def test_invalid_manifest_is_preserved_without_requests(self):
        path = self.folder / 'download-manifest.json'
        path.write_text('{"format":"other","entries":{}}', encoding='utf-8')
        before = path.read_bytes()
        engine, opener = client([])
        with self.assertRaises(ValueError):
            self.run_download([self.a], engine)
        self.assertEqual(opener.calls, [])
        self.assertEqual(path.read_bytes(), before)

    def test_downloaded_html_can_use_existing_json_conversion(self):
        from anaslo_converter import analyze, make_backup
        engine, opener = client([html()])
        result = self.run_download([self.a], engine)
        staging = analyze(result.paths)
        mapping = {r['machine']: r['machine'] for d in staging['days'] for r in d['records']}
        payload = make_backup(staging, mapping, [])
        self.assertEqual(payload['import_mode'], 'fill_missing')
        self.assertEqual([r['day'] for r in payload['records']], ['2026-09-15'])


if __name__ == '__main__':
    unittest.main()
