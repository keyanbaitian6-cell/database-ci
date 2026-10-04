import test from 'node:test';
import assert from 'node:assert/strict';
import { emptyData, validateData, mergeData, recordKey } from '../web/pscube/data.mjs';
import { checkVersion } from '../web/drive_fetch.mjs';
import { backupFileName, timestampWithOffset, buildBackup, driveUrl, fetchDrive, REMOTE_KEY, DRIVE_RETRY_DELAYS_MS } from '../web/pscube/sync.mjs';

const base = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/';
const machine = { store: 'c740601', rate: '20', machine: '試験機種', expected_count: 2, url: `${base}nc-v05-011.php?cd_ps=2&bai=20` };
const rec = (rack, day, patch = {}) => ({ ...machine, rack, day, bb: 5, rb: 3, at_art: 0, games: 3000, my: 900, observed_at: `${day}T12:00:00+09:00`,
  detail_url: `${base}nc-v06-001.php?cd_dai=${rack}#${day.replaceAll('-', '')}`,
  graph: { kind: rack === 1 ? 'daily' : 'overview', zero_y: 10, points: [[0, 10], [5, 4], [10, 7]] }, ...patch });
const data = () => validateData({ ...emptyData(), machines: [machine], records: [rec(1, '2026-10-01'), rec(2, '2026-10-01')] });
const SCRIPT = 'https://script.google.com/macros/s/AKfycb_test-ID/exec';
const respond = (body, status = 200) => async () => new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });
const memory = () => { let value = null; return { get: () => value, set: v => { value = v; } }; };

test('file name is separate from Meruhen and plain ASCII; timestamp carries the offset', () => {
  assert.equal(backupFileName(new Date(2026, 9, 1, 9, 5, 7)), 'pscube-backup-browser-20261001-090507.json');
  assert.match(timestampWithOffset(new Date(2026, 9, 1, 9, 5, 7)), /^2026-10-01T09:05:07[+-]\d\d:\d\d$/);
  assert.equal(REMOTE_KEY, 'database-viewer-remote');
});

test('exported backup is a valid pscube-viewer file with kind, source, time and capture marks', () => {
  const backup = buildBackup(data(), new Date(2026, 9, 1, 9, 5, 7));
  assert.equal(backup.format, 'pscube-viewer'); assert.equal(backup.kind, 'backup'); assert.equal(backup.source, 'browser');
  assert.deepEqual(backup.rack_captures, [recordKey(rec(1, '2026-10-01'))]);
  assert.deepEqual(validateData(JSON.parse(JSON.stringify(backup))), data());
});

test('Drive URL: only the Apps Script exec URL, with ?file=pscube', () => {
  assert.equal(driveUrl(SCRIPT), `${SCRIPT}?file=pscube`);
  for (const bad of ['', null, 'http://script.google.com/macros/s/x/exec', 'https://evil.example/macros/s/x/exec',
    `${SCRIPT}?x=1`, 'https://script.google.com/macros/s/x/exec/extra']) assert.throws(() => driveUrl(bad));
});

test('new Drive content is returned for merging; the same exported_at is skipped', async () => {
  const doc = { ...JSON.parse(JSON.stringify(data())), kind: 'viewer', source: 'pc', exported_at: '2026-10-01T20:00:00+09:00' };
  let requested;
  const fetchImpl = async (url, options) => { requested = [url, options.cache]; return respond(doc)(); };
  const first = await fetchDrive(SCRIPT, null, { fetchImpl });
  assert.deepEqual(requested, [`${SCRIPT}?file=pscube&check=1`, 'no-store'], '古いスクリプトは全文を返す：それをそのまま使う');
  assert.equal(first.unchanged, false); assert.equal(first.exportedAt, doc.exported_at); assert.equal(first.data.records.length, 2);
  assert.deepEqual(await fetchDrive(SCRIPT, doc.exported_at, { fetchImpl }), { unchanged: true, exportedAt: doc.exported_at });
  assert.equal((await fetchDrive(SCRIPT, '2026-09-30T00:00:00+09:00', { fetchImpl })).unchanged, false);
});

