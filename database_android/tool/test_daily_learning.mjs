import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import {dailyPanel} from '../../share_viewer/daily_learning.mjs';

const fixture=()=>({format:'daily-learning',version:1,status:'比較中',updated_at:'2026-11-11T07:30:00+09:00',
  inputs:{private:'公開しない'},models:{private:'公開しない'},days:[{target:'2026-11-11',input_day:'2026-11-10',
    saved_at:'2026-11-11T07:30:00+09:00',version:'test',groups:[{store:'nagamachiminami',name:'<試験>',active:'current',
      status:'改善未確認',selected:[['nagamachiminami','','<試験>',101]],current:[],learned:[],private:'公開しない'}]}]});
const source=readFileSync(new URL('./daily_learning_projection.js',import.meta.url),'utf8');
const context=vm.createContext({});vm.runInContext(source,context);
test('公開項目だけに限定し締切・形式を検査する',()=>{
  const out=context.projectDailyLearning(fixture());
  assert.ok(!JSON.stringify(out).includes('公開しない'));
  const raw=fixture();raw.days[0].saved_at='2026-11-11T08:00:00+09:00';
  assert.throws(()=>context.projectDailyLearning(raw));
  assert.throws(()=>context.projectDailyLearning({}));
});
test('共有ページの対象日・方式・候補・欠測・文字を検査する',()=>{
  const html=dailyPanel(fixture(),'nagamachiminami','2026-11-11');
  assert.ok(html.includes('従来方式')&&html.includes('101番'));
  assert.ok(html.includes('&lt;試験&gt;')&&!html.includes('<試験>'));
  assert.ok(dailyPanel(fixture(),'saiwaichou','2026-11-11').includes('保存済み候補はありません'));
});
test('両Googleスクリプトの生成物と元コードが一致する',()=>{
  for(const name of ['viewer_drive_script.gs','viewer_drive_script_readonly.gs']) {
    const text=readFileSync(new URL(name,import.meta.url),'utf8');
    assert.ok(text.includes(source.trim()));
    assert.ok(text.includes("if (key === 'daily-learning') return readDailyLearning();"));
  }
});
