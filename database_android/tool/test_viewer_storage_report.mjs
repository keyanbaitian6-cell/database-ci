// 閲覧ページの保存の診断（web/storage_report.mjs、2026-10-31）。保存した内容を読み直さず・変えず、
// 無い保存先を作らず、読み込みが途中で終わった回数を次に開いたときに数えることを確かめる。
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import {DIAG_KEY, DRIVE_HOLD_MS, driveHold, phaseStarted, phaseFinished, storageReportLines} from '../web/storage_report.mjs';

function memoryStorage(initial = {}) {
  const items = new Map(Object.entries(initial));
  return {get length() { return items.size; }, key: i => [...items.keys()][i] ?? null,
    getItem: k => items.has(k) ? items.get(k) : null, setItem: (k, v) => items.set(k, String(v))};
}
const at = text => () => new Date(text);

test('読み込みの途中でページが終わったら、次に始めたときに1回数える', () => {
  const storage = memoryStorage();
  phaseStarted('open', {storage, now: at('2026-10-31T00:00:00Z')});
  phaseFinished('open', {storage, now: at('2026-10-31T00:00:02.5Z')});
  phaseStarted('drive', {storage, now: at('2026-10-31T00:00:03Z')});
  // ここでSafariが落ちた。次に開く。
  phaseStarted('open', {storage, now: at('2026-10-31T01:00:00Z')});
  phaseFinished('open', {storage, now: at('2026-10-31T01:00:01Z')});
  const log = JSON.parse(storage.getItem(DIAG_KEY));
  assert.deepEqual(log.phases.open, {count: 2, unfinished: 0, last_ms: 1000, max_ms: 2500,
    last_at: '2026-10-31T01:00:01.000Z', last_unfinished_at: null});
  assert.equal(log.phases.drive.unfinished, 1);
  assert.equal(log.phases.drive.count, 0);
  assert.equal(log.phases.drive.last_unfinished_at, '2026-10-31T00:00:03.000Z');
  assert.equal(log.running, null);
  phaseFinished('drive', {storage});  // 始めていない区切りは数えない
  assert.equal(JSON.parse(storage.getItem(DIAG_KEY)).phases.drive.count, 0);
  phaseStarted('unknown', {storage});
  assert.equal(JSON.parse(storage.getItem(DIAG_KEY)).running, null, '知らない区切りは記録しない');
});

test('壊れた記録・書けない保存でも止まらない', () => {
  const storage = memoryStorage({[DIAG_KEY]: '{壊れた'});
  phaseStarted('open', {storage});
  assert.equal(JSON.parse(storage.getItem(DIAG_KEY)).running.phase, 'open');
  const broken = {getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }};
  assert.doesNotThrow(() => { phaseStarted('open', {storage: broken}); phaseFinished('open', {storage: broken}); });
});

test('確認できない項目は「確認できません」と書き、作らない理由を示す', () => {
  const lines = storageReportLines({estimate: null, persisted: null, databases: null, others: null, inspected: {},
    failed: [], loaded: null, log: {version: 1, running: null, phases: {}}, local_chars: null});
  assert.ok(lines.includes('保存領域の使用量：このブラウザでは確認できません'));
  assert.ok(lines.includes('本体の大きさ：このページではまだ読み込んでいません'));
  assert.ok(lines.some(l => l.startsWith('保存先の一覧：このブラウザでは確認できません（開くと空の保存先を作ってしまうため')));
  assert.ok(lines.includes('起動時の読み込み：まだ記録がありません'));
  assert.ok(lines.includes('Googleドライブの更新：まだ記録がありません'));
});

