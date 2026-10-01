"""Direct browser capture: read the live page's table/graph instead of OCR.

The user opens an embedded, normal browser window restricted to the two
target shops and browses it themselves (store, machine, date are all their
own clicks). One injected button hands the matching, *currently displayed*
HTML table or SVG graph straight to Python for validation, confirmation, and scoring --
no screenshot, no OCR, nothing sent anywhere external.

This module is split in two halves:
  * Pure functions (importable and unit-tested without a browser or display):
    URL/day/name validation, table-row building, graph-point building.
  * ``run_session`` and friends, which need `pywebview` and a live display and
    are only exercised by hand.
"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw
from auto_capture import AUTO_CAPTURE_JS, AutoCapture

from collector import HEADERS, HEADERS_NO_MAX_HOLD, HOST, parse_table
from core import (STORE_NAMES, Store, normalize_machine_name, auto_backup, day_fully_graphed, duplicate_warning,
                  graph_done, machine_progress, no_hits, progress_text, remember_for_undo, undo_last_save)

BROWSER_URLS = {
    'nagamachiminami': f'https://{HOST}/nagamachiminami/rack_info',
    'saiwaichou': f'https://{HOST}/saiwaichou/rack_info',
}
DEFAULT_START = BROWSER_URLS['nagamachiminami']


class TableExtractionError(ValueError):
    pass


class GraphExtractionError(ValueError):
    pass


def is_allowed_url(url):
    """Only the two target shops' pages -- matches the Android WebView allow-list."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != 'https' or parsed.hostname != HOST:
        return False
    location = parsed.path.strip('/').split('/')[0] if parsed.path.strip('/') else ''
    return location in STORE_NAMES


def same_page_url(a, b):
    """同じページのURLか。pywebview（WebView2）の get_current_url は日本語を元の文字に戻した形
    （例 machine_name=L ｽﾏｽﾛ化物語 KH）、ページの location.href は%に置き換えた形
    （machine_name=L%20%EF%BD%BD…）で返す（2026-10-01 実測）。そのまま比べると、日本語の機種名の
    全台一覧で「ON・ページ切り替え待ち」から抜けられなかった（利用者の報告）。両方の%を戻して比べる。"""
    from urllib.parse import unquote
    if not isinstance(a, str) or not isinstance(b, str):
        return a == b
    return unquote(a, errors='surrogateescape') == unquote(b, errors='surrogateescape')


def page_mismatch(current_url, payload):
    """Why the extracted data disagrees with the page actually shown, or None.

    The injected script's store/date/rack come from the page itself, so they
    are checked against the window's real URL here. When the URL (or its
    date/rack) is unknown there is nothing to check, and capture is allowed.
    """
    from urllib.parse import parse_qs, urlparse
    if not current_url or not isinstance(payload, dict):
        return None
    parsed = urlparse(current_url)
    parts = [p for p in parsed.path.split('/') if p]
    url_store = parts[0] if parts else None
    if url_store not in STORE_NAMES:
        return '対象店舗のページではありません。'
    if payload.get('store') and payload['store'] != url_store:
        return 'ページの店舗と読み取った店舗が違います。保存しませんでした。'
    query, fragment = parse_qs(parsed.query), parse_qs(parsed.fragment)
    url_day = (query.get('target_date') or fragment.get('database_day') or [None])[0]
    url_day = url_day.replace('/', '-') if url_day else None
    try:
        day = resolve_day(payload)
    except ValueError:
        day = None
    try:
        valid = bool(url_day) and date.fromisoformat(url_day).isoformat() == url_day
    except ValueError:
        valid = False
    if valid and day and day != url_day:
        return f'ページの日付（{url_day}）と読み取った日付（{day}）が違います。保存しませんでした。'
    url_rack = (query.get('rack_no') or [None])[0]
    rack = payload.get('rack')
    if url_rack and url_rack.isdigit() and rack is not None and str(rack) != url_rack:
        return f'ページの台番号（{url_rack}）と読み取った台番号（{rack}）が違います。保存しませんでした。'
    return None


def resolve_day(payload):
    """A URL's target_date always wins over any on-page displayed date."""
    target = payload.get('target_date')
    if target:
        date.fromisoformat(target)
        return target
    day = payload.get('day')
    if not day:
        raise ValueError('評価日を特定できません。日付を選んでから取り込んでください。')
    date.fromisoformat(day)
    return day


def build_table_rows(payload):
    """Validate a browser-extracted list-page table; never silently drop rows.

    ``payload`` is what the injected extraction script returns: the raw table
    matrix (header row + data rows, matching the site's own column order),
    the per-row detail links, and page identity (store/machine/target_date).
    """
    location = payload.get('store')
    if location not in STORE_NAMES:
        raise TableExtractionError('対象外の店舗のページです。長町南店・幸町店の一覧を開いてください。')
    if str(payload.get('kind_code')) != '21':
        raise TableExtractionError('対象は1000円46枚スロットのみです。対象の機種別一覧を開いてください。')
    machine = normalize_machine_name(payload.get('machine'))
    if not machine:
        raise TableExtractionError('機種名を取得できません。機種別の一覧ページを表示してください。')
    matrix = payload.get('matrix')
    links = payload.get('links')
    if not matrix or not links:
        raise TableExtractionError('一覧の表を検出できません。台番号を含む一覧を表示してから取り込んでください。')
    day = resolve_day(payload)
    updated = payload.get('updated_display') or ''
    source = payload.get('source_url') or ''
    # parse_table already refuses any duplicate rack number outright (whether
    # or not the duplicate rows agree), so a table is never silently merged.
    rows = parse_table(matrix, links, day, machine, source, updated, location)
    return rows, day, machine


def _curve_points(raw_points):
    points = []
    for item in raw_points or []:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise GraphExtractionError('グラフの座標形式が不正です。')
        points.append((float(item[0]), float(item[1])))
    if len(points) < 2:
        raise GraphExtractionError('グラフの線を検出できません。')
    if any(b[0] < a[0] for a, b in zip(points, points[1:])):
        raise GraphExtractionError('グラフの横軸が単調ではありません。')
    return points


def auto_four_points(points, baseline_y, width):
    peak = min(points, key=lambda p: p[1])
    trough = max(points, key=lambda p: p[1])
    end = points[-1]
    baseline_x = width * 0.85 if width else end[0]
    return dict(baseline_x=baseline_x, baseline_y=baseline_y,
                peak_x=peak[0], peak_y=peak[1],
                trough_x=trough[0], trough_y=trough[1],
                end_x=end[0], end_y=end[1])


AUTO_GRAPH_MIN_POINTS = 10
# The curve starts on the zero line and its last x reaches (almost) the right
# edge in every real capture on file (observed_graphs.json: first y within 0.5
# of the baseline, last x == full width). These tolerances leave room for that
# while still catching a half-loaded or mis-selected graph.
AUTO_GRAPH_START_TOLERANCE = 2.0
AUTO_GRAPH_MIN_END_X_RATIO = 0.8
AUTO_GRAPH_END_ZERO_TOLERANCE = 1.0


def graph_auto_save_blockers(context):
    """Reasons a graph may NOT be saved without the user looking at it.

    Empty list = every sanity check passed. The rule is deliberately
    conservative: skipping the confirmation screen is only worth it when the
    exact vector data extracted from the page is self-consistent, and any
    doubt sends the graph back to the normal confirmation dialog.
    """
    reasons = []
    points = context['points']
    baseline = context['baseline_y']
    if context.get('already_graphed'):
        reasons.append('この台は既にグラフが保存されています（上書きは確認が必要）')
    if context.get('updated_fields'):
        reasons.append('一覧の数値と詳細画面の数値が異なります')
    if context['games'] <= 0:
        reasons.append('総回転数が0です')
    if len(points) < AUTO_GRAPH_MIN_POINTS:
        reasons.append(f'グラフの点が少なすぎます（{len(points)}点）')
    if abs(points[0][1] - baseline) > AUTO_GRAPH_START_TOLERANCE:
        reasons.append('グラフの開始位置がゼロ線と一致しません')
    width = context.get('width')
    if width and points[-1][0] < width * AUTO_GRAPH_MIN_END_X_RATIO:
        reasons.append('グラフが右端まで描かれていません（読み込み途中の可能性）')
    if abs(points[-1][1] - baseline) <= AUTO_GRAPH_END_ZERO_TOLERANCE:
        reasons.append('終点がゼロ線とほぼ同じ位置です（上昇・下降を目で確認）')
    return reasons


def graph_measurement_result(context, curve):
    """The same graph_measurement dict the confirmation dialog would produce."""
    from screenshot_import import encode_preview_image
    auto = context['auto']
    preview_b64, preview_w, preview_h = encode_preview_image(curve)
    return dict(baseline_x=auto['baseline_x'], baseline_y=auto['baseline_y'],
                peak_x=auto['peak_x'], peak_y=auto['peak_y'],
                trough_x=auto['trough_x'], trough_y=auto['trough_y'],
                end_x=auto['end_x'], end_y=auto['end_y'],
                preview_image=preview_b64, preview_width=preview_w, preview_height=preview_h,
                curve=_curve_json(context['points']),
                method='browser-four-point-auto')


def _curve_json(points):
    """The exact SVG curve, kept so new indicators can be computed later
    without re-capturing every rack (today only four points are used)."""
    return [[round(x, 1), round(y, 1)] for x, y in points]


def now_stamp():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def render_curve_image(points, baseline_y, width, height):
    """Draw the exact vector curve -- no photo, nothing to OCR."""
    width = max(1, int(round(width)))
    height = max(1, int(round(height)))
    image = Image.new('RGB', (width, height), (12, 12, 16))
    draw = ImageDraw.Draw(image)
    draw.line([(0, baseline_y), (width, baseline_y)], fill=(230, 60, 60), width=1)
    if len(points) >= 2:
        draw.line(points, fill=(230, 230, 230), width=2)
    return image


