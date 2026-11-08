// Apps Script（tool/viewer_drive_script.gs）の共有カレンダー（2026-10-08、EVENT_CALENDAR.md）を、
// Googleの部品を偽物に置き換えて動かす。合言葉・形式の検査・新しい方が残る足し込み・置き場所。
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await fs.readFile(new URL('./viewer_drive_script.gs', import.meta.url), 'utf8');

function drive(properties = {}, code = source) {
  const files = [];
  const folder = (name) => ({
    name,
    createFile(fileName, text) {
      const file = makeFile(fileName, text, this);
      files.push(file);
      return file;
    },
  });
  const root = folder('root'), shared = folder('database共有');
  let clock = 1000;
  function makeFile(name, text, parent) {
    const file = {
      name, text, parent, trashed: false, updated: clock++,
      isTrashed: () => file.trashed,
      getLastUpdated: () => new Date(file.updated),
      getSize: () => file.text.length,
      getBlob: () => ({getDataAsString: () => file.text}),
      setContent(value) { file.text = value; file.updated = clock++; },
      getParents: () => { let done = false; return {hasNext: () => !done, next: () => { done = true; return file.parent; }}; },
    };
    return file;
  }
  files.push(makeFile('database-viewer.json', '{}', shared), makeFile('pscube-viewer-drive.json', '{}', shared));
  const locks = [];
  const context = {
    DriveApp: {
      getFolderById(id) {
        if (id !== 'validation-folder') throw new Error('folder');
        return {getFilesByName(name) {
          const list = files.filter(f => f.name === name && f.parent === shared);
          let i = 0;
          return {hasNext: () => i < list.length, next: () => list[i++]};
        }};
      },
      getFilesByName(name) {
        const list = files.filter(f => f.name === name);
        let i = 0;
        return {hasNext: () => i < list.length, next: () => list[i++]};
      },
      getRootFolder: () => root,
    },
    LockService: {getScriptLock: () => ({waitLock: () => locks.push('lock'), releaseLock: () => locks.push('release')})},
    PropertiesService: {getScriptProperties: () => ({getProperty: (name) => properties[name] ?? null})},
    ContentService: {
      MimeType: {JSON: 'json'},
      createTextOutput: (body) => ({body, setMimeType() { return this; }}),
    },
    JSON, Date, Object, Array, isNaN,
  };
  vm.createContext(context);
  vm.runInContext(code, context);
  const post = (body) => JSON.parse(context.doPost({postData: {contents: JSON.stringify(body)}}).body);
  const get = (file) => JSON.parse(context.doGet({parameter: {file}}).body);
  return {files, post, get, locks, shared, root};
}

const ev = (day, name, at, extra = {}) => ({store: 'nagamachiminami', day, name, updated_at: at, ...extra});

test('検証候補は設定先だけを読み、表示項目だけ返す', () => {
  const d = drive({PSCUBE_VALIDATION_FOLDER_ID: 'validation-folder'});
  const name = 'validation-candidates.json';
  const doc = {format: 'pscube-validation', version: 1, days: [{
    target: '2026-11-23', input_day: '2026-11-22', saved_at: '2026-11-23T08:59:59+09:00',
    preliminary: 1, input_snapshot: {secret: true},
    machines: [{name: 'ジャグラー', candidates: {
      random_draw: [101], date_two_exploratory: [123], day23: [123], private: [124],
    }}],
  }]};
  d.root.createFile(name, JSON.stringify(doc));
  assert.deepEqual(d.get('pscube-validation').days, []);
  const file = d.shared.createFile(name, JSON.stringify(doc));
  const {days} = d.get('pscube-validation');
  assert.equal(days[0].input_snapshot, undefined);
  assert.deepEqual(days[0].machines[0].candidates, {
    random_draw: [101], date_two_exploratory: [123], day23: [123],
  });
  file.setContent(JSON.stringify({payload: doc}));
  assert.match(d.get('pscube-validation').error, /確認できません/);
  file.setContent(JSON.stringify(doc).replace('08:59:59', '09:00:00'));
  assert.match(d.get('pscube-validation').error, /確認できません/);
  assert.match(drive().get('pscube-validation').error, /未設定/);
});

