import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import fs from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import test from 'node:test';
import vm from 'node:vm';
import {buildCloudScript} from './build_pscube_cloud_sync.mjs';
import {emptyData, mergeData, validateData, recordKey} from '../web/pscube/data.mjs';
import {fetchDrive} from '../web/pscube/sync.mjs';

const source = await fs.readFile(new URL('./pscube_cloud_sync.gs', import.meta.url), 'utf8');
const base = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/';
const machine = {store: 'c740601', rate: '20', machine: '試験機種🌈', expected_count: 3,
  url: base + 'nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=%E8%A9%A6%E9%A8%93', machine_type: 'normal'};
const graph = {kind: 'daily', zero_y: 100, points: Array.from({length: 60}, (_, i) => [i, i <= 30 ? 100 - 2 * i : 40 + (i - 30) * 3])};
function record(rack, day = '2026-10-12', patch = {}) {
  return {store: machine.store, rate: machine.rate, machine: machine.machine, rack, day, bb: 8, rb: 4, at_art: 0,
    games: 3000, my: 1000, observed_at: day + 'T23:00:00+09:00', net_medals: -300,
    detail_url: base + 'nc-v06-001.php?cd_dai=' + rack + '#' + day.replaceAll('-', ''), graph, ...patch};
}
const backup = (records, patch = {}) => ({...emptyData(), kind: 'backup', source: 'android',
  machines: [machine], records, rack_captures: records.filter(r => r.graph?.kind === 'daily').map(recordKey), ...patch});
const plain = value => JSON.parse(JSON.stringify(value));

test('P-STATION履歴：31日以前も保持・全期間ファイルは上書きせず日別原本に完全グラフと取得印を残す', () => {
  const d = drive({history: true}); d.setup();
  const baseFile = d.files.find(f => f.name === 'pscube-viewer-drive.json');
  const doc = () => plain(d.context.vpGet(baseFile, 'pscube', {}));
  assert.deepEqual(doc().records.map(r => r.day), ['2026-09-01', '2026-10-12']);
  const root = d.doc('database-viewer-parts-pscube.json');
  const raw = d.doc(root.cloud_days[0].name);
  assert.equal(raw.data.records[0].graph.points.length, 60); assert.equal(raw.data.rack_captures.length, 1);
  d.replace(baseFile, {...backup([record(1, '2026-10-12', {graph: plain(d.context.pscubeCloudThinGraph(graph))})]), kind: 'viewer'});
  d.sync();
  const afterPc = d.doc('database-viewer-parts-pscube.json').cloud_days.find(x => x.day === '2026-10-12');
  assert.equal(d.doc(afterPc.name).data.records[0].graph.points.length, 60, 'PCの軽量出力で完全グラフを縮めない');
  const writes = d.writes.length; d.sync(); assert.equal(d.writes.length, writes);
  d.add('pscube-backup-android-20261014-120000.json', backup([record(1, '2026-10-12', {games: 5000, observed_at: '2026-10-14T12:00:00+09:00'})]));
  d.sync(); assert.equal(doc().records.length, 2); assert.equal(doc().records[1].games, 5000);
  assert.equal(d.status().incremental.parts, 1);
  const check = plain(d.context.vpGet(baseFile, 'pscube', {check: '1'}));
  assert.equal(check.parts.version, 2); assert.ok(!JSON.stringify(check).includes('cloud_days'));
  assert.ok(!JSON.stringify(check).includes('history_inputs')); assert.ok(!JSON.stringify(check).includes('"id"'));
});

test('P-STATION履歴：新しい不正入力だけ報告・一時障害は次回再試行・旧入力削除でも履歴保持', () => {
  const d = drive({history: true}); d.setup();
  const bad = d.add('pscube-backup-android-20261014-000000.json', '{bad');
  assert.throws(() => d.sync(), /一部のバックアップ/); const reads = bad.reads;
  d.sync(); assert.equal(bad.reads, reads);
  const good = d.add('pscube-backup-android-20261014-120000.json', backup([record(2)]));
  let once = true; good.readHook = () => { if (once) {once = false; throw new Error('Service error: Drive');} };
  d.sync(); assert.ok(d.status().remaining > 0); d.sync(); assert.equal(d.status().remaining, 0);
  good.trashed = true; d.sync(); assert.equal(d.status().viewer_records, 3);
});

