// 閲覧ページ（メルヘン版）の「Googleドライブの更新」1回のメモリの山を、合成データで測る（2026-11-18）。
// 実データ・実Googleは使わない（Googleは page.route の偽物）。実ビルド（stage_viewer.py の出力）を実Chromiumで開く。
//   node tool/measure_viewer_update_peak.mjs <閲覧ページのビルド> <結果JSON> [実行回数=3] [日数=108] [1日の記録数=730]
// 測るもの：
//   ・描画用プロセスの使用量のピーク（Windowsの PeakWorkingSet64 / PeakPagefileUsage。起動からの最大値なので、
//     毎回、新しいブラウザ・同じ保存内容の写しで始める）
//   ・CDP（Runtime.getHeapUsage）を約10msごとに読んだ、JSヒープの使用量・確保量の最大
// 場面：unchanged（Googleの更新の目印が前回と同じ＝開くだけ）／changed1（新しい書き出しが1日分だけ来た更新1回）。
// 限界：同期処理の最中の山はCDPの10ms読みでは取り逃す（プロセス使用量のピークで補う）。Windows版Chromiumであり、
// iPhoneのSafari（JavaScriptCore）ではない。絶対値でなく、同じ条件での前後の比較に使う。
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [root, output, runsArg, daysArg, perDayArg] = process.argv.slice(2);
if (!root || !output) throw Error('使い方：node measure_viewer_update_peak.mjs <build> <result.json> [runs] [days] [perDay]');
const RUNS = Number(runsArg || 3), DAYS = Number(daysArg || 108), PER_DAY = Number(perDayArg || 730);
const PORT = 47831, prefix = '/database-viewer/', origin = `http://127.0.0.1:${PORT}`;
const SCRIPT = 'https://script.google.com/macros/s/AKfycbMEASURE/exec';
const work = await fs.mkdtemp(path.join(process.env.MEASURE_TMP || os.tmpdir(), 'vpeak-'));
const types = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.wasm': 'application/wasm', '.html': 'text/html', '.css': 'text/css', '.png': 'image/png'};
const server = http.createServer(async (req, res) => {
  let url = new URL(req.url, origin).pathname;
  if (url === '/setup') { res.setHeader('content-type', 'text/html'); res.end('<!doctype html><body>setup</body>'); return; }
  if (!url.startsWith(prefix)) { res.writeHead(404).end(); return; }
  url = decodeURIComponent(url.slice(prefix.length));
  const local = path.resolve(root, (!url || url.endsWith('/')) ? url + 'index.html' : url);
  if (!local.startsWith(path.resolve(root) + path.sep)) { res.writeHead(403).end(); return; }
  try { res.setHeader('content-type', types[path.extname(local)] || 'application/octet-stream'); res.end(await fs.readFile(local)); }
  catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(PORT, '127.0.0.1', resolve));

// ---- 合成データ（ページの中で作る。大きな文字列を通信で渡さない） ----
const OLD_EXPORT = '2026-11-17T23:50:00+09:00', NEW_EXPORT = '2026-11-18T00:20:00+09:00';
const seed = async ({url, days, perDay, oldExport, newExport}) => {
  let state = 12345;
  const rand = () => (state = (state * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
  const machines = ['ジャグラー', 'ハナハナ', 'ニューパルサー', 'ミスタージャグラー', 'ゴーゴージャグラー', 'アイムジャグラー', 'ファンキージャグラー', 'ハナビ', 'ディスクアップ', 'バーサス'];
  const stores = ['nagamachiminami', 'saiwaichou'];
  const lastDay = new Date(Date.UTC(2026, 10, 17));
  const dayList = [];
  for (let i = days - 1; i >= 0; i--) dayList.push(new Date(lastDay - i * 864e5).toISOString().slice(0, 10));
  const row = (day, rack, extra = 0) => {
    const games = 2000 + Math.floor(rand() * 6000), bb = Math.floor(games / 300 * (0.7 + rand() * 0.6)), rb = Math.floor(bb * (0.4 + rand() * 0.5));
    return {store: stores[rack % 2], day, machine: machines[rack % machines.length], rack: 1000 + Math.floor(rack / 2), games, bb, rb,
      at_art: 0, max_hold: Math.floor(rand() * 3000), my: Math.floor(rand() * 4000 - 2000), net_medals: Math.floor(rand() * 4000 - 2000),
      detail_url: `https://example.invalid/graph?day=${day}&rack=${rack}`,
      graph_measurement: {baseline_y: 100, peak_y: Math.floor(rand() * 100), trough_y: Math.floor(rand() * 100), end_y: Math.floor(rand() * 100),
        curve_index: rack, x_min: 0, x_max: games, confidence: 'measured', calibration: [0, 100, 200], note: ''},
      filler: ''.padEnd(extra, 'x')};
  };
  // 1記録あたり約420文字（実データの約7.9万件・約3,360万文字から）に合わせて、埋め草の長さを決める。
  const probe = JSON.stringify(row(dayList[0], 0)).length, filler = Math.max(0, 420 - probe);
  const hash = async text => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))].map(b => b.toString(16).padStart(2, '0')).join('');
  const header = exported => ({format: 'database-backup', version: 1, source: 'pc-viewer', exported_at: exported, date_events: [], machines: []});
  const parts = [], texts = {}, records = [];
  for (const day of dayList) {
    const rows = []; for (let r = 0; r < perDay; r++) rows.push(row(day, r, filler));
    const text = JSON.stringify(rows), h = await hash(text);
    texts[h] = text; parts.push({hash: h, day, count: rows.length, bytes: new TextEncoder().encode(text).length});
    for (const x of rows) records.push(x);
  }
  const manifest = (list, exported) => ({format: 'database-viewer-parts', version: 2, site: 'meruhen', revision: '', header: header(exported),
    parts: list, days: dayList, count: list.reduce((a, p) => a + p.count, 0)});
  const old = manifest(parts, oldExport); old.revision = await hash(JSON.stringify(parts));
  // 新しい書き出し：最新の日が1日分だけ変わる（記録が20台ふえる）。
  const lastRows = JSON.parse(texts[parts.at(-1).hash]); for (let r = perDay; r < perDay + 20; r++) lastRows.push(row(dayList.at(-1), r, filler));
  const changedText = JSON.stringify(lastRows), changedHash = await hash(changedText);
  const newParts = parts.slice(0, -1).concat([{hash: changedHash, day: dayList.at(-1), count: lastRows.length, bytes: new TextEncoder().encode(changedText).length}]);
  const fresh = manifest(newParts, newExport); fresh.revision = await hash(JSON.stringify(newParts));
  // 端末に前回の状態を作る：本体（保存した全文）・日別キャッシュ・更新の目印。
  const body = JSON.stringify({header: header(oldExport), records, candidates: [], date_events: [], history_days: dayList, file: 'Googleドライブ（自動）', loaded_at: oldExport});
  const open = (name, version, stores) => new Promise((resolve, reject) => {
    const q = indexedDB.open(name, version); q.onupgradeneeded = () => { for (const s of stores) if (!q.result.objectStoreNames.contains(s)) q.result.createObjectStore(s); };
    q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error);
  });
  const done = tx => new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onerror = tx.onabort = () => reject(tx.error); });
  const kv = await open('database-viewer', 1, ['kv']); let tx = kv.transaction('kv', 'readwrite'); tx.objectStore('kv').put(body, 'data'); await done(tx); kv.close();
  const key = url + '|meruhen', cache = await open('database-viewer-parts-v1', 2, ['snapshots', 'history-heads', 'history-days']);
  tx = cache.transaction(['history-heads', 'history-days'], 'readwrite');
  for (const p of parts) tx.objectStore('history-days').put({parts: {[p.hash]: texts[p.hash]}}, key + '|' + p.day);
  tx.objectStore('history-heads').put({header: {...old.header, parts_at: oldExport}, days: dayList, revision: 1}, key); await done(tx); cache.close();
  localStorage.setItem('database-viewer-remote', url);
  localStorage.setItem('database-viewer-drive-version-meruhen', JSON.stringify({version: 'parts:' + old.revision, exported_at: oldExport}));
  return {old, fresh, changed: {hash: changedHash, text: changedText}, records: records.length, bodyChars: body.length, avgRecordChars: Math.round(body.length / records.length)};
};