test('閲覧用ファイルと同じフォルダに作り、新しい方を残して足し込む', () => {
  const d = drive();
  assert.deepEqual(d.get('events').events, [], '無いときは空');
  let r = d.post({file: 'events', events: [
    ev('2026-10-20', '周年', '2026-10-08T03:00:00.000Z'),
    ev('2026-10-21', '半列', '2026-10-08T12:00:00+09:00'),
  ]});
  assert.deepEqual([r.ok, r.changed], [true, 2]);
  const file = d.files.find(f => f.name === 'database-events-shared.json');
  assert.equal(file.parent, d.shared);
  // 古い入力は負け、新しい入力（消した印を含む）は勝つ、同じ時刻なら送られてきた方。
  r = d.post({file: 'events', events: [
    ev('2026-10-20', '古い', '2026-10-08T02:00:00.000Z'),
    ev('2026-10-21', null, '2026-10-08T04:00:00.000Z'),
    ev('2026-10-22', '同時', '2026-10-08T05:00:00.000Z'),
  ]});
  assert.equal(r.changed, 2);
  r = d.post({file: 'events', events: [ev('2026-10-22', '同時2', '2026-10-08T14:00:00+09:00')]});
  const doc = d.get('events');
  assert.equal(doc.format, 'database-events');
  assert.equal(doc.kind, 'meruhen');
  assert.deepEqual(doc.events.map(e => [e.day, e.name]), [['2026-10-20', '周年'], ['2026-10-21', null], ['2026-10-22', '同時2']]);
  assert.deepEqual(d.locks, ['lock', 'release', 'lock', 'release', 'lock', 'release']);
});

test('形式の検査：時刻なし・不正な名前・P’s CUBEの貸玉なしは丸ごと受け付けない', () => {
  const d = drive();
  for (const events of [
    [ev('2026-10-20', '周年', undefined)],
    [ev('2026-10-20', '周年', '2026-10-08 12:00')],
    [ev('2026-10-20', 'x'.repeat(61), '2026-10-08T03:00:00Z')],
    [ev('2026-10-20', '改\n行', '2026-10-08T03:00:00Z')],
    [ev('20261020', '周年', '2026-10-08T03:00:00Z')],
    'not a list',
  ]) {
    assert.match(d.post({file: 'events', events}).error, /形式が不正/);
  }
  assert.match(d.post({file: 'pscube-events', events: [{...ev('2026-10-20', '周年', '2026-10-08T03:00:00Z'), store: 'c740601'}]}).error, /形式が不正/);
  const ok = d.post({file: 'pscube-events', events: [{...ev('2026-10-20', '周年', '2026-10-08T03:00:00Z'), store: 'c740601', rate: '20'}]});
  assert.equal(ok.ok, true);
  assert.equal(d.get('pscube-events').events[0].rate, '20');
  assert.match(d.post({file: '../etc', events: []}).error, /指定できない/);
});

test('今までの閲覧用ファイルの読み出しは残り、許可していない名前は断る', () => {
  const d = drive();
  assert.equal(d.get('').constructor, Object);
  assert.match(JSON.stringify(d.get('nothing')), /指定できない/);
});

// 確定が出た台の印🌈（2026-10-11、RAINBOW.md「iPhoneから付ける」）：閲覧ページで付け外しした🌈を足し込む。
const mark = (rack, on, at, extra = {}) => ({store: 'saiwaichou', day: '2026-10-10', rack, on, updated_at: at, ...extra});

test('🌈：閲覧用ファイルと同じフォルダに作り、台ごとに付け外しした時刻の新しい方を残す', () => {
  const d = drive();
  assert.deepEqual(d.get('rainbow').marks, [], '無いときは空');
  let r = d.post({file: 'rainbow', marks: [mark(660, true, '2026-10-11T12:00:00.000Z'), mark(1201, true, '2026-10-11T12:01:00.000Z')]});
  assert.deepEqual([r.ok, r.changed], [true, 2]);
  const file = d.files.find(f => f.name === 'database-rainbow-shared.json');
  assert.equal(file.parent, d.shared);
  r = d.post({file: 'rainbow', marks: [mark(660, false, '2026-10-11T11:00:00.000Z'), mark(1201, false, '2026-10-11T22:00:00+09:00')]});
  assert.equal(r.changed, 1, '古い付け外しは負ける');
  const doc = d.get('rainbow');
  assert.equal(doc.format, 'database-rainbow');
  assert.deepEqual(doc.marks.map(m => [m.rack, m.on]), [[660, true], [1201, false]]);
  assert.equal(d.post({file: 'rainbow', marks: doc.marks}).changed, 0, '同じものは書き直さない');
  // イベントのファイルは別のまま。
  assert.deepEqual(d.get('events').events, []);
});

test('🌈：形式の検査（時刻なし・台番号・on・店舗）は丸ごと受け付けない', () => {
  const d = drive();
  for (const marks of [
    [mark(660, true, undefined)], [mark(660, 'yes', '2026-10-11T12:00:00Z')], [mark(0, true, '2026-10-11T12:00:00Z')],
    [mark(1.5, true, '2026-10-11T12:00:00Z')], [mark(660, true, '2026-10-11T12:00:00Z', {store: '../x'})],
    [mark(660, true, '2026-10-11T12:00:00Z', {day: '20261010'})], 'not a list',
  ]) {
    assert.match(d.post({file: 'rainbow', marks}).error, /形式が不正/);
  }
  assert.equal(d.files.some(f => f.name === 'database-rainbow-shared.json'), false);
});

