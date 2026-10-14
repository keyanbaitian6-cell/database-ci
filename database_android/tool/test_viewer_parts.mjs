import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {partsClient, partsDrive, partsPublisher} from './build_viewer_parts.mjs';
import {fetchViewerParts, fetchViewerDocument, rememberViewerHistory, readViewerHistory} from '../web/viewer_parts.mjs';

const hash = text => createHash('sha256').update(text).digest('hex');
const plain = x => JSON.parse(JSON.stringify(x));
const iterator = values => { let i = 0; return {hasNext: () => i < values.length, next: () => values[i++]}; };
function fixture() {
  const files = [], writes = []; let time = Date.now(), serial = 0;
  const folder = {getFilesByName: name => iterator(files.filter(f => f.name === name && !f.trashed)), getFiles: () => iterator(files)};
  function add(name, text) {
    const f = {name, text, id: String(++serial), time: ++time, trashed: false,
      getId: () => f.id, getName: () => f.name, getLastUpdated: () => new Date(f.time), getSize: () => Buffer.byteLength(f.text),
      isTrashed: () => f.trashed, setTrashed: v => {f.trashed = v;}, getBlob: () => ({getDataAsString: () => f.text})};
    files.push(f); return f;
  }
  let failed = null;
  const write = (_, f, name, text) => {
    if (name === failed) throw new Error('mock write failure');
    writes.push(name); if (!f) return add(name, text); f.text = text; f.time = ++time; return f;
  };
  const context = vm.createContext({console, Utilities: {DigestAlgorithm: {SHA_256: 'sha256'}, Charset: {UTF_8: 'utf8'},
    computeDigest: (_, text) => [...createHash('sha256').update(text).digest()], newBlob: text => ({getBytes: () => Buffer.from(text)})},
    DriveApp: {getFilesByName: name => folder.getFilesByName(name), getFileById: id => {
      const f = files.find(f => f.id === id); if (!f) throw new Error('not found'); return f;
    }}, ContentService: {MimeType: {JSON: 'json'}, createTextOutput: text => ({text, setMimeType() {return this;}})}});
  vm.runInContext(partsPublisher(), context);
  const base = add('database-viewer.json', '{}');
  const doc = (records, site = 'meruhen') => ({format: site === 'meruhen' ? 'database-backup' : 'pscube-viewer', version: 1,
    source: 'pc-viewer', exported_at: new Date(++time).toISOString(), records});
  const publish = (records, site = 'meruhen') => context.vpPublish(folder, base, site, doc(records, site), write);
  const get = (params = {}, site = 'meruhen') => plain(context.vpGet(base, site, params));
  const read = url => get(Object.fromEntries(new URL(url).searchParams), new URL(url).searchParams.get('file') === 'pscube' ? 'pscube' : 'meruhen');
  return {context, files, writes, add, base, folder, publish, get, read, fail: name => {failed = name;}};
}
const row = (day, rack = 1, games = 100) => ({day, rack, games, store: 'saiwaichou', machine: '試験🌈'});
const storage = () => {const map = new Map(); return {map, get: key => map.get(key), set: (key, value) => map.set(key, value)};};

test('履歴v2：総量50MiB・12万5千件でも日別上限内なら許可、同一日の超過は拒否', () => {
  const f = fixture(); f.publish([row('2026-10-02')]);
  const m = f.get({check: '1'}).parts;
  const parts = Array.from({length: 50}, (_, i) => ({day: new Date(Date.UTC(2025, 0, i + 1)).toISOString().slice(0, 10),
    hash: hash(String(i)), count: 2500, bytes: 1048576}));
  const big = {...m, version: 2, parts, days: parts.map(p => p.day), count: 125000};
  assert.doesNotThrow(() => f.context.vpValidManifest(big, 'meruhen'));
  assert.throws(() => f.context.vpValidManifest({...big, version: 1}, 'meruhen'), /不正/);
  assert.throws(() => f.context.vpValidManifest({...big, parts: parts.map(p => ({...p, day: parts[0].day}))}, 'meruhen'), /不正/);
});

test('保存済み全期間の移行・期間落ち保持・空の日の明示削除・再起動読み込み', async () => {
  const f = fixture(), cache = storage(), url = 'https://a.test/exec';
  await rememberViewerHistory(url, 'meruhen', f.context ? {format: 'database-backup', records: [row('2025-01-01')]} : null, cache);
  f.publish([row('2026-10-02'), row('2026-10-03')]);
  let m = f.get({check: '1'}).parts;
  const first = await fetchViewerParts(url, 'meruhen', {...m, version: 2, days: ['2026-10-02', '2026-10-03']}, f.read, cache);
  assert.equal(first.records.length, 3);
  f.publish([row('2026-10-03')]); m = f.get({check: '1'}).parts;
  const second = await fetchViewerParts(url, 'meruhen', {...m, version: 2, days: ['2026-10-02', '2026-10-03']}, f.read, cache);
  assert.deepEqual(second.records.map(r => r.day), ['2025-01-01', '2026-10-03']);
  assert.equal((await readViewerHistory(url, 'meruhen', cache)).records.length, 2);
});