def build_graph_context(payload, store):
    """Validate a browser-extracted individual graph and inherit the list row.

    A matching store/day/rack row from an already-imported list is required
    (mirrors the existing screenshot flow's rule) so that a machine name is
    always available even on graph pages that never display one, and so a
    1000-yen/92-mai rack can never slip in through the graph screen alone.
    """
    location = payload.get('store')
    if location not in STORE_NAMES:
        raise GraphExtractionError('対象外の店舗のページです。長町南店・幸町店のグラフを開いてください。')
    rack = payload.get('rack')
    if rack is None:
        raise GraphExtractionError('台番号を検出できません。個別台のグラフ画面を表示してください。')
    rack = int(rack)
    day = resolve_day(payload)

    existing_rows = store.rows(day, None, location)
    match = next((r for r in existing_rows if int(r['rack']) == rack), None)
    if match is None:
        raise GraphExtractionError(
            f'{rack}番台：先にこの日付・店舗の一覧を取り込んでください（一覧に見つかりません）。')

    points = _curve_points(payload.get('points'))
    baseline_y = payload.get('baseline_y')
    if baseline_y is None:
        raise GraphExtractionError('ゼロ線を検出できません。')
    baseline_y = float(baseline_y)

    machine = normalize_machine_name(payload.get('machine')) or match['machine']

    updated_fields = {}

    def resolve_number(field):
        value = payload.get(field)
        if value is not None:
            value = int(value)
            if match.get(field) is not None and int(match[field]) != value:
                # 一覧の取り込み後にも、詳細画面側の総回転数や最大持玉は
                # 増加・補完される。店舗・日付・台番号で一覧行を特定済みなら、
                # 詳細画面で現在表示されている値を採用する。
                updated_fields[field] = (int(match[field]), value)
            return value
        if match.get(field) is not None:
            return int(match[field])
        raise GraphExtractionError(f'{rack}番台の数値を確認できません。')

    games = resolve_number('games')
    bb = resolve_number('bb')
    rb = resolve_number('rb')
    max_hold = resolve_number('max_hold')

    width = payload.get('width') or (points[-1][0] + 10)
    height = payload.get('height') or (max(y for _, y in points) + 20)
    auto = auto_four_points(points, baseline_y, width)

    already_graphed = bool(match.get('graph') or match.get('graph_measurement'))
    return dict(store=location, day=day, machine=machine, rack=rack,
                games=games, bb=bb, rb=rb, max_hold=max_hold,
                already_graphed=already_graphed,
                points=points, width=width, height=height, baseline_y=baseline_y,
                auto=auto, source_url=payload.get('source_url'),
                updated_fields=updated_fields)


# ---------------------------------------------------------------------------
# Live browser session (needs pywebview + a display; not covered by unittest)
# ---------------------------------------------------------------------------

READ_DAY_JS = r'''
  const readTargetDay = () => {
    const fromUrl = new URL(location.href).searchParams.get('target_date');
    if (fromUrl) return fromUrl;
    for (const anchor of document.querySelectorAll('a[href*="target_date="]')) {
      try {
        const day = new URL(anchor.href, location.href).searchParams.get('target_date');
        if (day) return day;
      } catch (_) {}
    }
    for (const option of document.querySelectorAll('select option:checked')) {
      const match = (option.textContent || '').match(/(20\d{2})\s*[\/.年-]\s*(\d{1,2})\s*[\/.月-]\s*(\d{1,2})/);
      if (match) return `${match[1]}-${match[2].padStart(2, '0')}-${match[3].padStart(2, '0')}`;
    }
    return null;
  };
'''

TABLE_EXTRACT_BODY = READ_DAY_JS + r'''
  // Two accepted shapes: the full header, and -- confirmed live at
  // saiwaichou, whose list page never shows a 最大持玉 column at all --
  // the same header with that last column dropped. Either way the
  // returned matrix's own header row is padded/kept as-is; parse_table()
  // on the Python side already knows both shapes and fills a missing
  // max_hold in later from the individual rack's graph page instead.
  const headerVariants = [''' + json.dumps(HEADERS) + ''', ''' + json.dumps(HEADERS_NO_MAX_HOLD) + r'''];
  const headers = headerVariants[0];
  // Header cells can also carry a sort-arrow glyph (e.g. "台番号▲") baked
  // into their own textContent, and some pages add a whole extra header
  // row of nothing but those glyphs -- both seen live at saiwaichou but
  // not in the synthetic fixtures used by the unit tests. Comparing on a
  // version with arrows/whitespace stripped, and locating the header by
  // content instead of assuming it is always row 0, tolerates either shape.
  const clean = s => (s || '').replace(/[▲▼△▽⇧⇩]/g, '').replace(/\s+/g, '');
  const wantHeaders = headers.map(clean);
  const cleanedVariants = headerVariants.map(h => h.map(clean));
  const tables = Array.from(document.querySelectorAll('table'));
  for (const table of tables) {
    const trs = Array.from(table.querySelectorAll('tr'));
    if (trs.length < 2) continue;
    const rawRows = trs.map(tr => Array.from(tr.querySelectorAll('th,td')).map(c => c.textContent.trim()));
    let headerIndex = -1;
    let matchedHeaders = null;
    for (let v = 0; v < headerVariants.length; v++) {
      const want = cleanedVariants[v];
      const idx = rawRows.findIndex(row => row.length === want.length && row.every((c, i) => clean(c) === want[i]));
      if (idx !== -1) { headerIndex = idx; matchedHeaders = headerVariants[v]; break; }
    }
    if (headerIndex === -1) continue;
    const dataRows = rawRows.slice(headerIndex + 1).filter(row => row.some(c => clean(c) !== ''));
    const matrix = [matchedHeaders, ...dataRows];
    const anchors = Array.from(table.querySelectorAll('td a'));
    const links = anchors.map(a => a.href);
    if (links.length !== dataRows.length) continue;
    const body = document.body ? document.body.innerText : '';
    const updated = body.split('\n').map(s => s.trim()).find(s => s.startsWith('更新日時')) || '';
    const pageUrl = new URL(location.href);
    const targetDate = readTargetDay();
    let machine = pageUrl.searchParams.get('machine_name') || '';
    for (let i = 0; machine.includes('%') && i < 3; i++) {
      try { machine = decodeURIComponent(machine); } catch (e) { break; }
    }
    machine = machine.replace(/\+/g, ' ').replace(/\s+/g, ' ').trim();
    const store = location.pathname.startsWith('/saiwaichou/') ? 'saiwaichou' :
      location.pathname.startsWith('/nagamachiminami/') ? 'nagamachiminami' : null;
    return JSON.stringify({
      matrix, links, store, machine, target_date: targetDate,
      kind_code: pageUrl.searchParams.get('kind_code'),
      source_url: location.href, updated_display: updated,
    });
  }
  // Nothing matched. Describe what actually is on the page (row/column
  // counts, whether the header text was found at all, how the first
  // column's cells are marked up) instead of a bare "not found" -- without
  // this, diagnosing a real site's markup means guessing blind, since the
  // live DOM here is never covered by the offline unit tests.
  const diagnostics = tables.map((table, i) => {
    const trs = Array.from(table.querySelectorAll('tr'));
    const rawRows = trs.map(tr => Array.from(tr.querySelectorAll('th,td')).map(c => c.textContent.trim()));
    let headerIndex = -1;
    for (const want of cleanedVariants) {
      const idx = rawRows.findIndex(row => row.length === want.length && row.every((c, i2) => clean(c) === want[i2]));
      if (idx !== -1) { headerIndex = idx; break; }
    }
    const sample = rawRows[headerIndex >= 0 ? headerIndex + 1 : 1] || rawRows[0] || [];
    return `表${i}: 行${trs.length} 列${sample.length} 見出し一致=${headerIndex >= 0 ? headerIndex : 'なし'}`
      + ` <a>=${table.querySelectorAll('td a').length} <button>=${table.querySelectorAll('td button').length}`
      + ` 先頭行=${JSON.stringify((rawRows[0] || []).slice(0, 8))}`;
  });
  const detail = diagnostics.length ? diagnostics.join(' / ') : 'ページに<table>が1つもありません。';
  return JSON.stringify({error: '一覧の表を検出できません。台番号を含む一覧ページを表示してください。\n[診断] ' + detail});
'''

GRAPH_EXTRACT_BODY = READ_DAY_JS + r'''
  const kind = new URL(location.href).searchParams.get('kind_code');
  if (kind && kind !== '21') return JSON.stringify({error: '対象は1000円46枚スロットのみです。'});
  const svg = document.querySelector('svg.today');
  if (!svg) return JSON.stringify({error: 'グラフを検出できません。個別台のグラフ画面を表示してください。'});
  const path = svg.querySelector('.path-slump path');
  const zero = svg.querySelector('.back-line-middle line');
  if (!path || !zero) return JSON.stringify({error: 'ゼロ線またはグラフ線を検出できません。'});
  const zeroY = zero.getAttribute('y1');
  if (zeroY === null || !zeroY.trim() || !Number.isFinite(Number(zeroY)))
    return JSON.stringify({error: 'ゼロ線の座標を検出できません。'});
  const d = path.getAttribute('d') || '';
  const nums = (d.match(/-?\d+(?:\.\d+)?/g) || []).map(Number);
  const points = [];
  for (let i = 0; i + 1 < nums.length; i += 2) points.push([nums[i], nums[i + 1]]);
  const box = svg.viewBox && svg.viewBox.baseVal;
  const width = box && box.width ? box.width : svg.getBoundingClientRect().width;
  const height = box && box.height ? box.height : svg.getBoundingClientRect().height;
  const textOf = sel => { const el = svg.querySelector(sel); return el ? el.textContent.trim() : ''; };
  const numOf = sel => { const text = textOf(sel).replace(/,/g, '');
    return /^\d+$/.test(text) ? Number(text) : null; };
  const url = new URL(location.href);
  const rackParam = url.searchParams.get('rack_no');
  let machine = url.searchParams.get('machine_name') || '';
  for (let i = 0; machine.includes('%') && i < 3; i++) {
    try { machine = decodeURIComponent(machine); } catch (e) { break; }
  }
  machine = machine.replace(/\+/g, ' ').replace(/\s+/g, ' ').trim();
  const store = location.pathname.startsWith('/saiwaichou/') ? 'saiwaichou' :
    location.pathname.startsWith('/nagamachiminami/') ? 'nagamachiminami' : null;
  return JSON.stringify({
    points, baseline_y: Number(zero.getAttribute('y1')), width, height,
    games: numOf('.info_soukaiten'), bb: numOf('.info_big'), rb: numOf('.info_reg'),
    max_hold: numOf('.info_max_mochidama'),
    rack: rackParam ? Number(rackParam) : null, target_date: readTargetDay(),
    machine: machine || null, store, source_url: location.href,
  });
'''