// P’s CUBEの当日分（2026-10-26）：合言葉が合うときだけ、同じフォルダの日ごとのファイルに書く。
const pscubeDay = (day, extra = {}) => ({
  format: 'pscube-viewer', version: 1, kind: 'backup', source: 'android', exported_at: '2026-10-26T23:50:00+09:00',
  machines: [{store: 'c740601', rate: '20', machine: '試験'}],
  records: [{store: 'c740601', rate: '20', day, machine: '試験', rack: 101}], ...extra,
});

test('P’s CUBEの当日分は合言葉が合うときだけ書き、同じ日は上書きする', () => {
  const unset = drive();
  assert.match(unset.post({file: 'pscube-day', key: 'x', day: '2026-10-26', backup: pscubeDay('2026-10-26')}).error, /設定されていません/);
  assert.equal(unset.files.some(f => f.name.startsWith('pscube-day-')), false);

  const d = drive({PSCUBE_UPLOAD_KEY: 'あいことば2026'});
  assert.match(d.post({file: 'pscube-day', key: 'ちがう', day: '2026-10-26', backup: pscubeDay('2026-10-26')}).error, /合言葉/);
  assert.match(d.post({file: 'pscube-day', day: '2026-10-26', backup: pscubeDay('2026-10-26')}).error, /合言葉/);
  const ok = (day, backup) => d.post({file: 'pscube-day', key: 'あいことば2026', day, backup});
  // 別の日の記録・形式違い・空・日付の誤りは断る。
  assert.match(ok('2026-10-26', pscubeDay('2026-10-25')).error, /形式/);
  assert.match(ok('2026-10-26', pscubeDay('2026-10-26', {format: 'database-backup'})).error, /形式/);
  assert.match(ok('2026-10-26', pscubeDay('2026-10-26', {records: []})).error, /形式/);
  assert.match(ok('2026-13-40', pscubeDay('2026-13-40')).error, /日付/);
  assert.equal(d.files.some(f => f.name.startsWith('pscube-day-')), false);

  let r = ok('2026-10-26', pscubeDay('2026-10-26'));
  assert.deepEqual([r.ok, r.name, r.records], [true, 'pscube-day-android-2026-10-26.json', 1]);
  const file = d.files.find(f => f.name === 'pscube-day-android-2026-10-26.json');
  assert.equal(file.parent, d.shared);
  r = ok('2026-10-26', pscubeDay('2026-10-26', {exported_at: '2026-10-27T00:30:00+09:00'}));
  assert.equal(r.ok, true);
  assert.equal(d.files.filter(f => f.name === 'pscube-day-android-2026-10-26.json').length, 1, '同じ日は1つのファイル');
  assert.equal(JSON.parse(file.text).exported_at, '2026-10-27T00:30:00+09:00');
  // 台の記録の閲覧用ファイル・ほかのファイルは書き換えない。
  assert.equal(d.files.find(f => f.name === 'pscube-viewer-drive.json').text, '{}');
});

test('Android日別送信は古い版・同時刻で異なる内容を拒み、同じ版の再送は安全',()=>{
  const d=drive({PSCUBE_UPLOAD_KEY:'合成の鍵12345678'});
  const payload=at=>({file:'pscube-day',key:'合成の鍵12345678',day:'2026-10-26',backup:{format:'pscube-viewer',version:1,kind:'backup',source:'android',exported_at:at,machines:[],records:[{day:'2026-10-26',games:3000}]}});
  const newest=payload('2026-10-26T23:00:00+09:00');
  const reply=d.post(newest);assert.equal(reply.ok,true);assert.equal(reply.day,newest.day);assert.equal(reply.exported_at,newest.backup.exported_at);
  assert.equal(d.post(newest).ok,true);
  assert.match(d.post(payload('2026-10-26T22:00:00+09:00')).error,/古い版/);
  const conflict=structuredClone(newest);conflict.backup.records[0].games=1000;
  assert.match(d.post(conflict).error,/同じ版/);
  assert.equal(JSON.parse(d.files.find(f=>f.name==='pscube-day-android-2026-10-26.json').text).records[0].games,3000);
});

