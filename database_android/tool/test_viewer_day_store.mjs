// 通常ゲートのtest_*.mjs配置。合成データと実Chromium IndexedDBだけで検証する。
import test from 'node:test';
import assert from 'node:assert/strict';
import {dayStoreBrowser} from './viewer_day_store_fixture.mjs';
let env;
test.before(async () => { env = await dayStoreBrowser(); });
test.after(async () => { await env?.close(); });
const run = fn => env.page.evaluate(fn);

test('日・店舗の範囲外の本文を読まず、1日更新でも過去本文を読まない', async () => {
  const result = await run(async () => {
    const s = module.createViewerDayStore({dbName: 'range'}), f = await fixture(60, 20);
    const first = await s.syncParts(endpoint, 'meruhen', f.manifest, f.get);
    io.length = 0;
    const chosen = await s.readRange(key, {days: [dayAt(3)], stores: ['saiwaichou']});
    const reads = io.filter(x => x.store === 'bodies' && x.method === 'get');
    const expected = JSON.stringify([key, first.days[dayAt(3)].shards.find(s => s.store === 'saiwaichou').hash]);
    io.length = 0;
    const same = await s.syncParts(endpoint, 'meruhen', f.manifest, () => { throw Error('不要な通信'); });
    const unchangedIO = io.slice();
    io.length = 0;
    const fresh = await fixture(60, 20, 59), updated = await s.syncParts(endpoint, 'meruhen', fresh.manifest, fresh.get);
    return {chosen, reads, expected, unchangedIO, same: same.revision === first.revision,
      updated: updated.revision, io: io.slice(), stats: fresh.stats(), oldHash: first.days[dayAt(0)], newHash: updated.days[dayAt(0)]};
  });
  assert.equal(result.chosen[0].records.length, 10);
  assert.deepEqual(result.reads.map(r => r.key), [result.expected]);
  assert.equal(result.same, true);
  assert.equal(result.unchangedIO.filter(r => r.store === 'bodies' || r.method === 'put').length, 0);
  assert.equal(result.stats.requests, 1);
  assert.deepEqual(result.oldHash, result.newHash);
  assert.equal(result.io.filter(r => r.method === 'getAll' || r.method === 'openCursor').length, 0);
  // 書き戻し照合だけ。旧日・同日の他店舗の本文は読まない。
  assert.equal(result.io.filter(r => r.store === 'bodies' && r.method === 'get').length, 3);
});

test('移行の中断・再開・再実行でキーと全項目・印・削除情報を保持する', async () => {
  const r = await run(async () => {
    const s = module.createViewerDayStore({dbName: 'migration'}), text = legacyText(8, 20);
    const before = await hash(text), partial = await s.migrateLegacy(key, {text, site: 'meruhen', maxDays: 3});
    let blocked; try { await s.writeDays(key, {expectedRevision: partial.revision}); } catch (e) { blocked = e.code; }
    // 別インスタンス＝タブ終了後の再起動に相当する接続で続きを実行。
    const next = module.createViewerDayStore({dbName: 'migration'});
    const completed = await next.migrateLegacy(key, {text, site: 'meruhen'});
    const rows = (await next.readRange(key, {from: dayAt(0), to: dayAt(7)})).flatMap(d => d.records);
    const sort = rows => rows.sort((a, b) => JSON.stringify([a.day, a.store, a.rack]).localeCompare(JSON.stringify([b.day, b.store, b.rack])));
    const canonical = v => Array.isArray(v) ? v.map(canonical) : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v).sort().map(k => [k, canonical(v[k])])) : v;
    const equal = JSON.stringify(canonical(sort(rows))) === JSON.stringify(canonical(sort(JSON.parse(text).records)));
    const meta = await next.readMetadata(key, 'legacy'), repeated = await next.migrateLegacy(key, {text, site: 'meruhen'});
    return {partial: partial.migration, complete: completed.migration, equal, meta, header, blocked,
      sameRevision: repeated.revision === completed.revision, intact: before === await hash(text)};
  });
  assert.equal(Object.keys(r.partial.receipts).length, 3);
  assert.equal(r.partial.status, 'running'); assert.equal(r.complete.status, 'complete');
  assert.equal(r.equal, true); assert.equal(r.intact, true); assert.equal(r.sameRevision, true);
  assert.equal(r.blocked, 'migration-running'); assert.deepEqual(r.meta, r.header);
});