test('wrong file (old script returns Meruhen data), script error, bad JSON, HTTP error and timeout change nothing', async () => {
  await assert.rejects(fetchDrive(SCRIPT, null, { fetchImpl: respond({ format: 'database-backup', exported_at: 'x' }) }), /Apps Scriptを更新/);
  await assert.rejects(fetchDrive(SCRIPT, null, { fetchImpl: respond({ error: 'pscube-viewer-drive.json がGoogleドライブに見つかりません。' }) }), /見つかりません/);
  await assert.rejects(fetchDrive(SCRIPT, null, { fetchImpl: respond('<html>login</html>') }), /読めません/);
  await assert.rejects(fetchDrive(SCRIPT, null, { fetchImpl: respond({}, 500), retryDelays: [] }), /500/);
  await assert.rejects(fetchDrive(SCRIPT, null, { fetchImpl: async () => { throw new TypeError('offline'); }, retryDelays: [] }), /接続できません/);
  const hang = (url, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(Object.assign(new Error('a'), { name: 'AbortError' }))));
  await assert.rejects(fetchDrive(SCRIPT, null, { fetchImpl: hang, timeoutMs: 20 }), /時間切れ/);
  const broken = { ...JSON.parse(JSON.stringify(data())), exported_at: 'x' }; broken.records[0].bb = -1;
  await assert.rejects(fetchDrive(SCRIPT, null, { fetchImpl: respond(broken) }));
});

test('Drive content merges without replacing newer local numbers or removing local racks', async () => {
  const local = validateData({ ...emptyData(), machines: [machine], records: [rec(1, '2026-10-01', { games: 4000, observed_at: '2026-10-01T20:00:00+09:00' }), rec(9, '2026-09-20')] });
  const remote = JSON.parse(JSON.stringify(data())); remote.exported_at = 'e'; remote.records[0].games = 3500;
  const fetched = await fetchDrive(SCRIPT, null, { fetchImpl: respond(remote) });
  const merged = mergeData(local, fetched.data);
  assert.equal(merged.records.find(r => r.rack === 1).games, 4000);
  assert.ok(merged.records.some(r => r.rack === 9)); assert.ok(merged.records.some(r => r.rack === 2));
});

test('intermittent 404 / 5xx / network failure from Apps Script is retried, then reported', async () => {
  assert.deepEqual(DRIVE_RETRY_DELAYS_MS, [1500, 3000, 3000]);
  const doc = { ...JSON.parse(JSON.stringify(data())), exported_at: 'r' };
  const sequence = statuses => { let i = 0; const calls = [];
    const fetchImpl = async url => { calls.push(url); const s = statuses[Math.min(i++, statuses.length - 1)];
      if (s === 'net') throw new TypeError('offline'); return respond(s === 200 ? doc : {}, s)(); };
    return { fetchImpl, calls }; };
  for (const statuses of [[404, 200], [503, 404, 200], ['net', 200]]) {
    const s = sequence(statuses);
    const result = await fetchDrive(SCRIPT, null, { fetchImpl: s.fetchImpl, retryDelays: [0, 0] });
    assert.equal(result.data.records.length, 2); assert.equal(s.calls.length, statuses.length);
  }
  const always = sequence([404]);
  await assert.rejects(fetchDrive(SCRIPT, null, { fetchImpl: always.fetchImpl, retryDelays: [0, 0] }), /404/);
  assert.equal(always.calls.length, 3);
  const forbidden = sequence([403]);
  await assert.rejects(fetchDrive(SCRIPT, null, { fetchImpl: forbidden.fetchImpl, retryDelays: [0, 0] }), /403/);
  assert.equal(forbidden.calls.length, 1, '403などは繰り返さない');
  const slow = sequence([404]);
  await assert.rejects(fetchDrive(SCRIPT, null, { fetchImpl: slow.fetchImpl, retryDelays: [10000, 10000], timeoutMs: 30 }), /時間切れ/);
});

