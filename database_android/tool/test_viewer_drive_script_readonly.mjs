// 閲覧専用の共有用スクリプト（tool/viewer_drive_script_readonly.gs、お試し 2026-10-09）を、Googleの部品を
// 偽物に置き換えて動かす。自分用スクリプトと同じ中身を返し、POSTは断って何も書かないこと。
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const load = (name) => fs.readFile(new URL('./' + name, import.meta.url), 'utf8');

function drive(source) {
  const files = [];
  const writes = [];
  const logs = [];
  let clock = 1000;
  const shared = {name: 'database共有', createFile: (name) => { writes.push(['create', name]); }};
  function makeFile(name, text) {
    const file = {
      name, text, trashed: false, updated: clock++,
      isTrashed: () => file.trashed,
      getLastUpdated: () => new Date(file.updated),
      getSize: () => file.text.length,
      getBlob: () => ({getDataAsString: () => file.text}),
      setContent: () => writes.push(['set', name]),
      getParents: () => { let done = false; return {hasNext: () => !done, next: () => { done = true; return shared; }}; },
    };
    return file;
  }
  files.push(
    makeFile('database-viewer.json', '{"format":"database-backup","records":[1]}'),
    makeFile('pscube-viewer-drive.json', '{"format":"pscube-viewer","records":[2]}'),
    makeFile('database-events-shared.json', '{"format":"database-events","version":1,"kind":"meruhen","events":[{"day":"2026-10-04"}]}'),
  );
  const old = makeFile('database-viewer.json', '{"old":true}');
  old.updated = 1; // 古い同名ファイルは選ばない
  const trashed = makeFile('database-viewer.json', '{"trashed":true}');
  trashed.trashed = true; trashed.updated = 99999;
  files.push(old, trashed);
  const context = {
    DriveApp: {
      getFilesByName(name) {
        const list = files.filter(f => f.name === name);
        let i = 0;
        return {hasNext: () => i < list.length, next: () => list[i++]};
      },
      getRootFolder: () => shared,
    },
    LockService: {getScriptLock: () => ({waitLock() {}, releaseLock() {}})},
    ContentService: {MimeType: {JSON: 'json'}, createTextOutput: (body) => ({body, setMimeType() { return this; }})},
    JSON, Date, Object, Array, isNaN,
    console: {log: (...args) => logs.push(args.join(' '))},
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  const get = (parameter) => context.doGet({parameter}).body;
  const post = (body) => JSON.parse(context.doPost({postData: {contents: JSON.stringify(body)}}).body);
  return {get, post, writes, logs};
}

test('自分用スクリプトと同じ中身を返す（記録・P’s CUBE・共有カレンダー・更新の目印・断る名前）', async () => {
  const mine = drive(await load('viewer_drive_script.gs'));
  const shared = drive(await load('viewer_drive_script_readonly.gs'));
  for (const parameter of [{}, {file: 'pscube'}, {file: 'events'}, {check: '1'}, {file: 'pscube', check: '1'}, {file: '../etc'}]) {
    assert.equal(shared.get(parameter), mine.get(parameter), JSON.stringify(parameter));
  }
  // まだ無い共有カレンダーは空の一覧（時刻だけ違うので形で比べる）。
  const empty = JSON.parse(shared.get({file: 'pscube-events'}));
  assert.deepEqual([empty.format, empty.kind, empty.events], ['database-events', 'pscube', []]);
});

test('イベントの書き込み（POST）は断り、Googleドライブに何も書かない', async () => {
  const shared = drive(await load('viewer_drive_script_readonly.gs'));
  const result = shared.post({file: 'events', events: [{store: 'nagamachiminami', day: '2026-10-20', name: '周年', updated_at: '2026-10-09T03:00:00Z'}]});
  assert.match(result.error, /閲覧専用/);
  assert.equal(result.ok, undefined);
  assert.deepEqual(shared.writes, []);
});

test('書けるのは🌈のファイルだけ（2026-10-11、RAINBOW.md「共有ページから付ける」）', async () => {
  const source = await load('viewer_drive_script_readonly.gs');
  const code = source.replace(/\/\/.*$/gm, '');
  for (const word of ['PropertiesService', 'setTrashed', 'removeFile']) assert.ok(!code.includes(word), word);
  // 書く先の名前は🌈のファイルだけ（setContent・createFile は postRainbow の中にしか無い）。
  const writer = code.slice(code.indexOf('function postRainbow'), code.indexOf('function rainbowDocument'));
  assert.equal(code.split('setContent').length - 1, writer.split('setContent').length - 1);
  assert.equal(code.split('createFile').length - 1, writer.split('createFile').length - 1);
  assert.match(writer, /RAINBOW_FILE\.name/);
});

test('🌈：自分用スクリプトと同じ足し込み・同じ読み出し。形の違う印は断る', async () => {
  const mark = (rack, on, at) => ({store: 'saiwaichou', day: '2026-10-10', rack, on, updated_at: at});
  const results = [];
  for (const name of ['viewer_drive_script.gs', 'viewer_drive_script_readonly.gs']) {
    const d = drive(await load(name));
    const first = d.post({file: 'rainbow', marks: [mark(660, true, '2026-10-11T12:00:00.000Z')]});
    assert.deepEqual([first.ok, first.changed], [true, 1], name);
    assert.ok(d.writes.some(([kind, file]) => kind === 'create' && file === 'database-rainbow-shared.json'), name);
    assert.match(d.post({file: 'rainbow', marks: [mark(0, true, '2026-10-11T12:00:00Z')]}).error, /形式が不正/);
    results.push(JSON.parse(d.get({file: 'rainbow'})).marks);
  }
  assert.deepEqual(results[0], results[1]);
  assert.deepEqual(results[1], [], '偽物のフォルダは作ったファイルを返さない（足し込みの中身は test_viewer_drive_script.mjs で確かめる）');
});

test('アクセスの記録：最初の読み込み（u=付き）だけ「実行数」に書き、呼び名の形が違えば「名前なし」。返す中身は変わらない', async () => {
  const d = drive(await load('viewer_drive_script_readonly.gs'));
  const plain = d.get({});
  assert.equal(d.get({u: 'himawari'}), plain);
  d.get({file: 'pscube', u: 'himawari'});
  d.get({file: 'events'});
  d.get({check: '1', u: 'himawari'});
  d.get({u: '<script>'});
  assert.deepEqual(d.logs, ['閲覧：名前なし', '閲覧：himawari', '閲覧：名前なし']);
  assert.deepEqual(d.writes, []);
});