test('未取得・完成した空の日・明示削除・Google期間外を区別する', async () => {
  const r = await run(async () => {
    const s = module.createViewerDayStore({dbName: 'states'}), f = await fixture(3, 4);
    let head = await s.syncParts(endpoint, 'meruhen', f.manifest, f.get);
    head = await s.writeDays(key, {expectedRevision: head.revision, updates: {
      [dayAt(1)]: {state: 'complete', records: []}, [dayAt(2)]: {state: 'deleted', records: [], deleted_at: '2026-01-03T00:00:00Z'}}});
    const m = {...f.manifest, days: [dayAt(1)], parts: [], curve_parts: [], count: 0, revision: 'd'.repeat(64), header: {...header, exported_at: '2026-01-04T00:00:00Z'}};
    await s.syncParts(endpoint, 'meruhen', m, () => { throw Error('空の日に通信'); });
    return await s.readRange(key, {days: [dayAt(0), dayAt(1), dayAt(2), dayAt(3)]});
  });
  assert.deepEqual(r.map(d => d.state), ['complete', 'empty', 'deleted', 'unfetched']);
  assert.equal(r[0].records.length, 4); assert.equal(r[2].deleted_at, '2026-01-03T00:00:00Z');
});

test('取得失敗・不正な部品・古い遅延応答では確定版を変更しない', async () => {
  const r = await run(async () => {
    const s = module.createViewerDayStore({dbName: 'network'}), f = await fixture(3, 4);
    const head = await s.syncParts(endpoint, 'meruhen', f.manifest, f.get), fresh = await fixture(3, 4, 2), errors = [];
    for (const get of [() => { throw Error('通信失敗'); }, async url => { const v = await fresh.get(url); v.parts[0].text = '[]'; return v; }]) {
      try { await s.syncParts(endpoint, 'meruhen', fresh.manifest, get); } catch (e) { errors.push(e.code || e.message); }
    }
    const intact = (await s.inspect(key)).revision === head.revision;
    await s.syncParts(endpoint, 'meruhen', fresh.manifest, fresh.get);
    try { await s.syncParts(endpoint, 'meruhen', f.manifest, f.get); } catch (e) { errors.push(e.code); }
    return {intact, errors};
  });
  assert.equal(r.intact, true); assert.deepEqual(r.errors, ['通信失敗', 'corrupt', 'stale']);
});

test('別接続の競合と遅延完了はCASで止まり、読みかけの範囲は同じ版を保つ', async () => {
  const r = await run(async () => {
    const s = module.createViewerDayStore({dbName: 'race'}), other = module.createViewerDayStore({dbName: 'race'}), f = await fixture(3, 4);
    const head = await s.syncParts(endpoint, 'meruhen', f.manifest, f.get);
    const stream = s.streamRange(key, {days: [dayAt(0), dayAt(1)]}), first = (await stream.next()).value;
    const results = await Promise.allSettled([s, other].map((client, i) => client.writeDays(key, {expectedRevision: head.revision,
      updates: {[dayAt(1)]: {state: 'complete', records: [{...rowsAt(1, 4)[0], bb: 80 + i}]}}})));
    const second = (await stream.next()).value;
    return {states: results.map(r => r.status), errors: results.filter(r => r.status === 'rejected').map(r => r.reason.code),
      first: first.revision, second: second.revision, count: second.records.length, head: (await s.inspect(key)).revision};
  });
  assert.equal(r.states.filter(s => s === 'fulfilled').length, 1); assert.deepEqual(r.errors, ['conflict']);
  assert.equal(r.first, r.second); assert.equal(r.count, 4); assert.equal(r.head, r.first + 1);
});

test('容量不足・索引確定時のabortで旧本文と前回確定内容を保持する', async () => {
  const r = await run(async () => {
    const s = module.createViewerDayStore({dbName: 'failure'}), text = legacyText(3, 4);
    const partial = await s.migrateLegacy(key, {text, site: 'meruhen', maxDays: 1}), before = await hash(text), errors = [];
    const put = IDBObjectStore.prototype.put;
    for (const failStore of ['bodies', 'heads']) {
      IDBObjectStore.prototype.put = function(...args) {
        if (this.name === failStore) { if (failStore === 'bodies') throw new DOMException('容量不足', 'QuotaExceededError'); this.transaction.abort(); }
        return put.apply(this, args);
      };
      try { await s.migrateLegacy(key, {text, site: 'meruhen'}); } catch (e) { errors.push(e.name); }
      finally { IDBObjectStore.prototype.put = put; }
      if ((await s.inspect(key)).revision !== partial.revision) throw Error('確定内容が変わった');
    }
    const done = await s.migrateLegacy(key, {text, site: 'meruhen'});
    return {errors, intact: before === await hash(text), done: done.migration.status};
  });
  assert.equal(r.errors.length, 2); assert.equal(r.errors[0], 'QuotaExceededError');
  assert.equal(r.intact, true); assert.equal(r.done, 'complete');
});

