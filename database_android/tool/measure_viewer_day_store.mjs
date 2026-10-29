// 実データ・外部通信なし。例: node .../measure_viewer_day_store.mjs work/day-measure.json
import fs from 'node:fs/promises';
import {performance} from 'node:perf_hooks';
import {dayStoreBrowser} from './viewer_day_store_fixture.mjs';
const output = process.argv[2];
if (!output) throw Error('結果JSONの保存先を指定してください。');
const sizes = process.argv.slice(3).map(Number);
if (sizes.some(n => !Number.isInteger(n) || n < 2)) throw Error('日数が不正です。');
const results = [];
async function measure(env, days, name, action) {
  const {page, browser} = env, session = await page.context().newCDPSession(page);
  const system = await browser.newBrowserCDPSession();
  const renderers = (await system.send('SystemInfo.getProcessInfo')).processInfo.filter(p => p.type === 'renderer').map(p => p.id);
  let rssPeak = 0, heapPeak = 0, samples = 0, busy = false;
  const sample = async () => {
    if (busy) return; busy = true;
    try {
      const values = await Promise.all(renderers.map(async pid => {
        try { const status = await fs.readFile(`/proc/${pid}/status`, 'utf8'); return Number(status.match(/^VmRSS:\s+(\d+)/m)?.[1] || 0) * 1024; } catch { return 0; }
      }));
      rssPeak = Math.max(rssPeak, values.reduce((a, b) => a + b, 0)); samples++;
    } finally { busy = false; }
  };
  await page.evaluate(() => {
    window.gc?.(); io.length = 0;
    window.heapSamples = [performance.memory?.usedJSHeapSize || 0];
    window.heapTimer = setInterval(() => heapSamples.push(performance.memory?.usedJSHeapSize || 0), 10);
  });
  const initialHeap = (await session.send('Runtime.getHeapUsage')).usedSize;
  await sample(); const initialRSS = rssPeak, timer = setInterval(sample, 10), started = performance.now();
  let outcome;
  try { outcome = await action(); }
  finally { clearInterval(timer); await sample(); }
  const elapsedMs = performance.now() - started;
  const telemetry = await page.evaluate(() => {
    clearInterval(heapTimer); heapSamples.push(performance.memory?.usedJSHeapSize || 0);
    return {heapPeak: Math.max(...heapSamples), heapSamples: heapSamples.length,
      bodyReads: io.filter(x => x.store === 'bodies' && x.method === 'get').length,
      bodyWrites: io.filter(x => x.store === 'bodies' && x.method === 'put').length,
      oldDayReads: io.filter(x => x.store === 'history-days' && x.method === 'get').length,
      oldDayWrites: io.filter(x => x.store === 'history-days' && x.method === 'put').length};
  });
  heapPeak = telemetry.heapPeak; delete telemetry.heapPeak;
  const storage = await page.evaluate(() => navigator.storage.estimate());
  const row = {storageUsageBytes: storage.usage, days, records: days * 770, scenario: name, elapsedMs, initialHeap, heapPeak,
    initialRendererRSS: initialRSS, rendererRSSPeak: rssPeak, rssSamples: samples, ...telemetry, ...outcome};
  results.push(row); await fs.writeFile(output, JSON.stringify({environment: {node: process.version, platform: process.platform,
    browser: browser.version(), sampleIntervalMs: 10, worker: false}, results}, null, 2) + '\n');
  await session.detach(); await system.detach();
  console.log(`${days}日 ${name}: ${Math.round(elapsedMs)}ms、ヒープ観測最大 ${(heapPeak / 1048576).toFixed(1)}MiB`);
}
for (const days of sizes.length ? sizes : [60, 180, 365]) {
  // 移行時は旧本文を保持。文字列の生成自体は測定外。全文解析モデルを常駐させない。
  let env = await dayStoreBrowser();
  try {
    await env.page.evaluate(days => { window.text = legacyText(days); window.store = module.createViewerDayStore({dbName: 'measure-migration'}); }, days);
    const bodyBytes = await env.page.evaluate(() => new TextEncoder().encode(text).length);
    await measure(env, days, '初回移行', async () => {
      const result = await env.page.evaluate(async () => { const h = await store.migrateLegacy(key, {text, site: 'meruhen'}); return {status: h.migration.status, verifiedRecords: h.migration.totalRecords}; });
      return {bodyBytes, ...result};
    });
    await env.page.evaluate(async days => { window.resume = module.createViewerDayStore({dbName: 'measure-resume'}); await resume.migrateLegacy(key, {text, site: 'meruhen', maxDays: Math.floor(days / 2)}); }, days);
    await measure(env, days, '半分から再開', async () => ({bodyBytes, ...await env.page.evaluate(async () => {
      const h = await resume.migrateLegacy(key, {text, site: 'meruhen'}); return {status: h.migration.status, verifiedRecords: h.migration.totalRecords};
    })}));
    await measure(env, days, '移行再実行と全日照合', async () => ({bodyBytes, ...await env.page.evaluate(async () => {
      const before = await store.inspect(key), after = await store.migrateLegacy(key, {text, site: 'meruhen'});
      if (before.revision !== after.revision) throw Error('再実行で確定版が変わった'); return {verifiedRecords: after.migration.totalRecords};
    })}));
  } finally { await env.close(); }
  env = await dayStoreBrowser();
  try {
    await env.page.evaluate(days => { window.text = legacyText(days); }, days);
    const bodyBytes = await env.page.evaluate(() => new TextEncoder().encode(text).length);
    await measure(env, days, '現行・旧本文引継ぎ', async () => ({bodyBytes, ...await env.page.evaluate(async () => {
      await module.rememberViewerHistory(endpoint, 'meruhen', JSON.parse(text)); return {legacyRetained: true};
    })}));
  } finally { await env.close(); }
  // 新APIの通常利用は旧本文・移行用位置一覧を持たない新ブラウザで測る。
  env = await dayStoreBrowser();
  try {
    await env.page.evaluate(async days => { window.f = await fixture(days); window.store = module.createViewerDayStore({dbName: 'measure-normal'}); }, days);
    const bodyBytes = await env.page.evaluate(() => f.manifest.parts.reduce((n, p) => n + p.bytes, 0));
    await measure(env, days, '新API・部品初回保存', async () => ({bodyBytes, ...await env.page.evaluate(async () => {
      await store.syncParts(endpoint, 'meruhen', f.manifest, f.get); return f.stats();
    })}));
    await measure(env, days, '新API・更新なし', async () => ({bodyBytes, ...await env.page.evaluate(async () => {
      const h = await store.inspect(key); await store.syncParts(endpoint, 'meruhen', f.manifest, () => { throw Error('不要な通信'); });
      return {requests: 0, unchanged: h.revision === (await store.inspect(key)).revision};
    })}));
    await env.page.evaluate(async days => { window.changed = await fixture(days, 770, days - 1); }, days);
    await measure(env, days, '新API・1日更新', async () => ({bodyBytes, ...await env.page.evaluate(async () => {
      await store.syncParts(endpoint, 'meruhen', changed.manifest, changed.get); return changed.stats();
    })}));
    await measure(env, days, '新API・7日1店舗読込', async () => ({bodyBytes, ...await env.page.evaluate(async days => {
      const read = await store.readRange(key, {from: dayAt(days - 7), to: dayAt(days - 1), stores: ['saiwaichou']});
      return {loadedDays: read.length, loadedRecords: read.reduce((n, d) => n + d.records.length, 0)};
    }, days)}));
  } finally { await env.close(); }
  // 現行経路の実IndexedDBとv2部品を模擬。FlutterのprepareMergeは含まない。
  env = await dayStoreBrowser();
  try {
    await env.page.evaluate(async days => { window.f = await fixture(days); }, days);
    const bodyBytes = await env.page.evaluate(() => f.manifest.parts.reduce((n, p) => n + p.bytes, 0));
    await measure(env, days, '現行・部品初回読込', async () => ({bodyBytes, ...await env.page.evaluate(async () => {
      const doc = await module.fetchViewerParts(endpoint, 'meruhen', f.manifest, f.get); return {loadedRecords: doc.records.length, ...f.stats()};
    })}));
    await measure(env, days, '現行・更新なし', async () => ({bodyBytes, ...await env.page.evaluate(async () => {
      const doc = await module.fetchViewerParts(endpoint, 'meruhen', f.manifest, () => { throw Error('不要な通信'); }); return {loadedRecords: doc.records.length, requests: 0};
    })}));
    await env.page.evaluate(async days => { window.changed = await fixture(days, 770, days - 1); }, days);
    await measure(env, days, '現行・1日更新', async () => ({bodyBytes, ...await env.page.evaluate(async () => {
      const doc = await module.fetchViewerParts(endpoint, 'meruhen', changed.manifest, changed.get); return {loadedRecords: doc.records.length, ...changed.stats()};
    })}));
  } finally { await env.close(); }
}
