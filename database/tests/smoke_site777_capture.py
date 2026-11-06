"""実WebView2＋合成31台の表/20+11グラフ。外部サイト・実DBを使わない。"""
import base64
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import parse_qs, urlsplit

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import site777_browser as browser
import site777_import as capture
from capture_card import CARD_JS
import webview

NOW = datetime.fromisoformat('2026-11-07T02:00:00+09:00')
SOURCE = 'https://m.site777.jp/f/{path}.do?pmc=04034001&urt=2000&mdc={model}&dtdd=0&pan={page}'


def image_bytes(background=False):
    image = Image.new('RGB', (260, 226), '#191e18')
    draw = ImageDraw.Draw(image)
    draw.line([(8, 111), (243, 111)], fill='gray' if background else 'white', width=2)
    if not background:
        draw.line([(9, 111), (30, 100), (80, 135), (120, 105)], fill='yellow', width=2)
    stream = BytesIO()
    image.save(stream, 'PNG')
    return stream.getvalue()


def fixture(kind, page, model='123'):
    count,start=(31,101) if model=='123' else (1,201)
    machine='試験ジャグラー３' if model=='123' else '試験AT'
    actual = SOURCE.format(path='D3300' if kind == 'table' else 'D4300', page=page,model=model)
    common = ('<h2 class=page-title>Ｐ－ＳＴＡＴＩＯＮ＆ＩＩ　スロット館</h2>'
              f'<div id=main><div class=mod-center><p>{machine}</p>'
              f'<p class=hd-style-radius>{count}台 /【20】スロ</p></div></div>'
              f'<ul class=tab-style-data><li class=active><a href="{actual}">11/6</a></li></ul>')
    common+='<ul class=tab-style-b>'+''.join(f'<li><a href="{SOURCE.format(path=p,page=1,model=model)}">{name}</a></li>' for p,name in [('D3300','大当り一覧'),('D4300','出玉推移一覧')])+'</ul>'
    if kind == 'table':
        headers = ['', '台番', '累計ｹﾞｰﾑ', 'BB回数', 'RB回数', '最高出玉', 'ART回数']
        table = '<table id=dedama_data_list><thead><tr>' + ''.join('<td>'+s+'</td>' for s in headers) + '</tr></thead><tbody>'
        for rack in range(start,start+count):
            table += f'<tr><td></td><td class=daiData><a href=#>{rack}</a></td><td>3000</td><td>10</td><td>8</td><td>900</td><td>--</td></tr>'
        table += '<tr><td>平均</td><td>999</td></tr></tbody></table>'
        content = '<div class=item aria-hidden=true style="display:none">' + table + '</div><div class=item aria-hidden=false>' + table + '</div>'
    else:
        racks=range(start+(page-1)*20,min(start+page*20,start+count))
        content = '<div class=lite-graph style="width:530px;display:grid;grid-template-columns:260px 260px;gap:8px">'
        for rack in racks:
            content += (f'<div class=graph-box><span>[{rack}]</span><img width=260 height=226 '
                        f'src="/f/contents/images/sp/graph-back.png" '
                        f'data-graph="/chart/RequestSPDedamaTransitionChartForPortal.do?rack={rack}"><label class=max-num>900枚</label></div>')
        content += '</div><ul class=pager-style>'
        content += ''.join(f'<li><a '+('class=active' if n == page else f'href="javascript:changePage(\'{n}\');"')+f'>{n}</a></li>' for n in range(1,(count+19)//20+1))+'</ul>'
        content += '''<script>
          const observer=new IntersectionObserver(entries=>entries.forEach(e=>{
            if(e.isIntersecting && e.target.dataset.graph){e.target.src=e.target.dataset.graph;delete e.target.dataset.graph;observer.unobserve(e.target);}
          })); document.querySelectorAll('img[data-graph]').forEach(img=>observer.observe(img));
          function changePage(n){window.chosenPage=n;}
        </script>'''
    return ('<!doctype html><meta charset=utf-8><link rel=icon href="data:,">'
            f'<div id=test-page>{kind}{page}</div>' + common + content).encode('utf-8')


def main():
    requests, result = [], {}
    watchdog = threading.Timer(75, lambda: os._exit(2))
    watchdog.daemon = True
    watchdog.start()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            u = urlsplit(self.path)
            if u.path.endswith('.png') or u.path.startswith('/chart/'):
                content, kind = image_bytes(u.path.endswith('.png')), 'image/png'
            else:
                content = fixture('table' if u.path == '/table' else 'graphs', int(parse_qs(u.query).get('pan', ['1'])[0]))
                kind = 'text/html; charset=utf-8'
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; img-src 'self'; connect-src 'none'")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    with tempfile.TemporaryDirectory(prefix='site777-capture-') as tmp:
        window = webview.create_window('サイトセブン解析・ローカル試験（自動終了）', base+'/table', width=560, height=800)
        ready = threading.Event()
        window.events.loaded += ready.set

        def wait(check, label, seconds=15):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                if check(): return
                time.sleep(.05)
            raise AssertionError(label)

        def read(kind, page=1):
            wait(lambda: window.evaluate_js("document.querySelector('#test-page')?.textContent") == kind+str(page), 'ページの準備待ち')
            script=(ROOT/'assets/site777_capture.js').read_text(encoding='utf-8')
            source=json.dumps(SOURCE.format(path='D3300' if kind=='table' else 'D4300', page=page,model='123'))
            # テストだけで対象文書のURLを対応付ける。製品にfixture用の分岐は入れない。
            script=script.replace('const sourceUrl = location.href;', 'const sourceUrl = '+source+';')
            script=script.replace('samePage(sourceUrl, location.href)', 'samePage(sourceUrl, '+source+')')
            window.evaluate_js(script)
            if kind=='graphs':
                window.evaluate_js("window.__done=false;databaseSite777.prepare(()=>false).then(()=>{window.__done=true;}).catch(e=>{window.__failure=e.message;window.__done=true;});void 0")
                wait(lambda: window.evaluate_js('window.__done'), '遅延グラフの準備待ち')
                assert not window.evaluate_js('window.__failure'), window.evaluate_js('window.__failure')
            return window.evaluate_js('databaseSite777.read()')

        def exercise():
            try:
                assert ready.wait(15)
                table=read('table')
                rows=capture.table_records(table,'2026-11-06',NOW)
                assert len(rows)==31 and rows[0]['at_art'] is None
                window.evaluate_js(CARD_JS+";window.testCard=databaseCaptureCard({id:'database-test-card'});testCard.card.append(testCard.grip);testCard.mount();")
                assert window.evaluate_js("document.querySelectorAll('#database-test-card button').length")==2
                graphs={}
                for page in (1,2):
                    window.load_url(base+f'/graphs?pan={page}')
                    payload=read('graphs',page)
                    graphs.update(capture.graph_records(payload,'2026-11-06','123',set(range(101,132)),NOW))
                    assert len(payload['graphs'])==(20 if page==1 else 11)
                assert len(graphs)==31
                chart_requests=[r for r in requests if r.startswith('/chart/')]
                assert len(chart_requests)==len(set(chart_requests))==31, '同じグラフを再取得しています'
                result.update(ok=True, table_rows=31, graph_pages=[20,11], chart_requests=31, common_card=True)
            except Exception:
                result.update(ok=False,error=traceback.format_exc())
            finally:
                window.destroy()

        webview.start(exercise,gui='edgechromium',private_mode=True,storage_path=str(Path(tmp)/'webview'))
    server.shutdown()
    watchdog.cancel()
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result.get('ok') else 1


if __name__=='__main__':
    raise SystemExit(main())