const profileFor = name => path.join(work, name);
const launch = (dir, limited = false) => chromium.launchPersistentContext(dir, {headless: true, executablePath: process.env.CHROMIUM_PATH || undefined,
  args: ['--no-sandbox', '--enable-precise-memory-info', ...(limited && process.env.HEAP_LIMIT ? [`--js-flags=--max-old-space-size=${process.env.HEAP_LIMIT}`] : [])], viewport: {width: 393, height: 852}});
let fixture;
{
  const context = await launch(profileFor('template')), page = await context.newPage();
  await page.goto(origin + '/setup');
  fixture = await page.evaluate(seed, {url: SCRIPT, days: DAYS, perDay: PER_DAY, oldExport: OLD_EXPORT, newExport: NEW_EXPORT});
  await context.close();
}
console.log(`合成データ：${fixture.records}件・${DAYS}日・本体${fixture.bodyChars}文字（1件あたり約${fixture.avgRecordChars}文字）`);

function processPeaks(dir) {
  const script = `$d = '${dir.replaceAll('\\', '\\\\').replaceAll("'", "''")}'; ` +
    `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*--type=renderer*' } | ` +
    `ForEach-Object { $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; if ($p) { '{0},{1},{2}' -f $p.Id, $p.PeakWorkingSet64, $p.PeakPagedMemorySize64 } }`;
  const text = execFileSync('powershell', ['-NoProfile', '-Command', script], {encoding: 'utf8'});
  return text.trim().split(/\r?\n/).filter(Boolean).map(line => { const [pid, ws, commit] = line.split(',').map(Number); return {pid, peakWorkingSet: ws, peakCommit: commit}; });
}