OVERLAY_JS = (
    "(() => {\n"
    "  if (window.__databaseOverlayInstalled) return;\n"
    "  window.__databaseOverlayInstalled = true;\n"
    "  const STORE_URLS = " + json.dumps(BROWSER_URLS) + ";\n"
    "  const STORE_LABELS = " + json.dumps(STORE_NAMES) + ";\n"
    # A small draggable card, not a full-width bar -- the site's own per-rack
    # pager ("<279番台 280番台 281番台>") sits near the top of the page, so a
    # bottom-of-screen bar meant a long mouse trip after every "next rack"
    # click. Remembering a drag (in a file on the Python side, so it survives
    # both the page reload that "next rack" causes and closing the browser)
    # keeps the capture buttons next to whatever the user is actually clicking.
    "  const card = document.createElement('div');\n"
    "  card.id = 'database-overlay';\n"
    "  card.style.cssText = 'position:fixed;z-index:2147483647;background:#203044;color:#fff;"
    "padding:8px;display:flex;flex-direction:column;gap:6px;font:13px system-ui;"
    "border-radius:10px;box-shadow:0 4px 14px rgba(0,0,0,.4);width:176px';\n"
    # カードの大きさ。サイトの文字や表に合わせて見やすい大きさに変えられる。
    # 倍率は localStorage に残すので、ページを移動しても同じ大きさのまま。
    # 位置と倍率は、ブラウザを閉じても残るようPython側のファイルに保存する
    # （このブラウザはプライベートモードなので localStorage は閉じると消える）。
    # 開くたびに install_overlay が window.__databaseLayout へ入れて渡す。
    "  const SIZE_MIN = 0.7, SIZE_MAX = 2, SIZE_STEP = 0.15;\n"
    "  const layout = window.__databaseLayout || {};\n"
    "  let sizeScale = 1;\n"
    "  if (layout.scale >= SIZE_MIN && layout.scale <= SIZE_MAX) sizeScale = layout.scale;\n"
    "  const saveLayout = () => {\n"
    "    const rect = card.getBoundingClientRect();\n"
    "    window.__databaseLayout = {left: rect.left, top: rect.top, scale: sizeScale};\n"
    "    try {\n"
    "      window.pywebview.api.save_overlay_layout(JSON.stringify(window.__databaseLayout));\n"
    "    } catch (e) {}\n"
    "  };\n"
    "  const grip = document.createElement('div');\n"
    "  grip.style.cssText = 'cursor:move;font-size:11px;opacity:.75;padding:2px 4px;"
    "user-select:none;display:flex;align-items:center;gap:4px';\n"
    "  const gripLabel = document.createElement('span');\n"
    "  gripLabel.textContent = 'database（ドラッグで移動）';\n"
    "  gripLabel.style.cssText = 'flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';\n"
    "  const sizeButton = (text, title, step) => {\n"
    "    const button = document.createElement('button');\n"
    "    button.textContent = text;\n"
    "    button.title = title;\n"
    "    button.style.cssText = 'border:1px solid #5b6b84;border-radius:5px;background:transparent;"
    "color:#c9d3e3;cursor:pointer;font-size:11px;line-height:1;padding:2px 5px';\n"
    "    button.addEventListener('mousedown', e => e.stopPropagation());\n"
    "    button.onclick = () => applySize(sizeScale + step);\n"
    "    return button;\n"
    "  };\n"
    "  grip.append(gripLabel, sizeButton('－', '小さくする', -SIZE_STEP),\n"
    "    sizeButton('＋', '大きくする', SIZE_STEP));\n"
    "  const currentStore = location.pathname.startsWith('/saiwaichou/') ? 'saiwaichou' :\n"
    "    location.pathname.startsWith('/nagamachiminami/') ? 'nagamachiminami' : null;\n"
    "  const otherStore = currentStore === 'saiwaichou' ? 'nagamachiminami' : 'saiwaichou';\n"
    "  const switchBtn = document.createElement('button');\n"
    "  switchBtn.textContent = STORE_LABELS[otherStore] + 'を開く';\n"
    "  switchBtn.style.cssText = 'padding:6px 10px;border:none;border-radius:6px;background:#3a4a63;"
    "color:#fff;cursor:pointer;font-size:12px;width:100%';\n"
    "  switchBtn.onclick = () => { location.href = STORE_URLS[otherStore]; };\n"
    # A person presses this one button on each page.  It chooses only the
    # matching operation for that displayed page (table, graph, or moving
    # from the machine list to the next needed machine); it never captures
    # data after navigation by itself.
    "  const captureBtn = document.createElement('button');\n"
    "  captureBtn.textContent = 'この画面を取り込む';\n"
    "  const pageIdentity = () => {\n"
    "    const url = new URL(location.href);\n"
    "    let machine = url.searchParams.get('machine_name') || '';\n"
    "    for (let i = 0; machine.includes('%') && i < 3; i++) {\n"
    "      try { machine = decodeURIComponent(machine); } catch (e) { break; }\n"
    "    }\n"
    "    machine = machine.replace(/\\+/g, ' ').replace(/\\s+/g, ' ').trim();\n"
    "    // A machine's list page usually has no target_date in its own URL; the\n"
    "    // rack links inside it (and the date picker) still say which day it is.\n"
    "    let day = url.searchParams.get('target_date');\n"
    "    if (!day) {\n"
    "      day = new URLSearchParams(url.hash.replace(/^#/, '')).get('database_day');\n"
    "    }\n"
    "    if (!day) {\n"
    "      for (const a of document.querySelectorAll('a[href*=\"target_date=\"]')) {\n"
    "        try { day = new URL(a.href).searchParams.get('target_date'); } catch (e) {}\n"
    "        if (day) break;\n"
    "      }\n"
    "    }\n"
    "    if (!day) {\n"
    "      for (const opt of document.querySelectorAll('select option:checked')) {\n"
    "        const m = (opt.textContent || '').match(/(\\d{4})\\/(\\d{2})\\/(\\d{2})/);\n"
    "        if (m) { day = m[1] + '-' + m[2] + '-' + m[3]; break; }\n"
    "      }\n"
    "    }\n"
    "    if (day) {\n"
    "      try { localStorage.setItem('database-active-day-' + currentStore, day); } catch (e) {}\n"
    "    } else if (new URLSearchParams(url.hash.replace(/^#/, '')).get('database_next_machine') === '1') {\n"
    "      try { day = localStorage.getItem('database-active-day-' + currentStore) || ''; } catch (e) {}\n"
    "    }\n"
    "    const rack = url.searchParams.get('rack_no');\n"
    "    return {store: currentStore, day, machine, rack: rack ? Number(rack) : null};\n"
    "  };\n"
    "  const progress = document.createElement('span');\n"
    "  progress.style.cssText = 'font-size:11px;opacity:.85;white-space:normal;word-break:break-word';\n"
    "  const refreshProgress = async () => {\n"
    "    try {\n"
    "      const id = pageIdentity();\n"
    "      const raw = await window.pywebview.api.progress(JSON.stringify({store: id.store, day: id.day}));\n"
    "      progress.textContent = (JSON.parse(raw).text || '');\n"
    "    } catch (e) {}\n"
    "  };\n"
    "  window.__databaseRefreshProgress = refreshProgress;\n"
    "  const markMachines = async () => {\n"
    "    if (!/rack_info_kt/.test(location.pathname)) return;\n"
    "    try {\n"
    "      const id = pageIdentity();\n"
    "      const links = machineLinks();\n"
    "      const names = links.map(item => item.name);\n"
    "      const raw = await window.pywebview.api.machine_status(JSON.stringify({store: id.store, day: id.day, machines: names}));\n"
    "      const data = JSON.parse(raw);\n"
    "      links.forEach((item, i) => {\n"
    "        const a = item.element;\n"
    "        if (!a) return;\n"
    "        const old = a.parentElement && a.parentElement.querySelector('.database-badge[data-for=\"' + i + '\"]');\n"
    "        if (old) old.remove();\n"
    "        const s = data.status[i];\n"
    "        const md = data.day ? (+data.day.slice(5, 7)) + '/' + (+data.day.slice(8, 10)) + ' ' : '';\n"
    "        const badge = document.createElement('span');\n"
    "        badge.className = 'database-badge';\n"
    "        badge.dataset.for = String(i);\n"
    "        let text, bg, fg;\n"
    "        if (s && s.excluded) { text = '対象外'; bg = 'transparent'; fg = '#8a94a6'; }\n"
    "        else if (!s) { text = md + '未取込'; bg = '#e2e2e5'; fg = '#707070'; }\n"
    "        else if (s.done >= s.total) { text = md + '済 ' + s.done + '/' + s.total; bg = '#0d8b74'; fg = '#fff'; }\n"
    "        else { text = md + s.done + '/' + s.total; bg = '#f5a623'; fg = '#1d1d1f'; }\n"
    "        badge.textContent = text;\n"
    "        badge.style.cssText = 'display:inline-block;margin-left:8px;padding:1px 9px;border-radius:980px;font:600 12px system-ui;background:' + bg + ';color:' + fg;\n"
    "        a.insertAdjacentElement('afterend', badge);\n"
    "      });\n"
    "    } catch (e) {}\n"
    "  };\n"
    "  const undoBtn = document.createElement('button');\n"
    "  undoBtn.textContent = '直前の保存を取り消す';\n"
    "  undoBtn.style.cssText = 'padding:4px 8px;border:1px solid #5b6b84;border-radius:6px;background:transparent;color:#c9d3e3;cursor:pointer;font-size:11px;width:100%';\n"
    "  undoBtn.onclick = async () => {\n"
    "    try {\n"
    "      const raw = await window.pywebview.api.undo_last_save();\n"
    "      status.textContent = JSON.parse(raw).message;\n"
    "      refreshProgress();\n"
    "    } catch (e) { status.textContent = String(e); }\n"
    "  };\n"
    "  const status = document.createElement('span');\n"
    "  status.id = 'database-capture-status';\n"
    "  status.style.cssText = 'font-size:11px;opacity:.9;white-space:normal;word-break:break-word';\n"
    "  captureBtn.style.cssText = 'padding:8px 10px;border:none;border-radius:6px;background:#0d8b74;"
    "color:#fff;cursor:pointer;font-size:13px;width:100%';\n"
    # The live list draws its header row ("機種名 台数 通常順 ピックアップ順")
    # with the same tr.teram2-link-block class as the machine rows. Skip it:
    # rows with <th>, and rows without .wrap-machine-name when others have it.
    "  const machineRows = () => {\n"
    "    const rows = Array.from(document.querySelectorAll('tr.teram2-link-block')).filter(row => !row.querySelector('th'));\n"
    "    const named = rows.filter(row => row.querySelector('.wrap-machine-name'));\n"
    "    return named.length ? named : rows;\n"
    "  };\n"
    "  const machineLinks = () => {\n"
    "    const anchors = Array.from(document.querySelectorAll('a[href*=\"machine_name\"]'));\n"
    "    if (anchors.length) return anchors.map(a => {\n"
    "      let name = new URL(a.href, location.origin).searchParams.get('machine_name') || '';\n"
    "      for (let i = 0; name.includes('%') && i < 3; i++) {\n"
    "        try { name = decodeURIComponent(name); } catch (e) { break; }\n"
    "      }\n"
    "      const countMatch = ((a.closest('tr') || a.parentElement || a).innerText || '').match(/(\\d+)\\s*台/);\n"
    "      return {name, url: a.href, count: countMatch ? Number(countMatch[1]) : null, element: a};\n"
    "    });\n"
    "    // The site's current machine list uses click handlers on table rows,\n"
    "    // not links.  Recreate its own destination from the visible name.\n"
    "    const kind = new URL(location.href).searchParams.get('kind_code') || '21';\n"
    "    return machineRows().map(row => {\n"
    "      const element = row.querySelector('.wrap-machine-name') || row;\n"
    "      const name = (element.textContent || '').replace(/\\s+/g, ' ').trim();\n"
    "      const countMatch = (row.innerText || '').match(/(\\d+)\\s*台/);\n"
    "      const encoded = encodeURIComponent(encodeURIComponent(name));\n"
    "      return {name, url: location.origin + '/' + currentStore + '/standlist_slot/?kind_code=' +\n"
    "        encodeURIComponent(kind) + '&machine_name=' + encoded,\n"
    "        count: countMatch ? Number(countMatch[1]) : null, element};\n"
    "    }).filter(item => item.name);\n"
    "  };\n"
    "  const waitForMachineLinks = async () => {\n"
    "    let items = machineLinks();\n"
    "    // The current site fills this list through an XHR after the document\n"
    "    // load event. Do not mistake that short loading interval for a broken\n"
    "    // list or navigate using an empty result.\n"
    "    for (let attempt = 0; !items.length && attempt < 12; attempt++) {\n"
    "      status.textContent = '機種一覧の読み込みを待っています…';\n"
    "      await new Promise(resolve => setTimeout(resolve, 350));\n"
    "      items = machineLinks();\n"
    "    }\n"
    "    return items;\n"
    "  };\n"
    "  let moveBusy = false, moveCommitted = false, moveEpoch = 0, pendingMachineFallback = null;\n"
    "  const moveToNextMachine = async (revision = null) => {\n"
    "    if (moveBusy) return;\n"
    "    moveBusy = true;\n"
    "    const epoch = moveEpoch, source = location.href;\n"
    "    const valid = () => epoch === moveEpoch && source === location.href;\n"
    "    try {\n"
    "    const id = pageIdentity();\n"
    "    status.textContent = '次の機種を探しています…';\n"
    "    const kind_code = new URL(location.href).searchParams.get('kind_code');\n"
    # Send only plain values. Each item also carries its DOM element (for the
    # badges), and on the live React-rendered site that element holds a
    # __reactFiber back-reference -> JSON.stringify throws "circular structure".
    "    const machines = (await waitForMachineLinks()).map(({name, url, count}) => ({name, url, count}));\n"
    "    if (!valid()) return;\n"
    "    const raw = await window.pywebview.api.next_unimported_machine(JSON.stringify({...id, kind_code, machines}));\n"
    "    const data = JSON.parse(raw);\n"
    "    if (!valid()) return;\n"
    "    const finish = () => {\n"
    "    if (!valid() || (revision !== null && (autoCancelled || autoWaitReason()))) return false;\n"
    "    if (data && data.url) {\n"
    "      try { localStorage.setItem('database-last-status', data.message || ''); } catch (e) {}\n"
    "      status.textContent = data.message || '';\n"
    # For a machine's table, press the site's own row instead of opening a URL
    # we reconstruct: the site adds the selected date (target_date) and its own
    # name encoding itself. Our reconstructed URL had no date, and the live
    # site answered it with an empty page ("該当する台情報がありません").
    # This only moves between pages; nothing is captured until the user
    # presses the capture button on the table page.
    "      if (data.machine && (data.reason === 'table' || data.reason === 'need_day')) {\n"
    "        const key = s => String(s || '').normalize('NFKC').replace(/\\+/g, ' ').replace(/\\s+/g, '');\n"
    "        const target = machineLinks().find(item => key(item.name) === key(data.machine));\n"
    "        if (target && target.element) {\n"
    "          const el = target.element;\n"
    "          const clickable = el.tagName === 'A' ? el : (el.closest('tr') || el);\n"
    "          const before = location.href;\n"
    "          moveCommitted = true;\n"
    "          clickable.click();\n"
    "          if (revision !== null) pendingMachineFallback = {before, url: data.url, machine: data.machine, started: Date.now(), epoch};\n"
    "          else setTimeout(() => { if (valid() && location.href === before) status.textContent = data.machine + ' の行を押しても移動しませんでした。一覧の機種名を直接押してください。'; }, 3000);\n"
    "          return true;\n"
    "        }\n"
    "      }\n"
    "      moveCommitted = true;\n"
    "      location.href = data.url;\n"
    "    } else {\n"
    "      status.textContent = (data && data.message) || '未取り込みの機種・グラフはありません。';\n"
    "    }\n"
    "    return true;\n"
    "    };\n"
    "    if (revision === null) { finish(); } else {\n"
    "      window.__databaseFinishMachine = finish;\n"
    "      try { await window.pywebview.api.commit_auto_move(revision); }\n"
    "      finally { window.__databaseFinishMachine = null; }\n"
    "    }\n"
    "    } finally { moveBusy = false; }\n"
    "  };\n"
    "  const moveToNextRack = async () => {\n"
    "    status.textContent = '次の未取り込み台を探しています…';\n"
    "    const raw = await window.pywebview.api.next_ungraphed_rack(JSON.stringify(pageIdentity()));\n"
    "    const data = JSON.parse(raw);\n"
    "    if (data && data.url) {\n"
    "      try { localStorage.setItem('database-last-status', data.message || ''); } catch (e) {}\n"
    "      location.href = data.url;\n"
    "    } else {\n"
    "      status.textContent = (data && data.message) || '店舗・日付を特定できませんでした。機種別一覧か個別台のページで押してください。';\n"
    "    }\n"
    "  };\n"
    "  card.append(grip, switchBtn, captureBtn, status, progress, undoBtn);\n"
    "  document.body.appendChild(card);\n"
    # Carries the "saved" / "残りN台" message across the page navigation that
    # a save (either kind) triggers -- set by the confirm subprocess (via
    # run_session()'s advance-signal watcher) or by nextBtn above, read back
    # here on the page that navigation lands on. localStorage is shared
    # across same-origin navigations, so this needs no extra plumbing.\n"
    "  try {\n"
    "    const lastStatus = localStorage.getItem('database-last-status');\n"
    "    if (lastStatus) {\n"
    "      status.textContent = lastStatus;\n"
    "      localStorage.removeItem('database-last-status');\n"
    "    }\n"
    "  } catch (e) {}\n"
    "  refreshProgress();\n"
    "  markMachines();\n"
    "  setTimeout(markMachines, 1000);\n"
    # 位置はすべて「画面に見えている座標」で扱う。カードは zoom で拡大するため、
    # 見た目の大きさは getBoundingClientRect で測り、CSS の left/top には
    # zoom で割った値を入れる（そうしないと拡大したとき位置がずれる）。
    "  const place = (left, top) => {\n"
    "    const rect = card.getBoundingClientRect();\n"
    "    const maxLeft = Math.max(0, window.innerWidth - rect.width - 4);\n"
    "    const maxTop = Math.max(0, window.innerHeight - rect.height - 4);\n"
    "    card.style.left = Math.min(Math.max(0, left), maxLeft) / sizeScale + 'px';\n"
    "    card.style.top = Math.min(Math.max(0, top), maxTop) / sizeScale + 'px';\n"
    "  };\n"
    # 大きさを変えても、そのときの画面上の位置はできるだけ動かさない。
    "  const applySize = value => {\n"
    "    const rect = card.getBoundingClientRect();\n"
    "    sizeScale = Math.min(SIZE_MAX, Math.max(SIZE_MIN, Math.round(value * 100) / 100));\n"
    "    card.style.zoom = sizeScale;\n"
    "    place(rect.left, rect.top);\n"
    "    saveLayout();\n"
    "  };\n"
    "  card.style.zoom = sizeScale;\n"
    "  if (typeof layout.left === 'number' && typeof layout.top === 'number') {\n"
    "    place(layout.left, layout.top);\n"
    "  } else {\n"
    "    place(window.innerWidth - 196, 12);\n"
    "  }\n"
    "  let dragging = null;\n"
    "  grip.addEventListener('mousedown', e => {\n"
    "    const rect = card.getBoundingClientRect();\n"
    "    dragging = {dx: e.clientX - rect.left, dy: e.clientY - rect.top};\n"
    "    e.preventDefault();\n"
    "  });\n"
    "  window.addEventListener('mousemove', e => {\n"
    "    if (!dragging) return;\n"
    "    place(e.clientX - dragging.dx, e.clientY - dragging.dy);\n"
    "  });\n"
    "  window.addEventListener('mouseup', () => {\n"
    "    if (!dragging) return;\n"
    "    dragging = null;\n"
    "    saveLayout();\n"
    "  });\n"
    "  const extractTable = () => {\n" + TABLE_EXTRACT_BODY + "\n  };\n"
    "  const extractGraph = () => {\n" + GRAPH_EXTRACT_BODY + "\n  };\n"
    "  captureBtn.onclick = async () => {\n"
    "    try {\n"
    "      const id = pageIdentity();\n"
    "      if (id.rack !== null) {\n"
    "        const result = extractGraph();\n"
    "        status.textContent = 'グラフを送信しました。';\n"
    "        window.pywebview.api.submit_graph(result);\n"
    "      } else if (id.machine) {\n"
    "        const result = extractTable();\n"
    "        status.textContent = '表を送信しました。';\n"
    "        window.pywebview.api.submit_table(result);\n"
    "      } else if (/rack_info_kt/.test(location.pathname)) {\n"
    "        await moveToNextMachine();\n"
    "      } else {\n"
    "        status.textContent = '1000円46枚スロット／ハイスロの機種一覧、機種別の表、または個別台のグラフを表示してから押してください。';\n"
    "      }\n"
    "    } catch (e) { status.textContent = String(e); }\n"
    "  };\n"
    + AUTO_CAPTURE_JS + "})();"
)

