import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import fs from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import {meruhenRecords} from '../../share_viewer/data.mjs';
import {fetchViewerParts} from '../web/viewer_parts.mjs';

const source = await fs.readFile(new URL('./meruhen_cloud_sync.gs', import.meta.url), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const graph = {baseline_y: 200, peak_y: 100, end_y: 110, curve: 'M0 200L1 100L2 110', preview_image: 'data:image/png;base64,test'};
function record(rack, day = '2026-10-02', patch = {}) {
  return {store: 'saiwaichou', kind_code: 21, machine: '試験 機種', rack, day,
    games: 1645, bb: 75, rb: 84, max_hold: 16000, captured_at: day + 'T23:59:00', ...patch};
}
const backup = (records, patch = {}) => ({format: 'database-backup', version: 1, source: 'android', records, ...patch});
const viewer = records => backup(records, {source: 'pc-viewer', days: 60, exported_at: '2026-10-13T09:00:00+09:00', date_events: []});

test('明示削除は最後の1台にも反映し、古いAndroid入力では復活せず、新しい復元は許可', () => {
  const d = drive({history: true}); d.setup();
  const base = d.files[0], get = () => plain(d.context.vpGet(base, 'meruhen', {}));
  const mark = {store: 'saiwaichou', machine: '試験 機種', rack: 537, day: '2026-10-02', deleted_at: '2026-10-15T12:00:00+09:00'};
  d.replace(base, {...viewer([]), record_deletions: [mark]}); d.sync();
  assert.equal(get().records.length, 0);
  assert.ok(d.doc('database-viewer-parts-meruhen.json').days.includes(mark.day));
  d.add('database-backup-android-20261015-120001.json', backup([record(537), record(538), record(500, '2025-01-01')]));
  d.sync();
  assert.deepEqual(get().records.map(r => r.rack).sort(), [500, 538]);
  d.replace(base, {...viewer([record(537, mark.day, {record_updated_at: '2026-10-15T12:01:00+09:00'})]), record_deletions: [mark]});
  d.sync(); assert.equal(get().records.filter(r => r.rack === 537).length, 1);
});

test('PC入力に記録の無い日（削除印・イベントだけ・60日より前）は、残っているPCの記録を消さない', () => {
  // 2026-10-17：8/1〜8/17だけのPC入力に、全期間の削除印と期間内のイベントが入っていたため、
  // その日のPCの記録が丸ごと置き換えられて消えた（9/14が0台など）。普段の60日分でも、
  // 削除印のある日が60日から外れると同じことが起きる。
  const d = drive({history: true}); d.setup();
  const base = d.files[0], get = () => plain(d.context.vpGet(base, 'meruhen', {}));
  const racks = day => get().records.filter(r => r.day === day).map(r => r.rack).sort();
  const mark = (rack, day, at) => ({store: 'saiwaichou', machine: '試験 機種', rack, day, deleted_at: at});
  const event = {store: 'saiwaichou', day: '2026-10-03', name: '試験イベント', updated_at: '2026-10-03T09:00:00+09:00'};
  const old = mark(601, '2026-09-14', '2026-10-01T12:00:00+09:00');
  d.replace(base, {...viewer([record(600, '2026-09-14'), record(601, '2026-09-14'), record(537), record(538, '2026-10-03')]),
    record_deletions: [old], date_events: [event]});
  d.sync();
  assert.deepEqual(racks('2026-09-14'), [600]);
  // 8/1だけの入力。9/14の削除印と10/3のイベントは入っているが、その日の記録は入っていない。
  d.replace(base, {...viewer([record(700, '2026-08-01')]), record_deletions: [old], date_events: [event]});
  while (d.sync().pending) { /* 24日ずつ */ }
  assert.deepEqual(racks('2026-08-01'), [700]);
  assert.deepEqual(racks('2026-09-14'), [600]);
  assert.deepEqual(racks('2026-10-02'), [537]);
  assert.deepEqual(racks('2026-10-03'), [538]);
  // 記録の無い日でも、新しい削除印は当てる（本当に消した台は消える）。
  d.replace(base, {...viewer([record(700, '2026-08-01')]),
    record_deletions: [old, mark(600, '2026-09-14', '2026-10-17T12:00:00+09:00')], date_events: [event]});
  while (d.sync().pending) { /* 24日ずつ */ }
  assert.deepEqual(racks('2026-09-14'), []);
  assert.deepEqual(racks('2026-10-02'), [537]);
});

test('不正な削除情報は旧一覧を保持して拒否する', () => {
  const d = drive({history: true}); d.setup();
  const before = d.doc('database-viewer-parts-meruhen.json');
  d.replace(d.files[0], {...viewer([]), record_deletions: [{store: 'saiwaichou', day: '2026-10-02', machine: '試験', rack: 537, deleted_at: 'bad'}]});
  assert.throws(() => d.sync(), /削除記録/);
  assert.deepEqual(d.doc('database-viewer-parts-meruhen.json').parts, before.parts);
  assert.deepEqual(d.doc('database-viewer-parts-meruhen.json').cloud_days, before.cloud_days);
  assert.equal(d.status().result, 'partial');
});

test('履歴の旧原本整理は7日超・未参照だけ、移行途中の入力削除でも進捗を解消し記録を保持', () => {
  const d = drive({history: true}); d.setup();
  const before = d.doc('database-viewer-parts-meruhen.json').cloud_days[0];
  const raw = d.files.find(f => f.id === before.id);
  d.add('database-backup-android.json', backup([record(537, '2026-10-02', {jo_net: 100})])); d.sync();
  raw.updated = Date.now() - 8 * 86400000;
  d.properties.delete('meruhenHistoryCleaned'); d.sync(); assert.equal(raw.trashed, true);
  const current = d.files.find(f => f.id === d.doc('database-viewer-parts-meruhen.json').cloud_days[0].id);
  current.updated = raw.updated;
  d.properties.delete('meruhenHistoryCleaned'); d.sync(); assert.equal(current.trashed, false);
  const input = d.add('database-backup-android-20261014-180000.json', backup(Array.from({length: 40}, (_, i) =>
    record(600, new Date(Date.UTC(2025, 0, i + 1)).toISOString().slice(0, 10)))));
  d.sync(); assert.ok(d.status().remaining > 0);
  input.trashed = true; d.sync(); assert.equal(d.status().remaining, 0);
  assert.equal(Object.keys(d.doc('database-viewer-parts-meruhen.json').history_progress).length, 0);
  assert.ok(d.status().viewer_records >= 25);
});

test('メルヘン履歴：60日以前も蓄積・変更日だけ原本更新・PC再出力後も差枚と過去分を保持', () => {
  const d = drive({history: true}), base = d.files[0];
  d.add('database-backup-android.json', backup([record(500, '2025-01-01', {jo_net: 123}), record(537, '2026-10-02', {jo_net: 15725})]));
  d.setup();
  const get = () => plain(d.context.vpGet(base, 'meruhen', {}));
  assert.deepEqual(get().records.map(r => r.day), ['2025-01-01', '2026-10-02']);
  const first = d.doc('database-viewer-parts-meruhen.json'), writes = d.writes.length;
  d.sync(); assert.equal(d.writes.length, writes); assert.equal(d.status().incremental.parts, 0);
  const ancient = first.cloud_days.find(d => d.day === '2025-01-01');
  d.add('database-backup-android-20261014-120000.json', backup([record(537, '2026-10-02', {jo_net: 18000, jo_captured_at: '2026-10-14T12:00:00+09:00'})]));
  d.sync();
  assert.equal(d.doc('database-viewer-parts-meruhen.json').cloud_days.find(d => d.day === ancient.day).id, ancient.id);
  assert.equal(get().records.find(r => r.rack === 537).jo_net, 18000);
  d.replace(base, viewer([record(600, '2026-10-14')])); d.sync();
  assert.equal(get().records.length, 3); assert.equal(get().records.find(r => r.rack === 537).jo_net, 18000);
  assert.equal(d.doc('database-viewer-parts-meruhen.json').version, 2);
});

test('メルヘン履歴：24日ずつ再開・一覧書込失敗は旧世代保持・破損原本は停止・閲覧パーツ復旧', () => {
  const d = drive({history: true}), base = d.files[0];
  const rows = Array.from({length: 55}, (_, i) => record(500, new Date(Date.UTC(2025, 0, i + 1)).toISOString().slice(0, 10)));
  d.add('database-backup-android.json', backup(rows)); d.setup();
  assert.ok(d.status().remaining > 0); d.sync(); d.sync();
  assert.equal(d.status().remaining, 0);
  const manifest = d.files.find(f => f.name === 'database-viewer-parts-meruhen.json'), before = manifest.text;
  d.add('database-backup-android-20261014-120000.json', backup([record(600, '2026-10-14')]));
  d.failApi(403, manifest.name); assert.throws(() => d.sync(), /更新に失敗/); assert.equal(manifest.text, before);
  d.failApi(200); d.sync(); assert.equal(d.status().remaining, 0);
  const root = JSON.parse(manifest.text), p = d.files.find(f => f.id === root.parts[0].id); p.trashed = true;
  d.context.rebuildMeruhenViewerParts(); while (d.status().remaining) d.sync();
  assert.equal(d.context.vpGet(base, 'meruhen', {}).records.length, 57);
  const raw = d.files.find(f => f.id === d.doc(manifest.name).cloud_days[0].id); d.replace(raw, '{}');
  d.add('database-backup-android-20261014-130000.json', backup([rows[0]]));
  assert.throws(() => d.sync(), /原本が(破損|見つかりません)/);
});

test('メルヘン差分：2日初回・1日更新・Web再取得・変更なし・PC再出力・出力失敗から復旧', async () => {
  const d = drive({incremental: true});
  const base = d.files[0], original = base.text;
  d.add('database-backup-android.json', backup([record(538, '2026-10-03')]));
  d.setup();
  const get = params => plain(d.context.vpGet(base, 'meruhen', params));
  const cache = new Map(), storage = {get: key => cache.get(key), set: (key, value) => cache.set(key, value)};
  let requests = [];
  const read = url => { const params = Object.fromEntries(new URL(url).searchParams); requests.push(params); return get(params); };
  const first = get({check: '1'}).parts;
  const doc = await fetchViewerParts('https://example.test/exec', 'meruhen', first, read, storage);
  assert.equal(doc.records.length, 2); assert.equal(base.text, original);
  assert.equal(d.status().incremental.parts, 2);
  const writes = d.writes.length, reads = d.calls.read;
  d.sync(); assert.equal(d.writes.length, writes); assert.equal(d.calls.read, reads);
  d.add('database-backup-android-20261013-220000.json', backup([record(537, '2026-10-02', {jo_net: 15725})]));
  d.sync(); assert.equal(d.status().incremental.parts, 1); assert.equal(base.text, original);
  const second = get({check: '1'}).parts;
  requests = [];
  const updated = await fetchViewerParts('https://example.test/exec', 'meruhen', second, read, storage);
  assert.equal(requests.length, 1); assert.equal(requests[0].parts.split(',').length, 1);
  assert.equal(updated.records.find(r => r.rack === 537).jo_net, 15725);
  assert.deepEqual(meruhenRecords(updated), meruhenRecords(get({})));
  assert.throws(() => get({parts: first.parts[0].hash, revision: first.revision}), /更新/);
  assert.throws(() => get({parts: 'private-id', revision: second.revision}), /指定/);
  const index = d.files.find(f => f.name === 'database-viewer-parts-meruhen.json'), saved = index.text;
  d.add('database-backup-android-20261013-230000.json', backup([record(539, '2026-10-03')]));
  d.failApi(403, index.name); assert.throws(() => d.sync(), /更新に失敗/); assert.equal(index.text, saved);
  assert.equal(get({}).records.length, 2);
  d.failApi(200); d.sync(); assert.equal(get({}).records.length, 3);
  d.replace(base, viewer([record(600, '2026-10-04')]));
  assert.equal(get({check: '1'}), null); // PCの新しい全件版を一旦使う。
  d.sync(); assert.equal(get({}).records.length, 4);
  d.setMode(false); d.sync(); assert.equal(get({}), null);
  assert.equal(JSON.parse(base.text).records.length, 4);
  d.setMode(true); d.sync(); assert.equal(get({}).records.length, 4);
  base.id = 'replacement-id'; // Driveで同サイズ・同更新日時の別IDへ差し替えられた場合。
  assert.equal(get({}), null); d.sync(); assert.equal(get({}).records.length, 4);
});

function drive({seed = true, incremental = false, history = false} = {}) {
  let clock = 1000, serial = 0;
  const files = [], writes = [], logs = [], triggers = [], properties = new Map();
  // Driveへの問い合わせ回数（ファイルごとの読み出し）。入力が増えたときの負荷を確かめる。
  const calls = {name: 0, id: 0, updated: 0, size: 0, trashed: 0, read: 0};
  let apiStatus = 200, apiName = null, locked = false;
  // 一時的な失敗：指定の回数だけ HTTP の失敗（times）か通信の例外（throws）を返し、そのあとは成功する。待った回数も数える。
  const flaky = {status: 0, name: null, times: 0, throws: 0, sleeps: [], attempts: 0};
  const iterator = list => { let i = 0; return {hasNext: () => i < list.length, next: () => list[i++]}; };
  const searchIn = (parent, query) => {
    assert.equal(query, "trashed = false and title contains 'database-backup-android'");
    return iterator(files.filter(f => f.parent === parent && !f.trashed && f.name.includes('database-backup-android')));
  };
  const root = {id: 'root', getId: () => 'root', isTrashed: () => false, searchFiles: query => searchIn(root, query)};
  const folder = {
    id: 'shared', getId: () => 'shared', isTrashed: () => false,
    getFiles: () => iterator(files.filter(f => f.parent === folder)),
    searchFiles: query => searchIn(folder, query),
    getFilesByName: name => iterator(files.filter(f => f.parent === folder && f.name === name)),
    createFile(blob) {
      const file = add(blob.name, blob.text);
      writes.push(['create', file.name]); return file;
    },
  };
  function add(name, value, parent = folder) {
    const file = {id: 'f' + serial++, name, text: typeof value === 'string' ? value : JSON.stringify(value),
      parent, updated: clock++, trashed: false, reads: 0, readHook: null,
      getId: () => { calls.id++; return file.id; }, getName: () => { calls.name++; return file.name; },
      isTrashed: () => { calls.trashed++; return file.trashed; },
      setTrashed: value => { file.trashed = value; },
      getLastUpdated: () => { calls.updated++; return new Date(file.updated); },
      getSize: () => { calls.size++; return Buffer.byteLength(file.text); },
      getParents: () => iterator([file.parent]),
      getBlob: () => ({getDataAsString() { calls.read++; file.reads++; if (file.readHook) file.readHook(file); return file.text; }}),
    };
    files.push(file); return file;
  }
  const context = {
    console: {log: text => logs.push(text)},
    DriveApp: {
      getFilesByName: name => iterator(files.filter(f => f.name === name)),
      getRootFolder: () => root,
      getFolderById: id => { assert.equal(id, 'shared'); return folder; },
      getFileById: id => { const file = files.find(f => f.id === id); assert.ok(file); return file; },
    },
    PropertiesService: {getScriptProperties: () => ({getProperty: key => properties.get(key) ?? null,
      setProperty: (key, value) => properties.set(key, value), deleteProperty: key => properties.delete(key),
      setProperties: obj => Object.entries(obj).forEach(([k, v]) => properties.set(k, v))})},
    LockService: {getScriptLock: () => ({tryLock: () => { if (locked) return false; locked = true; return true; },
      releaseLock: () => { locked = false; }})},
    ScriptApp: {
      getProjectTriggers: () => [...triggers], getOAuthToken: () => 'test-only-token',
      deleteTrigger: trigger => { triggers.splice(triggers.indexOf(trigger), 1); },
      newTrigger(handler) { let minutes; return {timeBased() { return this; }, everyMinutes(n) { assert.equal(n, 30); minutes = n; return this; },
        create() { const trigger = {minutes, getHandlerFunction: () => handler}; triggers.push(trigger); return trigger; }}; },
    },
    Utilities: {Charset: {UTF_8: 'UTF-8'}, DigestAlgorithm: {SHA_256: 'sha256'},
      computeDigest: (_, text) => [...createHash('sha256').update(text).digest()],
      newBlob: (text, mime, name) => ({text, mime, name, getBytes: () => [...Buffer.from(text)]}), sleep: ms => { flaky.sleeps.push(ms); }},
    UrlFetchApp: {fetch(url, options) {
      assert.match(url, /^https:\/\/www\.googleapis\.com\/upload\/drive\/v3\/files\/f\d+\?uploadType=media$/);
      assert.equal(options.method, 'patch'); assert.equal(options.headers.Authorization, 'Bearer test-only-token');
      const file = files.find(f => url.includes('/' + f.id + '?'));
      flaky.attempts++;
      if (flaky.throws > 0) { flaky.throws--; throw new Error('Address unavailable: https://www.googleapis.com/'); }
      if (flaky.times > 0 && (!flaky.name || flaky.name === file.name)) { flaky.times--; return {getResponseCode: () => flaky.status}; }
      const status = !apiName || apiName === file.name ? apiStatus : 200;
      if (status >= 200 && status < 300) { file.text = options.payload.text; file.updated = clock++; writes.push(['update', file.name]); }
      return {getResponseCode: () => status};
    }},
  };
  vm.createContext(context); vm.runInContext(source.replace('const MERUHEN_INCREMENTAL_VIEWER = false;', 'let MERUHEN_INCREMENTAL_VIEWER = ' + incremental + ';')
    .replace('const MERUHEN_HISTORY_VIEWER = false;', 'const MERUHEN_HISTORY_VIEWER = ' + history + ';'), context);
  const doc = name => JSON.parse(files.find(f => !f.trashed && f.parent === folder && f.name === name).text);
  const replace = (file, value) => { file.text = typeof value === 'string' ? value : JSON.stringify(value); file.updated = clock++; };
  if (seed) add('database-viewer.json', viewer([record(537, '2026-10-02', {games: 1624, bb: 70, rb: 77, captured_at: '2026-10-02T22:00:00'})]));
  const status = () => JSON.parse(properties.get('meruhenCloudStatus') ?? '{}');
  const failures = () => Object.values(JSON.parse(properties.get('meruhenCloudErrors') ?? '{}'));
  return {context, files, writes, logs, triggers, properties, folder, root, add, doc, replace, calls, status, failures,
    setMode: value => vm.runInContext('MERUHEN_INCREMENTAL_VIEWER = ' + value, context),
    failApi: (status, name = null) => { apiStatus = status; apiName = name; }, flaky, setup: () => context.setupMeruhenCloudSync(), sync: () => context.syncMeruhenCloud()};
}

test('初回・再設定は30分トリガー1個。他の関数のトリガーは保持', () => {
  const d = drive(), other = {getHandlerFunction: () => 'otherJob'};
  d.triggers.push(other, {getHandlerFunction: () => 'syncMeruhenCloud'});
  d.setup(); d.setup();
  assert.equal(d.triggers.length, 2); assert.equal(d.triggers[0], other);
  assert.equal(d.triggers[1].minutes, 30);
});

test('トリガー作成失敗でも旧トリガーを保持、フォルダの曖昧さ・重複出力では停止', () => {
  const d = drive(), old = {getHandlerFunction: () => 'syncMeruhenCloud'};
  d.triggers.push(old); d.context.ScriptApp.newTrigger = () => {throw new Error('trigger quota');};
  assert.throws(() => d.setup(), /trigger quota/); assert.deepEqual(d.triggers, [old]);
  const ambiguous = drive(); ambiguous.add('database-viewer.json', viewer([]), ambiguous.root);
  assert.throws(() => ambiguous.setup(), /一意/); assert.equal(ambiguous.writes.length, 0);
  const duplicate = drive(); duplicate.add('database-viewer.json', viewer([]));
  assert.throws(() => duplicate.setup(), /複数/); assert.equal(duplicate.writes.length, 0);
});

test('10/2の537番台に15725枚を反映。新しい日・台・両店を追加、画像を外し曲線を保持', () => {
  const d = drive(), file = d.files[0], id = file.id;
  const input = d.add('database-backup-android-20261013-192534.json', backup([
    record(537, '2026-10-02', {jo_net: 15725, jo_captured_at: '2026-10-13T19:25:00+09:00', graph_measurement: graph}),
    record(538, '2026-10-03', {max_hold: null, jo_net: -321}),
    record(1, '2026-10-03', {store: 'nagamachiminami', jo_net: 0}),
  ]), d.root);
  const original = input.text; d.setup();
  const doc = d.doc('database-viewer.json'), records = meruhenRecords(doc);
  assert.equal(file.id, id); assert.equal(input.text, original); assert.equal(doc.source, 'pc-viewer');
  assert.equal(records.length, 3); assert.equal(records.find(r => r.rack === 537).net, 15725);
  assert.equal(records.find(r => r.rack === 537).estimated, false);
  assert.equal(doc.records[0].games, 1645); assert.equal(doc.records[0].bb, 75);
  assert.equal(doc.records[0].graph_measurement.preview_image, undefined);
  assert.equal(doc.records[0].graph_measurement.curve, graph.curve);
  assert.equal(d.doc('database-android-cloud.json').records[0].jo_captured_at, '2026-10-13T19:25:00+09:00');
  assert.ok(doc.cloud_merged); assert.notEqual(doc.exported_at, '2026-10-13T09:00:00+09:00');
});

test('PCが閲覧用を再出力しても再反映。変更なしの回は大きいJSONを読まず書かない', () => {
  const d = drive(); d.add('database-backup-android.json', backup([record(537, undefined, {jo_net: 15725})]));
  d.setup(); const reads = d.files.map(f => f.reads), writes = d.writes.length;
  assert.equal(d.sync().changed, false); assert.deepEqual(d.files.map(f => f.reads), reads); assert.equal(d.writes.length, writes);
  const inputReads = d.files[1].reads;
  d.replace(d.files[0], viewer([record(537, undefined, {games: 1624, captured_at: '2026-10-02T22:00:00'})])); d.sync();
  assert.equal(d.doc('database-viewer.json').records[0].games, 1645);
  assert.equal(d.doc('database-viewer.json').records[0].jo_net, 15725); assert.equal(d.files[1].reads, inputReads);
});

test('数値の競合は取得時刻の新しい方。日本時間・UTC・時刻不明、古いグラフは除く', () => {
  const d = drive(), c = d.context;
  const base = record(1, undefined, {captured_at: '2026-10-02T23:00:00', graph_measurement: graph});
  const newer = record(1, undefined, {games: 2000, captured_at: '2026-10-02T14:01:00Z'});
  const merged = plain(c.meruhenPick(base, newer));
  assert.equal(merged.games, 2000); assert.equal('graph_measurement' in merged, false);
  assert.equal(c.meruhenPick(base, {...newer, captured_at: '2026-10-02T13:59:00Z'}), base);
  assert.equal(c.meruhenPick(base, {...newer, captured_at: null}), base);
  assert.equal(c.meruhenPick({...base, captured_at: null}, newer).games, 2000);
});

test('同じ数値のグラフ・最大持玉・確定設定を補い、既存の🌈・イベントを保持', () => {
  const d = drive(), events = [{store: 'saiwaichou', day: '2026-10-02', name: '周年', updated_at: '2026-10-13T00:00:00Z'}];
  d.replace(d.files[0], {...viewer([record(537, undefined, {max_hold: null, rainbow: false, rainbow_at: '2026-10-13T00:00:00Z'})]), date_events: events});
  const shared = d.add('database-rainbow-shared.json', {marks: []});
  d.add('database-backup-android.json', backup([record(537, undefined, {graph_measurement: graph, confirmed_setting: '6', rainbow: true})]));
  d.setup(); const r = d.doc('database-viewer.json').records[0];
  assert.equal(r.max_hold, 16000); assert.equal(r.confirmed_setting, '6'); assert.equal(r.rainbow, false);
  assert.equal(r.rainbow_at, '2026-10-13T00:00:00Z'); assert.equal(r.graph_measurement.curve, graph.curve);
  assert.deepEqual(d.doc('database-viewer.json').date_events, events); assert.equal(shared.reads, 0);
});

test('差枚が同じでも新しい取得時刻を保持し、その後に来た古い差枚へ戻さない', () => {
  const d = drive(), c = d.context;
  const a = record(1, undefined, {jo_net: 100, jo_captured_at: '2026-10-13T10:00:00Z'});
  const b = {...a, jo_captured_at: '2026-10-13T12:00:00Z'};
  const latest = c.meruhenPick(a, b);
  assert.equal(latest.jo_captured_at, b.jo_captured_at);
  assert.equal(c.meruhenPick(latest, {...a, jo_net: 200, jo_captured_at: '2026-10-13T11:00:00Z'}).jo_net, 100);
});

test('同数値で新しく取得した時刻も保持し、中間時刻の異なる数値へ巻き戻さない', () => {
  const c = drive().context, a = record(1, undefined, {captured_at: '2026-10-13T10:00:00Z'});
  const latest = c.meruhenPick(a, {...a, captured_at: '2026-10-13T12:00:00Z'});
  assert.equal(c.meruhenPick(latest, {...a, games: 3000, captured_at: '2026-10-13T11:00:00Z'}).games, a.games);
});

test('不正な入力は一度だけ報告して他を反映。更新すると再試行する', () => {
  for (const bad of ['{broken', backup([], {version: 2}), backup([], {source: 'pc-viewer'})]) {
    const d = drive(); d.setup();
    const file = d.add('database-backup-android-20261013-010000.json', bad);
    d.add('database-backup-android.json', backup([record(538)]));
    assert.throws(() => d.sync(), /一部のバックアップ/);
    assert.equal(d.doc('database-viewer.json').records.length, 2); assert.equal(d.failures().length, 1);
    const reads = file.reads; d.sync(); assert.equal(file.reads, reads);
    d.replace(file, backup([record(539)])); d.sync();
    assert.equal(d.doc('database-viewer.json').records.length, 3); assert.deepEqual(d.failures(), []);
  }
});

test('不正レコードの日付・整数・種別・店舗・確定設定はPC同様に飛ばす', () => {
  const d = drive();
  const invalid = [{day: '2026-13-01'}, {day: '2026-02-30'}, {day: '0000-01-01'}, {games: null}, {games: true},
    {rack: 0}, {bb: -1}, {rb: 1.5}, {kind_code: 20}, {store: 'unknown'}, {machine: ''},
    {confirmed_setting: '5'}, {max_hold: -1}, {previous_start: -1}].map(p => record(1, undefined, p));
  d.add('database-backup-android.json', backup([...invalid, record(538)])); d.setup();
  assert.deepEqual(d.doc('database-android-cloud.json').records.map(r => r.rack), [538]);
});

test('一時的な入力読み出し障害は壊れた版扱いせず次回再試行', () => {
  const d = drive(); d.setup();
  const file = d.add('database-backup-android.json', backup([record(538)]));
  file.readHook = () => {throw new Error('Service error: Drive');};
  d.sync(); assert.deepEqual(d.failures(), []); assert.equal(d.status().remaining, 1);
  file.readHook = null; d.sync(); assert.equal(d.doc('database-viewer.json').records.length, 2);
});

test('読み込み中に入力が変わったら次回へ回す', () => {
  const d = drive(); d.setup();
  const file = d.add('database-backup-android.json', backup([record(538)]));
  file.readHook = f => {d.replace(f, backup([record(539)])); f.readHook = null;};
  d.sync(); assert.equal(d.status().changed_while_reading, 1);
  assert.equal(d.doc('database-viewer.json').records.length, 1);
  d.sync(); assert.equal(d.doc('database-viewer.json').records[1].rack, 539);
});

test('出力失敗後も保存済みAndroid記録から回復。一時的な429は最大3回、403は1回', () => {
  const d = drive(); d.setup(); d.add('database-backup-android.json', backup([record(538)]));
  d.failApi(403, 'database-viewer.json'); const before = d.files[0].text;
  assert.throws(() => d.sync(), /HTTP 403/); assert.equal(d.files[0].text, before);
  assert.equal(d.doc('database-android-cloud.json').records.length, 1);
  d.failApi(200); d.sync(); assert.equal(d.doc('database-viewer.json').records.length, 2);
  d.add('database-backup-android-20261013-020000.json', backup([record(539)]));
  d.flaky.name = 'database-viewer.json'; d.flaky.status = 429; d.flaky.times = 2;
  d.sync(); assert.deepEqual(d.flaky.sleeps, [1000, 2000]);
  d.add('database-backup-android-20261013-030000.json', backup([record(540)]));
  d.failApi(403, 'database-viewer.json'); const attempts = d.flaky.attempts;
  assert.throws(() => d.sync(), /HTTP 403/); assert.equal(d.flaky.attempts - attempts, 2, '蓄積と閲覧に各1回');
});

test('蓄積の破損は上書きせず停止。Driveの一時障害なら同じ版で復旧', () => {
  const d = drive(); d.setup(); const store = d.files.find(f => f.name === 'database-android-cloud.json');
  d.replace(store, '{broken'); const before = d.files[0].text;
  assert.throws(() => d.sync(), /上書きせず/); assert.equal(store.text, '{broken'); assert.equal(d.files[0].text, before);
  d.replace(store, {format: 'database-android-cloud', version: 1, inputs: {}, records: []});
  store.readHook = () => {throw new Error('Drive unavailable');};
  assert.throws(() => d.sync(), /次の自動実行/); assert.deepEqual(d.failures(), []);
  store.readHook = null; d.sync();
});

test('蓄積内の不正な行を黙って落とさず停止', () => {
  const d = drive(); d.setup();
  d.replace(d.files.find(f => f.name === 'database-android-cloud.json'),
    {format: 'database-android-cloud', version: 1, inputs: {}, records: [record(1, undefined, {games: null})]});
  assert.throws(() => d.sync(), /上書きせず/);
});

test('書き込み直前にPCの閲覧データが更新された場合は停止し、次回に新しいPC版へ統合', () => {
  const d = drive(); d.setup();
  const file = d.add('database-backup-android.json', backup([record(538)]));
  file.readHook = () => {d.replace(d.files[0], viewer([record(600)])); file.readHook = null;};
  assert.throws(() => d.sync(), /変更/); assert.equal(d.doc('database-viewer.json').records[0].rack, 600);
  d.sync(); assert.deepEqual(d.doc('database-viewer.json').records.map(r => r.rack), [538, 600]);
});

test('非表示機種を除外。「+」表記は同じ台に統合。対象外ファイル・下位フォルダは読まない', () => {
  const d = drive();
  d.add('database-backup-android.json', backup([record(537, undefined, {machine: '試験+機種'}),
    record(1279, undefined, {machine: '聖闘士星矢 海皇覚醒'})]));
  const ignored = ['database-backup-auto.json', 'pscube-backup-android-20261013-010000.json',
    'database-backup-android-bad.json'].map(n => d.add(n, '{broken'));
  ignored.push(d.add('database-backup-android-20261013-010000.json', '{broken', {}));
  d.setup(); assert.equal(d.doc('database-viewer.json').records.length, 1);
  assert.equal(d.doc('database-android-cloud.json').records.length, 1);
  assert.ok(ignored.every(f => f.reads === 0));
});

test('最新日から60日。境界・年越し・古い入力を再処理しても閲覧用を書き直さない', () => {
  const d = drive(); d.replace(d.files[0], viewer([record(1, '2027-01-03')]));
  const rows = [record(2, '2026-11-05'), record(3, '2026-11-04')];
  d.add('database-backup-android.json', backup(rows)); d.setup();
  assert.deepEqual(d.doc('database-viewer.json').records.map(r => r.day), ['2026-11-05', '2027-01-03']);
  assert.deepEqual(d.doc('database-android-cloud.json').records.map(r => r.day), ['2026-11-05']);
  const updates = d.writes.filter(w => w[1] === 'database-viewer.json').length;
  d.add('database-backup-android-20261013-020000.json', backup([rows[1]])); d.sync();
  assert.equal(d.writes.filter(w => w[1] === 'database-viewer.json').length, updates);
});

test('10入力ずつ処理、10件の理由上限を外れた失敗版も再読込せず状態表示は読み取り専用', () => {
  const d = drive();
  for (let i = 0; i < 13; i++) d.add(`database-backup-android-20261013-${String(i).padStart(6, '0')}.json`, '{broken');
  d.setup(); assert.equal(d.status().remaining, 3); assert.equal(d.triggers.length, 1);
  assert.throws(() => d.sync(), /一部のバックアップ/); assert.equal(d.failures().length, 10);
  d.add('database-backup-android.json', backup([record(538)])); d.sync();
  assert.ok(d.files.filter(f => f.text === '{broken').every(f => f.reads === 1));
  const status = d.properties.get('meruhenCloudStatus'); d.context.showMeruhenCloudStatus();
  assert.equal(d.properties.get('meruhenCloudStatus'), status); assert.ok(d.logs.some(l => l.includes('全部で13件')));
});

test('48MiB上限は読む前・書く前に停止し既存閲覧データを維持、ロック中は何もしない', () => {
  const d = drive(); d.setup(); const before = d.files[0].text;
  const f = d.add('database-backup-android.json', backup([record(538)])); f.getSize = () => 49 * 1024 * 1024;
  assert.throws(() => d.sync(), /48MiB/); assert.equal(f.reads, 0); assert.equal(d.files[0].text, before);
  assert.throws(() => d.context.meruhenCheckSize('x'.repeat(48 * 1024 * 1024 + 1), 'test'), /48MiB/);
  const lock = d.context.LockService.getScriptLock(); lock.tryLock();
  const writes = d.writes.length; assert.equal(d.sync().busy, true); assert.equal(d.writes.length, writes); lock.releaseLock();
});

test('出力は共有パーサーとPC read_backup_file(allow_viewer=True)で読め、1行目はrecordsStartに一致', async () => {
  const d = drive(); d.add('database-backup-android.json', backup([record(537, undefined, {jo_net: 15725})])); d.setup();
  const text = d.files[0].text; assert.match(text.split('\n')[0], /"records"\s*:\s*\[$/);
  assert.equal(meruhenRecords(JSON.parse(text))[0].net, 15725);
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'meruhen-cloud-'));
  const file = path.join(temp, 'database-viewer.json');
  try {
    await fs.writeFile(file, text);
    const py = process.env.PYTHON || String.raw`C:\Users\keyan\.codex\.chatgpt-projects\g-p-6a9e28549ca0819184c877c6b3b3749e\database\.runtime\Scripts\python.exe`;
    const result = spawnSync(py, ['-c', 'import sys,json; from core import read_backup_file; rows,_=read_backup_file(sys.argv[1],allow_viewer=True); print(json.dumps(rows))', file],
      {cwd: fileURLToPath(new URL('../../database/', import.meta.url)), encoding: 'utf8'});
    assert.equal(result.status, 0, result.stderr || result.error?.message); assert.equal(JSON.parse(result.stdout)[0].jo_net, 15725);
  } finally {await fs.rm(file, {force: true}); await fs.rmdir(temp);}
});