test('実際のIndexedDBで、本体を読まず・無い保存先を作らずに件数と大きさを出す', async () => {
  const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
  const code = await fs.readFile(new URL('../web/storage_report.mjs', import.meta.url));
  const server = http.createServer((req, res) => {
    res.setHeader('content-type', req.url === '/storage_report.mjs' ? 'text/javascript' : 'text/html');
    res.end(req.url === '/storage_report.mjs' ? code : '<!doctype html><meta charset="utf-8"><title>保存の診断試験</title>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    const result = await page.evaluate(async () => {
      const open = (name, version, upgrade) => new Promise((resolve, reject) => {
        const q = indexedDB.open(name, version); q.onupgradeneeded = () => upgrade(q.result);
        q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error);
      });
      const put = (db, store, entries) => new Promise((resolve, reject) => {
        const tx = db.transaction(store, 'readwrite');
        for (const [k, v] of entries) tx.objectStore(store).put(v, k);
        tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
      });
      // 閲覧ページ（web/index.html）と同じ形の保存先。本体は大きな文字列。
      const body = '{"format":"database-backup","version":1,"records":[' + '{"x":1},'.repeat(200000) + '{"x":1}]}';
      let db = await open('database-viewer', 1, d => d.createObjectStore('kv'));
      await put(db, 'kv', [['data', body], ['active_source', 'meruhen'], ['rainbow_marks', JSON.stringify([{store: 's', day: '2026-10-30', rack: 1}, {store: 's', day: '2026-10-30', rack: 2}])]]);
      db.close();
      db = await open('database-viewer-parts-v1', 2, d => { for (const n of ['snapshots', 'history-heads', 'history-days']) d.createObjectStore(n); });
      await put(db, 'history-heads', [['k', {days: ['2026-10-29', '2026-10-30']}]]);
      await put(db, 'history-days', [['k|2026-10-29', {parts: {}}], ['k|2026-10-30', {parts: {}}]]);
      db.close();
      localStorage.setItem('database-viewer-remote', 'https://script.google.com/macros/s/x/exec');
      // 読んだ本文を記録する（本体 'data' を読まないことを確かめる）。
      const reads = [];
      for (const method of ['get', 'getAll', 'openCursor']) {
        const original = IDBObjectStore.prototype[method];
        IDBObjectStore.prototype[method] = function(...args) { reads.push(`${this.name}:${method}:${args[0] ?? ''}`); return original.apply(this, args); };
      }
      const diag = await import('/storage_report.mjs');
      diag.phaseStarted('open'); diag.phaseFinished('open');
      diag.phaseStarted('drive');  // 終わる前にページが終わった
      diag.phaseStarted('open'); diag.phaseFinished('open');
      const report = await diag.collectStorageReport({loaded: {chars: body.length, source: 'meruhen'}});
      const diagnosticReads = [...reads];
      const names = (await indexedDB.databases()).map(d => d.name).sort();
      // 診断のあとも、ページ本体は同じ版で保存先を開いて本体を読める。
      db = await open('database-viewer', 1, () => { throw new Error('作り直しになった'); });
      const kept = await new Promise(r => { const q = db.transaction('kv').objectStore('kv').get('data'); q.onsuccess = () => r(q.result.length); });
      db.close();
      return {lines: diag.storageReportLines(report), reads: diagnosticReads, names, kept, bodyChars: body.length, report};
    });
    assert.deepEqual(result.names, ['database-viewer', 'database-viewer-parts-v1'], '無い保存先（新しい日別保存・P’s CUBE）を作らない');
    assert.deepEqual(result.reads, ['kv:get:rainbow_marks'], '本体や日別の本文は読まない（数と小さな🌈の印だけ）');
    assert.equal(result.kept, result.bodyChars, '本体は変わらない');
    const text = result.lines.join('\n');
    assert.match(text, /^この端末の保存（診断）：保存した内容は読み直さず、変えていません。/);
    assert.match(text, /保存領域：約[\d.,]+MBを使用／上限の目安 約[\d.,]+MB/);
    assert.match(text, /本体（前に読み込んだ内容）：約1\.5MB（1,600,0\d\d文字、このページで読み込んだときの大きさ）/);
    assert.match(text, /本体の保存先：メルヘンの本体あり・🌈の印（本体と別）2件（\d+文字）/);
    assert.match(text, /日別キャッシュ（Googleの部品）：2日分（接続先1件・旧形式0件）/);
    assert.match(text, /新しい日別保存：まだ使っていません/);
    assert.doesNotMatch(text, /P’s CUBEの保存先/);
    assert.match(text, /小さな設定の保存（localStorage）：\d+文字/);
    assert.match(text, /起動時の読み込み：最後まで終わった2回・前回[\d.]+秒・最長[\d.]+秒・途中で終わった0回/);
    assert.match(text, /Googleドライブの更新：最後まで終わった0回・途中で終わった1回（最後：.+に始めた分）/);
    assert.deepEqual(result.report.failed, []);
  } finally { await browser.close(); await new Promise(r => server.close(r)); }
});