test('一覧から外れた過去分もハッシュ検査し、破損時には上書きしない', async () => {
  const f = fixture(), cache = storage(), url = 'https://a.test/exec';
  f.publish([row('2025-01-01')]); await fetchViewerDocument(url, 'meruhen', f.read, cache);
  const old = [...cache.map.values()][0]; old.parts[Object.keys(old.parts)[0]] = JSON.stringify([row('2025-01-01', 1, 999)]);
  f.publish([row('2026-10-02')]); const before = JSON.stringify([...cache.map]);
  await assert.rejects(fetchViewerDocument(url, 'meruhen', f.read, cache), /過去の履歴が破損/);
  assert.equal(JSON.stringify([...cache.map]), before);
});

test('配布版は生成元と一致（両ページ・両Apps Script・メルヘン同期）', () => {
  for (const path of ['../web/viewer_parts.mjs', '../../share_viewer/viewer_parts.mjs']) {
    assert.equal(readFileSync(new URL(path, import.meta.url), 'utf8').replaceAll('\r\n', '\n'), partsClient());
  }
  for (const path of ['viewer_drive_script.gs', 'viewer_drive_script_readonly.gs', 'meruhen_cloud_sync.gs']) {
    const source = readFileSync(new URL(path, import.meta.url), 'utf8').replaceAll('\r\n', '\n');
    assert.equal(source.split('// BEGIN GENERATED VIEWER PARTS\n')[1], path.startsWith('meruhen') ? partsPublisher() : partsDrive());
  }
});

test('両Apps Scriptの実doGet：差分と全件の内容一致・ID非公開・許可以外のpartを拒否', () => {
  for (const script of ['viewer_drive_script.gs', 'viewer_drive_script_readonly.gs']) {
    const f = fixture(); f.publish([row('2026-10-02'), row('2026-10-03')]);
    const source = readFileSync(new URL(script, import.meta.url), 'utf8');
    // coreは既に存在するため生成部分は再評価しない。
    vm.runInContext(source.split('// BEGIN GENERATED VIEWER PARTS')[0], f.context);
    const call = parameter => JSON.parse(f.context.doGet({parameter}).text);
    const check = call({check: '1'});
    assert.equal(check.format, 'drive-check'); assert.equal(check.parts.parts.length, 2);
    assert.ok(check.parts.parts.every(p => !('id' in p) && !('file_version' in p)));
    assert.equal(call({}).records.length, 2);
    assert.equal(call({revision: check.parts.revision, parts: check.parts.parts[0].hash}).parts.length, 1);
    assert.match(call({revision: check.parts.revision, parts: 'private-id'}).error, /指定/);
  }
});

test('初回・日別修正・期間落ち・日内削除・同一内容で時刻だけ変更', async () => {
  const f = fixture(), cache = storage(), rows = [row('2026-10-01'), row('2026-10-02'), row('2026-10-02', 2)];
  f.publish(rows);
  const first = await fetchViewerParts('https://a.test/exec', 'meruhen', f.get({check: '1'}).parts, f.read, cache);
  assert.equal(first.records.length, 3);
  const oldRevision = f.get({check: '1'}).version, writes = f.writes.length;
  f.publish([...rows].reverse()); assert.equal(f.get({check: '1'}).version, oldRevision); assert.equal(f.writes.length, writes);
  f.publish([row('2026-10-02', 2, 200)]);
  const updated = await fetchViewerParts('https://a.test/exec', 'meruhen', f.get({check: '1'}).parts, f.read, cache);
  assert.deepEqual(updated.records, [row('2026-10-01'), row('2026-10-02', 2, 200)]);
  assert.equal(Object.keys([...cache.map.values()][0].parts).length, 2);
});

test('共有の閲覧ログは差分有効前も後も1回だけ（確認・パーツ取得では重複しない）', () => {
  const f = fixture(), logs = []; f.context.console = {log: value => logs.push(value)};
  const source = readFileSync(new URL('viewer_drive_script_readonly.gs', import.meta.url), 'utf8');
  vm.runInContext(source.split('// BEGIN GENERATED VIEWER PARTS')[0], f.context);
  const call = parameter => JSON.parse(f.context.doGet({parameter}).text);
  call({check: '1', access: '1', u: 'friend'}); assert.equal(logs.length, 0);
  call({u: 'friend'}); assert.equal(logs.length, 1);
  f.publish([row('2026-10-02')]); logs.length = 0;
  const check = call({check: '1', access: '1', u: 'friend'}); assert.equal(logs.length, 1);
  call({parts: check.parts.parts[0].hash, revision: check.parts.revision}); assert.equal(logs.length, 1);
});

