"""4円パチンコの記録を見るページ（PC版、2026-10-12 利用者「記録を見る画面をとても見やすい感じでつくって。回転率わかりそうならだして」）。

data/pachinko.sqlite3（pachinko.py）から reports/pachinko.html を作って開く。ページは1枚で完結（外部の読み込みなし）。
- 店・日付を選び、台の一覧（総回転数・大当り・初当り・初当り確率・最大持玉・当り履歴）を並べ替えて見る。
- 末尾ごとの平均総回転数（末尾0が回されていたかを見る）と、機種ごとの平均。
- 台を押すと、スランプグラフ・当り履歴（初当りまでの回転数と連チャン数）・数字。
- 回転率（1,000円あたりの回転数）は出さない：サイトのグラフは約15分おきの粗い線で、当りで戻った玉の数も
  ページに無い（差玉・1セット最大出玉が空欄）ため、減った玉と戻った玉を分けられない。80番台（10/10）で
  試すと最後の当りのあとだけで約37回転／1,000円と、あり得ない値になった。理由をページに書く。
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import pachinko

REPORT_NAME = 'pachinko.html'
CURVE_LIMIT = 240   # グラフの点はこの数まで間引く（ページを軽くする）


def _int(value):
    try:
        return int(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return None


def _curve(measurement):
    if not isinstance(measurement, dict) or not isinstance(measurement.get('curve'), list):
        return None
    points = [p for p in measurement['curve'] if isinstance(p, list) and len(p) == 2]
    if len(points) < 2:
        return None
    step = max(1, len(points) // CURVE_LIMIT)
    kept = points[::step]
    if kept[-1] != points[-1]:
        kept.append(points[-1])
    return dict(points=kept, baseline_y=measurement.get('baseline_y'))


def report_records(rows):
    """ページに載せる形（ページの文字は載せない）。"""
    result = []
    for r in rows:
        panel = r.get('panel') or {}
        games = r.get('games') if r.get('games') is not None else _int(panel.get('総回転数'))
        hits = r.get('hits') if r.get('hits') is not None else _int(panel.get('大当り'))
        first = _int(panel.get('初当り'))
        history = r.get('hit_history') or None
        if first is None and history:
            first = len(history)
        result.append(dict(
            store=r.get('store'), day=r.get('day'), machine=r.get('machine') or '', rack=int(r['rack']),
            games=games, hits=hits, probability=r.get('probability') or panel.get('大当り確率'),
            first=first, max_hold=r.get('max_hold') if r.get('max_hold') is not None else _int(panel.get('最大持玉')),
            start=_int(panel.get('スタート')), prev_start=_int(panel.get('前日最終スタート')),
            max_chain=_int(panel.get('最大連チャン数')), history=history, graph=_curve(r.get('graph_measurement'))))
    return result


def build_report(slot_db_path, folder):
    """reports/pachinko.html を作り、そのパスを返す。記録が無ければ ValueError。"""
    from core import STORE_NAMES
    path = pachinko.db_path_for(slot_db_path)
    if not path.is_file():
        raise ValueError('パチンコの記録がまだありません。取り込み用ブラウザで4円パチンコの台一覧を取り込んでください。')
    store = pachinko.PachinkoStore(path)
    try:
        records = report_records(store.rows())
    finally:
        store.close()
    if not records:
        raise ValueError('パチンコの記録がまだありません。')
    data = json.dumps(dict(records=records, stores=STORE_NAMES), ensure_ascii=False).replace('</', '<\\/')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / REPORT_NAME
    output.write_text(PAGE.replace('__DATA__', data).replace('__TITLE__', html.escape('パチンコの記録')),
                      encoding='utf-8')
    return output


PAGE = r'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title>
<style>
:root{--ink:#1d1d1f;--bg:#f5f5f7;--card:#fff;--muted:#6e6e73;--line:#d2d2d7;--soft:#ededf0;--blue:#0071e3;
  --blue-soft:#e8f1fc;--amber:#b25e00;--amber-soft:#fff3e0;--green:#0b8a5f;--graph:#0c0c10;--graph-line:#e6e6e6;--zero:#e64646}
@media (prefers-color-scheme:dark){:root{--ink:#f5f5f7;--bg:#111113;--card:#1c1c1f;--muted:#a1a1a6;--line:#38383d;
  --soft:#2a2a2e;--blue:#3a8dff;--blue-soft:#14273d;--amber:#ffb347;--amber-soft:#33240f;--green:#3ecf8e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","Yu Gothic UI",Meiryo,sans-serif}
main{max-width:1080px;margin:auto;padding:28px 16px 48px}
h1{font-size:26px;font-weight:650;margin:0 0 2px} h2{font-size:17px;font-weight:650;margin:28px 0 8px}
.sub{color:var(--muted);margin:0}
.bar{position:sticky;top:0;z-index:5;background:var(--bg);padding:12px 0;margin:8px 0 4px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;border-bottom:1px solid var(--line)}
.seg{display:inline-flex;background:var(--soft);border-radius:10px;padding:3px}
.seg button{border:0;background:none;color:var(--ink);font:inherit;padding:6px 14px;border-radius:8px;cursor:pointer}
.seg button.on{background:var(--card);box-shadow:0 1px 3px rgba(0,0,0,.15);font-weight:600}
.day{display:inline-flex;align-items:center;gap:4px}
.day button{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;width:34px;height:34px;font-size:16px;cursor:pointer}
.day button:disabled{opacity:.35;cursor:default}
select{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 10px;height:34px}
label.small{color:var(--muted);font-size:12px;display:inline-flex;align-items:center;gap:6px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.kpi span{display:block;color:var(--muted);font-size:12px} .kpi b{display:block;font-size:24px;font-weight:650;font-variant-numeric:tabular-nums}
.kpi small{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.digits{display:grid;grid-template-columns:repeat(10,1fr);gap:6px;padding:14px;align-items:end;height:190px}
.digit{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;cursor:pointer}
.digit .col{width:70%;max-width:44px;background:var(--blue-soft);border-radius:6px 6px 0 0;min-height:2px}
.digit.zero .col{background:var(--amber)} .digit.on .col{outline:2px solid var(--blue)}
.digit b{font-size:12px;font-variant-numeric:tabular-nums;margin-bottom:3px} .digit span{font-size:12px;color:var(--muted);margin-top:4px}
.digit.zero span{color:var(--amber);font-weight:700}
table{width:100%;border-collapse:collapse} th{color:var(--muted);font-weight:500;font-size:12px;text-align:right;padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap;cursor:pointer;user-select:none}
th.l,td.l{text-align:left} th.on{color:var(--blue);font-weight:650}
td{padding:11px 12px;border-bottom:1px solid var(--soft);text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.rack{cursor:pointer} tr.rack:hover td{background:var(--soft)} tr.open td{background:var(--blue-soft)}
.rk{font-size:17px;font-weight:650} .tail0{display:inline-block;margin-left:6px;font-size:11px;font-weight:700;color:var(--amber);background:var(--amber-soft);border-radius:999px;padding:1px 8px;vertical-align:2px}
.meter{display:inline-block;width:70px;height:6px;background:var(--soft);border-radius:3px;margin-left:8px;vertical-align:middle;overflow:hidden}
.meter i{display:block;height:100%;background:var(--blue)}
td.none{color:var(--muted)} .m{color:var(--muted);font-size:12px;max-width:220px;overflow:hidden;text-overflow:ellipsis}
.detail td{padding:0;background:var(--card)!important;cursor:default}
.dwrap{padding:16px;display:grid;grid-template-columns:1.3fr 1fr;gap:16px;white-space:normal;text-align:left}
.dwrap h3{font-size:13px;color:var(--muted);font-weight:600;margin:0 0 6px}
.graph{background:var(--graph);border-radius:10px;width:100%;height:auto;display:block}
.nums{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.nums div{background:var(--soft);border-radius:8px;padding:8px 10px} .nums span{display:block;color:var(--muted);font-size:11px} .nums b{font-size:17px;font-variant-numeric:tabular-nums}
.hist{display:flex;align-items:flex-end;gap:4px;height:120px;margin-top:4px}
.hist div{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%;min-width:0}
.hist i{display:block;width:100%;background:var(--green);border-radius:4px 4px 0 0;min-height:2px}
.hist i.chain{background:var(--blue)} .hist b{font-size:11px;font-variant-numeric:tabular-nums} .hist span{font-size:10px;color:var(--muted)}
.legend{font-size:11px;color:var(--muted);margin-top:6px} .legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px;vertical-align:-1px}
.note{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;color:var(--muted);line-height:1.7}
.note b{color:var(--ink)}
.empty{padding:28px;text-align:center;color:var(--muted)}
@media (max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}.dwrap{grid-template-columns:1fr;padding:12px}.hide-s{display:none}.digits{gap:2px;padding:12px 6px}.digit b{font-size:9px}.digit .col{width:80%}.digit .long{display:none}.meter{display:none}th,td{padding:10px 7px}.nums{grid-template-columns:repeat(2,1fr)}.kpi b{font-size:20px}}
.table-wrap{overflow-x:auto}
</style></head><body><main>
<h1>パチンコの記録</h1>
<p class="sub">4円パチンコ。取り込み用ブラウザで取り込んだ台だけが出ます。</p>
<div class="bar">
  <div class="seg" id="stores"></div>
  <div class="day"><button id="prev" title="前の日">‹</button><select id="day"></select><button id="next" title="次の日">›</button></div>
  <label class="small">機種 <select id="machine"></select></label>
</div>
<div class="kpis" id="kpis"></div>
<h2>末尾ごとの平均総回転数</h2>
<p class="sub" style="margin-bottom:8px">棒を押すと、その末尾の台だけを下の一覧に出します（もう一度押すと全部）。末尾0はオレンジ。</p>
<div class="card digits" id="digits"></div>
<h2 id="listTitle">台の一覧</h2>
<div class="card table-wrap"><table><thead id="head"></thead><tbody id="rows"></tbody></table></div>
<h2>回転率について</h2>
<div class="note">回転率（1,000円あたりの回転数）は<b>出していません</b>。サイトのスランプグラフは約15分おきの粗い線で、当りで戻った玉の数もページに出ない（差玉・1セット最大出玉が空欄）ため、通常時に減った玉と当りで戻った玉を分けられないからです。代わりに、回転のよさの手がかりとして<b>総回転数</b>・<b>初当り確率</b>（総回転数÷初当り）・<b>末尾ごとの平均</b>を出しています。</div>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const KEY = 'database-pachinko-view';
let saved = {}; try { saved = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) {}
const state = {store: saved.store, day: null, machine: '', tail: null, sort: saved.sort || 'rack', desc: !!saved.desc, open: null};
const $ = id => document.getElementById(id);
const fmt = n => n == null ? '—' : Number(n).toLocaleString('ja-JP');
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const firstRate = r => r.games != null && r.first ? r.games / r.first : null;
const remember = () => { try { localStorage.setItem(KEY, JSON.stringify({store: state.store, sort: state.sort, desc: state.desc})); } catch (e) {} };
const stores = [...new Set(DATA.records.map(r => r.store))];
if (!stores.includes(state.store)) state.store = stores[0];
const daysOf = s => [...new Set(DATA.records.filter(r => r.store === s).map(r => r.day))].sort();
const shortDay = d => { const [y, m, dd] = d.split('-'); const w = '日月火水木金土'[new Date(+y, m - 1, +dd).getDay()]; return `${+m}/${+dd}（${w}）`; };

function dayRecords() {
  return DATA.records.filter(r => r.store === state.store && r.day === state.day && (!state.machine || r.machine === state.machine));
}

function renderStores() {
  $('stores').innerHTML = stores.map(s => `<button data-s="${s}" class="${s === state.store ? 'on' : ''}">${esc((DATA.stores[s] || s).replace(/^(スーパー)?メルヘンワールド/, ''))}</button>`).join('');
}

function renderDays() {
  const days = daysOf(state.store);
  if (!days.includes(state.day)) state.day = days[days.length - 1];
  $('day').innerHTML = days.map(d => `<option value="${d}" ${d === state.day ? 'selected' : ''}>${shortDay(d)}</option>`).join('');
  const i = days.indexOf(state.day);
  $('prev').disabled = i <= 0; $('next').disabled = i >= days.length - 1;
  const machines = [...new Set(DATA.records.filter(r => r.store === state.store && r.day === state.day).map(r => r.machine))].sort();
  if (state.machine && !machines.includes(state.machine)) state.machine = '';
  $('machine').innerHTML = `<option value="">すべて（${machines.length}機種）</option>` + machines.map(m => `<option ${m === state.machine ? 'selected' : ''}>${esc(m)}</option>`).join('');
}

function avg(list) { const v = list.filter(x => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; }

function renderKpis(rows) {
  const zero = rows.filter(r => r.rack % 10 === 0), rest = rows.filter(r => r.rack % 10 !== 0);
  const az = avg(zero.map(r => r.games)), ar = avg(rest.map(r => r.games));
  const diff = az != null && ar ? Math.round((az / ar - 1) * 100) : null;
  const fr = avg(rows.map(firstRate));
  $('kpis').innerHTML = [
    ['台数', `${rows.length}台`, `${new Set(rows.map(r => r.machine)).size}機種`],
    ['平均総回転数', fmt(avg(rows.map(r => r.games)) && Math.round(avg(rows.map(r => r.games)))), ''],
    ['末尾0の平均総回転数', az == null ? '—' : fmt(Math.round(az)), diff == null ? 'ほかの末尾と比べられません' : `ほかの末尾より ${diff >= 0 ? '+' : ''}${diff}%（${zero.length}台）`],
    ['平均の初当り確率', fr == null ? '—' : `1/${Math.round(fr)}`, '総回転数÷初当り'],
  ].map(([t, v, s]) => `<div class="kpi"><span>${t}</span><b>${v}</b><small>${s}</small></div>`).join('');
}

function renderDigits(rows) {
  const by = Array.from({length: 10}, (_, d) => rows.filter(r => r.rack % 10 === d));
  const avgs = by.map(list => avg(list.map(r => r.games)));
  const max = Math.max(1, ...avgs.filter(v => v != null));
  $('digits').innerHTML = avgs.map((v, d) => `<div class="digit ${d === 0 ? 'zero' : ''} ${state.tail === d ? 'on' : ''}" data-d="${d}" title="末尾${d}：${by[d].length}台">
    <b>${v == null ? '' : fmt(Math.round(v))}</b><div class="col" style="height:${v == null ? 0 : Math.max(2, v / max * 120)}px"></div><span><span class="long">末尾</span>${d}</span></div>`).join('');
}

const COLUMNS = [
  ['rack', '台番号', 'l'], ['machine', '機種', 'l hide-s'], ['games', '総回転数', ''], ['hits', '大当り', ''],
  ['first', '初当り', 'hide-s'], ['firstRate', '初当り確率', ''], ['max_hold', '最大持玉', 'hide-s'], ['history', '当り履歴', 'hide-s'],
];
const sortValue = (r, key) => key === 'firstRate' ? firstRate(r) : key === 'history' ? (r.history ? r.history.length : null) : r[key];

function renderTable(rows) {
  let list = rows.filter(r => state.tail == null || r.rack % 10 === state.tail);
  list.sort((a, b) => {
    const x = sortValue(a, state.sort), y = sortValue(b, state.sort);
    if (x == null && y == null) return a.rack - b.rack;
    if (x == null) return 1; if (y == null) return -1;
    const c = typeof x === 'string' ? x.localeCompare(y, 'ja') : x - y;
    return (state.desc ? -c : c) || a.rack - b.rack;
  });
  $('listTitle').textContent = `台の一覧（${list.length}台${state.tail == null ? '' : `・末尾${state.tail}だけ`}）`;
  $('head').innerHTML = '<tr>' + COLUMNS.map(([k, t, c]) => `<th class="${c} ${k === state.sort ? 'on' : ''}" data-k="${k}">${t}${k === state.sort ? (state.desc ? ' ▼' : ' ▲') : ''}</th>`).join('') + '</tr>';
  const maxGames = Math.max(1, ...list.map(r => r.games || 0));
  $('rows').innerHTML = list.length ? list.map(r => {
    const rate = firstRate(r);
    const key = `${r.rack}`;
    const main = `<tr class="rack ${state.open === key ? 'open' : ''}" data-r="${key}">
      <td class="l"><span class="rk">${r.rack}</span>${r.rack % 10 === 0 ? '<span class="tail0">末尾0</span>' : ''}</td>
      <td class="l m hide-s" title="${esc(r.machine)}">${esc(r.machine)}</td>
      <td>${fmt(r.games)}<span class="meter"><i style="width:${(r.games || 0) / maxGames * 100}%"></i></span></td>
      <td>${fmt(r.hits)}</td><td class="hide-s ${r.first == null ? 'none' : ''}">${fmt(r.first)}</td>
      <td class="${rate == null ? 'none' : ''}">${rate == null ? '—' : `1/${Math.round(rate)}`}</td>
      <td class="hide-s ${r.max_hold == null ? 'none' : ''}">${fmt(r.max_hold)}</td>
      <td class="hide-s ${r.history ? '' : 'none'}">${r.history ? `${r.history.length}回` : '未取り込み'}</td></tr>`;
    return main + (state.open === key ? `<tr class="detail"><td colspan="${COLUMNS.length}">${detail(r)}</td></tr>` : '');
  }).join('') : `<tr><td colspan="${COLUMNS.length}" class="empty">この条件の台はありません。</td></tr>`;
}

function graphSvg(g) {
  if (!g) return '<p class="sub">グラフは未取り込みです（台のページで「この画面を取り込む」）。</p>';
  const xs = g.points.map(p => p[0]), ys = g.points.map(p => p[1]).concat([g.baseline_y]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys) - 8, y1 = Math.max(...ys) + 8;
  const w = 600, h = 240, sx = x => (x - x0) / Math.max(1, x1 - x0) * w, sy = y => (y - y0) / Math.max(1, y1 - y0) * h;
  const path = g.points.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)} ${sy(p[1]).toFixed(1)}`).join(' ');
  return `<svg class="graph" viewBox="0 0 ${w} ${h}" role="img" aria-label="スランプグラフ">
    <line x1="0" x2="${w}" y1="${sy(g.baseline_y)}" y2="${sy(g.baseline_y)}" stroke="var(--zero)" stroke-width="1"/>
    <path d="${path}" fill="none" stroke="var(--graph-line)" stroke-width="2"/></svg>`;
}

function histBars(history) {
  if (!history || !history.length) return '<p class="sub">当り履歴は未取り込みです。</p>';
  const max = Math.max(1, ...history.map(h => h.games));
  return `<div class="hist">${history.map((h, i) => `<div title="${i + 1}回目：${h.games}回転で当り・${h.chain}連">
    <b>${h.games}</b><i class="${h.chain > 1 ? 'chain' : ''}" style="height:${h.games / max * 84}px"></i><span>${h.chain > 1 ? h.chain + '連' : i + 1}</span></div>`).join('')}</div>
    <div class="legend">棒の高さ＝その当りまでの回転数（ページの表示順）<i style="background:var(--green)"></i>単発<i style="background:var(--blue)"></i>連チャン</div>`;
}

function detail(r) {
  const nums = [['総回転数', fmt(r.games)], ['大当り', fmt(r.hits)], ['大当り確率', r.probability || '—'], ['初当り', fmt(r.first)],
    ['最大連チャン数', fmt(r.max_chain)], ['最大持玉', fmt(r.max_hold)], ['スタート', fmt(r.start)], ['前日最終スタート', fmt(r.prev_start)],
    ['初当り確率', firstRate(r) == null ? '—' : `1/${Math.round(firstRate(r))}`]];
  return `<div class="dwrap"><div><h3>${r.rack}番台　${esc(r.machine)}　${shortDay(r.day)}</h3>${graphSvg(r.graph)}
    <h3 style="margin-top:14px">当り履歴</h3>${histBars(r.history)}</div>
    <div><h3>数字</h3><div class="nums">${nums.map(([t, v]) => `<div><span>${t}</span><b>${v}</b></div>`).join('')}</div></div></div>`;
}

function render() {
  renderStores(); renderDays();
  const rows = dayRecords();
  renderKpis(rows); renderDigits(rows); renderTable(rows);
}

$('stores').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; state.store = b.dataset.s; state.day = null; state.tail = null; state.open = null; remember(); render(); });
$('day').addEventListener('change', e => { state.day = e.target.value; state.open = null; render(); });
$('machine').addEventListener('change', e => { state.machine = e.target.value; state.open = null; render(); });
const step = d => { const days = daysOf(state.store); const i = days.indexOf(state.day) + d; if (i >= 0 && i < days.length) { state.day = days[i]; state.open = null; render(); } };
$('prev').addEventListener('click', () => step(-1)); $('next').addEventListener('click', () => step(1));
$('digits').addEventListener('click', e => { const d = e.target.closest('.digit'); if (!d) return; const n = +d.dataset.d; state.tail = state.tail === n ? null : n; state.open = null; render(); });
$('head').addEventListener('click', e => { const th = e.target.closest('th'); if (!th) return; const k = th.dataset.k;
  if (state.sort === k) state.desc = !state.desc; else { state.sort = k; state.desc = k !== 'rack' && k !== 'machine'; } remember(); render(); });
$('rows').addEventListener('click', e => { const tr = e.target.closest('tr.rack'); if (!tr) return; state.open = state.open === tr.dataset.r ? null : tr.dataset.r; render(); });
render();
</script></body></html>
'''