test('time with the page hidden (iPhone app switch) does not count toward the timeout', async () => {
  const listeners = {};
  globalThis.document = { visibilityState: 'visible',
    addEventListener: (n, f) => { listeners[n] = f; }, removeEventListener: (n, f) => { if (listeners[n] === f) delete listeners[n]; } };
  try {
    let release;
    const doc = { ...JSON.parse(JSON.stringify(data())), exported_at: 'v' };
    const fetchImpl = () => new Promise(resolve => { release = () => resolve(respond(doc)()); });
    const pending = fetchDrive(SCRIPT, null, { fetchImpl, timeoutMs: 40 });
    await new Promise(r => setTimeout(r, 0));
    document.visibilityState = 'hidden'; listeners.visibilitychange();
    await new Promise(r => setTimeout(r, 80));   // 裏に回っている間は40msを過ぎても打ち切らない
    document.visibilityState = 'visible'; listeners.visibilitychange();
    release();
    assert.equal((await pending).data.records.length, 2);
    assert.equal(listeners.visibilitychange, undefined);
  } finally { delete globalThis.document; }
});

test('browser backup restores suffix marks and explicit removals; Drive without marks keeps local marks', async () => {
  const marks=[{store:'c740601',rate:'20',day:'2026-10-01',enabled:true,updated_at:'2026-10-02T00:00:00Z'},
    {store:'c740601',rate:'20',day:'2026-09-30',enabled:false,updated_at:'2026-10-02T00:00:01Z'}];
  const local={...data(),suffix_events:marks};
  assert.deepEqual(validateData(JSON.parse(JSON.stringify(buildBackup(local)))).suffix_events,marks);
  const remote=await fetchDrive(SCRIPT,null,{fetchImpl:respond({...data(),exported_at:'new'})});
  assert.deepEqual(mergeData(local,remote.data).suffix_events,marks);
});

// --- 2026-10-04：返事が固まるApps Scriptへの対策（出し直し）と、更新の目印だけの確認 ---

const newScript = (version, doc, log = []) => async (url, { signal }) => {
  log.push(url);
  if (url.includes('check=1')) return new Response(JSON.stringify({ format: 'drive-check', version, name: 'pscube-viewer-drive.json' }));
  return respond(doc)(url, { signal });
};

test('new Apps Script: the same version and exported_at is not downloaded again', async () => {
  const doc = { ...JSON.parse(JSON.stringify(data())), kind: 'viewer', source: 'pc', exported_at: '2026-10-04T12:00:00+09:00' };
  const versions = memory(), log = [];
  const first = await fetchDrive(SCRIPT, null, { fetchImpl: newScript('v1', doc, log), versions });
  assert.equal(first.unchanged, false);
  assert.deepEqual(log.map(u => u.endsWith('check=1')), [true, false], '初めは確かめてから読む');
  assert.deepEqual(versions.get(), { version: 'v1', exported_at: doc.exported_at });
  log.length = 0;
  assert.deepEqual(await fetchDrive(SCRIPT, doc.exported_at, { fetchImpl: newScript('v1', doc, log), versions }), { unchanged: true, exportedAt: doc.exported_at });
  assert.equal(log.length, 1, '目印が同じなら、ファイルは読まない');
  log.length = 0;
  const changed = await fetchDrive(SCRIPT, doc.exported_at, { fetchImpl: newScript('v2', { ...doc, exported_at: 'later' }, log), versions });
  assert.equal(changed.unchanged, false); assert.equal(log.length, 2);
  assert.deepEqual(versions.get(), { version: 'v2', exported_at: 'later' });
  // 別の内容を表示中（手でファイルを読み込んだ等）なら、目印が同じでも読み直す。
  log.length = 0;
  assert.equal((await fetchDrive(SCRIPT, 'something-else', { fetchImpl: newScript('v2', { ...doc, exported_at: 'later' }, log), versions })).unchanged, false);
  assert.equal(log.length, 2, '目印は同じでも、表示中の内容と書き出し時刻が違えば読む');
});