async function run(scenario, index) {
  const dir = profileFor(`${scenario}-${index}`);
  await fs.cp(profileFor('template'), dir, {recursive: true});
  const context = await launch(dir, true), page = context.pages()[0] || await context.newPage();
  const requests = [], errors = [];
  let crashed = false;
  page.on('pageerror', e => errors.push(e.message));
  page.on('crash', () => { crashed = true; });
  const manifest = scenario === 'unchanged' ? fixture.old : fixture.fresh;
  await context.route('https://script.google.com/**', route => {
    const url = new URL(route.request().url()), headers = {'access-control-allow-origin': '*'}, json = body => route.fulfill({status: 200, contentType: 'application/json', headers, body: JSON.stringify(body)});
    requests.push(url.search || '(本体)'); marks.push([Date.now() - started, (url.search || '(本体)').slice(0, 24)]);
    if (url.searchParams.has('check')) return json({format: 'drive-check', version: 'parts:' + manifest.revision, parts: manifest});
    if (url.searchParams.has('parts')) {
      assert.equal(url.searchParams.get('revision'), manifest.revision);
      const hashes = url.searchParams.get('parts').split(',');
      return json({format: 'database-viewer-parts', revision: manifest.revision, parts: hashes.map(h => { assert.equal(h, fixture.changed.hash); return {hash: h, text: fixture.changed.text}; })});
    }
    if (url.searchParams.has('file')) return json({error: 'この測定では共有ファイルを返しません。'});
    return json({error: 'この測定では全文を返しません。'});
  });
  const session = await context.newCDPSession(page);
  let heapPeak = 0, totalPeak = 0, samples = 0, busy = false;
  const series = [], marks = [];
  const sample = async () => {
    if (busy) return; busy = true;
    try { const h = await session.send('Runtime.getHeapUsage'); heapPeak = Math.max(heapPeak, h.usedSize); series.push([Date.now() - started, h.usedSize]); totalPeak = Math.max(totalPeak, h.totalSize); samples++; }
    catch { /* 読み込み中は読めないことがある */ } finally { busy = false; }
  };
  const started = Date.now(), timer = setInterval(sample, 10);
  await page.goto(origin + prefix);
  // 「Googleドライブの更新」の区切りが最後まで終わったら（診断の記録）、1回分が終わったとする。
  let finished = false;
  for (let i = 0; i < 1200 && !finished && !crashed; i++) {
    await page.waitForTimeout(250);
    finished = await page.evaluate(() => { try { const log = JSON.parse(localStorage.getItem('database-viewer-diag')); return !!log?.phases?.drive?.count && !log.running; } catch { return false; } }).catch(() => false);
  }
  const elapsedMs = Date.now() - started;
  if (process.env.DETAIL) {
    // 250msごとの使用量の最大（MiB）と、Googleへの通信の時刻。どの処理で山ができたかを見る（測定の補助）。
    const buckets = new Map(); for (const [t, v] of series) { const b = Math.floor(t / 250) * 250; buckets.set(b, Math.max(buckets.get(b) ?? 0, v)); }
    console.log('  通信：' + marks.map(([t, q]) => `${t}ms ${q}`).join(' / '));
    console.log('  ヒープ：' + [...buckets].map(([t, v]) => `${t}:${Math.round(v / 1048576)}`).join(' '));
  }
  if (crashed) { clearInterval(timer); await context.close(); return {scenario, run: index, crashed: true, elapsedMs, heapPeakMiB: +(heapPeak / 1048576).toFixed(1)}; }
  await page.waitForTimeout(1500); clearInterval(timer);
  // 終わったあとにガベージコレクションをかけて残った量（生きている量）。山との差が、一時的な山の大きさ。
  await session.send('HeapProfiler.collectGarbage'); const retained = (await session.send('Runtime.getHeapUsage')).usedSize;
  const unfinished = !finished;
  // 保存された本文（更新後）：件数と、変わった日の件数。直す前後で同じになることを確かめるために残す。
  const stored = await page.evaluate(async () => {
    const db = await new Promise((resolve, reject) => { const q = indexedDB.open('database-viewer', 1); q.onsuccess = () => resolve(q.result); q.onerror = () => reject(q.error); });
    const text = await new Promise((resolve, reject) => { const r = db.transaction('kv').objectStore('kv').get('data'); r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
    db.close();
    const doc = JSON.parse(text), last = doc.records.reduce((a, r) => r.day > a ? r.day : a, '');
    return {chars: text.length, records: doc.records.length, lastDay: last, lastDayRecords: doc.records.filter(r => r.day === last).length, exportedAt: doc.header?.exported_at ?? null};
  });
  // 描画用プロセスのピークは、ブラウザを閉じる前に読む。このページの描画用プロセスは、いちばん大きいもの。
  const peaks = processPeaks(dir), top = peaks.reduce((a, b) => b.peakWorkingSet > (a?.peakWorkingSet ?? 0) ? b : a, null);
  const row = {scenario, run: index, elapsedMs, unfinished, errors, requests: requests.length, heapPeakMiB: +(heapPeak / 1048576).toFixed(1), heapTotalPeakMiB: +(totalPeak / 1048576).toFixed(1), retainedAfterGcMiB: +(retained / 1048576).toFixed(1), samples,
    rendererPeakWorkingSetMiB: top ? +(top.peakWorkingSet / 1048576).toFixed(1) : null, rendererPeakCommitMiB: top ? +(top.peakCommit / 1048576).toFixed(1) : null, rendererCount: peaks.length, stored};
  await context.close();
  return row;
}

const results = [];
try {
  for (const scenario of (process.env.SCENARIOS || 'unchanged,changed1').split(',')) {
    for (let i = 1; i <= RUNS; i++) {
      const row = await run(scenario, i);
      results.push(row);
      if (row.crashed) { console.log(`${scenario} #${i}：ページが落ちた（ヒープ上限 ${process.env.HEAP_LIMIT}MB）`); continue; }
      console.log(`${scenario} #${i}：${row.elapsedMs}ms、JSヒープ最大${row.heapPeakMiB}MiB（確保${row.heapTotalPeakMiB}MiB、終了後の残り${row.retainedAfterGcMiB}MiB）、描画プロセスのピーク${row.rendererPeakWorkingSetMiB}MiB（コミット${row.rendererPeakCommitMiB}MiB）、通信${row.requests}回、保存${row.stored.records}件${row.unfinished ? '、最後まで終わらず' : ''}`);
    }
  }
} finally {
  await fs.writeFile(output, JSON.stringify({environment: {node: process.version, platform: process.platform, root, runs: RUNS, days: DAYS, perDay: PER_DAY,
    records: fixture.records, bodyChars: fixture.bodyChars}, results}, null, 2) + '\n');
  await new Promise(resolve => server.close(resolve));
  await fs.rm(work, {recursive: true, force: true}).catch(() => {});
}
