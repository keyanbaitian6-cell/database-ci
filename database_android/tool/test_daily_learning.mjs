import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
import test from 'node:test';
import {dailyPanel, dailyStale, defaultDailyTarget} from '../../share_viewer/daily_learning.mjs';

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
    if(ok) assert.ok(text(dailyPanel(night,'nagamachiminami','2026-11-11')).includes('101番'),stamp);
    else assert.throws(()=>dailyPanel(night,'nagamachiminami','2026-11-11'),undefined,stamp);
  }
  assert.throws(()=>context.projectDailyLearning({}));
});
const text=html=>html.replace(/<[^>]+>/g,'');
test('共有ページの対象日・方式・候補・欠測・文字を検査する',()=>{
  const html=dailyPanel(fixture(),'nagamachiminami','2026-11-11');
  assert.ok(text(html).includes('採用中 従来方式')&&text(html).includes('101番'));
  assert.ok(html.includes('&lt;試験&gt;')&&!html.includes('<試験>'));
  assert.ok(dailyPanel(fixture(),'saiwaichou','2026-11-11').includes('保存済み候補はありません'));
});
// 2026-11-14 利用者「各台番号をタップした際に当日のデータへ飛ぶように」：台番号はサイトのその台・対象日のページを別タブで開く。
test('台番号はサイトのその台・対象日のページへのリンク',async()=>{
  const {dailyRackUrl}=await import('../../share_viewer/daily_learning.mjs');
  const now=Date.parse('2026-11-14T10:00:00+09:00');
  assert.equal(dailyRackUrl('nagamachiminami',1162,'2026-11-14',now),'https://meruhenworld.pt.teramoba2.com/nagamachiminami/standgraph/?rack_no=1162&target_date=2026-11-14');
  assert.equal(dailyRackUrl('saiwaichou','710','2026-11-13',now),'https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph/?rack_no=710&target_date=2026-11-13');
  // P’s CUBE：過去の日は#に履歴の日付、今日・翌日は#なし（本日のタブ）。日本時間で決める（UTCではまだ前日の時刻）。
  assert.equal(dailyRackUrl('pscube:c740601:20',1526,'2026-11-13',now),'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=1526#20261113');
  assert.equal(dailyRackUrl('pscube:c740601:20',1526,'2026-11-14',now),'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=1526');
  assert.equal(dailyRackUrl('pscube:c740601:20',1526,'2026-11-14',Date.parse('2026-11-14T00:10:00+09:00')).includes('#'),false);
  assert.equal(dailyRackUrl('pscube:c740601:20',1526,'2026-11-15',now).includes('#'),false);
  for(const [store,rack,day] of [['unknown',1,'2026-11-14'],['saiwaichou',0,'2026-11-14'],['saiwaichou','1"x','2026-11-14'],['saiwaichou',1.5,'2026-11-14'],['saiwaichou',1,'11/14']])
    assert.equal(dailyRackUrl(store,rack,day,now),null,`${store} ${rack} ${day}`);
  const html=dailyPanel(fixture(),'nagamachiminami','2026-11-11',now);
  // 四角全体を押せるよう、リンクのある台は li の余白をリンク側へ移す（2026-11-14 利用者「おしやすいように」）。
  assert.ok(html.includes('<li class="daily-rack-linked"><a class="daily-rack-link" href="https://meruhenworld.pt.teramoba2.com/nagamachiminami/standgraph/?rack_no=101&amp;target_date=2026-11-11" target="_blank" rel="noopener noreferrer"'));
  assert.ok(text(html).includes('101番'));
  // 知らない店舗の候補はリンクにせず、台番号だけ出す。
  const other=fixture();other.days[0].groups[0].store='other';other.days[0].groups[0].selected=[['other','','<試験>',5]];
  const plain=dailyPanel(other,'other','2026-11-11',now);
  assert.ok(text(plain).includes('5番')&&!plain.includes('daily-rack-link'));
});
// 2026-11-12：4画面で同じ順・意味にそろえた表示。保存済みの台と順番をそのまま出し、候補数は表示中の候補から数える。
const many=()=>({format:'daily-learning',version:1,updated_at:'2026-11-12T00:30:00+09:00',
  status:'長町南：11/12の事前予測は保存済みです／幸町：処理失敗（原本DBを読めません）。従来方式を使用してください／P-STATION：取り込み待ち：P-STATIONの確定前データが残っています／同期先未設定または利用不可',
  days:[{target:'2026-11-12',input_day:'2026-11-11',saved_at:'2026-11-12T00:02:00+09:00',groups:[
    {store:'nagamachiminami',name:'L MHRｻﾝﾌﾞﾚｲｸXA',active:'learned',status:'改善を確認して採用中',saved_at:'2026-11-12T00:02:00+09:00',
      selected:[['nagamachiminami','','L MHRｻﾝﾌﾞﾚｲｸXA',1162],['nagamachiminami','','L MHRｻﾝﾌﾞﾚｲｸXA',1157]]},
    {store:'nagamachiminami',name:'とても長い機種名の表示を確かめるための試験機・スーパーロングネームエディション',active:'current',status:'学習済み・将来成績を比較中',
      selected:[['nagamachiminami','','とても長い機種名の表示を確かめるための試験機・スーパーロングネームエディション',7]]},
    {store:'nagamachiminami',name:'バラエティ',active:'current',status:'学習データ不足・従来方式',
      selected:[['nagamachiminami','','機種A',301],['nagamachiminami','','機種B',305]]},
    {store:'saiwaichou',name:'試験機',active:'current',status:'x',selected:[['saiwaichou','','試験機',1]]}]}]});
