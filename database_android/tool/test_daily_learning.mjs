import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
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
  // 保存できるのは対象日の前日23:30〜当日08:00（2026-11-11）。Googleスクリプトと共有ページで同じ判定。
  for(const [stamp,ok] of [['2026-11-10T23:30:00+09:00',true],['2026-11-10T23:29:59+09:00',false],['2026-11-11T00:00:00+09:00',true],
      ['2026-11-11T07:59:59+09:00',true],['2026-11-11T23:30:00+09:00',false],['2026-11-09T23:45:00+09:00',false],['2026-11-10T14:30:00Z',true]]) {
    const night=fixture();night.days[0].saved_at=stamp;
    if(ok) assert.equal(context.projectDailyLearning(night).days[0].groups[0].saved_at,stamp);
    else assert.throws(()=>context.projectDailyLearning(night),undefined,stamp);
    if(ok) assert.ok(dailyPanel(night,'nagamachiminami','2026-11-11').includes('101番'),stamp);
    else assert.throws(()=>dailyPanel(night,'nagamachiminami','2026-11-11'),undefined,stamp);
  }
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
    // 日次学習の部分は、履歴・日別読み込みの生成範囲より前に置く（末尾に置くと、ほかの生成が消す。2026-11-11）。
    const at=text.indexOf('// BEGIN DAILY_LEARNING');
    assert.ok(at>0 && at<text.indexOf('// BEGIN EVENT_HISTORY_SHARED') && at<text.indexOf('// BEGIN GENERATED VIEWER PARTS'));
    assert.equal(text.split('// BEGIN DAILY_LEARNING').length,2);
  }
  // 3つの生成スクリプトのどれで作り直しても変わらない（片方が、もう片方の部分を消さない）。
  for(const tool of ['build_daily_learning.mjs','build_event_history_share.mjs'])
    execFileSync(process.execPath,[fileURLToPath(new URL(tool,import.meta.url)),'--check']);
});
test('iPhoneの閲覧ページが日次学習をGoogleへ問い合わせられる（読める一覧に入っている）',async()=>{
  // 2026-11-12：shared_events.mjs の SHARED_FILES に 'daily-learning' が無く、iPhoneでは Google へ問い合わせる前に
  // 「読み込み先が不正です」で止まり、画面は「日次学習を読み込めません」になった。Dart の画面の試験は読み込みを
  // 差し替えるので気づけなかった。閲覧ページ（lib/）が fetchSharedEvents に渡す名前をすべて、ここで実際に通す。
  const {fetchShared,SHARED_FILES}=await import('../web/shared_events.mjs');
  const url='https://script.google.com/macros/s/AKfycbTEST/exec', calls=[];
  const fake=async(u)=>{calls.push(u);return new Response('{"format":"daily-learning"}',{status:200});};
  assert.equal(await fetchShared(url,'daily-learning',fake),'{"format":"daily-learning"}');
  assert.equal(calls[0],url+'?file=daily-learning');
  const lib=new URL('../lib/',import.meta.url);
  const names=new Set();
  for(const name of (await import('node:fs')).readdirSync(lib)) {
    const text=readFileSync(new URL(name,lib),'utf8');
    for(const m of text.matchAll(/fetchSharedEvents\(\s*[\w.]+,\s*'([\w-]+)'\s*\)/g)) names.add(m[1]);
  }
  assert.ok(names.has('daily-learning')&&names.size>=6,[...names].join(','));
  for(const name of names) assert.ok(SHARED_FILES.includes(name),`${name} が SHARED_FILES に無い`);
});
