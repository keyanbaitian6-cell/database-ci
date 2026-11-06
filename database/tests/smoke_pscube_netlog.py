"""手動で流す確認（Windows）：実WebView2で、通信の診断記録（pscube_netlog.py）が CDP の通知を受けて書かれるか。

python tests/smoke_pscube_netlog.py

smoke_pscube_net_capture.py と同じく、本番の run_session を一時DB・一時プロファイルで開き、すべての要求を
WebView2 の中（WebResourceRequested、フィルター '*'）で模擬ページが答える。窓は about:blank で開き、フィルターを
入れてから模擬サイトを開くので、実サイトには届かない。利用者のDB・Cookie・バックアップは使わない。
確かめること：CDPの通知が届く（cdp_enabled・要求の行がある）、ページ本体と差枚APIを分けて数える、
差枚APIの403をアプリの呼び出しとして数える、apikey・_i・_t の値が記録に無い、窓を閉じると集計を書く。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def check(case):
    import smoke_pscube_net_capture as smoke
    with tempfile.TemporaryDirectory(prefix='pscube-netlog-smoke-', ignore_cleanup_errors=True) as tmp:
        result = smoke.run(case, tmp)
        folder = Path(tmp) / 'data' / 'pscube_netlog'
        logs = sorted(folder.glob('net-*.jsonl'))
        summaries = sorted(folder.glob('net-*-summary.txt'))
        lines = [json.loads(x) for x in logs[-1].read_text(encoding='utf-8').splitlines()] if logs else []
        text = (logs[-1].read_text(encoding='utf-8') if logs else '') + (
            summaries[-1].read_text(encoding='utf-8') if summaries else '')
        reqs = [x for x in lines if x.get('ev') == 'req']
        return {'button': result.get('button'), 'files': len(logs), 'summaries': len(summaries),
                'events': sorted({x.get('ev') for x in lines}),
                'cats': sorted({(x['cat'], x.get('status')) for x in reqs}),  # JSON ではリストになる。下で tuple に戻す
                'navs': [x.get('reason') for x in lines if x.get('ev') == 'nav'],
                'called': sum(1 for x in lines if x.get('ev') == 'capture_end' and x.get('net_called')),
                'secret': any(s in text for s in ('local-key', 'local-i', 'local-t')),
                'summary_head': (summaries[-1].read_text(encoding='utf-8')[:1500] if summaries else '')}


if __name__ == '__main__':
    if len(sys.argv) > 1:
        sys.stdout.reconfigure(encoding='utf-8')
        print(json.dumps(check(sys.argv[1]), ensure_ascii=False))
        sys.exit(0)
    outputs = {}
    for name in ('ok', 'refused'):
        done = subprocess.run([sys.executable, __file__, name], capture_output=True, text=True, encoding='utf-8', timeout=420)
        line = [x for x in done.stdout.splitlines() if x.startswith('{')]
        assert line, (name, done.stdout[-2000:], done.stderr[-2000:])
        outputs[name] = json.loads(line[-1])
        outputs[name]['cats'] = [tuple(x) for x in outputs[name]['cats']]
    ok, refused = outputs['ok'], outputs['refused']
    for out in (ok, refused):
        assert out['files'] == 1 and out['summaries'] == 1, out
        assert 'cdp_enabled' in out['events'] and 'req' in out['events'], out
        assert not out['secret'], 'apikey・_i・_t の値が記録に残っている'
    # 実WebView2の呼び出し元は上の1段だけ（アプリが呼んでも上はサイトの jQuery.ajax）なので、差枚APIは「呼び出し元不明」に
    # 入る。アプリが取りに行った回数（保存の記録の net_called）と並べて見る。
    api = ('api_app', 'api_unknown')
    assert ('page', 200) in ok['cats'] and any((c, 200) in ok['cats'] for c in api), ok['cats']
    assert ok['called'] >= 1, ok
    assert any((c, 403) in refused['cats'] for c in api) and ('page', 403) not in refused['cats'], refused['cats']
    assert 'next_page' in ok['navs'], ok['navs']
    print('PASS: real WebView2 delivered CDP Network notices; pages and the net API were counted apart, '
          'the refused API was a net API 403 (not a page 403), the app fetch was counted from the save record, '
          'no secret query values were written, and the summary was saved')
    print(ok['summary_head'])