# 内部ブラウザにYouTubeを表示しない（クリックの邪魔になるため）。Android版
# （web_import_page.dart の _hideYouTubeScript）と同じ内容で、動画本体（iframe・
# embed・object）と、サムネイル＋再生ボタンだけを置く形式を隠す。表・日付の選択・
# 入力欄を含む枠には手を出さない。後から差し込まれるものも MutationObserver で隠す。
HIDE_YOUTUBE_JS = r'''
(() => {
  const ytUrl = /(^|[\s"'(,=])((https?:)?\/\/)?([a-z0-9-]+\.)*(youtube\.com|youtube-nocookie\.com|youtu\.be|ytimg\.com)(\/|$|["')\s])/i;
  const ytName = /youtube|(^|[-_\s])yt([-_\s]|$)/i;
  const FLAG = 'databaseHidden';
  const mentionsYouTube = el => {
    for (const attr of Array.from(el.attributes || [])) {
      if (attr.name === 'class' || attr.name === 'id') {
        if (ytName.test(attr.value)) return true;
      } else if (ytUrl.test(attr.value) || (attr.name.startsWith('data-') && ytName.test(attr.name))) {
        return true;
      }
    }
    return false;
  };
  // 取り込みに使う表や日付の選択を含む枠は、youtube の印があっても隠さない。
  const dataSelector = 'table, select, input, textarea, svg, canvas';
  const holdsData = el => el.matches(dataSelector) || !!el.querySelector(dataSelector);
  // 動画だけを包んでいる枠（再生ボタンや黒い背景を含む）までさかのぼって隠す。
  // 表・日付の選択、他の画像、ある程度の文字を含む枠の手前で止める（最大4段）。
  const hide = el => {
    if (!el || el.closest('[data-database-hidden]') || holdsData(el)) return;
    let target = el;
    for (let depth = 0; depth < 4; depth++) {
      const parent = target.parentElement;
      if (!parent || parent === document.body || parent === document.documentElement) break;
      if (holdsData(parent)) break;
      if ((parent.textContent || '').trim().length > 4) break;
      const otherImage = Array.from(parent.querySelectorAll('img, video, canvas, svg'))
        .some(item => !target.contains(item) && !item.closest('[data-database-hidden]') && !mentionsYouTube(item));
      if (otherImage) break;
      target = parent;
    }
    target.dataset[FLAG] = '1';
    target.style.setProperty('display', 'none', 'important');
  };
  const sweep = () => {
    document.querySelectorAll('iframe, embed, object').forEach(el => {
      const source = el.getAttribute('src') || el.getAttribute('data-src') || el.getAttribute('data') || '';
      if (!ytUrl.test(source) && !mentionsYouTube(el)) return;
      try { el.src = 'about:blank'; } catch (_) {}
      const parent = el.parentElement;
      el.remove();
      if (parent && parent !== document.body && !parent.dataset[FLAG] &&
          (parent.textContent || '').trim().length <= 4 && !holdsData(parent) &&
          !parent.querySelector('img, video, canvas, svg')) {
        hide(parent);
      }
    });
    // サムネイルと再生ボタンだけを置く形式
    document.querySelectorAll('body *:not([data-database-hidden])').forEach(el => {
      if (/^(SCRIPT|STYLE|LINK|META|HTML|BODY|HEAD)$/.test(el.tagName)) return;
      if (el.closest('[data-database-hidden]')) return;
      if (mentionsYouTube(el) && !holdsData(el)) hide(el);
    });
  };
  sweep();
  if (!window.__databaseHideYouTube) {
    let queued = false;
    window.__databaseHideYouTube = new MutationObserver(() => {
      if (queued) return;
      queued = true;
      setTimeout(() => { queued = false; sweep(); }, 200);
    });
    window.__databaseHideYouTube.observe(document.documentElement, {
      childList: true, subtree: true, attributes: true,
      attributeFilter: ['src', 'data-src', 'srcset', 'style', 'class', 'href'],
    });
  }
})()
'''