test('the version is remembered only after the content was read and checked', async () => {
  const versions = memory();
  const broken = { format: 'database-backup', exported_at: 'x' };
  await assert.rejects(fetchDrive(SCRIPT, null, { fetchImpl: newScript('v9', broken), versions }), /Apps Scriptを更新/);
  assert.equal(versions.get(), null);
});

test('a request that gets no answer is joined by a second one; the first success wins and the other is stopped', async () => {
  const doc = { ...JSON.parse(JSON.stringify(data())), exported_at: 'h' };
  const calls = [], aborted = [];
  const fetchImpl = (url, { signal }) => {
    const index = calls.push(url) - 1;
    signal.addEventListener('abort', () => aborted.push(index));
    if (index === 0) return new Promise(() => {});          // 1本目は固まる
    return respond(doc)();
  };
  const started = Date.now();
  const result = await fetchDrive(SCRIPT, null, { fetchImpl, hedgeMs: 30, timeoutMs: 5000, versions: memory() });
  assert.equal(result.data.records.length, 2);
  assert.ok(Date.now() - started < 1000, '固まった1本を待たない');
  assert.equal(calls.length, 2);
  assert.deepEqual(aborted, [0], '固まった方は止める');
});

test('a fast answer starts no second request; at most four requests are made in all', async () => {
  const doc = { ...JSON.parse(JSON.stringify(data())), exported_at: 'f' };
  let count = 0;
  await fetchDrive(SCRIPT, null, { fetchImpl: async () => { count++; return respond(doc)(); }, hedgeMs: 20, versions: memory() });
  await new Promise(r => setTimeout(r, 80));
  assert.equal(count, 1);
  let stuck = 0;
  const never = () => { stuck++; return new Promise(() => {}); };
  await assert.rejects(fetchDrive(SCRIPT, null, { fetchImpl: never, hedgeMs: 10, timeoutMs: 120, retryDelays: [1500, 3000, 3000], versions: memory() }), /時間切れ/);
  assert.equal(stuck, 4, '最初の1本と、出し直し3本まで');
});

test('slow 404 from one request does not hide a success from another', async () => {
  const doc = { ...JSON.parse(JSON.stringify(data())), exported_at: 's' };
  let n = 0;
  const fetchImpl = () => {
    const i = n++;
    if (i === 0) return new Promise(resolve => setTimeout(() => resolve(new Response('', { status: 404 })), 200));   // 遅れて404
    return new Promise(resolve => setTimeout(() => resolve(respond(doc)()), 20));
  };
  const result = await fetchDrive(SCRIPT, null, { fetchImpl, hedgeMs: 30, versions: memory() });
  assert.equal(result.exportedAt, 's');
});

test('the check reply is recognised even when it arrives in tiny pieces', async () => {
  const text = JSON.stringify({ format: 'drive-check', version: 'v7', name: 'pscube-viewer-drive.json' });
  const bytes = new TextEncoder().encode(text);
  const tiny = () => new Response(new ReadableStream({ start(c) { for (const b of bytes) c.enqueue(new Uint8Array([b])); c.close(); } }));
  const checked = await checkVersion('https://x/exec?check=1', { fetchImpl: async () => tiny() });
  assert.equal(checked.version, 'v7');
  const whole = JSON.stringify(data());
  const pieces = new TextEncoder().encode(whole);
  const slow = () => new Response(new ReadableStream({ start(c) { for (let i = 0; i < pieces.length; i += 5) c.enqueue(pieces.subarray(i, i + 5)); c.close(); } }));
  const old = await checkVersion('https://x/exec?check=1', { fetchImpl: async () => slow() });
  assert.equal(await new Response(old.stream).text(), whole, '古いスクリプトの全文は、先頭を見たあとも欠けずに渡る');
});
