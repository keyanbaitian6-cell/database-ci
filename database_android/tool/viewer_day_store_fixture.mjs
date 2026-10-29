// 合成データ専用。試験と測定で同じv2部品分け条件を使う。
import http from 'node:http';
import fs from 'node:fs/promises';
export async function dayStoreBrowser() {
  const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
  const code = await fs.readFile(new URL('../web/viewer_parts.mjs', import.meta.url));
  const server = http.createServer((req, res) => {
    res.setHeader('content-type', req.url === '/viewer_parts.mjs' ? 'text/javascript' : 'text/html');
    res.end(req.url === '/viewer_parts.mjs' ? code : '<!doctype html><meta charset="utf-8"><title>日別保存試験</title>');
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  let browser;
  try {
    browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || undefined,
      args: ['--no-sandbox', '--enable-precise-memory-info', '--js-flags=--expose-gc']});
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.evaluate(async () => {
      window.module = await import('/viewer_parts.mjs');
      window.hash = async text => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))].map(b => b.toString(16).padStart(2, '0')).join('');
      window.dayAt = i => new Date(Date.UTC(2025, 0, 1 + i)).toISOString().slice(0, 10);
      window.rowsAt = (i, count = 770, changed = false) => Array.from({length: count}, (_, n) => ({
        day: dayAt(i), store: n % 2 ? 'saiwaichou' : 'nagamachi', machine: `合成機種${n % 10}`, rack: n + 1,
        games: 5000 + n, bb: 20, rb: 10, net_medals: changed && n === 0 ? 999 : n - 300,
        rainbow: false, rainbow_at: '2026-01-01T00:00:00Z', record_updated_at: '2026-01-01T00:00:00Z',
        graph_measurement: {baseline_y: 100, peak_y: 20, end_y: 50, curve_index: n},
        synthetic_note: '合成測定用'.repeat(15)}));
      window.header = {format: 'database-backup', version: 1, exported_at: '2026-01-01T00:00:00Z',
        date_events: [{store: 'saiwaichou', day: dayAt(0), name: null, updated_at: '2026-01-02T00:00:00Z'}],
        rainbow_marks: [{store: 'saiwaichou', day: dayAt(0), rack: 2, on: false, updated_at: '2026-01-02T00:00:00Z'}],
        record_deletions: [{store: 'saiwaichou', day: dayAt(0), machine: '旧機種', rack: 9, deleted_at: '2026-01-02T00:00:00Z'}]};
      window.fixture = async (days, count = 770, changed = -1, site = 'meruhen') => {
        const parts = [];
        for (let i = 0; i < days; i++) {
          // 1日を2部品に分ける。本文は必要になったときだけ再生成する。
          const rows = rowsAt(i, count, changed === i);
          for (let half = 0; half < 2; half++) {
            const text = JSON.stringify(rows.slice(half * Math.ceil(count / 2), (half + 1) * Math.ceil(count / 2)));
            parts.push({hash: await hash(text), day: dayAt(i), count: JSON.parse(text).length, bytes: new TextEncoder().encode(text).length});
          }
        }
        const manifest = {format: 'database-viewer-parts', version: 2, site, days: Array.from({length: days}, (_, i) => dayAt(i)),
          header: {...header, format: site === 'meruhen' ? 'database-backup' : 'pscube-viewer', exported_at: changed < 0 ? header.exported_at : '2026-01-02T00:00:00Z'},
          revision: await hash(JSON.stringify(parts)), parts, count: days * count,
          curve_parts: [{day: dayAt(0), hash: 'c'.repeat(64), bytes: 32, count: 1}]};
        let requests = 0, bytes = 0;
        return {manifest, stats: () => ({requests, bytes}), get: async url => {
          const p = new URL(url).searchParams;
          if (p.has('curves')) throw new Error('詳細な線を要求しました');
          requests++;
          return {format: manifest.format, revision: manifest.revision, parts: p.get('parts').split(',').map(h => {
            const index = parts.findIndex(p => p.hash === h), i = Math.floor(index / 2), half = index % 2;
            const text = JSON.stringify(rowsAt(i, count, changed === i).slice(half * Math.ceil(count / 2), (half + 1) * Math.ceil(count / 2)));
            bytes += new TextEncoder().encode(text).length; return {hash: h, text};
          })};
        }};
      };
      window.legacyText = (days, count = 770) => {
        const chunks = [];
        for (let i = 0; i < days; i++) chunks.push(JSON.stringify(rowsAt(i, count)).slice(1, -1));
        return JSON.stringify(header).slice(0, -1) + ',"records":[' + chunks.join(',') + ']}';
      };
      window.key = 'https://example.invalid/viewer|meruhen';
      window.endpoint = 'https://example.invalid/viewer';
      window.io = [];
      for (const method of ['get', 'getAll', 'openCursor', 'put']) {
        const original = IDBObjectStore.prototype[method];
        IDBObjectStore.prototype[method] = function(...args) {
          io.push({store: this.name, method, key: method === 'put' ? args[1] : args[0]});
          return original.apply(this, args);
        };
      }
    });
    return {browser, page, close: async () => { await browser.close(); await new Promise(r => server.close(r)); }};
  } catch (e) { await browser?.close(); server.close(); throw e; }
}
