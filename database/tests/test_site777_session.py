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

NOW = datetime.fromisoformat('2026-11-07T02:00:00+09:00')


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
        allowed={'note','state','configure','pause','save_overlay_layout','capture'}
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
        # 2026-11-07 利用者「この改善は導入してね」：機種一覧の台数の合計だけ保存済みなら、その日は機種ページを開かない。
        from test_pscube_sync import machine, record, put
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:
            m=machine('別の出典の名前')
            put(store,m,[record(m,rack,day) for day in ('2026-11-04','2026-11-05') for rack in (101,102,103)]
                +[record(m,101,'2026-11-06'),record(machine('沖ドキ！GOLD-30'),900,'2026-11-06')])
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
        self.assertTrue(self.cycle(graph(metadata=True))['prepare_graphs'])
        self.assertTrue(self.cycle(graph())['complete'])  # 足りないのは101だけなので1ページ目で終わる
        store=PscubeStore(self.root/'pscube.sqlite3',recording=False)
        try:
            records={(r['rack'],r.get('source_site')) for r in store.export_payload()['records']}
            self.assertEqual(records,{(101,'site777'),(102,None)})
            self.assertIsNone(store._read('records',_record_key(anaslo)))
            self.assertEqual(store._read('records',_record_key(native)),native)
        finally:store.close()