test('P-STATION差分：1日だけ再出力し、PC用全期間バックアップを維持、失敗後も復旧する', () => {
  const d = drive({incremental: true});
  d.replace(d.files.find(f => f.name === 'pscube-backup-auto.json'), backup([record(10, '2026-10-11'), record(11)]));
  d.setup();
  const baseFile = d.files.find(f => f.name === 'pscube-viewer-drive.json');
  const baseText = baseFile.text;
  const get = () => plain(d.context.vpGet(baseFile, 'pscube', {}));
  assert.equal(d.status().incremental.parts, 2);
  const first = get(); assert.equal(validateData(first).records.length, 2);
  d.add('pscube-backup-android-20261013-220000.json', backup([record(11, '2026-10-12', {games: 4500, observed_at: '2026-10-13T22:00:00+09:00'})]));
  d.sync(); assert.equal(d.status().incremental.parts, 1); assert.equal(baseFile.text, baseText);
  assert.equal(get().records.find(r => r.rack === 11).games, 4500);
  assert.equal(d.doc('pscube-backup-cloud.json').records.find(r => r.rack === 11).games, 4500);
  const writes = d.writes.length; d.sync(); assert.equal(d.writes.length, writes);
  const index = d.files.find(f => f.name === 'database-viewer-parts-pscube.json'), old = index.text;
  d.add('pscube-backup-android-20261013-230000.json', backup([record(12)]));
  d.failApi(403, index.name); assert.throws(() => d.sync(), /更新に失敗/); assert.equal(index.text, old);
  d.failApi(200); d.sync(); assert.equal(get().records.length, 3);
  d.setMode(false); d.sync(); assert.equal(get(), null);
  assert.equal(JSON.parse(baseFile.text).records.length, 3);
  d.setMode(true); d.sync(); assert.equal(get().records.length, 3);
  baseFile.id = 'replacement-id';
  assert.equal(get(), null); d.sync(); assert.equal(get().records.length, 3);
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
    assert.equal(query, "trashed = false and title contains 'pscube-backup-'");
    return iterator(files.filter(f => f.parent === parent && !f.trashed && f.name.includes('pscube-backup-')));
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
  vm.createContext(context); vm.runInContext(source.replace('const PSCUBE_INCREMENTAL_VIEWER = false;', 'let PSCUBE_INCREMENTAL_VIEWER = ' + incremental + ';')
    .replace('const PSCUBE_HISTORY_VIEWER = false;', 'const PSCUBE_HISTORY_VIEWER = ' + history + ';'), context);
  const doc = name => JSON.parse(files.find(f => !f.trashed && f.parent === folder && f.name === name).text);
  const replace = (file, value) => { file.text = typeof value === 'string' ? value : JSON.stringify(value); file.updated = clock++; };
  if (seed) {
    add('database-viewer.json', {untouched: true});
    add('pscube-backup-auto.json', backup([record(1, '2026-09-01'), record(1)], {source: 'pc'}));
    add('pscube-viewer-drive.json', {...backup([record(1)]), kind: 'viewer'});
  }
  const status = () => JSON.parse(properties.get('pscubeCloudStatus') ?? '{}');
  const failures = () => Object.values(JSON.parse(properties.get('pscubeCloudErrors') ?? '{}'));
  return {context, files, writes, logs, triggers, properties, folder, root, add, doc, replace, calls, status, failures,
    setMode: value => vm.runInContext('PSCUBE_INCREMENTAL_VIEWER = ' + value, context),
    failApi: (status, name = null) => { apiStatus = status; apiName = name; }, flaky, setup: () => context.setupPscubeCloudSync(), sync: () => context.syncPscubeCloud()};
}

test('配布用Apps Scriptは共通パーサー・ランタイムから再生成した内容と一致する', () => {
  // Windowsのgitは .gs を CRLF で書き出すので、改行をそろえてから比べる（中身の違いは今までどおり検出する）。
  const lf = (text) => text.split('\r\n').join('\n');
  assert.equal(lf(source), lf(buildCloudScript()));
});

test('再設定で旧5分・重複トリガーを30分1個へ置き換え、他の関数と手動実行を保持する', () => {
  const d = drive();
  const other = {minutes: 5, getHandlerFunction: () => 'otherJob'};
  d.triggers.push(other, {minutes: 5, getHandlerFunction: () => 'syncPscubeCloud'},
    {minutes: 5, getHandlerFunction: () => 'syncPscubeCloud'});
  d.setup();
  assert.equal(d.triggers.length, 2); assert.equal(d.triggers[0], other);
  assert.equal(d.triggers[1].minutes, 30);
  d.setup(); assert.equal(d.triggers.length, 2); assert.equal(d.triggers[1].minutes, 30);
  d.add('pscube-backup-android-20261013-090000.json', backup([record(2)]));
  assert.equal(d.sync().viewerRecords, 2, '手動実行ですぐ反映できる');
  assert.equal(d.triggers.length, 2, '手動実行ではトリガーを増やさない');
});

test('新しいトリガーの作成に失敗した場合は旧トリガーを残す', () => {
  const d = drive();
  const old = {minutes: 5, getHandlerFunction: () => 'syncPscubeCloud'};
  d.triggers.push(old);
  d.context.ScriptApp.newTrigger = () => {throw new Error('trigger quota');};
  assert.throws(() => d.setup(), /trigger quota/);
  assert.deepEqual(d.triggers, [old]);
});

test('Androidのアップロードだけで両方の閲覧ページ用ファイルを更新し、全期間・共有設定・入力を保持する', async () => {
  const d = drive();
  const android = d.add('pscube-backup-android-20261013-090000.json', backup([record(2)]));
  const original = android.text;
  const viewer = d.files.find(f => f.name === 'pscube-viewer-drive.json');
  const oldId = viewer.id;
  const result = d.setup();
  assert.deepEqual([result.records, result.viewerRecords, result.pending], [3, 2, 0]);
  assert.equal(d.triggers.length, 1); assert.equal(viewer.id, oldId);
  assert.equal(d.doc('pscube-backup-cloud.json').kind, 'backup');
  assert.equal(d.doc('pscube-backup-cloud.json').records[0].day, '2026-09-01');
  assert.equal(d.doc('pscube-backup-cloud.json').records[1].graph.points.length, 60);
  assert.equal(d.doc('pscube-viewer-drive.json').records[0].graph.points.length, 16);
  assert.equal(android.text, original); assert.deepEqual(d.doc('database-viewer.json'), {untouched: true});
  assert.equal(d.doc('pscube-backup-cloud.json').source, 'cloud');
  const fetched = await fetchDrive('https://script.google.com/macros/s/test/exec', null, {
    fetchImpl: async () => new Response(viewer.text), versions: {get: () => null, set() {}}});
  assert.equal(fetched.data.records.length, 2);
  const reads = d.files.map(f => f.reads), writes = d.writes.length;
  assert.equal(d.sync().changed, false); assert.deepEqual(d.files.map(f => f.reads), reads);
  d.setup(); assert.equal(d.triggers.length, 1); assert.equal(d.writes.length, writes);
});

test('新しい数値を優先し、同じ数値は詳細グラフ・差枚を保ち、古い取得時刻をアップし直しても巻き戻さない', () => {
  const d = drive(); d.setup();
  const newer = record(1, '2026-10-12', {games: 4000, observed_at: '2026-10-13T02:00:00+09:00', net_medals: 1234});
  d.add('pscube-backup-android-20261013-090000.json', backup([newer])); d.sync();
  d.add('pscube-backup-android-20261013-100000.json', backup([record(1, '2026-10-12', {games: 5000, observed_at: '2026-10-12T20:00:00+09:00'})]));
  d.sync();
  const saved = d.doc('pscube-backup-cloud.json').records.find(r => r.day === '2026-10-12');
  assert.equal(saved.games, 4000); assert.equal(saved.net_medals, 1234);
  d.add('pscube-backup-android-20261013-110000.json', backup([{...newer, graph: {kind: 'overview', zero_y: 100, points: [[0, 100], [1, 90]]}, net_medals: null}]));
  d.sync(); const latest = d.doc('pscube-backup-cloud.json').records.find(r => r.day === '2026-10-12');
  assert.equal(latest.graph.kind, 'daily'); assert.equal(latest.net_medals, 1234);
});

test('数値が変わったら古い差枚・グラフ・取り込み済み印を引き継がない。時刻なしは回転数で比較', () => {
  const d = drive(); d.setup();
  const fresh = record(1, '2026-10-12', {games: 4000, observed_at: null, graph: null, net_medals: undefined});
  d.add('pscube-backup-android-20261013-090000.json', backup([fresh])); d.sync();
  const doc = d.doc('pscube-backup-cloud.json'), saved = doc.records.find(r => r.day === fresh.day);
  assert.equal(saved.games, 4000); assert.equal(saved.graph, null); assert.equal(saved.net_medals, undefined);
  assert.ok(!doc.rack_captures.includes(recordKey(fresh)));
  d.add('pscube-backup-android-20261013-100000.json', backup([{...fresh, games: 3900}])); d.sync();
  assert.equal(d.doc('pscube-viewer-drive.json').records[0].games, 4000);
});

test('イベント名と消した印を新しい時刻で統合し、共有イベント・🌈ファイルは書き換えない', () => {
  const d = drive();
  const event = {store: machine.store, rate: '20', day: '2026-10-12', name: '周年', updated_at: '2026-10-13T01:00:00Z'};
  const shared = d.add('pscube-events-shared.json', {events: [{...event, name: '別の入力'}]});
  const rainbow = d.add('database-rainbow-shared.json', {marks: [1]});
  const untouched = [shared.text, rainbow.text];
  d.add('pscube-backup-android-20261013-090000.json', backup([record(2)], {date_events: [event]})); d.setup();
  d.add('pscube-backup-android-20261013-100000.json', backup([record(2)], {date_events: [{...event, name: null, updated_at: '2026-10-13T02:00:00Z'}]})); d.sync();
  d.add('pscube-backup-android-20261013-110000.json', backup([record(2)], {date_events: [event]})); d.sync();
  assert.equal(d.doc('pscube-viewer-drive.json').date_events[0].name, null);
  assert.deepEqual([shared.text, rainbow.text], untouched);
});

test('不正な入力はそのファイルだけ取り消し、正常な入力は反映する。元ファイルは変えず、直すと再試行する', () => {
  const badDocs = ['{broken', backup([record(1, '2026-10-12', {games: -1})]),
    backup([record(1)], {rack_captures: ['wrong']}), {...backup([record(1)]), kind: 'viewer'},
    backup([record(1, '2026-10-12', {detail_url: 'https://evil.example/'})]),
    backup([record(1), record(1)]), backup([record(1)], {machines: []})];
  for (const bad of badDocs) {
    const d = drive(); d.setup();
    d.add('pscube-backup-android-20261013-080000.json', backup([record(2)]));
    const file = d.add('pscube-backup-android-20261013-090000.json', bad);
    const original = file.text;
    // 新しく取り込めない入力が見つかった回は、正常な分を反映したうえで失敗として知らせる。
    assert.throws(() => d.sync(), /一部のバックアップを取り込めませんでした（ほかは反映済み）：pscube-backup-android-20261013-090000\.json/);
    assert.equal(d.doc('pscube-viewer-drive.json').records.length, 2, '正常な入力（2番台）は反映済み');
    assert.equal(file.text, original, '元ファイルは書き換えない');
    assert.ok(d.files.includes(file) && !file.trashed && file.parent === d.folder, '元ファイルは消さない・移さない');
    const [failure] = d.failures();
    assert.equal(failure.name, file.name); assert.ok(failure.reason); assert.match(failure.checked_at, /^\d{4}-\d{2}-\d{2}T/);
    assert.equal(d.status().result, 'partial');
    // 同じ版のままなら読み直さず、毎回は失敗にしない（「変更なし（取り込めないファイルあり）」）。
    const reads = file.reads;
    const again = d.sync();
    assert.equal(again.changed, false); assert.deepEqual(plain(again.failed), [file.name]);
    assert.equal(file.reads, reads); assert.equal(d.status().result, 'unchanged-partial');
    // 直す（更新する）と再試行し、取り込めたら失敗の記録を消す。
    d.replace(file, backup([record(3)]));
    assert.equal(d.sync().viewerRecords, 3, '不正ファイルを直すと次回に取り込む');
    assert.deepEqual(d.failures(), []); assert.equal(d.status().result, 'ok');
  }
});

test('取り込み済みのファイルが壊れた版に更新されても、取り込み済みの記録は消さず巻き戻さない', () => {
  const d = drive();
  const file = d.add('pscube-backup-android-20261013-090000.json', backup([record(2, '2026-10-12', {games: 4000})]));
  d.setup();
  d.replace(file, '{broken');
  assert.throws(() => d.sync(), /取り込めませんでした/);
  const saved = d.doc('pscube-backup-cloud.json').records.find(r => r.rack === 2);
  assert.equal(saved.games, 4000, '前に取り込んだ記録はそのまま');
  assert.equal(d.doc('pscube-viewer-drive.json').records.length, 2);
  d.replace(file, backup([record(2, '2026-10-12', {games: 4500, observed_at: '2026-10-13T02:00:00+09:00'})]));
  d.sync(); assert.equal(d.doc('pscube-backup-cloud.json').records.find(r => r.rack === 2).games, 4500);
});

test('統合済みバックアップ自体が壊れていたら、入力の不正とは分けて上書きせずに止め、外すと入力から作り直す', () => {
  const d = drive(); d.add('pscube-backup-android-20261013-090000.json', backup([record(2)])); d.setup();
  const cloud = d.files.find(f => f.name === 'pscube-backup-cloud.json');
  d.replace(cloud, '{broken');
  d.add('pscube-backup-android-20261013-100000.json', backup([record(3)]));
  const writes = d.writes.length, viewer = d.doc('pscube-viewer-drive.json');
  assert.throws(() => d.sync(), /pscube-backup-cloud\.json を読めません.*上書きせずに止めました/);
  assert.equal(d.writes.length, writes); assert.equal(cloud.text, '{broken');
  assert.deepEqual(d.doc('pscube-viewer-drive.json'), viewer);
  assert.equal(d.status().result, 'error'); assert.equal(d.status().stop, 'backup');
  assert.deepEqual(d.failures(), [], '入力の失敗としては記録しない');
  cloud.name = 'pscube-backup-cloud-壊れた.json';   // 利用者が名前を変えて外す
  assert.equal(d.sync().viewerRecords, 3, '入力から作り直す');
});

test('セットアップ時に不正な入力があっても、正常な分を反映して自動実行は設定する', () => {
  const d = drive();
  d.add('pscube-backup-android-20261013-090000.json', '{broken');
  const result = d.setup();
  assert.equal(d.triggers.length, 1); assert.deepEqual(plain(result.failed), ['pscube-backup-android-20261013-090000.json']);
  assert.equal(d.doc('pscube-viewer-drive.json').records.length, 1);
});

test('入力が全部不正で統合済みバックアップも無いときは、何も作らずに止める', () => {
  const d = drive({seed: false}); d.add('pscube-viewer-drive.json', {});
  d.add('pscube-backup-android-20261013-090000.json', '{broken');
  assert.throws(() => d.setup(), /取り込めるP’s CUBEバックアップがありません：pscube-backup-android/);
  assert.equal(d.writes.length, 0); assert.equal(d.triggers.length, 0);
});

test('別フォルダ・ブラウザの部分バックアップ・ごみ箱・別サイトのファイルを拾わない', () => {
  const d = drive();
  d.add('pscube-backup-android-20261013-090000.json', backup([record(90)]), {id: 'another-folder'});
  d.add('pscube-backup-browser-20261013-090000.json', backup([record(91)]));
  d.add('pscube-backup-android-20261013-100000.json', backup([record(92)])).trashed = true;
  d.add('database-backup-android-20261013-090000.json', '{broken'); d.setup();
  assert.equal(d.doc('pscube-viewer-drive.json').records.length, 1);
});

test('マイドライブ直下と共有フォルダのバックアップを統合し、出力は共有フォルダだけに書く', () => {
  const d = drive();
  const latest = record(1, '2026-10-12', {games: 4500, observed_at: '2026-10-13T02:00:00+09:00'});
  const rootFile = d.add('pscube-backup-android-20261013-100621.json', backup([latest, record(2)]), d.root);
  const original = rootFile.text;
  d.add('pscube-backup-android-20261013-110000.json', backup([record(3)]));
  d.setup();
  const full = d.doc('pscube-backup-cloud.json');
  assert.equal(full.records.length, 4);
  assert.equal(full.records.find(r => r.rack === 1 && r.day === '2026-10-12').games, 4500);
  assert.equal(rootFile.text, original); assert.equal(rootFile.parent, d.root);
  assert.equal(d.files.filter(f => f.parent === d.root).length, 1, '出力をマイドライブへ作らない');
  assert.equal(d.sync().changed, false);
});

test('同じファイルを直下と共有フォルダの間で移動しても再処理・再出力しない', () => {
  const d = drive();
  const file = d.add('pscube-backup-android-20261013-100621.json', backup([record(2)]), d.root);
  d.setup(); const writes = d.writes.length, reads = file.reads;
  file.parent = d.folder; assert.equal(d.sync().changed, false);
  file.parent = d.root; assert.equal(d.sync().changed, false);
  assert.equal(d.writes.length, writes); assert.equal(file.reads, reads);
});

test('同じIDが両方の検索結果に出ても一度だけ読み、同内容の別コピーも台を増殖させない', () => {
  const d = drive();
  const file = d.add('pscube-backup-android-20261013-100621.json', backup([record(2)]));
  d.root.searchFiles = () => { let done = false; return {hasNext: () => !done, next: () => {done = true; return file;}}; };
  d.setup(); assert.equal(file.reads, 1);
  d.add('pscube-backup-android-20261013-110000.json', backup([record(2)]));
  d.sync(); assert.equal(d.doc('pscube-viewer-drive.json').records.length, 2);
});

test('初期設定で複数の共有フォルダ・同名出力の重複・バックアップ不在を検出する', () => {
  const d = drive();
  d.add('pscube-viewer-drive.json', {}, d.root);
  assert.throws(() => d.setup(), /一意/); assert.equal(d.writes.length, 0);
  const duplicate = drive(); duplicate.add('pscube-viewer-drive.json', {});
  assert.throws(() => duplicate.setup(), /複数/); assert.equal(duplicate.writes.length, 0);
  const empty = drive({seed: false}); empty.add('pscube-viewer-drive.json', {});
  assert.throws(() => empty.setup(), /バックアップがありません/); assert.equal(empty.triggers.length, 0);
});

test('PCが古い閲覧用を書いた場合、入力が増えていなくても統合済みの記録へ修復する', () => {
  const d = drive(); d.add('pscube-backup-android-20261013-090000.json', backup([record(2)])); d.setup();
  const viewer = d.files.find(f => f.name === 'pscube-viewer-drive.json');
  d.replace(viewer, {...backup([record(1)]), kind: 'viewer', source: 'pc'});
  const full = d.files.find(f => f.name === 'pscube-backup-cloud.json'), fullBefore = full.text;
  d.sync(); assert.equal(d.doc('pscube-viewer-drive.json').records.length, 2);
  assert.equal(full.text, fullBefore); assert.equal(d.sync().changed, false);
});

test('閲覧用の更新失敗はチェックポイントを確定せず、次の実行でバックアップから復旧する', () => {
  const d = drive(); d.setup();
  d.add('pscube-backup-android-20261013-090000.json', backup([record(2)]));
  const viewer = d.doc('pscube-viewer-drive.json'); d.failApi(503, 'pscube-viewer-drive.json');
  assert.throws(() => d.sync(), /HTTP 503/); assert.deepEqual(d.doc('pscube-viewer-drive.json'), viewer);
  assert.equal(d.doc('pscube-backup-cloud.json').records.length, 3, '全期間バックアップはすでに確定している');
  d.failApi(200); d.sync(); assert.equal(d.doc('pscube-viewer-drive.json').records.length, 2);
});

test('初回の入力が多い場合は分けて処理し、入力の移動・削除があっても統合済みの台を消さない', () => {
  const d = drive();
  for (let i = 0; i < 14; i++) d.add(`pscube-backup-android-20261013-${String(90000 + i).padStart(6, '0')}.json`, backup([record(i + 2)]));
  const first = d.setup(); assert.equal(first.pending, 5);
  const second = d.sync(); assert.equal(second.pending, 0); assert.equal(second.viewerRecords, 15);
  d.files.filter(f => f.name.startsWith('pscube-backup-android')).forEach(f => { f.trashed = true; });
  assert.equal(d.sync().viewerRecords, 15); assert.equal(d.sync().changed, false);
});

test('読み込み中にアップロードが変わった入力は、その回は取り込まず失敗にもしないで次回やり直す', () => {
  const d = drive(); d.setup();
  const file = d.add('pscube-backup-android-20261013-090000.json', backup([record(2)]));
  file.readHook = f => { f.updated++; };
  const writes = d.writes.length;
  const result = d.sync();
  assert.equal(result.pending, 1, '未取り込みのまま残す'); assert.equal(d.writes.length, writes);
  assert.deepEqual(d.failures(), [], '不正なファイルとは扱わない');
  file.readHook = null; assert.equal(d.sync().viewerRecords, 2);
});

test('容量・処理時間が大きい入力は次回に分け、入力の容量上限を超えたら出力を維持する', () => {
  const d = drive();
  for (let i = 0; i < 2; i++) {
    const file = d.add(`pscube-backup-android-20261013-09000${i}.json`, backup([record(i + 2)]));
    file.getSize = () => 40 * 1024 * 1024;
  }
  assert.equal(d.setup().pending, 1); assert.equal(d.sync().viewerRecords, 3);
  const huge = d.add('pscube-backup-android-20261013-100000.json', backup([record(4)]));
  huge.getSize = () => 49 * 1024 * 1024;
  const writes = d.writes.length;
  assert.throws(() => d.sync(), /48MiB/); assert.equal(d.writes.length, writes);
  const timed = drive();
  let ms = 0;
  timed.context.Date = class extends Date {static now() {return ms;}};
  timed.files.find(f => f.name === 'pscube-backup-auto.json').readHook = () => { ms += 190000; };
  timed.add('pscube-backup-android-20261013-090000.json', backup([record(2)]));
  assert.equal(timed.setup().pending, 1); assert.equal(timed.sync().viewerRecords, 2);
});

test('全期間バックアップの更新失敗は既存の全期間・閲覧用を両方維持する', () => {
  const d = drive(); d.setup();
  const before = [d.doc('pscube-backup-cloud.json'), d.doc('pscube-viewer-drive.json')];
  d.add('pscube-backup-android-20261013-090000.json', backup([record(2)]));
  d.failApi(403, 'pscube-backup-cloud.json'); assert.throws(() => d.sync(), /HTTP 403/);
  assert.deepEqual([d.doc('pscube-backup-cloud.json'), d.doc('pscube-viewer-drive.json')], before);
  d.failApi(200); assert.equal(d.sync().viewerRecords, 2);
});

test('Google用URLアダプターの検証・統合結果が実際のブラウザと一致する', () => {
  const d = drive();
  const a = backup([record(1), record(3, '2026-09-01')]);
  const b = backup([record(1, '2026-10-12', {net_medals: null, graph: {kind: 'overview', zero_y: 100, points: [[0, 100], [1, 90]]}}), record(2)]);
  assert.deepEqual(plain(d.context.validateData(a)), validateData(a));
  assert.deepEqual(plain(d.context.mergeData(a, b)), mergeData(a, b));
  for (const url of ['http://www.pscube.jp/', base.replace('www.pscube.jp', 'www.pscube.jp.evil') + 'nc-v06-001.php',
    base + 'nc-v06-001.php?cd_dai=2#20261012', base + 'nc-v06-001.php?cd_dai=1#20260230']) {
    assert.throws(() => d.context.validateData(backup([record(1, '2026-10-12', {detail_url: url})])));
  }
});

test('全期間バックアップは既存PCで読み込み可能で、グラフ軽量化もPCの出力と一致する', () => {
  const d = drive();
  d.add('pscube-backup-android-20261013-090000.json', backup([record(2)])); d.setup();
  const root = new URL('../../database/', import.meta.url);
  const code = `import json,sys,tempfile\nfrom pathlib import Path\nfrom pscube_import import PscubeStore,thin_graph,latest_pscube_backup\np=json.load(sys.stdin)\nwith tempfile.TemporaryDirectory() as folder:\n path=Path(folder)/'pscube-backup-cloud.json'\n path.write_text(json.dumps(p,ensure_ascii=False),encoding='utf-8')\n assert latest_pscube_backup(folder)==path\n s=PscubeStore(Path(folder)/'test.sqlite3')\n result=s.import_backup(path)\n assert result['added']==len(p['records'])\n out=s.export_payload('backup')\n assert set(out['rack_captures'])==set(p['rack_captures'])\n print(json.dumps({'records':out['records'],'thin':thin_graph(p['records'][0]['graph'])},ensure_ascii=False))\n s.close()\n`;
  const proc = spawnSync(process.env.PYTHON || 'python', ['-c', code], {cwd: root, input: JSON.stringify(d.doc('pscube-backup-cloud.json')), encoding: 'utf8'});
  assert.equal(proc.status, 0, proc.stderr);
  const result = JSON.parse(proc.stdout);
  assert.deepEqual(result.records, d.doc('pscube-backup-cloud.json').records);
  assert.deepEqual(result.thin, plain(d.context.pscubeCloudThinGraph(graph)));
});

test('入力が数百〜千ファイルでも、1ファイルの問い合わせ回数は一定で、変更なしの回は大きいJSONを読まない', (t) => {
  const measure = (count) => {
    const d = drive();
    // 実際の読み込みは10ファイルずつなので、取り込み済みの状態を作ってから数える。
    for (let i = 0; i < count; i++) {
      d.add(`pscube-backup-android-202610${String(1 + (i % 28)).padStart(2, '0')}-${String(100000 + i).slice(-6)}.json`,
        backup([record(2 + (i % 5))]), i % 2 ? d.root : d.folder);
    }
    for (let i = 0; i < Math.ceil(count / 10) + 2 && (i === 0 ? d.setup() : d.sync()).pending; i++);
    const before = {...d.calls};
    const started = performance.now();
    const unchanged = d.sync();
    const ms = performance.now() - started;
    const used = Object.fromEntries(Object.entries(d.calls).map(([k, v]) => [k, v - before[k]]));
    t.diagnostic(`${count}ファイル・変更なしの回：${JSON.stringify(used)}・${ms.toFixed(1)}ms`);
    return {unchanged, used, d};
  };
  const small = measure(100), medium = measure(300), large = measure(1000);
  for (const {unchanged, used} of [small, large]) {
    assert.equal(unchanged.changed, false);
    assert.equal(used.read, 0, '変更がない回はJSONを読まない');
  }
  // 1ファイルあたり名前・ID・更新時刻・サイズを1回ずつ（出力2ファイル分の確認は別に数回）。並べ替えで問い合わせない。
  for (const key of ['name', 'id', 'updated', 'size']) {
    assert.ok(small.used[key] <= 100 + 6 && large.used[key] <= 1000 + 6, `${key}: ${small.used[key]} / ${large.used[key]}`);
  }
  assert.ok(large.used.updated < 1000 * 1.1, '更新時刻は1ファイル1回');
  assert.ok(large.used.trashed <= 4, 'ごみ箱の確認は検索で済ませ、入力ごとには問い合わせない');
  // 新しい入力が1つ増えた回：読むのはその1ファイル＋統合済みバックアップだけ。
  const before = large.d.files.map(f => f.reads);
  large.d.add('pscube-backup-android-20261031-235959.json', backup([record(9)]));
  assert.equal(large.d.sync().viewerRecords, 7);
  const read = large.d.files.filter((f, i) => f.reads > (before[i] ?? 0)).map(f => f.name);
  assert.deepEqual(read.sort(), ['pscube-backup-android-20261031-235959.json', 'pscube-backup-cloud.json']);
});

test('状態の報告：正常・一部失敗・変更なし・停止を分け、件数・容量と上限に近づいた知らせを残す', () => {
  const d = drive(); d.add('pscube-backup-android-20261013-090000.json', backup([record(2)])); d.setup();
  const ok = d.status();
  assert.equal(ok.result, 'ok'); assert.equal(ok.records, 3); assert.equal(ok.viewer_records, 2);
  assert.ok(ok.backup_bytes > 0 && ok.viewer_bytes > 0); assert.deepEqual(ok.warnings, []);
  assert.equal(d.sync().changed, false); assert.equal(d.status().result, 'unchanged');
  const shown = d.context.showPscubeCloudStatus();
  assert.equal(shown.status.result, 'unchanged'); assert.match(d.logs.at(-2) + d.logs.at(-1), /全期間 3件/);
  const warn = s => d.context.pscubeCloudWarnings(s);
  assert.match(warn({backup_bytes: 30 * 1048576})[0], /上限の63%.*検討を始める目安/);
  assert.match(warn({backup_bytes: 40 * 1048576})[0], /上限の83%.*まもなく上限/);
  assert.match(warn({records: 130000})[0], /全期間の件数が上限の65%/);
  assert.match(warn({viewer_records: 85000})[0], /閲覧用の件数が上限の85%/);
  assert.match(warn({elapsed_ms: 150000})[0], /150秒/);
  assert.match(warn({inputs: 320})[0], /320個/);
  d.failApi(503, 'pscube-viewer-drive.json');
  d.add('pscube-backup-android-20261013-100000.json', backup([record(3)]));
  assert.throws(() => d.sync(), /HTTP 503/);
  assert.equal(d.status().result, 'error'); assert.equal(d.status().stop, 'output', '出力の失敗は入力の失敗と区別する');
  assert.deepEqual(d.failures(), []);
  // 失敗の記録はプロパティ1つの上限（約9KB）に収める：長い理由・多数の不正ファイルでも10件・120字まで。
  const many = drive(); many.setup();
  for (let i = 0; i < 25; i++) many.add(`pscube-backup-android-20261014-${String(100000 + i)}.json`, '{' + 'あ'.repeat(500));
  for (let i = 0; i < 4; i++) { try { many.sync(); } catch (_) { /* 新しい失敗の知らせ */ } }
  const stored = many.properties.get('pscubeCloudErrors');
  assert.ok(Buffer.byteLength(stored) < 9000, `${Buffer.byteLength(stored)}バイト`);
  assert.equal(many.failures().length, 10); assert.ok(many.failures().every(f => f.reason.length <= 120));
});

test('一時的な読み出しの失敗（Driveの通信障害）は壊れたファイルとして記録せず、次の実行で読み直す（再発防止 2026-10-13）', () => {
  const d = drive(); d.setup();
  const file = d.add('pscube-backup-android-20261013-090000.json', backup([record(2)]));
  const blob = file.getBlob;
  file.getBlob = () => { throw new Error('Service error: Drive'); };
  const result = d.sync();
  assert.deepEqual(d.failures(), [], '中身の不正ではないので失敗として記録しない');
  assert.equal(result.pending, 1, '未取り込みのまま次の実行へ残す');
  assert.equal(d.status().transient, 1);
  file.getBlob = blob;   // 通信が戻る（ファイルは更新されていない）
  assert.equal(d.sync().viewerRecords, 2, '同じ版のままでも次の実行で取り込む');
});

test('書き出しの一時的な失敗（429・5xx・通信の例外）は同じ実行の中で少し待って再試行し、403などはすぐ止める（再発防止 2026-10-13）', () => {
  const d = drive(); d.setup();
  d.add('pscube-backup-android-20261013-090000.json', backup([record(2)]));
  Object.assign(d.flaky, {status: 503, name: 'pscube-viewer-drive.json', times: 2});
  assert.equal(d.sync().viewerRecords, 2, '2回失敗しても3回目で書けば止めない');
  assert.deepEqual(plain(d.flaky.sleeps), [1000, 2000]);
  d.add('pscube-backup-android-20261013-100000.json', backup([record(3)]));
  Object.assign(d.flaky, {throws: 1, sleeps: []});
  assert.equal(d.sync().viewerRecords, 3, '通信の例外も再試行する');
  // 一時的でない失敗（権限など）は待たずに止め、次の自動実行に任せる。
  d.add('pscube-backup-android-20261013-110000.json', backup([record(4)]));
  Object.assign(d.flaky, {sleeps: [], attempts: 0}); d.failApi(403, 'pscube-backup-cloud.json');
  assert.throws(() => d.sync(), /HTTP 403/); assert.equal(d.flaky.attempts, 1); assert.deepEqual(plain(d.flaky.sleeps), []);
  // 続けて失敗する一時的な障害は3回で止める（既存の出力は書き換えない）。
  d.failApi(200); Object.assign(d.flaky, {status: 503, name: null, times: 99, attempts: 0});
  assert.throws(() => d.sync(), /HTTP 503/); assert.equal(d.flaky.attempts, 3);
  Object.assign(d.flaky, {times: 0}); assert.equal(d.sync().viewerRecords, 4, '障害が終われば次の実行で反映');
});

test('失敗記録の10件上限から外れた不正ファイルも、版が変わるまで読み直さず、毎回は通知しない。直せば取り込む（再発防止 2026-10-13）', () => {
  const d = drive(); d.setup();
  const broken = [];
  for (let i = 0; i < 12; i++) broken.push(d.add(`pscube-backup-android-20261014-${String(100000 + i)}.json`, '{broken ' + i));
  assert.throws(() => d.sync(), /取り込めませんでした/);   // 10ファイル
  assert.throws(() => d.sync(), /取り込めませんでした/);   // 残りの2ファイル
  const reads = broken.map(f => f.reads);
  // 別の正常なバックアップが届いた回（変更なしで終わらない回）でも、上限から外れた不正ファイルを読み直さず、新しい失敗にしない。
  d.add('pscube-backup-android-20261014-200000.json', backup([record(6)]));
  const third = d.sync();
  assert.equal(third.viewerRecords, 2);
  assert.deepEqual(plain(third.newFailures), [], '新しい失敗は無い（毎回通知しない）');
  assert.deepEqual(broken.map(f => f.reads), reads, '上限から外れたファイルも読み直さない');
  assert.equal(d.status().failed, 12, '件数は全部数える（詳しい理由は新しい10件）');
  assert.equal(d.failures().length, 10);
  // 上限から外れたファイルを直すと取り込む。
  const dropped = broken.find(f => !d.failures().some(x => x.name === f.name));
  d.replace(dropped, backup([record(5)]));
  assert.equal(d.sync().viewerRecords, 3);
  assert.equal(d.status().failed, 11);
});

test('先頭にBOMが付いたバックアップも読める（配布用スクリプトの書き方の取り違えの再発防止 2026-10-13）', () => {
  const d = drive(); d.setup();
  d.add('pscube-backup-android-20261013-090000.json', String.fromCharCode(0xfeff) + JSON.stringify(backup([record(2)])));
  assert.equal(d.sync().viewerRecords, 2);
  assert.ok(!source.includes(String.fromCharCode(0xfeff)), '配布用スクリプトに見えない文字（BOM）をそのまま入れない');
});
