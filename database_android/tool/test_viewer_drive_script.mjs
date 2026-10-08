// Apps Script（tool/viewer_drive_script.gs）の共有カレンダー（2026-10-08、EVENT_CALENDAR.md）を、
// Googleの部品を偽物に置き換えて動かす。合言葉・形式の検査・新しい方が残る足し込み・置き場所。
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await fs.readFile(new URL('./viewer_drive_script.gs', import.meta.url), 'utf8');

function drive() {
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
      getFilesByName(name) {
        const list = files.filter(f => f.name === name);
        let i = 0;
        return {hasNext: () => i < list.length, next: () => list[i++]};
      },
      getRootFolder: () => root,
    },
    LockService: {getScriptLock: () => ({waitLock: () => locks.push('lock'), releaseLock: () => locks.push('release')})},
    ContentService: {
      MimeType: {JSON: 'json'},
      createTextOutput: (body) => ({body, setMimeType() { return this; }}),
    },
    JSON, Date, Object, Array, isNaN,
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  const post = (body) => JSON.parse(context.doPost({postData: {contents: JSON.stringify(body)}}).body);
  const get = (file) => JSON.parse(context.doGet({parameter: {file}}).body);
  return {files, post, get, locks, shared, root};
}

const ev = (day, name, at, extra = {}) => ({store: 'nagamachiminami', day, name, updated_at: at, ...extra});

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
