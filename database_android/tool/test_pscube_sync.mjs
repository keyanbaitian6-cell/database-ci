import test from 'node:test';
import assert from 'node:assert/strict';
import { emptyData, validateData, mergeData, recordKey } from '../web/pscube/data.mjs';
import { backupFileName, timestampWithOffset, buildBackup, driveUrl, fetchDrive, REMOTE_KEY, DRIVE_RETRY_DELAYS_MS } from '../web/pscube/sync.mjs';

const base = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/';
const machine = { store: 'c740601', rate: '20', machine: '試験機種', expected_count: 2, url: `${base}nc-v05-011.php?cd_ps=2&bai=20` };
const rec = (rack, day, patch = {}) => ({ ...machine, rack, day, bb: 5, rb: 3, at_art: 0, games: 3000, my: 900, observed_at: `${day}T12:00:00+09:00`,
  detail_url: `${base}nc-v06-001.php?cd_dai=${rack}#${day.replaceAll('-', '')}`,
  graph: { kind: rack === 1 ? 'daily' : 'overview', zero_y: 10, points: [[0, 10], [5, 4], [10, 7]] }, ...patch });
const data = () => validateData({ ...emptyData(), machines: [machine], records: [rec(1, '2026-10-01'), rec(2, '2026-10-01')] });
const SCRIPT = 'https://script.google.com/macros/s/AKfycb_test-ID/exec';
const respond = (body, status = 200) => async () => ({ ok: status === 200, status, text: async () => typeof body === 'string' ? body : JSON.stringify(body) });

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
  assert.deepEqual(requested, [`${SCRIPT}?file=pscube`, 'no-store']);
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

test('intermittent 404 / 5xx / network failure from Apps Script is retried twice, then reported', async () => {
  assert.deepEqual(DRIVE_RETRY_DELAYS_MS, [1500, 3000]);
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