test('候補数・台の順番・採用方式・注意の振り分けが4画面の取り決めどおり',async()=>{
  const {dailyView,dailyStatusParts,dailyDateLabel,dailyTime}=await import('../../share_viewer/daily_learning.mjs');
  const now=Date.parse('2026-11-12T07:00:00+09:00');
  const v=dailyView(many(),'nagamachiminami','2026-11-12',now);
  assert.equal(v.count,5);
  assert.equal(v.scope,'2機種とバラエティ');
  assert.deepEqual(v.groups.map(g=>g.racks.map(r=>r.rack)),[[1162,1157],[7],[301,305]]);   // 保存した順のまま
  assert.deepEqual(v.groups[2].racks.map(r=>r.machine),['機種A','機種B']);                     // バラエティだけ台ごとの機種名
  assert.equal(v.groups[0].racks[0].machine,null);
  assert.deepEqual(v.groups.map(g=>g.learned),[true,false,false]);
  assert.deepEqual(v.alerts,['同期先未設定または利用不可']);                                      // ほかの店の失敗は、この店の注意にしない
  assert.deepEqual(dailyStatusParts(many().status,'saiwaichou').mine,['処理失敗（原本DBを読めません）。従来方式を使用してください']);
  assert.ok(dailyView(many(),'saiwaichou','2026-11-12',now).alerts[0].startsWith('処理失敗'));
  const html=dailyPanel(many(),'nagamachiminami','2026-11-12',now,['nagamachiminami','saiwaichou']);
  const plain=text(html);
  assert.ok(plain.includes('5台')&&plain.includes('採用中 日次学習版')&&plain.includes('採用中 従来方式'));
  assert.ok(plain.includes('L MHRサンブレイクXA'),'半角カナは全角にそろえる');
  assert.ok(!plain.includes('ｻﾝﾌﾞﾚｲｸ'));
  assert.ok(html.indexOf('data-learning-store')<html.indexOf('daily-alerts')&&html.indexOf('daily-alerts')<html.indexOf('daily-summary')
    &&html.indexOf('daily-summary')<html.indexOf('daily-group')&&html.lastIndexOf('daily-group')<html.indexOf('処理状況・日次学習について'));
  assert.ok(!html.includes('P-STATION</option>'),'共有ページで見られない店舗は選べない');
  assert.ok(/<details class="more daily-more"><summary>採用方式の説明・保存時刻/.test(html));
  assert.ok(!/<details[^>]*open/.test(html),'説明は閉じた状態');
  assert.ok(!/class="data-warning[^"]*"[^>]*>[^]*<details/.test(html.slice(0,html.indexOf('daily-summary'))),'注意は折りたたまない');
  assert.equal(dailyDateLabel('2026-11-12'),'11月12日（木）');
  assert.equal(dailyTime('2026-11-11T15:02:00Z'),'11月12日 0:02');
  // 過去日・未更新・候補なし
  const later=Date.parse('2026-11-14T09:00:00+09:00');
  const old=dailyView(many(),'nagamachiminami','2026-11-12',later).alerts.join('');
  assert.ok(old.includes('過去の対象日')&&old.includes('11月14日（土）の分の処理結果は届いていません'));
  const none=dailyView(many(),'pscube:c740601:20','2026-11-12',now);
  assert.equal(none.count,0);
  assert.ok(none.alerts.some(a=>a.includes('取り込み待ち'))&&none.alerts.some(a=>a.includes('保存済み候補はありません')));
  assert.ok(text(dailyPanel(many(),'pscube:c740601:20','2026-11-12',now)).includes('候補なし'));
});
test('最初に開く対象日は23:30から翌日、古い処理結果には注意を出す（2026-11-12）',()=>{
  const at=s=>Date.parse(s);
  assert.equal(defaultDailyTarget(at('2026-11-11T23:29:59+09:00')),'2026-11-11');
  assert.equal(defaultDailyTarget(at('2026-11-11T23:30:00+09:00')),'2026-11-12');
  assert.equal(defaultDailyTarget(at('2026-11-12T07:59:00+09:00')),'2026-11-12');
  assert.equal(defaultDailyTarget(at('2026-12-31T23:45:00+09:00')),'2027-01-01');
  const doc=fixture();
  assert.ok(dailyPanel(doc,'nagamachiminami','2026-11-11',at('2026-11-20T09:00:00+09:00')).includes('11月20日（金）の分の処理結果は届いていません'));
  assert.ok(!dailyPanel(doc,'nagamachiminami','2026-11-11',Date.parse(doc.updated_at)).includes('処理結果は届いていません'));
  // 2026-11-12：前の晩の23:30台に保存した候補に、0時を過ぎると「本日の処理結果は届いていません」と出ていた。
  // 最終処理の「日付」ではなく、最初に開く対象日の保存時間帯（その前日の23:30から）に入ってから届いたかで決める。
  const saved='2026-11-12T23:40:00+09:00';
  for(const now of ['2026-11-12T23:45:00+09:00','2026-11-13T00:10:00+09:00','2026-11-13T07:00:00+09:00','2026-11-13T15:00:00+09:00','2026-11-13T23:29:00+09:00'])
    assert.equal(dailyStale(saved,at(now)),false,now);
  assert.equal(dailyStale(saved,at('2026-11-13T23:30:00+09:00')),true);
  assert.equal(dailyStale('2026-11-12T08:10:00+09:00',at('2026-11-13T06:00:00+09:00')),true);
  assert.equal(dailyStale('2026-11-12T23:29:59+09:00',at('2026-11-12T23:45:00+09:00')),true);
  assert.equal(dailyStale('2026-11-12T14:40:00Z',at('2026-11-13T06:00:00+09:00')),false);
  for(const broken of ['',null,undefined,'x']) assert.equal(dailyStale(broken,at('2026-11-13T06:00:00+09:00')),true);
  const night=fixture();night.updated_at=saved;night.days[0].target='2026-11-13';night.days[0].saved_at=saved;
  assert.ok(!dailyPanel(night,'nagamachiminami','2026-11-13',at('2026-11-13T06:00:00+09:00')).includes('届いていません'));
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
