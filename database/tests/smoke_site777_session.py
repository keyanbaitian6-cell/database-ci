"""オーバーレイ→機種一覧2ページ→31台＋1台の保存をローカルだけで通す。

--failed-load（2026-11-08）：台の表のページを1回だけ HTTP 403 にし、読み込みの失敗で止まり（navigation_failed）、
自動の再開（待ち時間は2秒に縮める）で表示中のページを1回だけ読み込み直して最後まで取り込むことを、実 WebView2 で確かめる。
--graph-recovery：102台だけ画像待ちにし、成功分の途中保存後に画像を置換して回復。ページ再取得なしで完了する。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import parse_qs, urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import webview
from capture_card import CARD_JS
from pscube_import import PscubeRandomCapture, PscubeStore
import site777_browser
from site777_browser import DiagnosticLog,keep_popups_here
import site777_session
from site777_session import Session
from datetime import datetime
from smoke_site777_capture import fixture,image_bytes
# 11/6 が終わった日になる時刻（2026-11-08：今の営業日は確認が要り、初めは前の営業日を選ぶようにしたため）。
NOW=datetime.fromisoformat('2026-11-07T10:00:00+09:00')


def main():
    redirected='--redirect' in sys.argv
    without_guard='--without-guard' in sys.argv
    resource_only='--resource-only' in sys.argv
    # --range：11/6と11/5の2日を見せ、カードで「まで」を選んで2日分を古い順に取り込む（2026-11-07）。
    ranged='--range' in sys.argv
    failed_load='--failed-load' in sys.argv
    mixed_graphs='--mixed-graphs' in sys.argv
    graph_recovery='--graph-recovery' in sys.argv
    expected_count=31 if mixed_graphs else 32
    if failed_load:site777_session.RESUME_DELAY=2
    refused=[]
    if without_guard and not redirected:raise ValueError('対照試験には--redirectも指定してください')
    requests,result,handlers=[],{},[]
    watchdog=threading.Timer(170 if ranged else 90,lambda:os._exit(2));watchdog.daemon=True;watchdog.start()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            u=urlsplit(self.path);q=parse_qs(u.query)
            if failed_load and u.path.endswith('D3300.do') and q.get('mdc')==['123'] and not refused:
                refused.append(self.path)
                body='<!doctype html><meta charset=utf-8><title>403</title>拒否'.encode('utf-8')
                self.send_response(403);self.send_header('Content-Type','text/html; charset=utf-8')
                self.end_headers();self.wfile.write(body);return
            if redirected and u.path.endswith('D4300.do') and q.get('pmc')==['04034001']:
                self.send_response(302)
                self.send_header('Location',self.path.replace('pmc=04034001','pmc=23170004').replace('urt=2000','urt=2173'))
                self.end_headers();return
            if u.path.startswith('/chart/') or u.path.endswith('.png'):
                body=image_bytes(u.path.endswith('.png'));mime='image/png'
            else:
                model=q.get('mdc',['123'])[0];page=int(q.get('pan',['1'])[0])
                def source(path,model=None,page=1):
                    return f'https://m.site777.jp/f/{path}.do?pmc=04034001&urt=2000&pan={page}'+(f'&mdc={model}' if model else '')+('&dtdd=0' if path in ('D3300','D4300') else '')
                if u.path.endswith('D0300.do'):
                    model='123' if page==1 else '456';name='試験ジャグラー３ [31]' if page==1 else '試験AT'
                    text=f'<h2 class=page-title>Ｐ－ＳＴＡＴＩＯＮ＆ＩＩ　スロット館</h2><a class=imageSet href="{source("D2300",model)}"><strong>{name}</strong></a>'
                    text+='<ul class=pager-style>'+''.join(f'<li><a '+('class=active' if n==page else f'href="javascript:changePage(\'{n}\');"')+f'>{n}</a></li>' for n in (1,2))+'</ul>'
                elif u.path.endswith('D2300.do'):
                    text='<h2 class=page-title>Ｐ－ＳＴＡＴＩＯＮ＆ＩＩ　スロット館</h2><section id=halltop><div class="list-style mod-mt10px"><ul>'
                    text+=f'<li><a href="{source("D3300",model)}">大当り一覧</a></li></ul></div></section>'
                else:
                    kind='table' if u.path.endswith('D3300.do') else 'graphs'
                    text=fixture(kind,page,model).decode('utf-8')
                    if graph_recovery and kind=='graphs' and model=='123':
                        text=text.replace('data-graph="/chart/RequestSPDedamaTransitionChartForPortal.do?rack=102"','')
                    if mixed_graphs and model=='123':
                        if kind=='table':
                            text=text.replace('>102</a></td><td>3000</td>', '>102</a></td><td>499</td>')
                        else:
                            # 対象外102台の画像は最後まで出さない。非表示の複製も画像なし。
                            text=text.replace('data-graph="/chart/RequestSPDedamaTransitionChartForPortal.do?rack=102"','')
                            text+='<script>const duplicate=document.querySelector(".graph-box").cloneNode(true);duplicate.style.display="none";duplicate.querySelector("img").removeAttribute("src");document.querySelector(".lite-graph").prepend(duplicate);</script>'
                    if ranged:
                        older=q.get('dtdd')==['1']
                        here,other=('dtdd=1','dtdd=0') if older else ('dtdd=0','dtdd=1')
                        tabs=('<ul class=tab-style-data>'+''.join(
                            f'<li'+(' class=active' if (label=='11/5')==older else '')+f'><a href="{source("D3300" if kind=="table" else "D4300",model,page).replace("dtdd=0",d)}">{label}</a></li>'
                            for label,d in (('11/6','dtdd=0'),('11/5','dtdd=1')))+'</ul>')
                        start=text.index('<ul class=tab-style-data>');end=text.index('</ul>',start)+5
                        text=text[:start]+tabs+text[end:]
                        # 本物のページの下のメニューと同じく「設置機種」（機種一覧）へのリンクを置く。
                        text+=f'<nav><a href="{source("D0300")}">設置機種</a></nav>'
                        if older:
                            text=text.replace('dtdd=0','dtdd=1').replace('/chart/RequestSPDedamaTransitionChartForPortal.do?','/chart/RequestSPDedamaTransitionChartForPortal.do?day=1105&')
                            text=text.replace(tabs.replace('dtdd=0','dtdd=1'),tabs)
                # テスト文書のリンクだけをlocalhostへ対応付ける。外部のサイトへは一切移動しない。
                text+='''<script>
                  function localUrl(raw){const u=new URL(raw);if(u.origin!=='https://m.site777.jp')throw Error('外部移動を拒否');return location.origin+u.pathname+u.search;}
                  document.addEventListener('click',e=>{const a=e.target.closest('a[href]');if(!a)return;
                    if(a.href.startsWith('https://')){e.preventDefault();location.assign(localUrl(a.href));}},true);
                  function changePage(n){const u=new URL(location.href);u.searchParams.set('pan',n);location.assign(u.href);}
                </script>'''
                body=('<!doctype html><meta charset=utf-8><link rel=icon href="data:,">'+text).encode('utf-8');mime='text/html; charset=utf-8'
            self.send_response(200);self.send_header('Content-Type',mime)
            self.send_header('Content-Security-Policy',"default-src 'none'; img-src 'self'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; connect-src 'none'")
            self.end_headers();self.wfile.write(body)

        def log_message(self,*args):pass

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}'
    with tempfile.TemporaryDirectory(prefix='site777-session-') as tmp:
        folder=Path(tmp);log=DiagnosticLog(folder)
        session=Session(folder,log,now=lambda:NOW,store_factory=lambda path:PscubeStore(path,recording=False))
        session._pace=PscubeRandomCapture(clock=lambda:time.monotonic()*100,draw=lambda n:0)
        window=webview.create_window('サイトセブン自動取り込み・ローカル試験（自動終了）',
            base+'/f/D0300.do?pmc=04034001&urt=2000&pan=1',width=560,height=800,js_api=session)
        class FixtureWindow:
            def get_current_url(self):
                raw=window.get_current_url()
                if not raw.startswith(base+'/'):raise ValueError('localhost以外へ移動しました')
                return raw.replace(base,'https://m.site777.jp',1)
        session._window=FixtureWindow()
        ready=threading.Event()
        def mapped_url(raw):
            return raw.replace(base,'https://m.site777.jp',1) if raw.startswith(base+'/') else raw
        def install():
            guards={} if without_guard else dict(
                navigation_guard=None if resource_only else lambda raw,redirected:session._navigation_starting(mapped_url(raw),redirected),
                document_guard=lambda raw:session._document_allowed(mapped_url(raw)),document_filter=base+'/f/*',
                navigation_done=session._navigation_done)  # 本番の窓（site777_browser.run）と同じく読み込みの完了をつなぐ
            handlers.extend(keep_popups_here(window,log,**guards))
        def loaded():
            try:
                session._loaded()
                mapped=json.dumps(session._window.get_current_url())
                reader=(ROOT/'assets/site777_capture.js').read_text(encoding='utf-8')
                reader=reader.replace('const sourceUrl = location.href;','const sourceUrl = '+mapped+';')
                reader=reader.replace('samePage(sourceUrl, location.href)','samePage(sourceUrl, '+mapped+')')
                overlay=(ROOT/'assets/site777_overlay.js').read_text(encoding='utf-8').replace('const u=new URL(location.href);','const u=new URL('+mapped+');')
                if graph_recovery:
                    window.evaluate_js('window.__site777GraphWaitMs=1200;')
                window.evaluate_js(CARD_JS+'\n;'+reader+'\n;'+overlay)
                ready.set()
            except Exception:result.update(ok=False,error=traceback.format_exc());ready.set()
        def exercise():
            try:
                assert ready.wait(15),'カードを表示できません'
                if ranged:
                    window.evaluate_js("const u=document.querySelector('#database-site777-until');"
                                       "u.value='2026-11-05';u.dispatchEvent(new Event('change'))")
                    time.sleep(1.5)
                    assert (session.state()['day'],session.state()['queue'])==('2026-11-05',['2026-11-06']),session.state()
                window.evaluate_js("document.querySelector('#database-site777-auto').click()")
                recovered=False
                deadline=time.monotonic()+(140 if ranged else 65)
                while time.monotonic()<deadline:
                    state=session.state()
                    if graph_recovery and not recovered and log.path.exists():
                        rows=[json.loads(line) for line in log.path.read_text(encoding='utf-8').splitlines()]
                        staged=[r for r in rows if r['kind']=='graphs_staged']
                        if staged:
                            assert 101 in staged[0]['racks'] and 102 not in staged[0]['racks'],staged
                            window.evaluate_js('''const box=[...document.querySelectorAll('.graph-box')].find(b=>b.querySelector('span')?.textContent==='[102]');
                              const img=box.querySelector('img'),fresh=img.cloneNode();img.replaceWith(fresh);
                              fresh.src='/chart/RequestSPDedamaTransitionChartForPortal.do?rack=102';''')
                            recovered=True
                    if redirected:
                        foreign=any('pmc=23170004' in r for r in requests)
                        if without_guard and foreign:break
                        if not without_guard and not state['enabled'] and '移動を止めました' in state['status']:break
                        time.sleep(.15);continue
                    if failed_load:
                        # 本番の窓の見張り（site777_browser.run の watch_finished）と同じく、時刻が来たら再開して読み込み直す。
                        again=session._resume_if_due()
                        if again:site777_browser.reload_page(window,again.replace('https://m.site777.jp',base,1))
                    if state['added']==expected_count and not state['enabled']:break
                    if failed_load and state['resume_at']:time.sleep(.15);continue
                    if not state['enabled'] and state['status']!='P-STATIONの20円スロットを開き、取り込む日付を確認してください。':
                        raise AssertionError(state['status'])
                    time.sleep(.15)
                if redirected:
                    foreign=any('pmc=23170004' in r for r in requests)
                    assert foreign==without_guard,(requests,session.state())
                    assert not (folder/'pscube.sqlite3').exists(),'別店舗のデータを書き込みました'
                    if without_guard:
                        result.update(ok=True,local_negative_control=True,foreign_request_observed=True)
                        return
                    assert not session.state()['enabled'],session.state()
                    if resource_only:
                        result.update(ok=True,resource_guard_blocked=True,foreign_requests=0,no_db_write=True)
                        return
                    assert window.evaluate_js("document.querySelector('#test-page')?.textContent")=='table1'
                    # 元ページの8秒の移動待ちタイマーが、停止理由を上書きしないこと。
                    time.sleep(9)
                    assert '移動を止めました' in session.state()['status'],session.state()
                    assert '移動を止めました' in window.evaluate_js("document.querySelector('#database-site777-status')?.textContent"),'カードに停止理由が出ません'
                    assert 'OFF' in window.evaluate_js("document.querySelector('#database-site777-auto')?.textContent"),'カードがOFFになりません'
                    result.update(ok=True,redirect_blocked=True,foreign_requests=0,original_table_kept=True,no_db_write=True)
                    return
                assert session.state()['added']==expected_count,session.state()
                store=PscubeStore(folder/'pscube.sqlite3',recording=False)
                try:records=store.export_payload()['records']
                finally:store.close()
                if ranged:
                    days=sorted({r['day'] for r in records})
                    assert days==['2026-11-05','2026-11-06'] and len(records)==64,(days,len(records))
                    assert len(session.state()['finished_days'])==2 and '範囲の取り込みが完了しました' in session.state()['status'],session.state()
                    charts=[r for r in requests if r.startswith('/chart/')]
                    assert len(charts)==len(set(charts))==64,'同じグラフを再取得しています'
                    result.update(ok=True,records=64,days=days,graph_requests=64,auto_off_at_end=True)
                    return
                assert len(records)==expected_count and all(r['source_site']=='site777' for r in records)
                if mixed_graphs:
                    assert all(r['rack']!=102 for r in records)
                    charts=[r for r in requests if r.startswith('/chart/')]
                    assert len(charts)==len(set(charts))==31,charts
                    assert not any('rack=102' in r for r in charts),charts
                    result.update(ok=True,records=31,missing_unneeded_graph_skipped=True,hidden_graph_skipped=True,
                                  graph_requests=31,auto_off_at_end=True)
                    return
                if failed_load:
                    rows=[json.loads(line) for line in log.path.read_text(encoding='utf-8').splitlines()]
                    off=[r for r in rows if r['kind']=='auto_off' and r['reason']=='navigation_failed']
                    resumed=[r for r in rows if r['kind']=='auto_resume']
                    assert len(refused)==1 and len(off)==1 and 'HTTP 403' in off[0]['message'] and off[0]['resume']=='scheduled',(refused,off)
                    assert [(r['reason'],r['count'],r['reload']) for r in resumed]==[('navigation_failed',1,True)],resumed
                    tables=[r for r in requests if '/f/D3300.do' in r and 'mdc=123' in r]
                    assert len(tables)==2,('拒否された表を1回だけ読み込み直す',tables)
                    result.update(ok=True,failed_load_stopped=True,resumed_once=True,table_requests=2,records=32)
                    return
                charts=[r for r in requests if r.startswith('/chart/')]
                assert len(charts)==len(set(charts))==32,'同じグラフを再取得しています'
                if graph_recovery:
                    assert recovered,'画像待ちと途中保存を通りませんでした'
                    pages=[r for r in requests if urlsplit(r).path=='/f/D4300.do'
                           and parse_qs(urlsplit(r).query).get('mdc')==['123']
                           and parse_qs(urlsplit(r).query).get('pan')==['1']]
                    assert len(pages)==1,('回復したページを再取得しています',pages)
                    result.update(ok=True,records=32,partial_saved_then_recovered=True,
                                  stalled_page_requests=1,graph_requests=32,auto_off_at_end=True)
                    return
                result.update(ok=True,records=32,machines=2,index_pages=2,graph_requests=32,auto_off_at_end=True)
            except Exception:
                tail=[]
                try:tail=[{k:v for k,v in json.loads(line).items() if k in ('kind','reason','ok','status','error','href','reload')}
                          for line in log.path.read_text(encoding='utf-8').splitlines()[-14:]]
                except OSError:pass
                result.update(ok=False,error=traceback.format_exc(),state=session.state(),requests=requests[-6:],log=tail)
            finally:window.destroy()
        window.events.before_show+=install;window.events.loaded+=loaded
        webview.start(exercise,gui='edgechromium',private_mode=True,storage_path=str(folder/'webview'))
    server.shutdown();watchdog.cancel()
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result.get('ok') else 1


if __name__=='__main__':raise SystemExit(main())
