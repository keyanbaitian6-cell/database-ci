"""P’s CUBEの通信の診断記録（pscube_netlog.py、2026-11-06）。実サイトには接続せず、CDPの通知を模して確かめる。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pscube_netlog  # noqa: E402
from pscube_netlog import NetLog  # noqa: E402

SITE = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/'
APP_STACK = {'type': 'script', 'stack': {'callFrames': [{'url': SITE + 'nc-v06-001.php?cd_dai=1120'}, {'url': ''}]}}
SITE_STACK = {'type': 'script', 'stack': {'callFrames': [{'url': 'https://www.pscube.jp/js/graph.js'}]}}
ALIVE_STACK = {'type': 'script', 'stack': {'callFrames': [{'url': 'https://www.pscube.jp/js/jquery.netcube.alive.js'}]}}


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


class NetLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.log = NetLog(self.tmp.name, clock=self.clock, version={'commit': 'test'}, start=False)
        self.log._write({'ev': 'session_start', 'session': self.log.session}, self.clock())
        self.n = 0

    def tearDown(self):
        if self.log._file is not None:
            self.log._file.close()
        self.tmp.cleanup()

    # ---- 模擬の通知 ----
    def send(self, url, rtype='Document', status=200, initiator=None, rid=None, cache=None, bytes_=1000,
             fail=None, dt=0.2):
        if rid is None:
            self.n += 1
            rid = f'R{self.n}'
        self.log.cdp('Network.requestWillBeSent', json.dumps({
            'requestId': rid, 'type': rtype, 'request': {'url': url, 'method': 'GET', 'hasPostData': False},
            'initiator': initiator or {'type': 'other'}}))
        self.clock.now += dt
        if fail:
            self.log.cdp('Network.loadingFailed', json.dumps({'requestId': rid, 'errorText': fail, 'canceled': False}))
            return rid
        if cache == 'memory':
            self.log.cdp('Network.requestServedFromCache', json.dumps({'requestId': rid}))
        self.log.cdp('Network.responseReceived', json.dumps({'requestId': rid, 'type': rtype, 'response': {
            'status': status, 'fromDiskCache': cache == 'disk'}}))
        self.log.cdp('Network.loadingFinished', json.dumps({'requestId': rid, 'encodedDataLength':
                                                            0 if cache else bytes_}))
        return rid

    def finish(self):
        self.log.close()
        return self.log.totals.result(self.log.session, self.log.started, self.clock())

    def lines(self):
        return [json.loads(x) for x in self.log.path.read_text(encoding='utf-8').splitlines()]

    def totals(self, r):
        out = {}
        for (minute, state, cat), b in r['by'].items():
            t = out.setdefault((state, cat), {k: 0 for k in b})
            for k, v in b.items():
                t[k] += v
        return out

    # ---- 試験 ----
    def test_a_repeated_notice_of_the_same_request_is_counted_once_and_a_redirect_per_hop(self):
        body = json.dumps({'requestId': 'X', 'type': 'Document',
                           'request': {'url': SITE + 'nc-v03-001.php?cd_ps=2', 'method': 'GET'}})
        self.log.cdp('Network.requestWillBeSent', body)
        self.log.cdp('Network.requestWillBeSent', body)   # 同じ要求の重ねての通知
        self.log.cdp('Network.requestWillBeSent', json.dumps({
            'requestId': 'X', 'type': 'Document', 'request': {'url': SITE + 'nc-v03-001.php?cd_ps=2&x=1'},
            'redirectResponse': {'status': 302}}))
        self.log.cdp('Network.responseReceived', json.dumps({'requestId': 'X', 'response': {'status': 200}}))
        self.log.cdp('Network.loadingFinished', json.dumps({'requestId': 'X', 'encodedDataLength': 500}))
        r = self.finish()
        t = self.totals(r)[('before', 'page')]
        self.assertEqual((t['requests'], t['redirect'], t['network']), (2, 1, 2), 'リダイレクトの段ごとに1回、重ねての通知は数えない')
        self.assertEqual(r['duplicate_notices'], 1)

    def test_page_403_and_net_api_403_are_kept_apart_and_a_site_top_frame_is_not_called_the_site(self):
        self.log.set_state('on')
        self.send(SITE + 'nc-v06-001.php?cd_dai=1120', status=403)
        self.send(SITE + 'nc-m06-003.php?cd_dai=1120&YMD_biz=20261105&apikey=K&_i=I&_t=T', 'XHR', 403, APP_STACK)
        self.send(SITE + 'nc-m06-003.php?cd_dai=1120&YMD_biz=20261105', 'XHR', 200, SITE_STACK)
        self.send(SITE + 'nc-m06-003.php?cd_dai=1121', 'XHR', 200, {'type': 'script'})
        r = self.finish()
        self.assertEqual(r['status'], {('page', 403): 1, ('api_app', 403): 1})
        t = self.totals(r)
        # 実WebView2のスタックは上の1段だけ。アプリがサイトの jQuery.ajax を呼んでも上の段はサイトのスクリプトに
        # なるので、URLのある段だけでは「サイト自身」と言えない（2026-11-06 確認試験）。
        self.assertEqual(t[('on', 'api_unknown')]['requests'], 2, 'サイトの段だけ・スタック無しは呼び出し元不明')
        self.assertNotIn('api_site', pscube_netlog.CATEGORIES)
        self.assertIn('HTTP 403（page）', r['first'])
        self.assertIn('HTTP 403（api_app）', r['first'])

    def test_periodic_requests_count_by_their_caller_not_by_loading_the_alive_script(self):
        self.log.set_state('on')
        self.send('https://www.pscube.jp/js/jquery.netcube.alive.js', 'Script')
        self.send('https://www.pscube.jp/alive.php', 'XHR', initiator=ALIVE_STACK)
        self.send('https://www.pscube.jp/other.php', 'Fetch', initiator=SITE_STACK)
        self.send('https://www.pscube.jp/img/a.png', 'Image', cache='disk')
        self.send('https://www.pscube.jp/img/b.png', 'Image', cache='memory')
        self.send('https://ads.example.net/x.js', 'Script')
        self.send('https://www.youtube.com/embed/x', 'Document')
        r = self.finish()
        t = self.totals(r)
        self.assertEqual(t[('on', 'resource')]['requests'], 3, 'alive.js の読み込みは資源として数える')
        self.assertEqual((t[('on', 'resource')]['network'], t[('on', 'resource')]['cache']), (1, 2))
        self.assertEqual(t[('on', 'site_periodic')]['requests'], 1)
        self.assertEqual(t[('on', 'site_data')]['requests'], 1)
        self.assertEqual(t[('on', 'third_party_resource')]['requests'], 1)
        self.assertEqual(t[('on', 'youtube_local')]['network'], 0, 'アプリが手元で止めるYouTubeは通信に数えない')
        self.assertIn(('site_periodic', 'www.pscube.jp/js/jquery.netcube.alive.js'), r['scripts'])

    def test_dom_not_ready_is_an_event_not_an_http_403(self):
        self.log.set_state('on')
        self.send(SITE + 'nc-v05-011.php?cd_ps=2&bai=20')
        self.log.event('dom_missing', count=5)
        self.log.event('message', text='ON・サイトがデータを表示しなくなりました')
        r = self.finish()
        self.assertEqual(r['status'], {}, 'DOMの判定はHTTPの状態に入れない')
        self.assertEqual(r['events']['dom_missing'], 1)
        self.assertIn('dom_missing', r['first'])
        self.assertNotIn('HTTP 403（page）', r['first'])

    def test_reloads_save_failures_and_unplanned_navigations_can_be_followed(self):
        self.log.set_state('on')
        page = SITE + 'nc-v03-001.php?cd_ps=2#top'
        self.log.event('capture_end', ok=False, stage='save', error='保存できませんでした')
        self.log.intent('reload_list', page)
        self.log.nav_start(1, SITE + 'nc-v03-001.php?cd_ps=2')
        self.log.nav_done(1, True, 'NoError', 200)
        self.log.intent('next_page', SITE + 'nc-v05-011.php?cd_ps=2&bai=20')
        self.log.nav_start(2, SITE + 'nc-v05-011.php?cd_ps=2&bai=20')
        self.log.nav_start(3, SITE + 'nc-v06-001.php?cd_dai=9')   # アプリが決めていない移動
        self.log.event('capture_end', ok=True, kind='全台一覧')
        r = self.finish()
        self.assertEqual(r['navs'], {'reload_list': 1, 'next_page': 1, 'site_or_user': 1})
        self.assertEqual((r['captures']['ok'], r['captures']['error']), (1, 1))
        recs = [x for x in self.lines() if x['ev'] == 'nav']
        self.assertEqual([x['reason'] for x in recs], ['reload_list', 'next_page', 'site_or_user'])

    def test_requests_while_off_resting_and_after_the_end_are_counted_apart(self):
        self.log.set_state('on')
        self.send(SITE + 'nc-v03-001.php?cd_ps=2')
        self.log.set_state('rest')
        self.log.intent('rest')
        self.log.nav_start(4, 'about:blank')
        self.send('https://www.pscube.jp/alive.php', 'XHR', initiator=ALIVE_STACK)
        self.log.set_state('off')
        self.send('https://www.pscube.jp/alive.php', 'XHR', initiator=ALIVE_STACK)
        self.log.set_state('done')
        self.send('https://www.pscube.jp/alive.php', 'XHR', initiator=ALIVE_STACK)
        r = self.finish()
        self.assertEqual(r['navs'], {'rest': 1})
        self.assertEqual(r['after'], {('rest', 'site_periodic', 'www.pscube.jp/alive.php'): 1,
                                      ('off', 'site_periodic', 'www.pscube.jp/alive.php'): 1,
                                      ('done', 'site_periodic', 'www.pscube.jp/alive.php'): 1})
        text = pscube_netlog.format_summary(r)
        self.assertIn('［休憩中］', text)
        self.assertIn('［自動OFF（ONのあと）］', text)
        self.assertIn('［完了・停止のあと］', text)

    def test_the_load_before_the_first_on_is_not_counted_as_left_after_off(self):
        self.send(SITE.rsplit('cgi-bin/', 1)[0])                       # 窓を開いた直後（まだ一度もONにしていない）
        self.send('https://www.pscube.jp/cdn-cgi/rum', 'XHR')
        self.log.set_state('off')                                       # 見張りは最初 'off' を渡す
        self.send('https://www.pscube.jp/js/store2.min.js', 'XHR')
        self.log.set_state('on')
        self.send(SITE + 'nc-v03-001.php?cd_ps=2')
        self.log.set_state('off')
        self.send('https://www.pscube.jp/alive.php', 'XHR')
        r = self.finish()
        t = self.totals(r)
        self.assertEqual(t[('before', 'site_data')]['requests'], 2)
        self.assertEqual(t[('off', 'site_data')]['requests'], 1)
        self.assertEqual(r['after'], {('off', 'site_data', 'www.pscube.jp/alive.php'): 1}, 'ONの前の読み込みは残留に入れない')
        self.assertIn('自動ONの前', pscube_netlog.format_summary(r))

    def test_an_older_log_is_read_with_the_current_states_and_categories(self):
        path = Path(self.tmp.name) / 'net-old.jsonl'
        base = {'state': 'off', 'saving': False, 'hop': 0, 'status': 200, 'cache': None, 'bytes': 10, 'error': None,
                'redirect': False, 'how': 'finished', 'ms': 5, 'method': 'GET', 'post': False, 'init': {}}
        rows = [{'t': '2026-11-06T16:34:55.000', 'ev': 'session_start', 'session': 'old'},
                {**base, 't': '2026-11-06T16:34:56.000', 'ev': 'req', 'id': 'a', 'type': 'Document', 'cat': 'page',
                 'url': {'host': 'www.pscube.jp', 'path': '/x/', 'q': {}, 'drop': []}},
                {**base, 't': '2026-11-06T16:35:30.000', 'ev': 'req', 'id': 'b', 'type': 'XHR', 'cat': 'api_site',
                 'url': {'host': 'www.pscube.jp', 'path': '/x/cgi-bin/nc-m06-003.php', 'q': {}, 'drop': ['apikey']}}]
        path.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in rows) + '\n', encoding='utf-8')
        text = pscube_netlog.summarize_file(path)
        self.assertIn('［自動ONの前', text)
        self.assertIn('差枚API（呼び出し元はスタックから分からない）：1／1', text)
        self.assertNotIn('［自動OFF（ONのあと）］', text)

    def test_secrets_in_urls_never_reach_the_log(self):
        self.log.set_state('on')
        self.send(SITE + 'nc-m06-003.php?cd_dai=1120&YMD_biz=20261105&apikey=SECRETKEY&_i=SECRETI&_t=SECRETT#x',
                  'XHR', 403, APP_STACK)
        self.log.intent('next_page', SITE + 'nc-v06-001.php?cd_dai=1&token=SECRETTOKEN')
        self.log.nav_start(5, SITE + 'nc-v06-001.php?cd_dai=1&token=SECRETTOKEN')
        self.finish()
        text = self.log.path.read_text(encoding='utf-8') + self.log.summary_path.read_text(encoding='utf-8')
        for secret in ('SECRETKEY', 'SECRETI', 'SECRETT', 'SECRETTOKEN'):
            self.assertNotIn(secret, text)
        req = next(x for x in self.lines() if x['ev'] == 'req')
        self.assertEqual(req['url']['q'], {'cd_dai': '1120', 'YMD_biz': '20261105'})
        self.assertEqual(req['url']['drop'], ['_i', '_t', 'apikey'], '名前だけ残す')

    def test_the_file_has_a_size_cap_but_the_totals_keep_counting(self):
        self.log.max_file_bytes = 3000
        self.log.set_state('on')
        for i in range(60):
            self.send(SITE + f'nc-v06-001.php?cd_dai={i}')
        r = self.finish()
        self.assertLess(self.log.path.stat().st_size, 3000 + 2000)
        self.assertTrue(any(x['ev'] == 'truncated' for x in self.lines()))
        self.assertEqual(self.totals(r)[('on', 'page')]['requests'], 60)

    def test_a_failure_to_write_does_not_raise_and_is_reported(self):
        blocker = Path(self.tmp.name) / 'file'
        blocker.write_text('x')
        log = NetLog(blocker, clock=self.clock, version={}, start=False)   # 下にフォルダーを作れない
        log.cdp('Network.requestWillBeSent', json.dumps({'requestId': 'A', 'type': 'Document',
                                                         'request': {'url': SITE + 'nc-v03-001.php'}}))
        log.cdp('Network.loadingFinished', json.dumps({'requestId': 'A', 'encodedDataLength': 10}))
        log.close()
        self.assertIsNotNone(log.write_failed)
        self.assertEqual(log.totals.by[next(iter(log.totals.by))]['requests'], 1)

    def test_a_full_queue_drops_and_counts_instead_of_waiting(self):
        log = NetLog(self.tmp.name, clock=self.clock, version={}, queue_size=2, start=False)
        for _ in range(5):
            log.cdp('Network.requestServedFromCache', '{}')
        self.assertEqual(log.dropped, 3)

    def test_net_api_requests_are_set_against_the_times_the_app_fetched(self):
        self.log.set_state('on')
        for day in ('20261104', '20261105'):
            self.send(SITE + 'nc-m06-003.php?cd_dai=1120&YMD_biz=' + day, 'XHR', 200, SITE_STACK)
            self.log.event('capture_end', ok=True, kind='台別7日分', net_called=True)
        self.send(SITE + 'nc-m06-003.php?cd_dai=1120&YMD_biz=20261105', 'XHR', 200, SITE_STACK)
        self.log.event('capture_end', ok=True, kind='機種一覧', net_called=False)
        r = self.finish()
        self.assertEqual(r['captures']['app_api_calls'], 2)
        text = pscube_netlog.format_summary(r)
        self.assertIn('差枚APIの要求 3件（うち通信 3件）／アプリが取りに行った回数 2回（保存の記録から）／差 1件', text)
        self.assertIn('www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-m06-003.php 3件', text)

    def test_the_app_fetch_is_read_from_the_records_sent_to_save(self):
        cap = lambda reason, **kw: {'net_capture': {'version': 1, 'reason': reason, **kw}}  # noqa: E731
        self.assertEqual(pscube_netlog.app_net_fetch({'records': [cap('ok'), cap('missing_series')]}), (True, []))
        self.assertEqual(pscube_netlog.app_net_fetch(json.dumps({'records': [cap('network', http_status=403)] * 7})),
                         (True, [403]))
        self.assertEqual(pscube_netlog.app_net_fetch({'records': [cap('not_ready')]}), (False, []), '送らなかった回')
        self.assertEqual(pscube_netlog.app_net_fetch({'records': [{'day': '2026-11-05'}]}), (False, []), '一覧のページ')
        self.assertEqual(pscube_netlog.app_net_fetch('{broken'), (None, []))

    def test_a_failed_request_and_an_orphan_notice(self):
        self.log.set_state('on')
        self.send(SITE + 'nc-m06-003.php?cd_dai=1', 'XHR', initiator=APP_STACK, fail='net::ERR_TIMED_OUT')
        self.log.cdp('Network.loadingFinished', json.dumps({'requestId': 'unknown', 'encodedDataLength': 1}))
        r = self.finish()
        self.assertEqual(r['failures'], {('api_app', 'net::ERR_TIMED_OUT'): 1})
        self.assertEqual(r['orphan_notices'], 1)

    def test_old_logs_are_pruned_to_the_newest_ten(self):
        folder = Path(self.tmp.name) / pscube_netlog.DIR_NAME
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(12):
            (folder / f'net-20261101-0000{i:02d}-aaaaaa.jsonl').write_text('{}\n')
            (folder / f'net-20261101-0000{i:02d}-aaaaaa-summary.txt').write_text('x')
        self.log._prune()
        names = sorted(p.name for p in folder.glob('*.jsonl'))
        self.assertEqual(len(names), 10)
        self.assertNotIn('net-20261101-000000-aaaaaa.jsonl', names)
        self.assertFalse((folder / 'net-20261101-000000-aaaaaa-summary.txt').exists())

    def test_the_saved_file_can_be_summarised_again(self):
        self.log.set_state('on')
        self.send(SITE + 'nc-v06-001.php?cd_dai=1', status=403)
        self.log.event('capture_end', ok=True, kind='台別7日分')
        self.finish()
        text = pscube_netlog.summarize_file(self.log.path)
        self.assertIn('HTTP 403 1件', text)
        self.assertIn('保存できた 1回', text)
        self.assertEqual(self.log.summary_path.read_text(encoding='utf-8').count('ページ本体'),
                         self.log.summary_path.read_text(encoding='utf-8').count('ページ本体'))

    def test_pilot_state_names(self):
        class Pilot:
            completed = None
            parked = None
            enabled = False

            def state(self):
                return {'enabled': self.enabled}
        p = Pilot()
        self.assertEqual(pscube_netlog.pilot_state(p, None), 'off')
        p.enabled = True
        self.assertEqual(pscube_netlog.pilot_state(p, None), 'on')
        p.parked = {}
        self.assertEqual(pscube_netlog.pilot_state(p, None), 'rest')
        p.completed = '止めました'
        self.assertEqual(pscube_netlog.pilot_state(p, None), 'done')


class InstallTests(unittest.TestCase):
    """WebView2 につなぐ処理：通知を受けるだけで、CDP の命令は Network.enable（本文は受け取らない）だけ。"""

    def test_install_only_listens_and_enables_the_network_notices(self):
        class Event:
            def __init__(self):
                self.handlers = []

            def __iadd__(self, handler):
                self.handlers.append(handler)
                return self

        class Receiver:
            def __init__(self):
                self.DevToolsProtocolEventReceived = Event()

        class Core:
            def __init__(self):
                self.receivers, self.calls = {}, []

            def GetDevToolsProtocolEventReceiver(self, name):
                return self.receivers.setdefault(name, Receiver())

            def CallDevToolsProtocolMethodAsync(self, name, params):
                self.calls.append((name, json.loads(params)))

        class Control:
            def __init__(self):
                self.NavigationStarting, self.NavigationCompleted = Event(), Event()
                self.CoreWebView2InitializationCompleted = Event()
                self.CoreWebView2 = None

        control, core = Control(), Core()
        window = type('W', (), {'native': type('N', (), {'webview': control})()})()
        with tempfile.TemporaryDirectory() as tmp:
            log = NetLog(tmp, version={}, start=False)
            keep = pscube_netlog.install(window, log)
            ready = control.CoreWebView2InitializationCompleted.handlers[0]
            ready(type('S', (), {'CoreWebView2': core})(), type('A', (), {'IsSuccess': True})())
            self.assertEqual(core.calls, [('Network.enable', {'maxPostDataSize': 0})], 'キャッシュの設定などは変えない')
            self.assertEqual(sorted(core.receivers), sorted(pscube_netlog.CDP_EVENTS))
            handler = core.receivers['Network.requestWillBeSent'].DevToolsProtocolEventReceived.handlers[0]
            handler(None, type('A', (), {'ParameterObjectAsJson': '{"requestId":"1"}'})())
            nav = control.NavigationStarting.handlers[0]
            nav(None, type('A', (), {'NavigationId': 7, 'Uri': SITE + 'nc-v03-001.php', 'IsRedirected': False})())
            kinds = [log.queue.get_nowait()[0] for _ in range(log.queue.qsize())]
            self.assertEqual(kinds, ['event', 'cdp', 'nav'])
            self.assertTrue(keep)


if __name__ == '__main__':
    unittest.main()
