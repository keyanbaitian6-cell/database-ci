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

function drive({seed = true} = {}) {
  let clock = 1000, serial = 0;
  const files = [], writes = [], logs = [], triggers = [], properties = new Map();
  let apiStatus = 200, apiName = null, locked = false;
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
      getId: () => file.id, getName: () => file.name, isTrashed: () => file.trashed,
      getLastUpdated: () => new Date(file.updated), getSize: () => Buffer.byteLength(file.text),
      getParents: () => iterator([file.parent]),
      getBlob: () => ({getDataAsString() { file.reads++; if (file.readHook) file.readHook(file); return file.text; }}),
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
    Utilities: {DigestAlgorithm: {SHA_256: 'sha256'},
      computeDigest: (_, text) => [...createHash('sha256').update(text).digest()],
      newBlob: (text, mime, name) => ({text, mime, name})},
    UrlFetchApp: {fetch(url, options) {
      assert.match(url, /^https:\/\/www\.googleapis\.com\/upload\/drive\/v3\/files\/f\d+\?uploadType=media$/);
      assert.equal(options.method, 'patch'); assert.equal(options.headers.Authorization, 'Bearer test-only-token');
      const file = files.find(f => url.includes('/' + f.id + '?'));
      const status = !apiName || apiName === file.name ? apiStatus : 200;
      if (status >= 200 && status < 300) { file.text = options.payload.text; file.updated = clock++; writes.push(['update', file.name]); }
      return {getResponseCode: () => status};
    }},
  };
  vm.createContext(context); vm.runInContext(source, context);
  const doc = name => JSON.parse(files.find(f => !f.trashed && f.parent === folder && f.name === name).text);
  const replace = (file, value) => { file.text = typeof value === 'string' ? value : JSON.stringify(value); file.updated = clock++; };
  if (seed) {
    add('database-viewer.json', {untouched: true});
    add('pscube-backup-auto.json', backup([record(1, '2026-09-01'), record(1)], {source: 'pc'}));
    add('pscube-viewer-drive.json', {...backup([record(1)]), kind: 'viewer'});
  }
  return {context, files, writes, logs, triggers, properties, folder, root, add, doc, replace,
    failApi: (status, name = null) => { apiStatus = status; apiName = name; }, setup: () => context.setupPscubeCloudSync(), sync: () => context.syncPscubeCloud()};
}

test('配布用Apps Scriptは共通パーサー・ランタイムから再生成した内容と一致する', () => {
  assert.equal(source, buildCloudScript());
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

test('壊れたJSON・不正な台・機種・印・閲覧用偽装ファイルは全件検証で止め、既存出力を維持する', () => {
  const badDocs = ['{broken', backup([record(1, '2026-10-12', {games: -1})]),
    backup([record(1)], {rack_captures: ['wrong']}), {...backup([record(1)]), kind: 'viewer'},
    backup([record(1, '2026-10-12', {detail_url: 'https://evil.example/'})]),
    backup([record(1), record(1)]), backup([record(1)], {machines: []})];
  for (const bad of badDocs) {
    const d = drive(); d.setup();
    const before = [d.doc('pscube-backup-cloud.json'), d.doc('pscube-viewer-drive.json')];
    d.add('pscube-backup-android-20261013-080000.json', backup([record(2)]));
    const file = d.add('pscube-backup-android-20261013-090000.json', bad);
    const writes = d.writes.length;
    assert.throws(() => d.sync()); assert.equal(d.writes.length, writes);
    assert.deepEqual([d.doc('pscube-backup-cloud.json'), d.doc('pscube-viewer-drive.json')], before);
    d.replace(file, backup([record(3)])); d.sync();
    assert.equal(d.doc('pscube-viewer-drive.json').records.length, 3, '不正ファイルを直すと次回に復旧する');
  }
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

test('読み込み中にアップロードが変われば何も書かず再試行する', () => {
  const d = drive(); d.setup();
  const file = d.add('pscube-backup-android-20261013-090000.json', backup([record(2)]));
  file.readHook = f => { f.updated++; };
  const writes = d.writes.length;
  assert.throws(() => d.sync(), /読み込み中/); assert.equal(d.writes.length, writes);
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