test('キャッシュ破損・消失・保存拒否・接続先とサイトの分離', async () => {
  const f = fixture(), cache = storage(); f.publish([row('2026-10-02')]);
  const m = f.get({check: '1'}).parts; let calls = 0;
  const read = url => {calls++; return f.read(url);};
  await fetchViewerParts('https://a.test/exec', 'meruhen', m, read, cache); assert.equal(calls, 1);
  await fetchViewerParts('https://a.test/exec?u=name', 'meruhen', m, read, cache); assert.equal(calls, 1);
  await fetchViewerParts('https://b.test/exec', 'meruhen', m, read, cache); assert.equal(calls, 2);
  [...cache.map.values()][0].parts[m.parts[0].hash] = '[]';
  await fetchViewerParts('https://a.test/exec', 'meruhen', m, read, cache); assert.equal(calls, 3);
  cache.map.clear(); await fetchViewerParts('https://a.test/exec', 'meruhen', m, read, cache); assert.equal(calls, 4);
  const noCache = {get() {throw new Error('disabled');}, set() {throw new Error('quota');}};
  await assert.rejects(fetchViewerParts('https://a.test/exec', 'meruhen', m, read, noCache), /保存データは変更していません/);
  await assert.rejects(fetchViewerParts('https://a.test/exec', 'pscube', m, read, cache), /不正/);
});

test('壊れた通信・途中の世代変更では保存せず、一覧を取り直すと回復する', async () => {
  const f = fixture(), cache = storage(); f.publish([row('2026-10-02')]);
  await fetchViewerDocument('https://a.test/exec', 'meruhen', f.read, cache);
  const before = JSON.stringify([...cache.map]); f.publish([row('2026-10-02', 1, 999)]);
  const broken = url => {const value = f.read(url); if (value.parts?.[0]?.text) value.parts[0].text = '[]'; return value;};
  await assert.rejects(fetchViewerDocument('https://a.test/exec', 'meruhen', broken, cache), /一致/);
  assert.equal(JSON.stringify([...cache.map]), before);
  let changed = false;
  const racing = url => {if (new URL(url).searchParams.has('parts') && !changed) {
    changed = true; f.publish([row('2026-10-02', 1, 777)]);
  } return f.read(url);};
  assert.equal((await fetchViewerDocument('https://a.test/exec', 'meruhen', racing, cache)).records[0].games, 777);
});

test('全件応答の旧スクリプト・checkだけ対応の旧スクリプトも読める', async () => {
  const doc = {records: [row('2026-10-02')]};
  assert.deepEqual(await fetchViewerDocument('https://a.test/exec', 'meruhen', async () => doc), doc);
  assert.deepEqual(await fetchViewerDocument('https://a.test/exec', 'meruhen', async url =>
    new URL(url).searchParams.has('check') ? {format: 'drive-check', version: 'old'} : doc), doc);
});

test('1MiB超の1日を分割、8個単位で取得、上限・重複・過大な一覧を保存前に拒否', async () => {
  const f = fixture(); f.publish(Array.from({length: 10}, (_, i) => ({...row('2026-10-02', i), payload: '界'.repeat(190000)})));
  const m = f.get({check: '1'}).parts;
  assert.equal(m.parts.length, 10); assert.ok(m.parts.every(p => p.bytes <= 1048576));
  let calls = 0;
  const doc = await fetchViewerParts('https://a.test/exec', 'meruhen', m, url => {calls++; return f.read(url);}, storage());
  assert.equal(calls, 2); assert.equal(doc.records.length, 10);
  const writes = f.writes.length;
  assert.throws(() => f.publish([{...row('2026-10-03'), payload: 'x'.repeat(1048576)}]), /1MiB/);
  assert.equal(f.writes.length, writes);
  await assert.rejects(fetchViewerParts('https://a.test/exec', 'meruhen', {...m, parts: [m.parts[0], m.parts[0]]}, f.read), /不正/);
});

test('失敗時の旧一覧保持・未使用パーツ再利用・生成物修復・7日経過の生成物だけ整理', () => {
  const f = fixture(); f.publish([row('2026-10-02')]);
  const index = f.files.find(x => x.name === 'database-viewer-parts-meruhen.json'), before = index.text;
  f.fail(index.name); assert.throws(() => f.publish([row('2026-10-02', 1, 999)]), /failure/);
  assert.equal(index.text, before); const count = f.files.length;
  f.fail(null); f.publish([row('2026-10-02', 1, 999)]); assert.equal(f.files.length, count);
  const m = JSON.parse(index.text), active = f.files.find(x => x.id === m.parts[0].id);
  active.trashed = true; f.publish([row('2026-10-02', 1, 999)]);
  assert.equal(f.get({}).records[0].games, 999);
  const old = f.files.find(x => x.name.startsWith('database-viewer-part-') && x !== active);
  old.time = Date.now() - 8 * 86400000;
  const backup = f.add('database-backup-android.json', '{}'); backup.time = old.time;
  assert.equal(f.context.vpPrune(f.folder, 'meruhen'), 1);
  assert.equal(old.trashed, true); assert.equal(backup.trashed, false); assert.equal(f.base.trashed, false);
});
