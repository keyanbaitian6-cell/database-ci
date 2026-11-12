"""自動取り込みの順序・停止・再開・原子的な保存を一時DBで確認する。"""
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pscube_import import PscubeStore
from site777_browser import DiagnosticLog
from site777_session import Session
from site777_import import source_url
from test_site777_import import bitmap

NOW = datetime.fromisoformat('2026-11-07T10:00:00+09:00')


def url(path, model='123', page=1):
    return f'https://m.site777.jp/f/{path}.do?pmc=04034001&urt=2000&mdc={model}&dtdd=0&pan={page}'


def table():
    return {'kind':'table','url':url('D3300'),'machine':'試験ジャグラー3','model_id':'123','count':2,
            'selected_md':'11/6','days':[{'label':'11/6','url':url('D3300')}],
            'headers':['','台番','累計ゲーム','BB回数','RB回数','最高出玉','ART回数'],
            'rows':[['','101','3000','10','8','900','--'],['','102','2800','9','5','900','0']],
            'graph_url':url('D4300'), 'index_url':url('D0300')}


def graph(page=1, metadata=False):
    value={'kind':'graphs','url':url('D4300',page=page),'model_id':'123','count':2,
           'selected_md':'11/6','page':page,'pages':[{'number':1},{'number':2}], 'index_url':url('D0300')}
    if metadata:value['deferred_images']=True
    else:value['graphs']=[{'rack':100+page,'png':bitmap(),'my_label':'900枚'}]
    return value