test('更新の途中で終わっていたら、そこから6時間は起動時の自動更新を止める印を出す（2026-11-18）', () => {
  const storage = memoryStorage();
  assert.equal(driveHold({storage, now: at('2026-11-18T00:00:00Z')}), null, '記録なしは止めない');
  phaseStarted('drive', {storage, now: at('2026-11-18T00:27:00Z')});
  // ここでSafariが落ちた。次に開く（起動時の読み込みを始める）。
  phaseStarted('open', {storage, now: at('2026-11-18T00:30:00Z')});
  const until = '2026-11-18T06:27:00.000Z';
  assert.equal(driveHold({storage, now: at('2026-11-18T00:30:00Z')}), until);
  assert.equal(driveHold({storage, now: at('2026-11-18T06:26:59Z')}), until, '6時間たつ直前まで止める');
  assert.equal(driveHold({storage, now: at('2026-11-18T06:27:00Z')}), null, '6時間たったら止めない');
  assert.equal(DRIVE_HOLD_MS, 6 * 3600 * 1000);
  // 起動時の読み込みだけが落ちた（更新の途中ではない）のでは、止める印は出ない。
  const other = memoryStorage();
  phaseStarted('open', {storage: other, now: at('2026-11-18T00:00:00Z')});
  phaseStarted('open', {storage: other, now: at('2026-11-18T00:05:00Z')});
  assert.equal(driveHold({storage: other, now: at('2026-11-18T00:06:00Z')}), null);
  // 更新が最後まで終わったら印は消える。途中の回数・時間の記録は残る。
  phaseFinished('open', {storage, now: at('2026-11-18T00:30:01Z')});
  phaseStarted('drive', {storage, now: at('2026-11-18T00:31:00Z')});
  assert.equal(driveHold({storage, now: at('2026-11-18T00:31:00Z')}), until, '更新が終わるまでは印のまま');
  phaseFinished('drive', {storage, now: at('2026-11-18T00:31:30Z')});
  assert.equal(driveHold({storage, now: at('2026-11-18T00:32:00Z')}), null);
  const log = JSON.parse(storage.getItem(DIAG_KEY));
  assert.equal(log.drive_halt, undefined);
  assert.equal(log.phases.drive.unfinished, 1);
  assert.equal(log.phases.drive.count, 1);
});

test('止める印は、壊れた記録・書けない保存・大きく戻った時計では、止め続けない', () => {
  const broken = memoryStorage({[DIAG_KEY]: '{壊れた'});
  assert.equal(driveHold({storage: broken}), null);
  const denied = {getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }};
  assert.equal(driveHold({storage: denied}), null);
  const badTime = memoryStorage({[DIAG_KEY]: JSON.stringify({version: 1, running: null, phases: {}, drive_halt: {at: '不明'}})});
  assert.equal(driveHold({storage: badTime}), null);
  const future = memoryStorage({[DIAG_KEY]: JSON.stringify({version: 1, running: null, phases: {}, drive_halt: {at: '2030-01-01T00:00:00Z'}})});
  assert.equal(driveHold({storage: future, now: at('2026-11-18T00:00:00Z')}), null, '時計が6時間より大きく戻っていたら信じない');
});