// Astraの指摘：要求の上限を保存全体にも使うと、5,001件目の次の送信で全履歴を失う。
for (const name of ['viewer_drive_script.gs', 'viewer_drive_script_readonly.gs']) {
  const code = await fs.readFile(new URL('./' + name, import.meta.url), 'utf8');
  const markAt = rack => ({store:'saiwaichou', day:'2026-10-28', rack, on:true, updated_at:'2026-10-29T00:00:00Z'});
  test(name + ': 5,000件を超える統合・再送でも全件と外した印を保持する', () => {
    const d = drive({}, code);
    assert.equal(d.post({file:'rainbow', marks:Array.from({length:5000}, (_, i) => markAt(i + 1))}).ok, true);
    assert.equal(d.post({file:'rainbow', marks:[markAt(5001)]}).marks, 5001);
    const off = {...markAt(1), on:false, updated_at:'2026-10-29T01:00:00Z'};
    assert.equal(d.post({file:'rainbow', marks:[markAt(5002), off]}).marks, 5002);
    assert.equal(d.post({file:'rainbow', marks:[off]}).changed, 0);
    assert.equal(d.get('rainbow').marks.find(m => m.rack === 1).on, false);
    assert.match(d.post({file:'rainbow', marks:Array.from({length:5001}, (_, i) => markAt(i + 1))}).error, /形式/);
    assert.equal(d.get('rainbow').marks.length, 5002);
  });
  test(name + ': 壊れた既存ファイル・形式違い・不正な1件を上書きせずロックを解放する', () => {
    for (const text of ['{broken', 'null', '{}', JSON.stringify({format:'wrong',version:1,marks:[]}),
      JSON.stringify({format:'database-rainbow',version:2,marks:[]}),
      JSON.stringify({format:'database-rainbow',version:1,marks:[markAt(1), {...markAt(2), on:'yes'}]})]) {
      const d = drive({}, code);d.post({file:'rainbow',marks:[markAt(1)]});
      const file=d.files.find(f=>f.name==='database-rainbow-shared.json');file.text=text;const at=file.updated;
      assert.match(d.post({file:'rainbow',marks:[markAt(3)]}).error,/保存済み/);
      assert.equal(file.text,text);assert.equal(file.updated,at);
      assert.deepEqual(d.locks.slice(-2),['lock','release']);
    }
  });
  test(name + ': 保存総数の上限を超えたら削らず元のファイルを残す', () => {
    // 本番10万件の境界を小さくして同じ分岐を検証する。
    const d=drive({}, code.replace('const RAINBOW_STORED_MAX = 100000;', 'const RAINBOW_STORED_MAX = 2;'));
    d.post({file:'rainbow',marks:[markAt(1),markAt(2)]});
    const file=d.files.find(f=>f.name==='database-rainbow-shared.json');const before=file.text;
    assert.match(d.post({file:'rainbow',marks:[markAt(3)]}).error,/上限/);
    assert.equal(file.text,before);assert.equal(d.get('rainbow').marks.length,2);
  });
}

test('共有イベント：既存ファイルが不正なら変更しない（メルヘン・P’s CUBE）',()=>{
  for(const key of ['events','pscube-events']) {
    const event={store:key==='events'?'saiwaichou':'c740601',day:'2026-10-28',name:'周年',updated_at:'2026-10-29T00:00:00Z',...(key==='events'?{}:{rate:'20'})};
    for(const broken of ['{broken','null',JSON.stringify({format:'database-events',version:1,kind:'wrong',events:[]})]) {
      const d=drive();assert.equal(d.post({file:key,events:[event]}).ok,true);
      const file=d.files.find(f=>f.name===(key==='events'?'database-events-shared.json':'pscube-events-shared.json'));
      file.text=broken;assert.match(d.post({file:key,events:[event]}).error,/保存済み/);assert.equal(file.text,broken);
      assert.deepEqual(d.locks.slice(-2),['lock','release']);
    }
  }
});

test('共有イベント：要求上限を超えて保存済みでも消さずに統合する',()=>{
  const d=drive();
  const events=Array.from({length:5000},(_,i)=>({store:'s'+i,day:'2026-10-28',name:'周年',updated_at:'2026-10-29T00:00:00Z'}));
  assert.equal(d.post({file:'events',events}).events,5000);
  assert.equal(d.post({file:'events',events:[{...events[0],store:'next'}]}).events,5001);
  assert.equal(d.post({file:'events',events:[{...events[0],store:'last'}]}).events,5002);
});


test('両Googleスクリプトは保存保護の対応を診断で返す',async()=>{
  for(const name of ['viewer_drive_script.gs','viewer_drive_script_readonly.gs']) {
    const code=await fs.readFile(new URL('./'+name,import.meta.url),'utf8');
    const d=drive({},code);const doc=d.get('diagnostic');
    assert.equal(doc.format,'database-release');assert.ok(doc.capabilities.includes('rainbow-storage-v2'));
    assert.deepEqual(d.locks,[]);
  }
});
