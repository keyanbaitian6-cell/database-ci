"""Offline display of saved P's CUBE records, including external supplements.

Read the dedicated SQLite DB in read-only mode. No scoring or synchronization.
"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from core import FLIP7_CSS, FLIP7_FAN, SUMMARY_REPORT_CSS
from pscube_import import is_excluded_machine
import anaslo_net
import site777_net


def net_value(r):
    """(差枚, 要確認か)。本当の差枚、無ければ補完の台の推定差枚（確かでなければ要確認）。どちらも無ければ (None, False)。
    閲覧ページ・共有カレンダーと同じく、推定差枚も合計に入れる（2026-11-06 利用者「全部入れる」）。"""
    if type(r.get('net_medals')) is int:
        return r['net_medals'], False
    e = r.get('net_estimate')
    if ((r.get('source_site') == 'anaslo' and anaslo_net.valid(e))
            or (r.get('source_site') == 'site777' and site777_net.valid(e))):
        return e['value'], not e['sure']
    return None, False


def net_text(r):
    """差枚の欄の文字。本当の差枚があればそれ。無ければ補完の台の推定差枚（「推定」、勝ち負けを言い切れない・
    確かでない台は「※」）。アナスロ（anaslo_net.py）・サイトセブン（site777_net.py、2026-11-07）。"""
    if type(r.get('net_medals')) is int:
        return f"{r['net_medals']:+,}"
    value, needs_check = net_value(r)
    return None if value is None else f"推定 {value:+,}{'※' if needs_check else ''}"


def read_records(path):
    path = Path(path)
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        return [r for row in db.execute('SELECT payload FROM records')
                if not is_excluded_machine((r := json.loads(row[0]))['machine'])]


def has_external_day(path, day):
    return any(r['day'] == day and r.get('source_site') in ('anaslo', 'site777') for r in read_records(path))


def build_report(path, folder, day=None, machine=None):
    records = read_records(path)
    days = sorted({r['day'] for r in records}, reverse=True)
    if not days:
        raise ValueError('P-STATIONのローカル保存データがありません。')
    day = day or days[0]
    if not any(r['day'] == day and (machine is None or r['machine'] == machine) for r in records):
        raise ValueError(f'{day}のP-STATION保存データがありません。')
    compact = []
    for r in records:
        row = {key: r.get(key) for key in ('day', 'machine', 'rate', 'rack', 'games', 'bb', 'rb', 'at_art', 'my')}
        row['net'] = net_text(r)
        row['source'] = {'anaslo': 'アナスロ（補完）', 'site777': 'サイトセブン（補完）'}.get(r.get('source_site'), 'P’s CUBE')
        row['combined'] = ((r.get('source_probabilities') or {}).get('combined') or {}).get('display')
        compact.append(row)
    data = json.dumps({'records': compact, 'day': day, 'machine': machine}, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    text = (PAGE.replace('__STYLE__', SUMMARY_REPORT_CSS + FLIP7_CSS)
            .replace('__FAN__', FLIP7_FAN).replace('__DATA__', data))
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / 'pscube-local.html'
    output.write_text(text, encoding='utf-8')
    return output


PAGE = r'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>database P-STATION 保存データ</title>
<style>__STYLE__
main{max-width:1200px}.filters{display:flex;gap:16px;flex-wrap:wrap;margin:18px 0}
select{font:inherit;padding:8px;border:1px solid var(--hairline);border-radius:6px;max-width:100%}
.card{overflow-x:auto}th{text-align:left;padding:12px 14px;white-space:nowrap;background:#f5f5f7}
</style></head><body><main>
<div class="f7-brand">__FAN__<h1>P-STATION 保存データ</h1></div>
<p class="sub">P-STATION&amp;IIスロット館 ｜ このPCの保存済み記録</p>
<div class="filters"><label>日付 <select id="day"></select></label><label>機種名 <select id="machine"></select></label></div>
<p class="sub" id="count"></p>
<p class="sub">アナスロ補完のMYは不明のため「—」です。補完の台の差枚は、グラフから読んだ推定です（「推定」。※は確かでない・勝ち負けを言い切れない台。サイトセブンは画像の目盛りから読み、見切れなどで読めない台は「—」）。補完データは採点・翌日候補の対象外です。BB・RB・ARTと合成確率は掲載値です。</p>
<div class="card"><table><thead><tr><th>機種名</th><th>貸玉</th><th>台番号</th><th>総回転</th><th>BB</th><th>RB</th><th>ART</th><th>MY</th><th>差枚</th><th>合成確率（掲載）</th><th>出典</th></tr></thead><tbody id="rows"></tbody></table></div>
</main><script type="application/json" id="data">__DATA__</script><script>
'use strict';
const data=JSON.parse(document.getElementById('data').textContent);
const day=document.getElementById('day'),machine=document.getElementById('machine');
function option(select,value,label){const o=document.createElement('option');o.value=value;o.textContent=label;select.append(o);}
for(const d of [...new Set(data.records.map(r=>r.day))].sort().reverse())option(day,d,d);
day.value=data.day;
function machines(preferred=''){
  machine.replaceChildren();option(machine,'','すべての機種');
  for(const m of [...new Set(data.records.filter(r=>r.day===day.value).map(r=>r.machine))].sort())option(machine,m,m);
  if([...machine.options].some(o=>o.value===preferred))machine.value=preferred;
}
function render(){
  const records=data.records.filter(r=>r.day===day.value&&(!machine.value||r.machine===machine.value))
    .sort((a,b)=>a.machine.localeCompare(b.machine,'ja')||Number(a.rate)-Number(b.rate)||a.rack-b.rack);
  const body=document.getElementById('rows');body.replaceChildren();
  for(const r of records){const tr=document.createElement('tr');
    for(const key of ['machine','rate','rack','games','bb','rb','at_art','my','net','combined','source']){
      const td=document.createElement('td');td.textContent=r[key]===null||r[key]===undefined?'—':String(r[key]);
      if(!['machine','combined','source'].includes(key))td.className='num';tr.append(td);
    }body.append(tr);
  }
  document.getElementById('count').textContent=day.value+'：'+records.length+'台 ／ '+new Set(records.map(r=>r.machine)).size+'機種';
}
day.addEventListener('change',()=>{machines(machine.value);render();});machine.addEventListener('change',render);
machines(data.machine||'');render();
</script></body></html>'''