class SessionTest(unittest.TestCase):
    def test_page_api_does_not_expose_file_paths_store_factories_or_native_window(self):
        allowed={'note','state','configure','pause','save_overlay_layout','capture','machine_status','skip_graph'}
        public={name for name in dir(self.session) if not name.startswith('_')}
        self.assertEqual(public,allowed)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.session=self.new_session()
        self.epoch=self.session.configure(True,'2026-11-06')['epoch']

    def new_session(self):
        return Session(self.root,DiagnosticLog(self.root),now=lambda:NOW,
                       store_factory=lambda path:PscubeStore(path,recording=False))

    def cycle(self,payload):
        result=self.session.capture(json.dumps(payload),self.epoch)
        self.assertNotIn('error',result,result.get('error'))
        return result

    def log(self,kind=None):
        path=self.root/'logs'/'site777-browser.log'
        rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
        return [r for r in rows if kind is None or r['kind']==kind]

    def test_no_new_capture_is_ready_until_the_requested_page_has_loaded(self):
        # 2026-11-08 Codexのレビュー：移動先の応答が遅いと、5〜7秒の間隔だけで旧画面を読み直していた。
        # 移動を指示したら、読み込みが終わる（_loaded）まで ready にしない。
        self.session._pace.due=lambda:0
        self.assertTrue(self.session.state()['ready'])
        self.assertIn('D4300',self.cycle(table())['action']['url'])
        state=self.session.state()
        self.assertTrue(state['navigating']);self.assertFalse(state['ready']);self.assertTrue(state['enabled'])
        self.session._loaded()
        self.session._pace.due=lambda:0
        state=self.session.state()
        self.assertFalse(state['navigating']);self.assertTrue(state['ready'])

    def test_a_navigation_that_never_finishes_stops_with_its_reason(self):
        import site777_session
        self.cycle(table())
        self.session._pending_since-=site777_session.NAVIGATION_LIMIT+1
        state=self.session.state()
        self.assertFalse(state['enabled'])
        self.assertIn('秒たっても終わらない',state['status'])
        self.assertEqual(self.log('auto_off')[-1]['reason'],'navigation_timeout')

    def test_a_failed_page_load_during_auto_capture_stops_without_reloading(self):
        self.session._navigation_done(False,None,'OperationCanceled')
        self.assertTrue(self.session.state()['enabled'],'守りで取り消した移動・置き換わった移動では止めない')
        self.session._navigation_done(True,200,None)
        self.assertTrue(self.session.state()['enabled'])
        self.session._navigation_done(False,403,'Unknown')
        state=self.session.state()
        self.assertFalse(state['enabled'])
        self.assertIn('HTTP 403',state['status'])
        self.assertEqual(self.log('auto_off')[-1]['reason'],'navigation_failed')
        # OFFのとき（手動で見ているとき）は何もしない。
        self.session._navigation_done(False,500,'Unknown')
        self.assertEqual(len(self.log('auto_off')),1)

    def test_a_late_result_from_before_a_restart_does_not_turn_the_new_run_off(self):
        # 2026-11-08 Codexのレビュー：停止前の読み取りが遅れて届くと、再開したばかりの取り込みまでOFFにしていた。
        old=self.epoch
        self.session.pause()
        new=self.session.configure(True,'2026-11-06')['epoch']
        result=self.session.capture(json.dumps(table()),old)
        self.assertTrue(result.get('stale'))
        state=self.session.state()
        self.assertTrue(state['enabled']);self.assertEqual(state['epoch'],new)
        self.assertEqual(state['status'],'自動取り込みを開始します。')
        self.assertTrue(self.log('stale_result_dropped'))
        self.assertEqual([r['reason'] for r in self.log('auto_off')],['stopped'],'古い処理では止めた記録を足さない')
        # 今の実行番号の読み取りは続けられる。
        self.epoch=new
        self.assertIn('D4300',self.cycle(table())['action']['url'])

    def test_every_stop_leaves_a_reason_code_day_and_stage_without_urls(self):
        # 2026-11-08：自動取り込みがOFFになった理由を後から区別できるよう、理由コード・営業日・工程・実行番号を残す。
        import site777_browser
        self.cycle(table())
        self.session.pause('3回読み込み直しても https://m.site777.jp/f/D4300.do?pmc=04034001&secret=abc','graph_retry_limit',3)
        row=self.log('auto_off')[-1]
        self.assertEqual((row['reason'],row['day'],row['stage'],row['retries'],row['was_on']),
                         ('graph_retry_limit','2026-11-06','table',3,True))
        self.assertNotIn('secret',json.dumps(self.log(),ensure_ascii=False))
        self.assertIn('（URL）',row['message'])
        stop=site777_browser.take_stop_message(self.root)
        self.assertRegex(stop,r'^11/07 10:00に停止【画像待ちの上限】：3回読み込み直しても')
        self.assertIsNone(site777_browser.take_stop_message(self.root),'1回読んだら消す')
        # 理由コードはページから渡るので、形の違うものは使わない。
        self.session.pause(None,'<script>',-1)
        row=self.log('auto_off')[-1]
        self.assertEqual(row['reason'],'stopped');self.assertNotIn('retries',row)
        # 読み取りの失敗も、例外の型だけでなく理由と工程を残す。
        self.epoch=self.session.configure(True,'2026-11-06')['epoch']
        bad=table();bad['days']=[]
        self.assertIn('error',self.session.capture(json.dumps(bad),self.epoch))
        row=self.log('auto_off')[-1]
        self.assertEqual((row['reason'],row['stage'],row['error_type']),('capture_error','table','ValueError'))
        self.assertIn('掲載日付がありません',row['message'])

    def test_a_backup_failure_is_shown_in_the_completion_message(self):
        # 2026-11-08 Codexのレビュー：DBには保存できても、バックアップ・同期フォルダーへの書き出しの失敗を
        # 捨てて、いつもの完了の文で窓を閉じていた。
        from unittest.mock import patch
        index={'kind':'index','url':url('D0300'),'page':1,'pages':[{'number':1}],'index_url':url('D0300'),
               'machines':[{'name':'試験ジャグラー3','model_id':'123','url':url('D2300'),'count':2}]}
        with patch('site777_session.auto_backup',return_value='バックアップに失敗（取り込みは保存済み）'):
            self.cycle(table());self.cycle(graph(metadata=True));self.cycle(graph())
            result=self.cycle(graph(2))
        self.assertIn('バックアップに失敗',result['state']['status'])
        self.assertTrue(self.cycle(index)['complete'])
        self.assertIn('バックアップに失敗（取り込みは保存済み）',self.session._completed)
        self.assertIn('サイトへ戻る必要はありません',self.session._completed)
        self.assertEqual(self.log('backup_problem')[-1]['result'],'バックアップに失敗（取り込みは保存済み）')
        self.assertFalse(self.log('auto_finished')[-1]['backup_ok'])
        # 新しく開始したら注意は消す。うまくいったときは何も足さない。
        self.epoch=self.session.configure(True,'2026-11-06')['epoch']
        self.assertTrue(self.cycle(index)['complete'])
        self.assertNotIn('バックアップ',self.session._completed)

    def due(self):
        """待っている自動の再開の時刻を今にする（3分待たない）。"""
        from time import monotonic
        self.assertIsNotNone(self.session._resume_at)
        self.session._resume_at=monotonic()-1
        return self.session._resume_if_due()

    def test_a_stop_during_auto_capture_resumes_after_three_minutes_and_reloads_the_page_once(self):
        # 2026-11-08 利用者「別店舗など、取り込み対象以外へ移動しようとした（navigation_blocked）これ以外は全て
        # 3分後には自動復帰でお願いします」「利用者の停止ボタンも対象外」「連続5回まで」。
        import site777_session
        from types import SimpleNamespace
        here=url('D4300')
        self.session._window=SimpleNamespace(get_current_url=lambda:here)
        self.assertEqual(site777_session.RESUME_DELAY,180)
        self.session.pause('リンクを押しても移動しないため停止しました。','not_moved')
        state=self.session.state()
        self.assertFalse(state['enabled'])
        self.assertEqual(state['resume_at'],'10:03')
        self.assertIn('10:03に自動で再開します（1/5回目',state['status'])
        self.assertIsNone(self.session._resume_if_due(),'3分たつまでは再開しない')
        self.assertEqual(self.due(),here,'表示中のページを1回だけ読み込み直す')
        state=self.session.state()
        self.assertTrue(state['enabled']);self.assertTrue(state['navigating']);self.assertIsNone(state['resume_at'])
        self.assertEqual((state['day'],state['direction'],state['resume_serial']),('2026-11-06','top',1))
        self.assertIn('自動で再開しました（1/5回目）',state['status'])
        self.assertIsNone(self.session._resume_if_due(),'1回だけ')
        row=self.log('auto_resume')[-1]
        self.assertEqual((row['reason'],row['count'],row['reload']),('not_moved',1,True))

    def test_every_reason_except_blocked_pages_and_the_stop_button_resumes(self):
        import site777_session
        for reason in sorted(site777_session.RESUMABLE):
            with self.subTest(reason=reason):
                self.epoch=self.session.configure(True,'2026-11-06')['epoch']
                self.session.pause('止まりました。',reason)
                self.assertIsNotNone(self.session.state()['resume_at'])
        for reason in ('navigation_blocked','user_stop','stopped'):
            with self.subTest(reason=reason):
                self.epoch=self.session.configure(True,'2026-11-06')['epoch']
                self.session.pause('止まりました。',reason)
                self.assertIsNone(self.session.state()['resume_at'])
        # 別店舗への移動を止めたとき（実際の守りの経路）も再開しない。
        self.epoch=self.session.configure(True,'2026-11-06')['epoch']
        self.assertFalse(self.session._navigation_starting(url('D4300').replace('04034001','23170004'),True))
        self.assertIsNone(self.session.state()['resume_at'])
        # 手動の取り込み（OFF）の失敗は再開しない。読み取りの失敗（ON）は再開する。
        bad=table();bad['days']=[]
        self.epoch=self.session.configure(False,'2026-11-06')['epoch']
        self.assertIn('error',self.session.capture(json.dumps(bad),self.epoch))
        self.assertIsNone(self.session.state()['resume_at'])
        self.epoch=self.session.configure(True,'2026-11-06')['epoch']
        self.assertIn('error',self.session.capture(json.dumps(bad),self.epoch))
        self.assertIsNotNone(self.session.state()['resume_at'])
        self.assertEqual(self.log('auto_off')[-1]['resume'],'scheduled')

    def test_the_stop_button_or_a_date_change_cancels_a_waiting_resume(self):
        self.session.pause('止まりました。','capture_error')
        self.session.pause(None,'user_stop')
        self.assertIsNone(self.session.state()['resume_at'])
        self.assertIsNone(self.session._resume_if_due())
        self.epoch=self.session.configure(True,'2026-11-06')['epoch']
        self.session.pause('止まりました。','capture_error')
        self.session.configure(False,'2026-11-05')
        self.assertIsNone(self.session.state()['resume_at'])

    def test_resuming_gives_up_after_five_in_a_row_without_progress_and_progress_counts_again(self):
        for count in range(1,6):
            self.session.pause('止まりました。','navigation_failed')
            self.assertIn(f'（{count}/5回目',self.session.state()['status'])
            self.due()
        self.session.pause('止まりました。','navigation_failed')
        state=self.session.state()
        self.assertIsNone(state['resume_at'])
        self.assertIn('5回続けても取り込みが進まないため',state['status'])
        self.assertEqual(self.log('auto_off')[-1]['resume'],'gave_up')
        import site777_browser
        self.assertIn('5回続けても',site777_browser.take_stop_message(self.root),'ホームのログ欄にも出す')
        # 利用者が開始し直したら数え直す。途中で機種が1つ済めば（取り込みが進めば）数え直す。
        self.epoch=self.session.configure(True,'2026-11-06')['epoch']
        self.assertEqual(self.session._resume_count,0)
        self.session._resume_count=4
        self.cycle(table());self.cycle(graph(metadata=True));self.cycle(graph())
        self.assertEqual(self.session._resume_count,4)
        self.cycle(graph(2))
        self.assertEqual(self.session._resume_count,0)

    def test_a_redirect_to_the_login_page_says_login_is_needed_and_does_not_resume(self):
        # 2026-11-08 Codexの提案：「認証の確認が必要」を、別店舗への移動と分けて出す。自動では再開しない。
        import site777_browser
        login='https://m.site777.jp/f/P0300.do?skskb=3&returnUrl=%2FF0900.do'
        self.assertFalse(self.session._navigation_starting(login,True))
        state=self.session.state()
        self.assertFalse(state['enabled']);self.assertIsNone(state['resume_at'])
        self.assertIn('ログインの確認が必要です',state['status'])
        self.assertEqual(self.log('auto_off')[-1]['reason'],'login_required')
        self.assertIn('【ログインの確認が必要】',site777_browser.take_stop_message(self.root))
        self.assertTrue(self.session._navigation_starting(login,False),'止めたあとは、利用者がログイン画面を開ける')
        self.assertNotIn('returnUrl',json.dumps(self.log(),ensure_ascii=False))

    def test_reopening_the_window_shows_the_last_run_and_selects_the_remaining_days(self):
        # 2026-11-08 Codexの提案：窓を開き直すと日付の範囲を選び直しになり、前回どこまで取り込んだか分からなかった。
        self.epoch=self.session.configure(True,'2026-11-04','2026-11-06','bottom')['epoch']
        self.session.pause('3回読み込み直してもグラフが表示されないため停止しました。','graph_retry_limit',3)
        self.session.pause(None,'user_stop')
        reopened=self.new_session().state()
        self.assertEqual(reopened['previous'],'前回（11/07 10:00）：11/04〜11/06を取り込む途中で止まりました【停止ボタン】。'
                         '済み：なし。残りの11/04〜11/06を選んであります（開始を押すと続きから。保存済みの台は飛ばします）。')
        self.assertEqual((reopened['day'],reopened['until'],reopened['queue'],reopened['direction']),
                         ('2026-11-04','2026-11-06',['2026-11-05','2026-11-06'],'bottom'))
        self.assertFalse(reopened['enabled'])
        # 開始したら案内は消す。
        session=self.new_session()
        self.assertIsNone(session.configure(True,'2026-11-05')['previous'])
        # 取り込み中に窓を閉じた（止まった記録が無い）とき。
        self.assertIn('止まった理由の記録なし',self.new_session().state()['previous'])
        # 掲載が終わった日が残っているときは選ばず、選び直しを案内する。
        (self.root/'site777-last-run.json').write_text(json.dumps({'at':'2026-10-02T23:00+09:00','start':'2026-10-01',
            'until':'2026-10-01','finished_days':[],'remaining':['2026-10-01'],'stopped':'読み取りの失敗','completed':False}),encoding='utf-8')
        reopened=self.new_session().state()
        self.assertIn('掲載が終わった日があります',reopened['previous'])
        self.assertEqual(reopened['day'],self.session._days[1])  # 初めは前の営業日（今日は確認が要る、2026-11-08）
        # 壊れたファイルは無視する。
        (self.root/'site777-last-run.json').write_text('{',encoding='utf-8')
        self.assertIsNone(self.new_session().state()['previous'])

    def test_the_last_run_keeps_the_original_range_across_auto_resume_and_records_completion(self):
        from types import SimpleNamespace
        self.session._window=SimpleNamespace(get_current_url=lambda:url('D4300'))
        self.epoch=self.session.configure(True,'2026-11-04','2026-11-06')['epoch']
        with self.session._state_lock:
            self.session._day,self.session._queue=('2026-11-05',['2026-11-06'])
            self.session._finished_days=['11/04（追加1台・既存0台・グラフ不明0台）']
        self.session.pause('止まりました。','navigation_failed')
        self.due()
        saved=json.loads((self.root/'site777-last-run.json').read_text(encoding='utf-8'))
        self.assertEqual((saved['start'],saved['until'],saved['remaining']),('2026-11-04','2026-11-06',['2026-11-05','2026-11-06']))
        self.assertEqual(saved['finished_days'],['11/04（追加1台・既存0台・グラフ不明0台）'])
        self.assertIn('済み：11/04（追加1台',self.new_session().state()['previous'])
        # 最後まで終わったら「最後まで取り込みました」。残りの日は選ばない（いつもの最新の日）。
        index={'kind':'index','url':url('D0300'),'page':1,'pages':[{'number':1}],'index_url':url('D0300'),
               'machines':[{'name':'試験ジャグラー3','model_id':'123','url':url('D2300'),'count':2}]}
        self.session._window=None
        self.epoch=self.session.configure(True,'2026-11-06')['epoch']
        self.cycle(table());self.cycle(graph(metadata=True));self.cycle(graph());self.cycle(graph(2))
        self.assertTrue(self.cycle(index)['complete'])
        reopened=self.new_session().state()
        self.assertEqual(reopened['previous'],'前回（11/07 10:00）：11/06を最後まで取り込みました。')
        self.assertEqual(reopened['day'],self.session._days[0])

    def test_table_then_both_graph_pages_before_any_db_record_is_saved(self):
        self.assertEqual(self.cycle(table())['action']['url'].split('/f/')[1].split('.')[0],'D4300')
        self.assertFalse((self.root/'pscube.sqlite3').exists())
        self.assertTrue(self.cycle(graph(metadata=True))['prepare_graphs'])
        self.assertEqual(self.cycle(graph())['action'],{'type':'page','number':2})
        self.assertFalse((self.root/'pscube.sqlite3').exists())
        self.cycle(graph(2))
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:
            records=store.export_payload()['records']
            self.assertEqual({r['rack'] for r in records},{101,102})
            self.assertTrue(all(r['source_site']=='site777' and r['net_medals'] is None for r in records))
        finally:store.close()

    def test_graph_page_first_moves_to_table_and_other_day_presses_the_day_tab(self):
        # 2026-11-07 利用者「グラフの時に日付を切り替えてる挙動じゃなかった」：グラフ一覧で押しても止めずに進む。
        first=graph(metadata=True)
        first.update(selected_md='11/5',table_url=url('D3300'),
                     days=[{'label':'11/6','url':url('D4300')},{'label':'11/5','url':url('D4300').replace('dtdd=0','dtdd=1')}])
        result=self.cycle(first)
        self.assertEqual(result['action'],{'type':'link','url':source_url(url('D3300'),'table')})
        self.cycle(table())
        result=self.cycle(first)
        self.assertEqual(result['action']['type'],'link')
        self.assertIn('dtdd=0',result['action']['url'])
        self.assertIn('D4300',result['action']['url'])
        self.assertTrue(self.session.state()['enabled'])
        self.assertFalse((self.root/'pscube.sqlite3').exists())

    def test_auto_completion_leaves_the_close_message_but_manual_does_not(self):
        # 2026-11-07 利用者「取り込み終わったなら閉じる仕様にしてね」：自動で最後まで終わったときだけ窓を閉じる文を残す。
        index={'kind':'index','url':url('D0300'),'page':1,'pages':[{'number':1}],'index_url':url('D0300'),
               'machines':[{'name':'試験ジャグラー3','model_id':'123','url':url('D2300'),'count':2}]}
        for enabled in (True,False):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as folder:
                self.root=Path(folder)
                self.session=self.new_session()
                self.epoch=self.session.configure(enabled,'2026-11-06')['epoch']
                self.assertIsNone(self.session._completed)
                self.cycle(table());self.cycle(graph(metadata=True));self.cycle(graph());self.cycle(graph(2))
                self.assertTrue(self.cycle(index)['complete'])
                if enabled:self.assertIn('取り込む台はありませんでした',self.session._completed)
                else:self.assertIsNone(self.session._completed)
                self.session.configure(False,'2026-11-06')
                self.assertIsNone(self.session._completed,'設定し直したら消す')

    def test_stop_invalidates_extraction_in_flight(self):
        self.session.configure(False)
        result=self.session.capture(json.dumps(table()),self.epoch)
        self.assertIn('error',result)
        self.assertFalse((self.root/'pscube.sqlite3').exists())

    def test_wrong_day_or_rack_on_second_page_does_not_save_partial_machine(self):
        self.cycle(table())
        self.cycle(graph())
        bad=graph(2)
        bad['graphs'][0]['rack']=999
        result=self.session.capture(json.dumps(bad),self.epoch)
        self.assertIn('error',result)
        self.assertFalse(result['state']['enabled'])
        self.assertFalse((self.root/'pscube.sqlite3').exists())

    def test_reopen_reuses_saved_graph_page(self):
        self.cycle(table())
        self.cycle(graph())
        self.session=self.new_session()
        self.epoch=self.session.configure(True,'2026-11-06')['epoch']
        self.cycle(table())
        result=self.cycle(graph(metadata=True))
        self.assertEqual(result['action'],{'type':'page','number':2})
        self.assertNotIn('prepare_graphs',result)
        self.cycle(graph(2))

    def test_duplicate_rack_across_pages_is_rejected_without_overwriting_staging(self):
        self.cycle(table())
        self.cycle(graph())
        path=self.root/'site777-staging'/'2026-11-06-123.json'
        before=path.read_bytes()
        repeated=graph(2)
        repeated['graphs'][0]['rack']=101
        result=self.session.capture(json.dumps(repeated),self.epoch)
        self.assertIn('error',result)
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((self.root/'pscube.sqlite3').exists())

    def test_wrong_date_my_or_page_number_stops_before_save(self):
        for field,value in [('selected_md','11/5'),('my_label','901枚'),('page',2)]:
            with self.subTest(field=field):
                self.session=self.new_session()
                self.epoch=self.session.configure(True,'2026-11-06')['epoch']
                self.cycle(table())
                bad=graph()
                if field=='my_label':bad['graphs'][0][field]=value
                else:bad[field]=value
                result=self.session.capture(json.dumps(bad),self.epoch)
                self.assertIn('error',result)
                self.assertFalse((self.root/'pscube.sqlite3').exists())

    def test_actual_browser_page_change_before_final_save_rejects_all_records(self):
        self.cycle(table())
        self.cycle(graph())
        class MovingWindow:
            calls=0
            def get_current_url(self):
                self.calls+=1
                return url('D4300',page=2) if self.calls==1 else url('D4300',page=1)
        self.session._window=MovingWindow()
        result=self.session.capture(json.dumps(graph(2)),self.epoch)
        self.assertIn('error',result)
        self.assertFalse((self.root/'pscube.sqlite3').exists())

    def test_foreign_hall_redirect_is_blocked_and_resource_guard_survives_stop(self):
        good=url('D4300')
        bad=good.replace('04034001','23170004').replace('2000','2173')
        self.assertTrue(self.session._navigation_starting(good,False))
        self.assertFalse(self.session._navigation_starting(bad,True))
        self.assertFalse(self.session.state()['enabled'])
        self.assertIn('移動を止めました',self.session.state()['status'])
        self.assertFalse(self.session._document_allowed(bad))
        self.assertTrue(self.session._document_allowed(good))
        self.assertTrue(self.session._document_allowed('https://example.com/captcha-frame'))
        self.assertFalse((self.root/'pscube.sqlite3').exists())
        # 利用者が明示的にOFFへ切り替えたら、通常の手動閲覧へ戻れる。
        self.session.configure(False)
        self.assertTrue(self.session._navigation_starting(bad,False))

    def test_manual_capture_action_also_protects_its_pending_navigation(self):
        self.epoch=self.session.configure(False)['epoch']
        self.cycle(table())
        self.assertFalse(self.session._navigation_starting(url('D4300').replace('2000','500'),False))
        self.assertFalse((self.root/'pscube.sqlite3').exists())

    def test_all_index_pages_are_read_before_using_a_previously_listed_next_machine(self):
        def index(page, model):
            return {'kind':'index','url':url('D0300',page=page),'page':page,
                    'pages':[{'number':1},{'number':2}],
                    'machines':[{'name':'試験機種'+model,'model_id':model,'url':url('D2300',model)}]}
        self.assertEqual(self.cycle(index(1,'123'))['action'],{'type':'page','number':2})
        result=self.cycle(index(2,'456'))
        self.assertEqual(result['action']['type'],'listed')
        self.assertIn('mdc=123',result['action']['url'])
        self.session._done.add('123')
        self.assertIn('mdc=456',self.session._next()['action']['url'])

    def test_a_date_range_runs_oldest_first_and_returns_to_the_machine_list_between_days(self):
        # 2026-11-07 利用者「日付範囲指定できるようにしてほしい」。古い日から順に、日が終わったら機種一覧へ戻る。
        days=[{'label':'11/6','url':url('D3300')},{'label':'11/5','url':url('D3300').replace('dtdd=0','dtdd=1')}]
        def day_table(label):
            value=table();value['selected_md']=label;value['days']=days;return value
        def day_graph(label,page=1,metadata=False):
            value=graph(page,metadata);value['selected_md']=label;return value
        index={'kind':'index','url':url('D0300'),'page':1,'pages':[{'number':1}],
               'machines':[{'name':'試験ジャグラー3','model_id':'123','url':url('D2300')}]}
        state=self.session.configure(True,'2026-11-06','2026-11-05')
        self.assertEqual((state['day'],state['queue'],state['until']),('2026-11-05',['2026-11-06'],'2026-11-06'))
        self.epoch=state['epoch']
        self.assertEqual(self.cycle(index)['action']['type'],'listed')
        for label in ('11/5','11/6'):
            self.assertIn('D4300',self.cycle(day_table(label))['action']['url'])
            self.assertTrue(self.cycle(day_graph(label,metadata=True))['prepare_graphs'])
            self.assertEqual(self.cycle(day_graph(label))['action'],{'type':'page','number':2})
            result=self.cycle(day_graph(label,2))
            if label=='11/5':
                # 1日目が終わったら、次の日のために機種一覧へ戻る（自動はONのまま）。
                self.assertIn('D0300',result['action']['url'])
                self.assertEqual((result['state']['day'],result['state']['queue'],result['state']['enabled']),('2026-11-06',[],True))
                self.assertEqual(len(result['state']['finished_days']),1)
                self.assertEqual(self.cycle(index)['action']['type'],'listed')
        self.assertTrue(result['complete'])
        self.assertFalse(result['state']['enabled'])
        self.assertIn('範囲の取り込みが完了しました',result['state']['status'])
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:
            records=store.export_payload()['records']
            self.assertEqual(sorted((r['day'],r['rack']) for r in records),
                             [('2026-11-05',101),('2026-11-05',102),('2026-11-06',101),('2026-11-06',102)])
        finally:store.close()

    def test_a_range_outside_the_listed_days_or_without_a_start_is_rejected(self):
        with self.assertRaises(ValueError):
            self.session.configure(False,None,'2026-11-05')
        with self.assertRaises(ValueError):
            self.session.configure(False,'2025-01-01','2025-01-02')
        state=self.session.configure(False,'2026-11-05','2026-11-05')
        self.assertEqual((state['day'],state['queue'],state['until']),('2026-11-05',[],None))

    def test_days_already_fully_saved_are_skipped_without_opening_machine_pages(self):
        # 2026-11-07 利用者「この改善は導入してね」：機種一覧の台数だけ、どの機種も保存済みなら、その日は機種ページを開かない。
        # 2026-11-08：台数の合計ではなく機種ごとに照合する（別機種の台で数が足りても飛ばさない、下の試験）。
        from test_pscube_sync import machine, record, put
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:
            a,b=machine('試験機種123'),machine('試験機種456')
            for m,racks in ((a,(101,102)),(b,(103,))):
                put(store,m,[record(m,rack,day) for day in ('2026-11-04','2026-11-05') for rack in racks]
                    +([record(m,101,'2026-11-06')] if m is a else []))
            put(store,machine('沖ドキ！GOLD-30'),[record(machine('沖ドキ！GOLD-30'),900,'2026-11-06')])
        finally:store.close()
        def index(counts):
            return {'kind':'index','url':url('D0300'),'page':1,'pages':[{'number':1}],
                    'machines':[{'name':'試験機種'+model,'model_id':model,'url':url('D2300',model),'count':count}
                                for model,count in counts]}
        state=self.session.configure(True,'2026-11-04','2026-11-06')
        self.epoch=state['epoch']
        result=self.cycle(index([('123',2),('456',1)]))
        # 11/4・11/5 は3台そろっているので飛ばし、11/6 は1台だけ（取り込まない機種の台は数えない）なので機種へ進む。
        self.assertEqual(result['action']['type'],'listed')
        self.assertIn('mdc=123',result['action']['url'])
        self.assertEqual(result['state']['day'],'2026-11-06')
        self.assertEqual(len(result['state']['finished_days']),2)
        self.assertTrue(all('機種ページを開かずに飛ばした' in d for d in result['state']['finished_days']))
        self.assertTrue(result['state']['enabled'])

    def test_other_machines_with_the_same_number_of_racks_never_finish_the_day(self):
        # 2026-11-08 Codexのレビュー：対象の機種の台が1台も無くても、別の機種の台が同じ数だけあると
        # 「全台が保存済み」として完了していた。機種ごとにそろっていなければ、機種ページを開く。
        from test_pscube_sync import machine, record, put
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:
            m=machine('別機種');put(store,m,[record(m,rack,'2026-11-06') for rack in (901,902)])
        finally:store.close()
        index={'kind':'index','url':url('D0300'),'page':1,'pages':[{'number':1}],'index_url':url('D0300'),
               'machines':[{'name':'試験ジャグラー3','model_id':'123','url':url('D2300'),'count':2}]}
        result=self.cycle(index)
        self.assertEqual(result['action'],{'type':'listed','url':source_url(url('D2300'),'model')})
        self.assertTrue(result['state']['enabled'])
        self.assertIsNone(self.session._completed)
        self.assertEqual(self.log('day_check')[-1]['covered'],0)

    def test_a_fully_saved_single_day_finishes_and_unknown_counts_never_skip(self):
        from test_pscube_sync import machine, record, put
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:
            m=machine('試験ジャグラー3')
            put(store,m,[record(m,rack,'2026-11-06') for rack in (101,102)])
        finally:store.close()
        def index(count):
            return {'kind':'index','url':url('D0300'),'page':1,'pages':[{'number':1}],
                    'machines':[{'name':'試験ジャグラー3','model_id':'123','url':url('D2300'),'count':count}]}
        self.epoch=self.session.configure(True,'2026-11-06')['epoch']
        result=self.cycle(index(2))
        self.assertTrue(result['complete'])
        self.assertFalse(result['state']['enabled'])
        self.assertIn('取り込む台はありませんでした',result['state']['status'])
        # 台数が読めない（None）・足りないときは、今までどおり機種ページで確かめる。
        for count in (None,3):
            session=self.new_session()
            self.session=session
            self.epoch=session.configure(True,'2026-11-06')['epoch']
            self.assertEqual(self.cycle(index(count))['action']['type'],'listed')

    def test_reopened_index_skips_machines_already_saved_from_site777(self):
        # 2026-11-07 利用者「機種一覧で取り込んでってやったら未取り込みに飛べばよくない？なんでまたゴーゴージャグラーからいくの？」
        self.cycle(table());self.cycle(graph(metadata=True));self.cycle(graph());self.cycle(graph(2))
        self.session=self.new_session()
        self.epoch=self.session.configure(False,'2026-11-06')['epoch']
        other=url('D2300',model='456')
        index={'kind':'index','url':url('D0300'),'page':1,'pages':[{'number':1}],'index_url':url('D0300'),
               'machines':[{'name':'試験ジャグラー3','model_id':'123','url':url('D2300'),'count':2},
                           {'name':'別の機種','model_id':'456','url':other,'count':1}]}
        result=self.cycle(index)
        self.assertEqual(result['action'],{'type':'listed','url':source_url(other,'model')},'保存済みの機種は開かずに次の未取り込みへ')
        self.assertIn('保存済みの1機種は開かずに飛ばしました',result['state']['status'])
        # 台が足りない機種・台数の読めない機種は今までどおり開く。
        for count in (3,None):
            self.session=self.new_session()
            self.epoch=self.session.configure(False,'2026-11-06')['epoch']
            index['machines'][0]['count']=count
            self.assertEqual(self.cycle(index)['action']['url'],source_url(url('D2300'),'model'))

    def test_index_skips_machine_saved_from_pscube_by_name_like_meruhen(self):
        # メルヘンと同じく、保存済みの台を機種名ごとに数える（P’s CUBEで取った台の機種も開かない）。
        from test_pscube_sync import machine, record, put
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:
            m=machine('試験ジャグラー3');put(store,m,[record(m,rack,'2026-11-06') for rack in (101,102)])
        finally:store.close()
        other=url('D2300',model='456')
        index={'kind':'index','url':url('D0300'),'page':1,'pages':[{'number':1}],'index_url':url('D0300'),
               'machines':[{'name':'試験ジャグラー3','model_id':'123','url':url('D2300'),'count':2},
                           {'name':'別の機種','model_id':'456','url':other,'count':1}]}
        self.assertEqual(self.cycle(index)['action']['url'],source_url(other,'model'))

    def test_bottom_direction_picks_from_the_end_and_interval_is_5_to_7_seconds(self):
        # 2026-11-07 利用者「メルヘンは上から取り込みとか下から取り込みとか」「5～7秒程度にしよう」
        from site777_session import Site777RandomCapture
        from pscube_import import PscubeRandomCapture
        self.assertEqual((Site777RandomCapture.LOW,Site777RandomCapture.HIGH),(5,7))
        self.assertEqual((PscubeRandomCapture.LOW,PscubeRandomCapture.HIGH),(10,20),'P’s CUBEの間隔は変えない')
        for draw in (lambda n:0,lambda n:n-1):
            pace=Site777RandomCapture(draw=draw);pace.configure(True,15)
            self.assertTrue(5<=pace.state()['seconds']<=7)
        index={'kind':'index','url':url('D0300'),'page':1,'pages':[{'number':1}],'index_url':url('D0300'),
               'machines':[{'name':'上の機種','model_id':'123','url':url('D2300'),'count':2},
                           {'name':'下の機種','model_id':'456','url':url('D2300',model='456'),'count':1}]}
        state=self.session.configure(True,'2026-11-06',None,'bottom')
        self.epoch=state['epoch'];self.assertEqual(state['direction'],'bottom')
        self.assertEqual(self.cycle(index)['action']['url'],source_url(url('D2300',model='456'),'model'))
        self.assertEqual(self.session.configure(False,'2026-11-06')['direction'],'bottom','向きを渡さなければ保つ')
        with self.assertRaises(ValueError):self.session.configure(True,'2026-11-06',None,'left')

    def test_anaslo_supplements_are_replaced_by_site777(self):
        # 2026-11-07 利用者「サイトセブンのを取り込んでっていってるの」：アナスロで補った台はサイトセブンで置き換える。
        from test_pscube_sync import machine, record, put
        from pscube_import import _record_key
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:
            m=machine('アナスロの別表記')
            anaslo=record(m,101,'2026-11-06',source_site='anaslo',my=None)
            native=record(m,102,'2026-11-06')
            put(store,m,[anaslo,native])
        finally:store.close()
        # 飛ばす判定：アナスロの台は数えない（2台のうち保存済みは P’s CUBE の1台だけ）。
        index={'kind':'index','url':url('D0300'),'page':1,'pages':[{'number':1}],
               'machines':[{'name':'試験ジャグラー3','model_id':'123','url':url('D2300'),'count':2}]}
        self.assertEqual(self.cycle(index)['action']['type'],'listed')
        self.assertEqual(self.session._occupied(),{102})
        # 全台表→グラフ2ページ：101（アナスロ）はサイトセブンに置き換わり、102（P’s CUBE本来）はそのまま。
        self.assertIn('D4300',self.cycle(table())['action']['url'])
        meta=graph(metadata=True);meta['graph_racks']=[101,102]
        self.assertEqual(self.cycle(meta)['wanted_racks'],[101],'同じページの保存済み102は画像を待たない')
        full=graph();full['graph_racks']=[101,102]
        self.assertTrue(self.cycle(full)['complete'])  # 足りないのは101だけなので1ページ目で終わる
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:
            records={(r['rack'],r.get('source_site')) for r in store.export_payload()['records']}
            self.assertEqual(records,{(101,'site777'),(102,None)})
            self.assertIsNone(store._read('records',_record_key(anaslo)))
            self.assertEqual(store._read('records',_record_key(native)),native)
        finally:store.close()

    def evening_session(self, now):
        # setUp の取り込みの「前回の案内」が日付を選ばないよう、別のフォルダーで開く。
        self.evening=self.root/'evening';self.evening.mkdir()
        return Session(self.evening,DiagnosticLog(self.evening),now=lambda:now,
                       store_factory=lambda path:PscubeStore(path,recording=False))

    def test_the_current_business_day_needs_confirmation_and_the_first_choice_is_the_day_before(self):
        # 2026-11-08：営業中の日を取り込むと、その時点の数値のまま残り、あとで取り込み直しても置き換わらなかった
        # （サイトセブンは無い台だけ補う）。初めは前の営業日を選び、今の営業日以降は確かめてから。
        from pscube_import import _record_key
        session=self.evening_session(datetime.fromisoformat('2026-11-06T19:00:00+09:00'))
        state=session.state()
        self.assertEqual((state['unfinished_from'],state['day'],state['today_ok']),('2026-11-06','2026-11-05',False))
        epoch=state['epoch']
        for args in (('2026-11-06',),('2026-11-04','2026-11-06')):
            with self.assertRaisesRegex(ValueError,'11/06の分はまだ確定していません.*23:30以降に取り込み直すと置き換わります'):
                session.configure(True,*args)
            self.assertEqual((session.state()['epoch'],session.state()['enabled'],session.state()['day']),
                             (epoch,False,'2026-11-05'),'確認なしの開始は何も変えない')
        self.assertTrue(session.configure(True,'2026-11-04','2026-11-05')['enabled'],'終わった日だけなら確認は要らない')
        # 手動の取り込みでも、確認していなければ保存しない。
        epoch=session.configure(False,'2026-11-06')['epoch']
        result=session.capture(json.dumps(table()),epoch)
        self.assertIn('まだ確定していないため、取り込みませんでした',result['error'])
        self.assertFalse((self.evening/'pscube.sqlite3').exists())
        # 確かめたら取り込める。止まって3分後に自動で再開しても、確認は引き継ぐ。
        from types import SimpleNamespace
        session._window=SimpleNamespace(get_current_url=lambda:url('D3300'))
        state=session.configure(True,'2026-11-06',None,None,True)
        self.assertTrue(state['today_ok'])
        session.pause('リンクを押しても移動しないため停止しました。','not_moved')
        self.assertTrue(session.state()['today_ok'],'止めるだけでは確認を消さない')
        from time import monotonic
        session._resume_at=monotonic()-1
        self.assertEqual(session._resume_if_due(),url('D3300'))
        state=session.state()
        self.assertTrue(state['enabled']);self.assertTrue(state['today_ok'])
        session._window=None
        epoch=state['epoch']
        for payload in (table(),graph(metadata=True),graph(),graph(2)):
            result=session.capture(json.dumps(payload),epoch)
            self.assertNotIn('error',result,result.get('error'))
        store=PscubeStore(self.evening/'pscube.sqlite3',recording=False)
        try:self.assertEqual(sorted(r['rack'] for r in store.export_payload()['records']),[101,102])
        finally:store.close()
        # 日付を選び直したら、確認はやり直す。
        self.assertFalse(session.configure(False,'2026-11-05')['today_ok'])
        # 午前0〜3時に出る翌日のタブ（営業日より後の日）も確かめる対象。
        self.assertEqual(Session._unfinished(['2026-11-07','2026-11-06','2026-11-05'],'2026-11-06'),
                         ['2026-11-07','2026-11-06'])

    def test_a_backup_failure_survives_an_auto_resume_and_a_later_success_clears_it(self):
        # 2026-11-08：自動の再開（configure(True)）がバックアップの失敗の知らせを消し、再開のあと書き出さずに完了すると
        # 完了の文に出なかった。書き出しは毎回DB全体なので、あとで成功したら知らせは消す。
        from types import SimpleNamespace
        from unittest.mock import patch
        failed='バックアップに失敗（取り込みは保存済み）'
        self.session._backup_note=failed
        self.session._window=SimpleNamespace(get_current_url=lambda:url('D3300'))
        self.session.pause('リンクを押しても移動しないため停止しました。','not_moved')
        self.assertEqual(self.due(),url('D3300'))
        self.assertTrue(self.session.state()['enabled'])
        self.assertEqual(self.session._backup_note,failed,'自動の再開では消さない')
        self.assertIn(failed,self.session._with_backup('範囲の取り込みが完了しました。'))
        self.session._window=None
        self.epoch=self.session.state()['epoch']
        with patch('site777_session.auto_backup',return_value='バックアップ済み'):
            self.cycle(table());self.cycle(graph(metadata=True));self.cycle(graph())
            result=self.cycle(graph(2))
        self.assertIsNone(self.session._backup_note)
        self.assertNotIn('バックアップに失敗',result['state']['status'])
        self.assertTrue(self.log('backup_recovered'))
        # 利用者が新しく開始したときは、今までどおり消す。
        self.session._backup_note=failed
        self.session.configure(True,'2026-11-06')
        self.assertIsNone(self.session._backup_note)

    def test_a_backup_already_written_by_a_newer_export_counts_as_success(self):
        # 2026-11-08：073f0eb から auto_backup は「バックアップ済み（より新しい時点の書き出しが先に済んでいます）」も返す。
        # 完全一致で比べていたので、成功なのに「バックアップに失敗」と出ていた。
        from unittest.mock import patch
        with patch('site777_session.auto_backup',return_value='バックアップ済み（より新しい時点の書き出しが先に済んでいます）'):
            self.cycle(table());self.cycle(graph(metadata=True));self.cycle(graph())
            result=self.cycle(graph(2))
        self.assertIsNone(self.session._backup_note)
        self.assertNotIn('バックアップに失敗',result['state']['status'])
        self.assertFalse(self.log('backup_problem'))

    def test_opening_the_window_removes_staging_of_days_that_can_no_longer_be_captured(self):
        # 2026-11-08：機種ごとの途中の記録を消す仕組みが無く、1日に約50本ずつ増えていた。元の資料（sources）は残す。
        staging=self.root/'site777-staging';(staging/'sources').mkdir(parents=True,exist_ok=True)
        for name in ('2026-10-23-120141.json','2026-10-24-120141.json','2026-11-06-120141.json','memo.json'):
            (staging/name).write_text('{}',encoding='utf-8')
        (staging/'sources'/'abc.json').write_text('{}',encoding='utf-8')
        self.new_session()  # 今の営業日 11/07 → 14日前の 10/24 より前だけ消す
        self.assertEqual(sorted(p.name for p in staging.glob('*.json')),
                         ['2026-10-24-120141.json','2026-11-06-120141.json','memo.json'])
        self.assertTrue((staging/'sources'/'abc.json').exists())
        self.assertEqual((self.log('staging_pruned')[-1]['removed'],self.log('staging_pruned')[-1]['before']),(1,'2026-10-24'))

    def test_a_day_is_final_from_half_past_eleven_that_night(self):
        # 2026-11-10 利用者「23時半以降に取り込みだしたやつも飛ばしていいです。23時45分くらいに最終更新だから」
        # → 確定はその日の23:30以降（2026-11-08 は翌日0:30だった）。
        for now,first,chosen in (('2026-11-06T23:29:00+09:00','2026-11-06','2026-11-05'),
                                 ('2026-11-06T23:30:00+09:00','2026-11-07','2026-11-06'),
                                 ('2026-11-06T23:59:00+09:00','2026-11-07','2026-11-06'),
                                 ('2026-11-07T00:29:00+09:00','2026-11-07','2026-11-06'),
                                 ('2026-11-07T02:59:00+09:00','2026-11-07','2026-11-06'),
                                 ('2026-11-07T10:00:00+09:00','2026-11-07','2026-11-06')):
            folder=self.root/now[:16].replace(':','');folder.mkdir()
            state=Session(folder,DiagnosticLog(folder),now=lambda now=now:datetime.fromisoformat(now)).state()
            self.assertEqual((state['unfinished_from'],state['day']),(first,chosen),now)

    def test_racks_captured_before_the_day_is_final_are_replaced_by_a_later_capture(self):
        # 2026-11-08：営業中（2026-11-10 からはその日の23:30より前）に取ったサイトセブンの台は、あとで取り込み直すと置き換わる。
        # 確定（23:30以降）した台は今までどおり置き換えない。
        from types import SimpleNamespace
        def capture(now,games,today_ok=False):
            session=Session(self.root,DiagnosticLog(self.root),now=lambda:datetime.fromisoformat(now),
                            store_factory=lambda path:PscubeStore(path,recording=False))
            epoch=session.configure(True,'2026-11-06',None,None,today_ok)['epoch']
            payload=table();payload['rows'][0][2]=str(games)
            results=[session.capture(json.dumps(x),epoch) for x in (payload,graph(metadata=True),graph(),graph(2))]
            return session,results
        def games():
            store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
            try:return {r['rack']:(r['games'],r['source_captured_at'][:16]) for r in store.export_payload()['records']}
            finally:store.close()
        (self.root/'site777-last-run.json').unlink(missing_ok=True)
        capture('2026-11-06T23:10:00+09:00',3000,True)
        self.assertEqual(games()[101],(3000,'2026-11-06T23:10'))
        # 23:30より前の取り込み直し（まだ確定前）でも、新しい方で置き換える。
        session,results=capture('2026-11-06T23:25:00+09:00',3100,True)
        self.assertEqual(games()[101],(3100,'2026-11-06T23:25'))
        # 確定後：確定前の台を未取り込みとして数え、取り直して置き換える。
        session,results=capture('2026-11-07T10:00:00+09:00',8000)
        self.assertNotIn('error',results[0],results[0].get('error'))
        self.assertIn('D4300',results[0]['action']['url'],'確定前の台はもう一度グラフを読む')
        self.assertEqual(games()[101],(8000,'2026-11-07T10:00'))
        # 確定した台は置き換えない（表は「既存の記録を保持」で終わる）。
        session,results=capture('2026-11-07T11:00:00+09:00',9000)
        self.assertNotIn('error',results[0],results[0].get('error'))
        self.assertNotIn('D4300',results[0]['action']['url'],'確定した台のグラフは読みに行かない')
        self.assertIn('既存の記録を保持',results[0]['state']['status'])
        self.assertEqual(games()[101],(8000,'2026-11-07T10:00'))

    def test_the_merge_rule_replaces_only_racks_that_were_not_final_and_only_with_newer_ones(self):
        from pscube_import import _merge, site777_final, site777_supersedes
        def rack(captured,games=100,source='site777'):
            return {'source_site':source,'day':'2026-11-06','source_captured_at':captured,'games':games}
        early,late,final=rack('2026-11-06T23:10:00+09:00',1),rack('2026-11-06T23:29:59+09:00',2),rack('2026-11-06T23:30:00+09:00',3)
        self.assertEqual([site777_final(r) for r in (early,late,final)],[False,False,True])
        self.assertIs(_merge(early,late),late);self.assertIs(_merge(late,final),final)
        self.assertIs(_merge(late,early),late,'古い取り込みでは置き換えない')
        self.assertIs(_merge(final,rack('2026-11-07T10:00:00+09:00',4)),final,'確定した台は置き換えない')
        self.assertFalse(site777_supersedes(rack('2026-11-06T23:10:00+09:00',source=None),late),'P’s CUBE本来の台は対象外')
        self.assertTrue(site777_final(rack(None)),'時刻が読めない台は確定として扱う（置き換えない）')

    def saved(self):
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:return {r['rack']:r['games'] for r in store.export_payload()['records']}
        finally:store.close()

    def index(self,count=2):
        return {'kind':'index','url':url('D0300'),'page':1,'pages':[{'number':1}],'index_url':url('D0300'),
                'machines':[{'name':'試験ジャグラー3','model_id':'123','url':url('D2300'),'count':count},
                            {'name':'別の機種','model_id':'456','url':url('D2300',model='456'),'count':1}]}

    def test_graph_wait_targets_only_needed_racks_on_mixed_page(self):
        payload=table();payload['rows'][1][2]='499'
        self.cycle(payload)
        meta=graph(metadata=True);meta['graph_racks']=[101,102]
        self.assertEqual(self.cycle(meta)['wanted_racks'],[101])
        full=graph();full['graph_racks']=[101,102]
        self.cycle(full)
        self.assertEqual(self.saved(),{101:3000})

    def test_graph_page_with_only_unneeded_racks_advances_without_images(self):
        payload=table();payload['rows'][0][2]='0'
        self.cycle(payload)
        meta=graph(metadata=True);meta['graph_racks']=[101]
        self.assertEqual(self.cycle(meta)['wanted_racks'],[102])
        full=graph();full.update(graph_racks=[101],graphs=[])
        self.assertEqual(self.cycle(full)['action'],{'type':'page','number':2})
        self.assertEqual(self.saved(),{})
        self.cycle(graph(2))
        self.assertEqual(self.saved(),{102:2800})

    def test_filtered_graph_page_still_rejects_missing_or_foreign_racks(self):
        for racks, images in (([101,999], []), ([101,101], []), ([101,102], []), ([101,102], graph()['graphs'])):
            with self.subTest(racks=racks,images=len(images)):
                self.session=self.new_session()
                self.epoch=self.session.configure(True,'2026-11-06')['epoch']
                self.cycle(table())
                full=graph();full.update(graph_racks=racks,graphs=images)
                self.assertIn('error',self.session.capture(json.dumps(full),self.epoch))
                self.assertEqual(self.saved(),{})

    def test_one_rack_whose_graph_never_loads_is_saved_without_a_graph(self):
        # 2026-11-13 1:15〜1:40、ゴーゴージャグラー3の1286番台だけグラフが仮の画像のままで、3分後の再開を繰り返した。
        # 利用者「グラフなしで進めるようにお願いね」：その台は「グラフ不明」で保存して進む。1機種につき1台まで。
        from site777_import import validate_record
        self.assertFalse(self.session.skip_graph(101,self.epoch)['ok'],'グラフ一覧の前は断る')
        self.cycle(table());self.assertTrue(self.cycle(graph(metadata=True))['prepare_graphs'])
        self.assertFalse(self.session.skip_graph(101,self.epoch+1)['ok'],'古い実行番号は断る')
        self.assertFalse(self.session.skip_graph(999,self.epoch)['ok'],'表に無い台は断る')
        self.assertFalse(self.session.skip_graph('101',self.epoch)['ok'])
        self.assertTrue(self.session.skip_graph(101,self.epoch)['ok'])
        self.assertFalse(self.session.skip_graph(102,self.epoch)['ok'],'2台目は断る（呼ぶ側が今までどおり止める）')
        self.assertEqual([(r['rack'],r['day']) for r in self.log('graph_skipped')],[(101,'2026-11-06')])
        # 同じページの読み直し：101の画像は待たない。
        meta=graph(metadata=True);meta['graph_racks']=[101]
        self.assertEqual(self.cycle(meta)['wanted_racks'],[102])
        full=graph();full.update(graph_racks=[101],graphs=[])
        self.assertEqual(self.cycle(full)['action'],{'type':'page','number':2})
        self.cycle(graph(2))
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:records={r['rack']:r for r in store.export_payload()['records']}
        finally:store.close()
        self.assertEqual({k:r['games'] for k,r in records.items()},{101:3000,102:2800},'表の数値は保存する')
        self.assertIsNone(records[101]['graph'])
        self.assertEqual(records[101]['source_graph']['missing'],'image_not_loaded')
        self.assertIsNotNone(records[102]['graph'])
        for record in records.values():validate_record(record)          # 別の端末・閲覧ページと同じ形の確認を通る
        self.assertIn('グラフ不明1台',self.session.state()['status'])

    def test_graph_skip_needs_auto_capture_on_and_is_kept_when_the_window_reopens(self):
        self.cycle(table());self.cycle(graph(metadata=True))
        self.assertTrue(self.session.skip_graph(101,self.epoch)['ok'])
        # 窓を開き直して同じ表を読んでも、グラフなしにした台は覚えている（もう一度待たない）。
        self.session=self.new_session();self.epoch=self.session.configure(True,'2026-11-06')['epoch']
        self.cycle(table())
        meta=graph(metadata=True);meta['graph_racks']=[101]
        self.assertEqual(self.cycle(meta)['wanted_racks'],[102])
        self.assertFalse(self.session.skip_graph(102,self.epoch)['ok'],'開き直しても1機種1台まで')
        self.session.configure(False)
        self.assertFalse(self.session.skip_graph(102,self.epoch)['ok'],'自動取り込みがOFFなら断る')

    def test_racks_under_500_games_are_not_saved_and_count_as_done(self):
        # 2026-11-10 利用者「サイトセブンの取り込みについて、0ゲーム、500g未満の台については取り込まなく定位」。
        # 500Gちょうどは取り込む。取り込まなかった台のグラフは読まず、機種一覧では済みに数える（毎回開き直さない）。
        payload=table();payload['rows'][1][2]='499'
        self.assertIn('D4300',self.cycle(payload)['action']['url'])
        self.cycle(graph(metadata=True))
        result=self.cycle(graph())
        self.assertNotEqual(result.get('action'),{'type':'page','number':2},'取り込まない台のグラフページは読まない')
        self.assertEqual(self.saved(),{101:3000})
        self.assertEqual(self.session.machine_status(json.dumps({'machines':self.index()['machines']}))['status'],
                         [{'done':2,'total':2,'excluded':False},{'done':0,'total':1,'excluded':False}])
        self.session=self.new_session()
        self.epoch=self.session.configure(False,'2026-11-06')['epoch']
        self.assertEqual(self.cycle(self.index())['action']['url'],source_url(url('D2300',model='456'),'model'),
                         '500G未満の台は済みに数え、その機種は開かない')
        # 0Gと500Gちょうど：0Gは取り込まず、500Gは取り込む。全台が500G未満なら、グラフを読まずに次へ。
        def day5(value):
            value['selected_md']='11/5';value['days']=[{'label':'11/5','url':url('D3300')}];return value
        for games in ('0','500'):
            session=self.new_session();self.session=session
            self.epoch=session.configure(False,'2026-11-05')['epoch']
            payload=day5(table());payload['rows'][0][2]='0';payload['rows'][1][2]=games
            result=self.cycle(payload)
            if games=='0':
                self.assertNotIn('D4300',result['action']['url'])
                self.assertIn('500G未満の2台は取り込まず',result['state']['status'])
            else:
                self.assertIn('D4300',result['action']['url'])
                self.cycle(day5(graph(metadata=True)))
                self.assertEqual(self.cycle(day5(graph()))['action'],{'type':'page','number':2})
                self.cycle(day5(graph(2)))
        self.assertEqual(self.saved(),{101:3000,102:500})

    def test_low_racks_of_a_day_that_is_not_final_are_not_remembered(self):
        # 確定前（その日の23:30より前）の500G未満の台は、あとで500Gを超えることがあるので済みに数えない。
        session=self.evening_session(datetime.fromisoformat('2026-11-06T19:00:00+09:00'))
        epoch=session.configure(False,'2026-11-06',None,None,True)['epoch']
        payload=table();payload['rows'][0][2]='10';payload['rows'][1][2]='20'
        self.assertNotIn('error',session.capture(json.dumps(payload),epoch))
        self.assertFalse((self.evening/'site777-staging'/'2026-11-06-low.json').exists())
        self.assertEqual(session.machine_status(json.dumps({'machines':self.index()['machines']}))['status'][0]['done'],0)

    def test_machine_status_reports_saved_racks_for_each_listed_machine(self):
        # 機種一覧の横の表示（2026-11-10 利用者「なぜメルヘンと同じ仕様になってないんだ。機種のよこに未取り込みとかもでてないし」）。
        from test_pscube_sync import machine, record, put
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:
            m=machine('試験ジャグラー3');put(store,m,[record(m,101,'2026-11-06')])
        finally:store.close()
        machines=self.index(2)['machines']+[{'name':'沖ドキ！GOLD-30','model_id':'789','count':None},
                                           {'name':'壊れた','model_id':'x','count':1}]
        state=self.session.machine_status(json.dumps({'machines':machines}))
        self.assertEqual(state['day'],'2026-11-06')
        self.assertEqual(state['status'][:2],[{'done':1,'total':2,'excluded':False},{'done':0,'total':1,'excluded':False}])
        self.assertTrue(state['status'][2]['excluded'],'取り込まない機種は対象外')
        self.assertEqual(state['status'][3],{'done':0,'total':1,'excluded':False})
        self.assertEqual(self.session.machine_status('壊れた'),{'day':'2026-11-06','status':[]})