OVERLAY_JS = OVERLAY_JS + '\n;' + HIDE_YOUTUBE_JS


def _find_next_ungraphed(store, day, machine, location, current_rack=None):
    """Shared by the manual "次の未取り込み台へ" button and the automatic
    advance-after-save path: the already-imported row (if any) for this
    store/day/machine that still has no graph, plus how many remain and how
    many rows exist at all (so a caller can tell "nothing imported yet"
    apart from "already fully graphed" -- both look like "no target" but
    need a different message).
    """
    rows = store.rows(day, machine, location)
    pending = sorted(
        # 大当たり0回の台はグラフを取らないので、次の台にしない。
        (r for r in rows if not graph_done(r)),
        key=lambda r: int(r['rack']))
    if not pending:
        return None, 0, len(rows)
    later = [r for r in pending
             if current_rack is None or int(r['rack']) > int(current_rack)]
    target = later[0] if later else pending[0]
    return target, len(pending), len(rows)


# 取り込みの対象外の機種。次の機種の候補にせず、印は「対象外」にし、表・グラフも保存しない。
# 長町南店はジャグラーシリーズ、幸町店はブラックボードを公開していない。
# （幸町のジャグラー、長町南のスーパーブラックジャック等は対象のまま）
# 沖ドキ（サイトの表記は「沖ドキ」「オキドキ」の両方）は、両店とも利用者の指定で対象外（2026-09-29）。
_OKIDOKI_WORDS = ('沖ドキ', 'オキドキ')
EXCLUDED_MACHINE_WORDS = {'nagamachiminami': ('ジャグラー', *_OKIDOKI_WORDS),
                          'saiwaichou': ('ブラックボード', *_OKIDOKI_WORDS)}
EXCLUDED_MACHINE_NOTES = {'nagamachiminami': '長町南店のジャグラーと沖ドキ',
                          'saiwaichou': '幸町店のブラックボードと沖ドキ'}


def is_list_header(name):
    """機種一覧の見出し行（「機種名 台数 通常順 ピックアップ順」）か。
    実サイトでは見出し行も機種の行と同じ tr.teram2-link-block で描画されており、
    機種として拾うと「次の機種」に選ばれて、押しても移動しない行へ進もうとしていた。"""
    text = ''.join(unicodedata.normalize('NFKC', str(name or '')).split())
    return text.startswith('機種名') and '台数' in text


# 営業日の切り替わり時刻。深夜2時までは前日扱い（9/22の26時＝9/23 1:59 までは9/22）。
BUSINESS_DAY_CUTOFF_HOUR = 2


def today_iso(now=None):
    """「今日」の営業日（yyyy-mm-dd）。深夜2時までは前日の日付を返す。

    サイトの機種一覧ページには日付が無い。そのページの取り込み状況（印・進み具合）は、
    サイトの日付選択の初期値と同じ「今日」で判定する（以前は保存済みの最新日で判定して
    いたため、今日の分を消すと前日の「済」が表示されて紛らわしかった）。
    利用者の認識に合わせ、深夜0時〜2時はまだ前日（例：9/22の24時〜26時）として扱う。
    """
    now = now or datetime.now()
    return (now - timedelta(hours=BUSINESS_DAY_CUTOFF_HOUR)).date().isoformat()


def is_excluded_machine(location, name):
    """取り込みの対象外の機種か。長町南は機種名が半角カナのこともある（例「ｶﾊﾞﾈﾘ」「沖ﾄﾞｷ」）
    ため、NFKCで全角へそろえてから判定する（「ｼﾞｬｸﾞﾗｰ」も「ジャグラー」として扱う）。"""
    words = EXCLUDED_MACHINE_WORDS.get(location, ())
    text = unicodedata.normalize('NFKC', str(name or ''))
    return any(word in text for word in words)


def machine_list_url(location, day):
    """The site's own machine-list page (the same one the table import already
    fetches to cross-check rack counts)."""
    # The fragment is local-only.  The overlay uses it after a completed
    # machine to select the next necessary machine; it does not capture data.
    # The site does not keep target_date in this category-list URL, so retain
    # the already validated saved day in a local-only fragment.
    return (f'https://{HOST}/{location}/rack_info_kt/?kind_code=21'
            f'#database_next_machine=1&database_day={day}')


def _next_step(store, day, machine, location, current_rack=None):
    """What to do after a save / on "次の未取り込み台へ": one place decides.

    kind: 'next' (jump to the next rack without a graph), 'machine_done'
    (everything on this machine is graphed -> back to the machine list),
    'no_link' (next rack known but no saved site link), 'no_rows'.
    """
    target, remaining, total = _find_next_ungraphed(store, day, machine, location, current_rack)
    if total == 0:
        return dict(kind='no_rows', url=None,
                    text='この機種・日付の一覧をまだ取り込んでいません。先に一覧を取り込んでください。')
    if target is None:
        return dict(kind='machine_done', url=machine_list_url(location, day),
                    text='この機種はすべて取り込み済みです。機種一覧へ移動します。')
    rack = int(target['rack'])
    url = target.get('detail_url')
    if not url:
        return dict(kind='no_link', url=None, rack=rack, remaining=remaining,
                    text=f'{rack}番台が次ですが、保存済みの一覧に個別台リンクがありません。'
                         'この機種の一覧を「この表を取り込む」でもう一度取り込むと使えます。')
    return dict(kind='next', url=url, rack=rack, remaining=remaining,
                text=f'次：{rack}番台（残り{remaining}台）')


def _advance_signal_path():
    import os
    import tempfile
    return Path(os.environ.get('DATABASE_ADVANCE_SIGNAL') or
                str(Path(tempfile.gettempdir()) / 'database-browser-advance-signal.json'))


def _write_advance_signal(message, next_url=None):
    """Hand a status message (and optionally a URL to move on to) from the
    confirmation subprocess back to the main browser process -- the two are
    separate OS processes, so a small well-known file is the handoff, the
    same pattern ``_Bridge._spawn`` already uses in the other direction.
    """
    payload = json.dumps(dict(message=message, next_url=next_url), ensure_ascii=False)
    _advance_signal_path().write_text(payload, encoding='utf-8')


def _bring_to_front(window):
    """Force a Tk window to the OS foreground.

    Windows leaves a window opened by a background subprocess behind the
    browser instead of focusing it, which silently breaks both mouse clicks
    (until the user notices and clicks it themselves) and the Enter/Esc
    shortcuts on the confirmation dialog. ``-topmost`` toggled briefly is the
    standard Tk workaround for Windows' focus-stealing prevention.
    """
    try:
        window.lift()
        window.attributes('-topmost', True)
        window.after(200, lambda: window.attributes('-topmost', False))
        window.focus_force()
    except Exception:  # noqa: BLE001 -- best-effort; never block on this.
        pass


# 取り込みブラウザの窓とオーバーレイの配置。最初は利用者が整えた配置
# （2026-09-28 に画面から読み取った値。1920×1080・表示倍率100%）で開き、
# 動かしたり大きさを変えたりしたら、次に開くときもその配置にする。
# 窓の値は pywebview の論理ピクセル（枠を含む外側）、オーバーレイの値は
# ページ内の表示座標と倍率。
DEFAULT_BROWSER_LAYOUT = {
    'window': {'x': 1231, 'y': 481, 'width': 573, 'height': 495},
    'overlay': {'left': 213, 'top': 84, 'scale': 1.6},
}
BROWSER_LAYOUT_FILE = 'browser_layout.json'
_WINDOW_MIN_SIZE = (200, 100)   # pywebview の min_size と同じ
_OVERLAY_SCALE_RANGE = (0.7, 2.0)  # オーバーレイの SIZE_MIN / SIZE_MAX と同じ


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def clean_window_layout(value):
    """A saved window rect, or None when it is missing or unusable.

    A minimized window reports a position like (-32000, -32000); that and
    anything smaller than the window's minimum size is thrown away.
    """
    if not isinstance(value, dict) or not all(_number(value.get(k)) for k in ('x', 'y', 'width', 'height')):
        return None
    x, y, width, height = (int(round(value[k])) for k in ('x', 'y', 'width', 'height'))
    if x <= -10000 or y <= -10000 or width < _WINDOW_MIN_SIZE[0] or height < _WINDOW_MIN_SIZE[1]:
        return None
    return {'x': x, 'y': y, 'width': width, 'height': height}


def clean_overlay_layout(value):
    if not isinstance(value, dict) or not all(_number(value.get(k)) for k in ('left', 'top', 'scale')):
        return None
    low, high = _OVERLAY_SCALE_RANGE
    if not low <= value['scale'] <= high:
        return None
    return {'left': max(0.0, float(value['left'])), 'top': max(0.0, float(value['top'])),
            'scale': float(value['scale'])}


def window_visible_on(window, screen):
    """True if the window's title bar is on the screen enough to grab it.

    ``screen`` is (x, y, width, height) of the whole desktop, or None when
    it is unknown (then the saved position is trusted). Guards against a
    position saved on a monitor that is no longer attached.
    """
    if screen is None:
        return True
    sx, sy, sw, sh = screen
    overlap_w = min(window['x'] + window['width'], sx + sw) - max(window['x'], sx)
    overlap_h = min(window['y'] + 40, sy + sh) - max(window['y'], sy)
    return overlap_w >= 100 and overlap_h >= 30


