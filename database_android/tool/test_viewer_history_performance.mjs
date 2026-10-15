// Long-history regression: every record is preserved; IndexedDB JSON is read
// one day at a time instead of loading every encoded day alongside the model.
import assert from 'node:assert/strict';
import test from 'node:test';
import http from 'node:http';
import {readFile} from 'node:fs/promises';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const moduleText = await readFile(new URL('../web/viewer_parts.mjs', import.meta.url), 'utf8');
const server = http.createServer((request, response) => {
  response.setHeader('content-type', request.url.endsWith('.mjs') ? 'text/javascript' : 'text/html');
  response.end(request.url.endsWith('.mjs') ? moduleText : '<!doctype html><title>history fixture</title>');
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  for (const years of [1, 3]) await test(`${years}年分の履歴を欠落なく日単位で読む`, async () => {
    const context = await browser.newContext(), page = await context.newPage();
    try {
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      const result = await page.evaluate(async years => {
        const {rememberViewerHistory, readViewerHistory} = await import('./viewer_parts.mjs');
        const url = 'https://example.test/exec', days = years * 365, records = [];
        for (let i = 0; i < days; i++) {
          const day = new Date(Date.UTC(2023, 0, i + 1)).toISOString().slice(0, 10);
          for (let rack = 1; rack <= 50; rack++) records.push({store: 'saiwaichou', day, machine: '履歴試験', rack, games: i + rack, bb: 10, rb: 5});
        }
        await rememberViewerHistory(url, 'meruhen', {format: 'database-backup', version: 1, exported_at: '2026-10-15T00:00:00Z', records});
        const original = IDBObjectStore.prototype.get;
        let pending = 0, peak = 0;
        IDBObjectStore.prototype.get = function (...args) {
          const request = original.apply(this, args);
          if (this.name === 'history-days') {
            peak = Math.max(peak, ++pending);
            request.addEventListener('success', () => pending--, {once: true});
            request.addEventListener('error', () => pending--, {once: true});
          }
          return request;
        };
        const started = performance.now();
        const doc = await readViewerHistory(url, 'meruhen');
        const elapsed = performance.now() - started;
        IDBObjectStore.prototype.get = original;
        if (JSON.stringify(doc.records) !== JSON.stringify(records)) throw new Error('全期間の内容が変わりました');
        // A concurrent tab changing the head must never return a mixed snapshot.
        let changed = false;
        IDBObjectStore.prototype.get = function (...args) {
          const request = original.apply(this, args);
          if (this.name === 'history-days' && !changed) {
            changed = true;
            const db = this.transaction.db;
            request.addEventListener('success', () => {
              const tx = db.transaction('history-heads', 'readwrite'), heads = tx.objectStore('history-heads');
              const head = heads.get(url + '|meruhen');
              head.onsuccess = () => heads.put({...head.result, revision: (head.result.revision || 0) + 1}, url + '|meruhen');
            }, {once: true});
          }
          return request;
        };
        let rejected = false;
        try { await readViewerHistory(url, 'meruhen'); } catch (error) { rejected = /履歴が更新/.test(error.message); }
        finally { IDBObjectStore.prototype.get = original; }
        if (!rejected) throw new Error('同時更新した履歴が混ざって返りました');
        return {days: doc.history_days.length, records: doc.records.length, peak, elapsed_ms: Math.round(elapsed)};
      }, years);
      assert.equal(result.days, years * 365);
      assert.equal(result.records, years * 365 * 50);
      assert.equal(result.peak, 1, '全日分のJSONを同時に取得しない');
      console.log(`history benchmark (desktop Chromium): ${JSON.stringify(result)}`);
    } finally { await context.close(); }
  });
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
