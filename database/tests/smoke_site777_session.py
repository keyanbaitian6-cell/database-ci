"""オーバーレイ→機種一覧2ページ→31台＋1台の保存をローカルだけで通す。"""
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
from site777_browser import DiagnosticLog,keep_popups_here
from site777_session import Session
from smoke_site777_capture import fixture,image_bytes,NOW


def main():
    requests,result,handlers=[],{},[]
    watchdog=threading.Timer(90,lambda:os._exit(2));watchdog.daemon=True;watchdog.start()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            u=urlsplit(self.path);q=parse_qs(u.query)
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
        def install():handlers.extend(keep_popups_here(window,log))
        def loaded():
            try:
                session._loaded()
                mapped=json.dumps(session._window.get_current_url())
                reader=(ROOT/'assets/site777_capture.js').read_text(encoding='utf-8')
                reader=reader.replace('const sourceUrl = location.href;','const sourceUrl = '+mapped+';')
                reader=reader.replace('samePage(sourceUrl, location.href)','samePage(sourceUrl, '+mapped+')')
                overlay=(ROOT/'assets/site777_overlay.js').read_text(encoding='utf-8').replace('const u=new URL(location.href);','const u=new URL('+mapped+');')
                window.evaluate_js(CARD_JS+'\n;'+reader+'\n;'+overlay)
                ready.set()
            except Exception:result.update(ok=False,error=traceback.format_exc());ready.set()
        def exercise():
            try:
                assert ready.wait(15),'カードを表示できません'
                window.evaluate_js("document.querySelector('#database-site777-auto').click()")
                deadline=time.monotonic()+65
                while time.monotonic()<deadline:
                    state=session.state()
                    if state['added']==32 and not state['enabled']:break
                    if not state['enabled'] and state['status']!='P-STATIONの20円スロットを開き、取り込む日付を確認してください。':
                        raise AssertionError(state['status'])
                    time.sleep(.15)
                assert session.state()['added']==32,session.state()
                store=PscubeStore(folder/'pscube.sqlite3',recording=False)
                try:records=store.export_payload()['records']
                finally:store.close()
                assert len(records)==32 and all(r['source_site']=='site777' for r in records)
                charts=[r for r in requests if r.startswith('/chart/')]
                assert len(charts)==len(set(charts))==32,'同じグラフを再取得しています'
                result.update(ok=True,records=32,machines=2,index_pages=2,graph_requests=32,auto_off_at_end=True)
            except Exception:
                result.update(ok=False,error=traceback.format_exc(),state=session.state())
            finally:window.destroy()
        window.events.before_show+=install;window.events.loaded+=loaded
        webview.start(exercise,gui='edgechromium',private_mode=True,storage_path=str(folder/'webview'))
    server.shutdown();watchdog.cancel()
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result.get('ok') else 1


if __name__=='__main__':raise SystemExit(main())