test('欠損・破損・移行元変更・重複キーを空と扱わない', async () => {
  const r = await run(async () => {
    const s = module.createViewerDayStore({dbName: 'corrupt'}), text = legacyText(3, 4);
    const h = await s.migrateLegacy(key, {text, site: 'meruhen', maxDays: 1}), errors = [];
    try { await s.migrateLegacy(key, {text: text + ' ', site: 'meruhen'}); } catch (e) { errors.push(e.code); }
    const ref = h.days[dayAt(0)].shards[0];
    async function damage(value) {
      await new Promise((resolve, reject) => { const req = indexedDB.open('corrupt', 1); req.onsuccess = () => {
        const db = req.result, tx = db.transaction('bodies', 'readwrite'), store = tx.objectStore('bodies'), id = JSON.stringify([key, ref.hash]);
        if (value === null) store.delete(id); else store.put(value, id);
        tx.oncomplete = () => { db.close(); resolve(); }; tx.onabort = () => reject(tx.error);
      }; });
    }
    for (const value of ['[]', null]) {
      await damage(value); try { await s.readRange(key, {days: [dayAt(0)]}); } catch (e) { errors.push(e.code); }
      try { await s.migrateLegacy(key, {text, site: 'meruhen'}); } catch (e) { errors.push(e.code); }
    }
    const bad = JSON.stringify({...header, records: [rowsAt(0, 4)[0], rowsAt(0, 4)[0]]});
    try { await module.createViewerDayStore({dbName: 'duplicate'}).migrateLegacy(key, {text: bad, site: 'meruhen'}); } catch (e) { errors.push(e.code); }
    return {errors, status: (await s.inspect(key)).migration.status};
  });
  assert.deepEqual(r.errors, ['source-changed', 'corrupt', 'corrupt', 'missing', 'missing', 'corrupt']);
  assert.equal(r.status, 'running');
});

// 2026-10-29 レビュー指摘1：途中の日の検査で落ちると running が確定済みのまま残り、再実行も通常更新もできなかった。
test('検査で落ちる旧本文は何も確定せず、未完了の移行は捨てて別の旧本文で始め直せる', async () => {
  const r = await run(async () => {
    const s = module.createViewerDayStore({dbName: 'abandon'}), days = [], errors = [];
    for (let i = 0; i < 3; i++) days.push(rowsAt(i, 4));
    days[2].push({...days[2][0]}); // 3日目にだけ同じキー
    try { await s.migrateLegacy(key, {text: JSON.stringify({...header, records: days.flat()}), site: 'meruhen'}); } catch (e) { errors.push(e.code); }
    const afterBad = await s.inspect(key);
    const partial = await s.migrateLegacy(key, {text: legacyText(3, 4), site: 'meruhen', maxDays: 1});
    const other = JSON.stringify({...header, exported_at: '2026-01-09T00:00:00Z', records: days.flat().slice(0, -1)});
    try { await s.migrateLegacy(key, {text: other, site: 'meruhen'}); } catch (e) { errors.push(e.code); }
    const abandoned = await s.abandonMigration(key);
    const gone = (await s.readRange(key, {days: [dayAt(0)]}))[0].state;
    const done = await s.migrateLegacy(key, {text: other, site: 'meruhen'});
    try { await s.abandonMigration(key); } catch (e) { errors.push(e.code); }
    try { await module.createViewerDayStore({dbName: 'abandon-none'}).abandonMigration(key); } catch (e) { errors.push(e.code); }
    return {errors, afterBad: {revision: afterBad.revision, migration: afterBad.migration ?? null},
      partialRevision: partial.revision, partial: partial.migration.status,
      abandoned: {revision: abandoned.revision, migration: abandoned.migration ?? null, days: Object.keys(abandoned.days).length,
        metadata: Object.keys(abandoned.metadata).length, prior: abandoned.abandonedMigration.days},
      gone, done: done.migration.status, total: done.migration.totalRecords,
      afterDone: (await s.readRange(key, {from: dayAt(0), to: dayAt(2)})).reduce((n, d) => n + d.records.length, 0)};
  });
  assert.deepEqual(r.errors, ['corrupt', 'source-changed', 'migration-complete', 'no-migration']);
  assert.deepEqual(r.afterBad, {revision: 0, migration: null}, '検査で落ちる旧本文では running を確定しない');
  assert.equal(r.partial, 'running');
  assert.deepEqual(r.abandoned, {revision: r.partialRevision + 1, migration: null, days: 0, metadata: 0, prior: 1});
  assert.equal(r.gone, 'unfetched');
  assert.equal(r.done, 'complete'); assert.equal(r.total, 12); assert.equal(r.afterDone, 12);
});

