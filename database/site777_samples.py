"""利用者が表示した資料の控え。追加通信・ページ移動・DB更新は行わない。

data/site777-samples.enabled がある間だけ site777_browser から呼ばれる開発用の処理。
資料は Git 対象外の data/site777-samples に JSON として保存する（HTMLを実行しない）。
Cookie・ストレージ・通信ヘッダーは読まない。入力欄の値は控えから取り除く。
"""
from __future__ import annotations

import json
import time
import unicodedata
from html.parser import HTMLParser
from datetime import datetime
from pathlib import Path
from site777_import import same_page, source_url
from uuid import uuid4

MAX_BYTES = 12 * 1024 * 1024
MAX_SAMPLES = 20
MAX_TOTAL_BYTES = 80 * 1024 * 1024
ENABLED_SECONDS = 30 * 60


class _SensitiveInput(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = False

    def handle_starttag(self, tag, attrs):
        if tag == 'input' and dict(attrs).get('type', '').lower() == 'password':
            self.found = True

SNAPSHOT_JS = r'''(() => {
  const text = (document.body ? document.body.innerText : '').normalize('NFKC');
  if (!/P[\s－-]*STATION/i.test(text) || !/スロット館/.test(text) ||
      document.querySelector('input[type=password]')) return null;
  const start = location.href;
  const clone = document.documentElement.cloneNode(true);
  clone.querySelectorAll('script,noscript,iframe').forEach(el => el.remove());
  clone.querySelectorAll('input').forEach(el => {
    el.removeAttribute('value');
    el.removeAttribute('checked');
  });
  clone.querySelectorAll('textarea').forEach(el => { el.textContent = ''; });
  clone.querySelectorAll('[id^=database-]').forEach(el => el.remove());
  const images = Array.from(document.images).filter(img => img.naturalWidth >= 100 && img.naturalHeight >= 80)
    .slice(0, 100).map(img => {
      const result = {src: img.currentSrc || img.src, width: img.naturalWidth, height: img.naturalHeight};
      if (!img.complete) { result.error = '読み込み未完了'; return result; }
      try {
        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
        canvas.getContext('2d').drawImage(img, 0, 0);
        result.png = canvas.toDataURL('image/png');
      } catch (_) { result.error = 'この画像は表示済みの画素を読み出せません'; }
      return result;
    });
  const canvases = Array.from(document.querySelectorAll('canvas')).slice(0, 100).map(canvas => {
    try { return {width: canvas.width, height: canvas.height, png: canvas.toDataURL('image/png')}; }
    catch (_) { return {error: 'このcanvasは画素を読み出せません'}; }
  });
  if (start !== location.href) return null;
  return {url: start, html: clone.outerHTML, images, canvases};
})()'''


def enabled(data_dir):
    flag = Path(data_dir) / 'site777-samples.enabled'
    try:
        return flag.is_file() and 0 <= time.time() - flag.stat().st_mtime <= ENABLED_SECONDS
    except OSError:
        return False


def save_sample(data_dir, payload):
    """表示済みのP-STATION資料だけをローカル保存。認証ページや別サイトを拒否する。"""
    if not isinstance(payload, dict):
        return None
    try:
        source_url(payload.get('url'))
    except (TypeError, ValueError):
        return None
    html = payload.get('html')
    normalized = unicodedata.normalize('NFKC', html) if isinstance(html, str) else ''
    if (not isinstance(html, str)
            or 'スロット館' not in normalized or 'STATION' not in normalized.upper()):
        return None
    sensitive = _SensitiveInput()
    sensitive.feed(html)
    if sensitive.found:
        return None
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(body) > MAX_BYTES:
        raise ValueError('資料が大きすぎるため保存を止めました。')
    folder = Path(data_dir) / 'site777-samples'
    folder.mkdir(parents=True, exist_ok=True)
    existing = list(folder.glob('page-*.json'))
    if len(existing) >= MAX_SAMPLES or sum(p.stat().st_size for p in existing) + len(body) > MAX_TOTAL_BYTES:
        return None
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    path = folder / f'page-{stamp}-{uuid4().hex[:8]}.json'
    with path.open('xb') as stream:
        stream.write(body)
    return path


def collect(window, data_dir, log):
    if not enabled(data_dir):
        return
    try:
        before = window.get_current_url()
        try:
            source_url(before)
        except (TypeError, ValueError):
            return
        payload = window.evaluate_js(SNAPSHOT_JS)
        if not isinstance(payload, dict):
            log.write('sample_skipped', reason='no_target_data')
            return
        if not same_page(payload.get('url'), before) or not same_page(window.get_current_url(), before):
            log.write('sample_skipped', reason='page_changed')
            return
        path = save_sample(data_dir, payload)
        if path:
            log.write('sample_saved', file=path.name, images=len(payload.get('images', [])))
        else:
            log.write('sample_skipped', reason='validation_or_limit')
    except Exception:  # 読み取り失敗で表示やセッションを壊さない。例外の本文にURL等を出さない。
        log.write('sample_failed')