def _desktop_rect():
    """The whole Windows desktop (all monitors), or None off Windows."""
    try:
        import ctypes
        metrics = ctypes.windll.user32.GetSystemMetrics
        rect = tuple(metrics(i) for i in (76, 77, 78, 79))  # SM_[XY]VIRTUALSCREEN, SM_C[XY]VIRTUALSCREEN
    except Exception:  # noqa: BLE001 - not Windows, or the call is unavailable
        return None
    return rect if rect[2] > 0 and rect[3] > 0 else None


def load_browser_layout(folder, screen=None):
    """The layout to open with: what was saved last time, else the default.

    Each half (window / overlay) falls back to the default on its own, and a
    window that would open off every screen falls back to the plain 1280×900
    centered window the browser used before (``x``/``y`` of None).
    """
    try:
        saved = json.loads((Path(folder) / BROWSER_LAYOUT_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    window = clean_window_layout(saved.get('window')) or dict(DEFAULT_BROWSER_LAYOUT['window'])
    if not window_visible_on(window, screen):
        window = {'x': None, 'y': None, 'width': 1280, 'height': 900}
    overlay = clean_overlay_layout(saved.get('overlay')) or dict(DEFAULT_BROWSER_LAYOUT['overlay'])
    return {'window': window, 'overlay': overlay}


def save_browser_layout(folder, layout):
    """Write the layout atomically. A failure only loses the remembered layout."""
    path = Path(folder) / BROWSER_LAYOUT_FILE
    temporary = path.with_name(path.name + '.tmp')
    try:
        temporary.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
        return True
    except OSError:
        return False


class _Bridge:
    """Exposed to the page as ``window.pywebview.api``.

    Runs on pywebview's own thread(s). It never touches Tkinter itself --
    a Tk toplevel created on a background thread while pywebview's native
    WebView2 loop owns the main thread was found to open but never actually
    become visible/interactive (confirmed on a real machine: the process
    logged "received a 'table' submission." and then hung forever on that
    one dialog, silently swallowing every later click). Each submission is
    instead handed to a brand-new, ordinary process -- the same proven
    Tkinter-as-sole-GUI setup ``app.py`` itself already uses -- so the
    browser stays free to keep accepting the next click immediately.
    """

    def __init__(self, db_path, reports_folder, script_path, layout=None):
        # pywebview recursively inspects public attributes to build its JS API.
        # A public Window reaches WinForms native properties and can deadlock
        # API injection. Keep all internal state out of that traversal.
        self._db_path = str(db_path)
        self._reports_folder = str(reports_folder)
        self._script_path = str(script_path)
        self._window = None  # set once the window exists (for the real URL)
        self._children = []  # review windows still open when the browser closes
        self._submit_lock = threading.Lock()
        self._auto = AutoCapture()
        self._overlay_ready = threading.Event()
        self._auto_display = None
        self._manual_continuation = True
        self._advance_generation = None
        self._auto_session = 0
        self._advance_session = None
        self._advance_url = None
        self._pending_advance = None
        import tempfile
        import uuid
        self._signal_path = Path(tempfile.gettempdir()) / f'database-advance-{uuid.uuid4().hex}.json'
        self._layout_folder = Path(db_path).parent
        self._layout = layout or {'window': dict(DEFAULT_BROWSER_LAYOUT['window']),
                                  'overlay': dict(DEFAULT_BROWSER_LAYOUT['overlay'])}

    def get_auto_capture(self):
        return dict(self._auto.state(), manual_continuation=self._manual_continuation)

    def set_auto_capture(self, enabled, seconds=3.5):
        with self._auto._lock:
            self._auto.configure(enabled, seconds)
            self._auto_session += 1
            self._manual_continuation = False
            return self.get_auto_capture()

    def commit_auto_move(self, revision):
        return self._auto.run_current(revision, lambda: self._window.evaluate_js(
            'window.__databaseFinishMachine && window.__databaseFinishMachine()'))

    def _poll_advance(self):
        """Consume this browser's save result; defer movement behind a challenge."""
        if self._signal_path.exists():
            try:
                payload = json.loads(self._signal_path.read_text(encoding='utf-8'))
                self._signal_path.unlink()
            except (OSError, ValueError):
                return True
            self._pending_advance = (payload, self._advance_generation,
                                     self._advance_session, self._advance_url)
        if self._pending_advance is None:
            return False
        payload, generation, session, source_url = self._pending_advance
        message, url = payload.get('message'), payload.get('next_url')
        if message:
            self._window.evaluate_js("try { localStorage.setItem('database-last-status', " +
                json.dumps(message) + "); } catch (e) {}")
            self._window.evaluate_js('window.__databaseRefreshProgress && window.__databaseRefreshProgress()')
            self._window.evaluate_js("(() => { const s = document.getElementById('database-capture-status'); "
                "if (s) s.textContent = " + json.dumps(message) + '; })()')
            payload.pop('message', None)
        if url and is_allowed_url(url):
            if generation is None:
                self._window.evaluate_js('location.href = ' + json.dumps(url))
            else:
                state = self._auto.state()
                if state['enabled'] and self._auto_session == session:
                    # A reload or a manually resolved challenge changes the
                    # document revision, but must not cancel this save's
                    # continuation when the browser returns to its source.
                    if not self._overlay_ready.is_set():
                        return True
                    current_url = self._window.get_current_url() or ''
                    if current_url.split('#')[0] != (source_url or '').split('#')[0]:
                        waiting = self._window.evaluate_js(
                            'window.__databaseAutoWaitReason && window.__databaseAutoWaitReason()')
                        if isinstance(waiting, dict) and ('確認画面' in waiting.get('error', '') or
                                                         '読み込み' in waiting.get('error', '')):
                            self._auto.pause('ON・確認画面の終了後に次へ進みます', state['revision'])
                            self._render_auto()
                            return True
                        self._pending_advance = None
                        return True
                    moved = self._auto.run_current(state['revision'], lambda: self._window.evaluate_js(
                        'window.__databaseAutoAdvance && window.__databaseAutoAdvance(' + json.dumps(url) + ')'))
                    if not moved:
                        self._auto.pause('ON・確認画面の終了後に次へ進みます', state['revision'])
                        self._render_auto()
                        return True
        self._pending_advance = None
        return True

    def _loading(self):
        self._overlay_ready.clear()
        self._auto.loaded()  # Invalidate extraction from the previous document.

    def _loaded(self):
        self._auto.loaded()
        self._auto_display = None
        self._overlay_ready.set()

    def _auto_tick(self):
        """Python timer works independently of minimized-page JS timers."""
        if not self._overlay_ready.is_set():
            return
        generation = self._auto.due(busy=any(c.poll() is None for c in self._children))
        if generation is not None:
            try:
                current = self._window.get_current_url()
                if not is_allowed_url(current or ''):
                    self._auto.pause('ON・対象店舗のページ待ち', generation)
                else:
                    probe = self._window.evaluate_js('window.__databaseAutoProbe && window.__databaseAutoProbe()')
                    if not isinstance(probe, dict) or probe.get('error'):
                        reason = probe.get('error') if isinstance(probe, dict) else 'ページの準備待ち'
                        self._auto.pause('ON・待機：' + str(reason), generation)
                    elif not same_page_url(probe.get('url'), current) or current != self._window.get_current_url():
                        self._auto.pause('ON・ページ切り替え待ち', generation)
                    elif probe.get('kind') == 'machines':
                        # JS serializes asynchronous selection; admission is checked
                        # again in commit_auto_move after the awaited DB query.
                        self._auto.run_current(generation, lambda: self._window.evaluate_js(
                            'window.__databaseAutoMoveMachine(' + str(generation) + ')'))
                    elif probe.get('kind') in ('table', 'graph'):
                        raw = self._checked(probe['raw'])
                        payload = json.loads(raw) if isinstance(raw, str) else raw
                        if not isinstance(payload, dict) or payload.get('error'):
                            self._auto.pause('ON・保存待機：読み取り内容を確認してください。', generation)
                        else:
                            day = resolve_day(payload)
                            key = (probe['kind'], current.split('#')[0], day,
                                   json.dumps(payload, sort_keys=True, ensure_ascii=False))
                            self._auto.submit(generation, key, lambda: self._spawn(probe['kind'], raw))
                    else:
                        self._auto.pause('ON・対象ページ待ち', generation)
            except Exception as exc:
                # Errors never change the user's ON setting or repeat saves.
                self._auto.pause('ON・待機：' + str(exc), generation)
        self._render_auto()

    def _render_auto(self):
        state = self.get_auto_capture()
        if state != self._auto_display:
            try:
                self._window.evaluate_js('window.__databaseRenderAuto && window.__databaseRenderAuto(' +
                                         json.dumps(state, ensure_ascii=False) + ')')
                self._auto_display = state
            except Exception:
                pass

    def save_overlay_layout(self, raw):
        """Remember where the overlay card is and how big (called on drag / －＋)."""
        try:
            overlay = clean_overlay_layout(json.loads(raw) if isinstance(raw, str) else raw)
        except ValueError:
            overlay = None
        if overlay is None:
            return False
        self._layout['overlay'] = overlay
        return save_browser_layout(self._layout_folder, self._layout)

    def _note_window(self, **values):
        """Record the window's latest position or size (from pywebview events)."""
        window = clean_window_layout({**self._layout['window'], **values})
        if window is not None:
            self._layout['window'] = window

    def _checked(self, raw):
        """Replace the data with an error when it disagrees with the real page."""
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return raw
        if not isinstance(payload, dict) or payload.get('error') or self._window is None:
            return raw
        try:
            current = self._window.get_current_url()
        except Exception:  # noqa: BLE001 - no URL means nothing to check
            return raw
        reason = page_mismatch(current, payload)
        return json.dumps({'error': reason}, ensure_ascii=False) if reason else raw

    def submit_table(self, raw):
        self._spawn('table', self._checked(raw))

    def submit_graph(self, raw):
        self._spawn('graph', self._checked(raw))

    def next_ungraphed_rack(self, raw):
        """Look up which already-imported rack (for this store/day/machine)
        still has no saved graph, and hand back the site's own link to it.

        This only ever returns a URL the user's own earlier list import
        already recorded (``detail_url``, taken verbatim from that table's
        own anchor tag) -- it never guesses or constructs a URL. The click
        that follows it is still the user's, one rack at a time; this just
        saves them re-finding the right link via the site's own rack pager.
        """
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return json.dumps({'url': None})
        store_path = payload.get('store')
        day = payload.get('day')
        machine = payload.get('machine') or None
        current_rack = payload.get('rack')
        if not (store_path and day):
            return json.dumps({'url': None, 'reason': 'unknown_page'})
        db = Store(self._db_path)
        try:
            if not machine and current_rack is not None:
                # An individual rack's own graph page often has no
                # machine_name in its URL at all (only rack_no/target_date) --
                # the same gap build_graph_context() already works around by
                # inheriting the name from that rack's own list row instead.
                existing = db.rows(day, None, store_path)
                match = next((r for r in existing
                              if int(r['rack']) == int(current_rack)), None)
                machine = match['machine'] if match else None
            if not machine:
                return json.dumps({'url': None, 'reason': 'unknown_machine',
                                   'message': '機種名を特定できません。一覧の取り込み後にお試しください。'},
                                  ensure_ascii=False)
            step = _next_step(db, day, machine, store_path, current_rack)
        finally:
            db.close()
        reason = {'next': None, 'machine_done': 'all_done'}.get(step['kind'], step['kind'])
        return json.dumps({'url': step['url'], 'rack': step.get('rack'), 'remaining': step.get('remaining', 0),
                           'reason': reason, 'message': step['text']}, ensure_ascii=False)

    def next_unimported_machine(self, raw):
        """Choose the next item from the displayed machine list.

        A partially imported machine takes priority so its missing graphs are
        completed first.  Otherwise this returns the site's displayed link for
        a never-imported machine or one whose cabinet count changed.  It only
        navigates; the user still presses the capture button for every table
        and graph.
        """
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return json.dumps({'url': None, 'message': '機種一覧を読み取れませんでした。'}, ensure_ascii=False)
        store_path = payload.get('store')
        day = payload.get('day')
        raw_machines = payload.get('machines') or []
        if store_path not in STORE_NAMES:
            return json.dumps({'url': None,
                               'message': '店舗・日付を特定できませんでした。1000円46枚スロット／ハイスロの機種一覧を表示してください。'},
                              ensure_ascii=False)
        # 低貸し（kind_code=10・5）の機種一覧では、次の機種を選ばない。表の保存時にも
        # 21以外は拒否しているが、その前に低貸しの表へ案内してしまっていた。
        page_kind = payload.get('kind_code')
        if page_kind not in (None, '', '21', 21):
            return json.dumps({'url': None, 'reason': 'wrong_kind',
                               'message': '1000円46枚スロット（ハイスロ）の機種一覧で押してください。'
                                          '低貸しの機種は取り込みの対象外です。'},
                              ensure_ascii=False)

        def listed_url(value):
            if not isinstance(value, str) or not is_allowed_url(value):
                return None
            parsed = urlparse(value)
            if not parsed.path.startswith(f'/{store_path}/'):
                return None
            # 旧形式のリンクは種別を持たないことがあるので、無いものは通す。
            # 種別が明示されていて21以外（低貸し）のものだけ除く。
            kind = parse_qs(parsed.query).get('kind_code')
            return value if kind in (None, ['21']) else None

        # 一覧に機種が出ているのに、すべて対象外（長町南のジャグラーなど）なら、
        # 「読み込み中」ではなく「残りなし」と案内する。
        raw_machines = [m for m in raw_machines
                        if not (isinstance(m, dict) and is_list_header(m.get('name')))]
        listed_names = [normalize_machine_name(m.get('name')) for m in raw_machines
                        if isinstance(m, dict) and listed_url(m.get('url'))]
        only_excluded = bool(listed_names) and all(
            is_excluded_machine(store_path, name) for name in listed_names if name)
        all_done_message = json.dumps({
            'url': None, 'reason': 'all_done',
            'message': f'未取り込みの機種・グラフはありません。（{EXCLUDED_MACHINE_NOTES.get(store_path, "データ非公開の機種")}は対象外）'},
            ensure_ascii=False)

        # The category-level list has no date when an import session first
        # opens. Visit one listed table first; it exposes the selected date.
        # A return after completing a machine carries its day in the fragment.
        if not day:
            # 日付を確かめるために開く機種も、今日まだ済んでいない機種を優先する
            # （開いた先でそのまま表を取り込めるように）。
            db = Store(self._db_path)
            try:
                today_progress = machine_progress(db, store_path, today_iso())
            finally:
                db.close()

            def done_today(name):
                done_total = today_progress.get(re.sub(r'\s+', '', name))
                return done_total is not None and done_total[0] >= done_total[1]
            candidates = []
            for raw_machine in raw_machines:
                if not isinstance(raw_machine, dict):
                    continue
                url = listed_url(raw_machine.get('url'))
                name = normalize_machine_name(raw_machine.get('name'))
                if url and name and not is_excluded_machine(store_path, name):
                    candidates.append((url, name))
            candidates.sort(key=lambda item: done_today(item[1]))   # 安定ソート：未済が先
            if candidates:
                url, name = candidates[0]
                return json.dumps({
                    'url': url,
                    'machine': name,
                    'reason': 'need_day',
                    'message': f'{name}の一覧で対象日を確認します。表示後に「この画面を取り込む」を押してください。',
                }, ensure_ascii=False)
            if only_excluded:
                return all_done_message
            return json.dumps({'url': None, 'message': '機種一覧が表示されるのを待ってから、もう一度押してください。（しばらく待っても表示されない場合は、ページを再読み込みしてください）'}, ensure_ascii=False)

        machines = []
        for raw_machine in raw_machines:
            if not isinstance(raw_machine, dict):
                continue
            name = normalize_machine_name(raw_machine.get('name'))
            url = listed_url(raw_machine.get('url'))
            if not name or not url or is_excluded_machine(store_path, name):
                continue
            count = raw_machine.get('count')
            machines.append(dict(name=name, url=url,
                                 count=int(count) if isinstance(count, (int, float)) else None))
        if not machines:
            if only_excluded:
                return all_done_message
            return json.dumps({'url': None, 'message': '機種一覧が表示されるのを待ってから、もう一度押してください。（しばらく待っても表示されない場合は、ページを再読み込みしてください）'}, ensure_ascii=False)

        db = Store(self._db_path)
        try:
            progress = machine_progress(db, store_path, day)
            for machine in machines:
                key = re.sub(r'\s+', '', normalize_machine_name(machine['name']))
                done_total = progress.get(key)
                if done_total is None or done_total[0] >= done_total[1]:
                    continue
                step = _next_step(db, day, machine['name'], store_path)
                if step['kind'] == 'next' and listed_url(step.get('url')):
                    return json.dumps({'url': step['url'], 'reason': 'graph',
                                       'message': f"未取得グラフが残る{machine['name']}へ移動します。{step['text']}"},
                                      ensure_ascii=False)
                # Old rows can lack detail_url.  Re-import this displayed table
                # so it records current per-rack links before resuming graphs.
                return json.dumps({'url': machine['url'], 'machine': machine['name'], 'reason': 'table',
                                   'message': f"{machine['name']}の一覧を更新して、未取得グラフを続けます。"},
                                  ensure_ascii=False)

            for machine in machines:
                key = re.sub(r'\s+', '', normalize_machine_name(machine['name']))
                done_total = progress.get(key)
                # 一覧の台数が保存台数より「多い」ときだけ取り込み直しを案内する。
                # 一覧は今の設置台数なので、減台後に前日分を取り込むと保存台数の方が
                # 多くなる。取り込み直しても台は上書きされるだけで消えないため、
                # 「少ない」を台数変更として扱うと同じ機種へ戻し続けてしまう。
                changed = (done_total is not None and machine['count'] is not None and
                           machine['count'] > done_total[1])
                if done_total is None or changed:
                    message = (f"{machine['name']}は設置台数が変わっています。現在の表を取り込んでください。"
                               if changed else
                               f"{machine['name']}は未取込です。現在の表を取り込んでください。")
                    return json.dumps({'url': machine['url'], 'machine': machine['name'],
                                       'reason': 'table', 'message': message},
                                      ensure_ascii=False)
        finally:
            db.close()
        return json.dumps({'url': None, 'reason': 'all_done',
                           'message': '未取り込みの機種・グラフはありません。'}, ensure_ascii=False)

    def progress(self, raw):
        """"今日 長町南 42/80台・幸町 18/60台" for the overlay's progress line."""
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return json.dumps({'text': ''})
        day, store_path = payload.get('day'), payload.get('store')
        db = Store(self._db_path)
        try:
            guessed = not day and bool(store_path)
            if guessed:
                day = today_iso()
            text = progress_text(db, day) if day else ''
            if guessed and not text:
                text = f'{day}　まだ取り込みがありません'
        finally:
            db.close()
        return json.dumps({'text': text}, ensure_ascii=False)

    def machine_status(self, raw):
        """Saved-vs-listed counts for each machine link on the site's machine-list page."""
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return json.dumps({'status': []})
        store_path, day = payload.get('store'), payload.get('day')
        names = [str(n or '') for n in payload.get('machines') or []]
        if store_path not in STORE_NAMES:
            return json.dumps({'status': [None] * len(names)})
        db = Store(self._db_path)
        try:
            day = day or today_iso()
            progress = machine_progress(db, store_path, day)
        finally:
            db.close()
        status = []
        for name in names:
            if is_excluded_machine(store_path, name):
                status.append({'excluded': True})
                continue
            done_total = progress.get(re.sub(r'\s+', '', normalize_machine_name(name)))
            status.append(None if done_total is None else dict(done=done_total[0], total=done_total[1]))
        return json.dumps({'day': day, 'status': status}, ensure_ascii=False)

    def undo_last_save(self):
        db = Store(self._db_path)
        try:
            label = undo_last_save(db, Path(self._db_path).parent)
        except ValueError as exc:
            return json.dumps({'message': str(exc)}, ensure_ascii=False)
        finally:
            db.close()
        return json.dumps({'message': f'取り消しました：{label}'}, ensure_ascii=False)

    def _spawn(self, kind, raw):
        # The API is called on multiple pywebview threads. Admit only one save
        # process at a time, including a manual click racing an automatic tick.
        with self._auto._lock, self._submit_lock:
            self._children = [c for c in self._children if c.poll() is None]
            if self._children:
                return False
            self._spawn_unlocked(kind, raw)
            return True

    def _spawn_unlocked(self, kind, raw):
        import os
        import subprocess
        import sys
        import tempfile
        import uuid

        payload_path = Path(tempfile.gettempdir()) / f'database-import-{uuid.uuid4().hex}.json'
        payload_path.write_text(raw if isinstance(raw, str) else json.dumps(raw), encoding='utf-8')
        print(f'browser_import: received a {kind!r} submission, opening a review window...',
              flush=True)
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command.append(self._script_path)
        command.extend([f'--confirm-{kind}', str(payload_path), self._db_path, self._reports_folder])
        self._children = [c for c in self._children if c.poll() is None]
        state = self._auto.state()
        self._advance_generation = state['revision'] if state['enabled'] else None
        self._advance_session = self._auto_session if state['enabled'] else None
        self._advance_url = self._window.get_current_url() if state['enabled'] else None
        self._manual_continuation = not state['enabled']
        self._children.append(subprocess.Popen(command, env={**os.environ,
            'DATABASE_ADVANCE_SIGNAL': str(self._signal_path)}))


def _load_payload(payload_path):
    try:
        payload = json.loads(Path(payload_path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return None, f'データの形式が不正です：{exc}'
    if not isinstance(payload, dict):
        return None, 'データの形式が不正です。'
    if payload.get('error'):
        return None, payload['error']
    return payload, None


class _OnDemandRoot:
    """The parent window, built only if something actually has to be shown.

    Creating a Tk root costs ~80ms, and the graph path usually shows nothing
    at all (auto-save, or a successful table import), so paying for it on
    every single rack was the largest remaining part of the wait between
    racks. Error dialogs and the confirmation dialog ask for it through
    ``get()``, which builds and fronts it the first time.
    """

    def __init__(self, tk):
        self._tk = tk
        self._root = None

    def get(self):
        if self._root is None:
            self._root = _stub_root(self._tk)
            _bring_to_front(self._root)
        return self._root


def _stub_root(tk):
    """A parent window for a single dialog that must stay a real window.

    ``root.withdraw()`` (and ``.iconify()``) looked like the right way to
    keep this invisible, but on this Windows/Tk build it silently breaks
    ``Toplevel.transient(root)``: the child is created without error and
    ``wait_window`` blocks on it forever, yet it never actually paints --
    confirmed by reproducing it directly (see the investigation that found
    this). Keeping the root mapped -- just 1x1 and borderless, tucked in the
    corner -- avoids that while staying effectively invisible.
    """
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry('1x1+0+0')
    return root


def _confirm_table(payload_path, db_path, reports_folder):
    """Standalone process: save one table submission, then exit.

    No review step: this reads the site's own HTML table directly (not OCR),
    so there is nothing for a person to correct -- build_table_rows already
    refuses anything it cannot trust (wrong headers, duplicate racks, wrong
    kind_code, ...). The user asked for "take in the table" to just mean
    "saved", matching that a save-then-confirm click was pure friction here.
    """
    import tkinter as tk
    from tkinter import messagebox

    from core import STORE_NAMES, report

    payload, error = _load_payload(payload_path)
    root = _OnDemandRoot(tk)
    if error:
        messagebox.showerror('取り込みできません', error, parent=root.get())
        return
    try:
        rows, day, machine = build_table_rows(payload)
    except (TableExtractionError, ValueError) as exc:
        messagebox.showerror('取り込みできません', str(exc), parent=root.get())
        return
    if is_excluded_machine(payload.get('store'), machine):
        _write_advance_signal(f'{machine}は取り込みの対象外です。保存しませんでした。')
        return
    store = Store(db_path)
    try:
        location = payload['store']
        saved_rows = [dict(store=location, kind_code=21, day=day, machine=machine,
                            rack=r['rack'], bb=r['bb'], rb=r['rb'], games=r['games'],
                            previous_start=r['previous_start'], max_hold=r['max_hold'],
                            source_url=payload.get('source_url'),
                            captured_at=now_stamp(),
                            # "次の未取り込み台へ" follows this link; without it saved rows
                            # can never be jumped to.
                            detail_url=r.get('detail_url'))
                      for r in rows]
        data_dir = Path(db_path).parent
        previous = store.payload_map([
            (r['store'], r['day'], r['machine'], int(r['rack'])) for r in saved_rows
        ])
        store.save(saved_rows)
        remember_for_undo(store, data_dir, f'{machine}の一覧{len(saved_rows)}台', saved_rows,
                          previous=previous)
        # 自動バックアップは保存のたびではなく、内部ブラウザを閉じたときに1回だけ
        # 取る（run_session）。全データの書き出しは記録が増えるほど重くなり、
        # 1台ごとに待たされるようになるため。
        # No confirmation click here on purpose: nothing about "it saved" needs
        # a decision, and this happens once per machine (not once per rack),
        # so the browser's own status line is enough feedback. It also moves
        # straight on to the first rack that still lacks a graph.
        step = _next_step(store, day, machine, location, None)
        head = f'{len(saved_rows)}台を保存しました。'
        no_hit = sum(1 for r in saved_rows if no_hits(r))
        if no_hit:
            head += f'大当たり0回の{no_hit}台はグラフを省略します。'
        if step['kind'] == 'next':
            head += f"最初の未取り込み台へ移動します。{step['text']}"
        else:
            head += step['text']
        warning = duplicate_warning(store, day, location, machine)
        _write_advance_signal(' '.join(part for part in (head, warning) if part), next_url=step['url'])
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        messagebox.showerror('予期しないエラー', f'{exc.__class__.__name__}: {exc}', parent=root.get())
    finally:
        store.close()


def _confirm_graph(payload_path, db_path, reports_folder):
    """Standalone process: review and save one graph submission, then exit."""
    import tkinter as tk
    from tkinter import messagebox

    from core import STORE_NAMES, report

    payload, error = _load_payload(payload_path)
    root = _OnDemandRoot(tk)
    if error:
        messagebox.showerror('取り込みできません', error, parent=root.get())
        return
    store = Store(db_path)
    try:
        try:
            context = build_graph_context(payload, store)
        except (GraphExtractionError, ValueError) as exc:
            messagebox.showerror('取り込みできません', str(exc), parent=root.get())
            return
        if is_excluded_machine(context['store'], context['machine']):
            _write_advance_signal(f"{context['machine']}は取り込みの対象外です。保存しませんでした。")
            return
        curve = render_curve_image(context['points'], context['baseline_y'],
                                    context['width'], context['height'])
        # グラフを読めた時点で保存する。点の手修正・採点確定画面は出さず、
        # 保存後に次の個別台へ進む。線やゼロ線を読めない場合だけ上の例外で止める。
        result = graph_measurement_result(context, curve)
        stats = dict(games=context['games'], bb=context['bb'],
                     rb=context['rb'], max_hold=context['max_hold'])
        row = dict(store=context['store'], kind_code=21, day=context['day'],
                   machine=context['machine'], rack=context['rack'],
                   source_url=context.get('source_url'), graph_measurement=result)
        row.update(stats)
        row['captured_at'] = now_stamp()
        data_dir = Path(db_path).parent
        previous = store.payload_map([
            (row['store'], row['day'], row['machine'], int(row['rack']))
        ])
        store.save([row])
        remember_for_undo(store, data_dir, f"{context['rack']}番台のグラフ", [row],
                          previous=previous)
        # 自動バックアップは内部ブラウザを閉じたときに1回だけ（run_session）。
        # No OK-click confirmation here on purpose -- with dozens of racks to
        # get through, a popup per rack was pure friction for a fact that
        # carries no decision. The next rack's own page loading is the
        # confirmation that this one saved; see the advance-signal watcher
        # in run_session() for how the browser picks this up across processes.
        step = _next_step(store, context['day'], context['machine'], context['store'], context['rack'])
        direction = '上昇' if context['points'][-1][1] < context['baseline_y'] else '下降'
        saved = (f"{context['rack']}番台を保存しました"
                 f"（{context['games']}G・BIG{context['bb']}・REG{context['rb']}・終点{direction}）。")
        parts = [saved, step['text']]
        if step['kind'] == 'machine_done' and day_fully_graphed(store, context['day']):
            # ウィンドウは開かない。案内だけ出す（まとめはメイン画面から開く）。
            parts.append('この日の取り込み済みの台はすべて完了しました。')
        parts.append(duplicate_warning(store, context['day'], context['store'], context['machine'], context['rack']))
        _write_advance_signal(' '.join(part for part in parts if part), next_url=step['url'])
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        messagebox.showerror('予期しないエラー', f'{exc.__class__.__name__}: {exc}', parent=root.get())
    finally:
        store.close()


def run_session(db_path, reports_folder):
    """Open the embedded browser. Table/graph review happens in separate
    processes spawned by :class:`_Bridge`; this also runs one background
    thread that watches for the advance-signal file those processes write
    (see ``_write_advance_signal``), so a confirmed graph's own process can
    still nudge this window on to the next rack without either process
    reaching directly into the other's memory.
    """
    import threading
    import webview

    layout = load_browser_layout(Path(db_path).parent, _desktop_rect())
    bridge = _Bridge(db_path, reports_folder, str(Path(__file__).resolve()), layout=layout)
    placement = layout['window']
    window = webview.create_window('database ブラウザ取り込み', DEFAULT_START,
                                    width=placement['width'], height=placement['height'],
                                    x=placement['x'], y=placement['y'], js_api=bridge)
    bridge._window = window
    # 動かした・大きさを変えた窓の配置を覚えておき、閉じたときに保存する。
    window.events.moved += lambda x, y: bridge._note_window(x=x, y=y)
    window.events.resized += lambda width, height: bridge._note_window(width=width, height=height)
    window.events.before_load += bridge._loading

    def install_overlay():
        try:
            current = window.get_current_url() or ''
        except Exception:
            return
        if current and not current.startswith('data:') and not is_allowed_url(current):
            window.load_url(DEFAULT_START)
            return
        try:
            window.evaluate_js('window.__databaseLayout = ' + json.dumps(bridge._layout['overlay'])
                               + ';\n' + OVERLAY_JS)
            bridge._loaded()
        except Exception:
            pass

    stop = threading.Event()
    window.events.closed += stop.set
    def stop_auto_capture():
        bridge.set_auto_capture(False, bridge.get_auto_capture()['seconds'])
    window.events.closed += stop_auto_capture

    def watch_advance_signal():
        while not stop.wait(0.1 if bridge.get_auto_capture()['enabled'] else 0.35):
            try:
                if not bridge._poll_advance():
                    bridge._auto_tick()
            except Exception as exc:
                state = bridge.get_auto_capture()
                if state['enabled']:
                    bridge._auto.pause('ON・待機：' + str(exc), state['revision'])

    window.events.loaded += install_overlay
    webview.start(func=watch_advance_signal, gui='edgechromium')
    if bridge._layout['window'].get('x') is not None:
        save_browser_layout(Path(db_path).parent, bridge._layout)
    backup_after_session(bridge._children, db_path)


def backup_after_session(children, db_path):
    """Take the automatic backup once, after the browser window has closed.

    A review window that is still open finishes (and saves) first, so the
    backup includes it. A failed backup never raises: it is retried on the
    next close, and the saved records are already safe in SQLite.
    """
    for child in children:
        try:
            child.wait()
        except Exception:  # noqa: BLE001 - a vanished child has nothing to wait for
            pass
    store = Store(db_path)
    try:
        return auto_backup(store, Path(db_path).parent)
    finally:
        store.close()


if __name__ == '__main__':
    import sys

    if getattr(sys, 'frozen', False):
        executable_dir = Path(sys.executable).resolve().parent
        root = next(
            (candidate for candidate in (executable_dir.parent, executable_dir.parent.parent, executable_dir)
             if (candidate / 'data').exists() or (candidate / 'app.py').exists()),
            executable_dir,
        )
    else:
        root = Path(__file__).parent
    args = sys.argv[1:]
    if args and args[0] in ('--confirm-table', '--confirm-graph'):
        payload_arg, db_arg, reports_arg = args[1], Path(args[2]), Path(args[3])
        target = _confirm_table if args[0] == '--confirm-table' else _confirm_graph
        target(payload_arg, db_arg, reports_arg)
    else:
        db_arg = Path(args[0]) if len(args) > 0 else root / 'data' / 'database.sqlite3'
        reports_arg = Path(args[1]) if len(args) > 1 else root / 'reports'
        run_session(db_arg, reports_arg)