test('旧JSONの整形・エスケープ・順序・不正末尾とP’s CUBEを確認する', async () => {
  const r = await run(async () => {
    const errors = [];
    const doc = {records: [{...rowsAt(0, 4)[0], note: '括弧 [ ] { } と \\"', graph_measurement: {curve: [[0, 1], [2, 3]]}}], ...header, format: 'pscube-viewer'};
    const s = module.createViewerDayStore({dbName: 'pscube'}), text = JSON.stringify(doc, null, 2);
    const h = await s.migrateLegacy('p', {text, site: 'pscube'}), saved = await s.readRange('p', {days: [dayAt(0)]});
    for (const bad of [text + 'x', text.replace('"records": [', '"records": [null,'), text.replace(/\n}$/, ',\n}'), '{"records":[],"records":[]}']) {
      try { await module.createViewerDayStore({dbName: 'bad-json-' + errors.length}).migrateLegacy('p', {text: bad, site: 'pscube'}); } catch (e) { errors.push(e.name); }
    }
    const f = await fixture(3, 4, -1, 'pscube'), p = module.createViewerDayStore({dbName: 'pscube-parts'});
    await p.syncParts(endpoint, 'pscube', f.manifest, f.get);
    return {status: h.migration.status, saved: saved[0].records, original: doc.records, errors,
      count: (await p.readRange(endpoint + '|pscube', {days: [dayAt(2)]}))[0].records.length};
  });
  assert.equal(r.status, 'complete'); assert.deepEqual(r.saved, r.original); assert.equal(r.errors.length, 4); assert.equal(r.count, 4);
});

test('2つの実タブと終了後の再開で古い処理を確定させない', async () => {
  const {page} = env, second = await page.context().newPage();
  try {
    await second.goto(page.url());
    await run(async () => { window.tabsStore = module.createViewerDayStore({dbName: 'tabs'});
      window.tabsHead = await tabsStore.migrateLegacy(key, {text: legacyText(3, 4), site: 'meruhen', maxDays: 1}); });
    const continued = await second.evaluate(async () => {
      const {createViewerDayStore} = await import('/viewer_parts.mjs');
      const store = createViewerDayStore({dbName: 'tabs'});
      return (await store.inspect('https://example.invalid/viewer|meruhen')).migration.status;
    });
    assert.equal(continued, 'running');
    await second.close();
    const r = await run(async () => {
      const h = await tabsStore.migrateLegacy(key, {text: legacyText(3, 4), site: 'meruhen'});
      let code; try { await tabsStore.writeDays(key, {expectedRevision: tabsHead.revision, updates: {[dayAt(0)]: {state: 'complete', records: []}}}); } catch (e) { code = e.code; }
      return {code, status: h.migration.status};
    });
    assert.deepEqual(r, {code: 'conflict', status: 'complete'});
  } finally { if (!second.isClosed()) await second.close(); }
});

test('期間外の補助情報と外した印・イベント削除の新しい時刻を残す', async () => {
  const r = await run(async () => {
    const store = module.createViewerDayStore({dbName: 'annotations'}), f = await fixture(3, 4);
    await store.syncParts(endpoint, 'meruhen', f.manifest, f.get);
    const m = structuredClone(f.manifest); m.header.exported_at = '2026-01-05T00:00:00Z';
    m.header.rainbow_marks[0].on = true; m.header.rainbow_marks[0].updated_at = '2026-01-01T00:00:00Z';
    m.header.date_events = []; delete m.header.record_deletions;
    await store.syncParts(endpoint, 'meruhen', m, () => { throw Error('本文通信'); });
    return {saved: await store.readMetadata(key, 'parts'), header};
  });
  for (const name of ['date_events', 'rainbow_marks', 'record_deletions']) assert.deepEqual(r.saved[name], r.header[name]);
});

test('索引が壊れている場合は未取得扱いで書き直さない', async () => {
  const r = await run(async () => {
    const store = module.createViewerDayStore({dbName: 'bad-index'}), f = await fixture(3, 4);
    await store.syncParts(endpoint, 'meruhen', f.manifest, f.get);
    await new Promise(resolve => { const req = indexedDB.open('bad-index', 1); req.onsuccess = () => {
      const db = req.result, tx = db.transaction('heads', 'readwrite'), s = tx.objectStore('heads'), read = s.get(key);
      read.onsuccess = () => { const record = read.result; delete record.value.days[dayAt(0)]; s.put(record, key); };
      tx.oncomplete = () => { db.close(); resolve(); };
    }; });
    const errors = []; for (const action of [() => store.inspect(key), () => store.syncParts(endpoint, 'meruhen', f.manifest, f.get)]) {
      try { await action(); } catch (e) { errors.push(e.code); }
    }
    return errors;
  });
  assert.deepEqual(r, ['corrupt', 'corrupt']);
});

