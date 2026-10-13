import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {meruhenRecords, indexRecords, varietyWeek, meruhenScore, applyRainbowMarks} from '../../share_viewer/data.mjs';

const fixture = JSON.parse(fs.readFileSync(new URL('../test/fixtures/variety_week.json', import.meta.url), 'utf8'));
const racks = rows => rows.map(x => x.rack);
test('前日まで7日：70点ちょうど、🌈なし、重複、範囲外の🌈、欠損（Flutterと同じ例）', () => {
  const byDay = indexRecords(meruhenRecords(fixture));
  const week = varietyWeek(byDay, 'saiwaichou', '2026-10-13');
  assert.deepEqual([week.days[0],week.days.at(-1)],['2026-10-06','2026-10-12']);
  assert.deepEqual(racks(week.rows),[1101,1102,1103,1104,1105,1106]);
  assert.deepEqual(racks(week.high),[1101,1102]);
  assert.deepEqual(week.high[0].high.map(h => h.score.total),Array(7).fill(70));
  assert.deepEqual(racks(week.noRainbow),[1102,1103,1104,1105]);
  assert.deepEqual(week.rows.map(x => [x.observedDays,x.rainbowDays]),[[7,1],[7,0],[7,0],[7,0],[4,0],[0,0]]);
  assert.deepEqual(racks(week.unknown),[1106]);
  assert.equal(varietyWeek(byDay, 'nagamachiminami', '2026-10-13').rows.length,0);
  assert.equal(varietyWeek(byDay,'saiwaichou','2026-10-12').rows.find(x => x.rack === 1104).rainbowDays,1);
  assert.equal(varietyWeek(byDay,'saiwaichou','2027-01-03').days[0],'2026-12-27');
  applyRainbowMarks(byDay,[{store:'saiwaichou',day:'2026-10-12',rack:1102,on:true,updated_at:'2026-10-13T00:00:00Z'}]);
  assert.ok(!racks(varietyWeek(byDay,'saiwaichou','2026-10-13').noRainbow).includes(1102),'付け外しで直ちに分類を更新');
});

test('共有の採点は既存のPC採点v12と一致（欠損、低稼働、0回、ゼロ線、比較除外、70点境界）', () => {
  const raw = [...fixture.records];
  for(let i=0;i<40;i++) raw.push({store:'saiwaichou',machine:'採点比較',rack:2000+i,
    day:`2026-09-${String(1+i%20).padStart(2,'0')}`,games:[0,500,501,1000,3000,8000,88888888][i%7],
    bb:i%11,rb:i%3,max_hold:i%5===0?null:i*100,
    ...(i%4===0?{}:{graph_measurement:{baseline_y:200,peak_y:100,trough_y:220,end_y:[200,199.5,100,240][i%4]}})});
  const py = process.env.PYTHON || String.raw`C:\Users\keyan\.codex\.chatgpt-projects\g-p-6a9e28549ca0819184c877c6b3b3749e\database\.runtime\Scripts\python.exe`;
  const result=spawnSync(py,['-c','import sys,json; from core import score; rows=json.load(sys.stdin); print(json.dumps([dict(total=score(r,rows)["total"],provisional=score(r,rows)["provisional"]) for r in rows]))'],
    {cwd:fileURLToPath(new URL('../../database/',import.meta.url)),input:JSON.stringify(raw),encoding:'utf8'});
  assert.equal(result.status,0,result.stderr || result.error?.message);
  const expected=JSON.parse(result.stdout), records=meruhenRecords({records:raw});
  records.forEach((r,i)=>assert.deepEqual(meruhenScore(r,records),expected[i],`${r.machine} ${r.day} ${r.rack}`));
  const exact=records.find(r=>r.rack===1102 && r.day==='2026-10-12');
  assert.equal(meruhenScore(exact,records).total,70);
  assert.equal(meruhenScore({...exact,graph:{...exact.graph,end_y:101}},records).total,69.9);
});