for (const days of [60, 180, 365]) test(`${days}日・複数部品で移行再開と7日読込の件数が一致する`, async () => {
  const r = await env.page.evaluate(async days => {
    const store = module.createViewerDayStore({dbName: 'scale-' + days}), text = legacyText(days, 4);
    await store.migrateLegacy(key, {text, site: 'meruhen', maxDays: Math.floor(days / 2)});
    const h = await store.migrateLegacy(key, {text, site: 'meruhen'});
    const f = await fixture(days, 4); await store.syncParts(endpoint, 'meruhen', f.manifest, f.get);
    io.length = 0;
    const selected = await store.readRange(key, {from: dayAt(days - 7), to: dayAt(days - 1), stores: ['saiwaichou']});
    return {total: h.migration.totalRecords, loaded: selected.reduce((n, d) => n + d.records.length, 0), reads: io.filter(x => x.store === 'bodies' && x.method === 'get').length};
  }, days);
  assert.deepEqual(r, {total: days * 4, loaded: 14, reads: 7});
});

test('複数日の途中取得失敗は保存途中の本文を公開せず、同じ入力で再開できる', async () => {
  const r = await run(async () => {
    const store = module.createViewerDayStore({dbName: 'partial-network'}), initial = await fixture(3, 4), fresh = await fixture(5, 4);
    const old = await store.syncParts(endpoint, 'meruhen', initial.manifest, initial.get);
    fresh.manifest.header.exported_at = '2026-01-02T00:00:00Z';
    let calls = 0, failed = false;
    try { await store.syncParts(endpoint, 'meruhen', fresh.manifest, url => { if (++calls === 2) throw Error('通信中断'); return fresh.get(url); }); } catch { failed = true; }
    const unchanged = (await store.inspect(key)).revision === old.revision;
    const absent = (await store.readRange(key, {days: [dayAt(3)]}))[0].state;
    await store.syncParts(endpoint, 'meruhen', fresh.manifest, fresh.get);
    return {failed, unchanged, absent, count: (await store.readRange(key, {from: dayAt(0), to: dayAt(4)})).reduce((n, d) => n + d.records.length, 0)};
  });
  assert.deepEqual(r, {failed: true, unchanged: true, absent: 'unfetched', count: 20});
});

test('旧v1一覧・範囲なし・不正な印を拒否し、終了要求後も再開できる', async () => {
  const r = await run(async () => {
    const store = module.createViewerDayStore({dbName: 'validation'}), f = await fixture(3, 4), errors = [];
    try { await store.syncParts(endpoint, 'meruhen', {...f.manifest, version: 1, curve_parts: undefined}, f.get); } catch (e) { errors.push(e.code); }
    try { await store.readRange(key); } catch (e) { errors.push(e.code); }
    const bad = {...header, rainbow_marks: [null], records: rowsAt(0, 4)};
    try { await store.migrateLegacy(key, {text: JSON.stringify(bad), site: 'meruhen'}); } catch (e) { errors.push(e.code); }
    const before = (await store.inspect(key)).revision, controller = new AbortController(); controller.abort();
    try { await store.migrateLegacy(key, {text: legacyText(3, 4), site: 'meruhen', signal: controller.signal}); } catch (e) { errors.push(e.name); }
    const done = await store.migrateLegacy(key, {text: legacyText(3, 4), site: 'meruhen'});
    // 移行後に通常更新しても、再実行は保管した移行時の本文を照合し、現行版を巻き戻さない。
    const next = await store.writeDays(key, {expectedRevision: done.revision, updates: {[dayAt(0)]: {state: 'complete', records: []}}});
    const again = await store.migrateLegacy(key, {text: legacyText(3, 4), site: 'meruhen'});
    return {errors, before, unchanged: next.revision === again.revision, state: (await store.readRange(key, {days: [dayAt(0)]}))[0].state};
  });
  assert.deepEqual(r.errors, ['legacy-manifest', 'range-required', 'corrupt', 'AbortError']);
  assert.equal(r.before, 0); assert.equal(r.unchanged, true); assert.equal(r.state, 'empty');
});
