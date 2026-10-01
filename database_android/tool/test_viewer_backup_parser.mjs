import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

// Execute the exact browser importer through its normal URL entry point.
// Synthetic data only: no browser, Drive access, IndexedDB, or user records.
const html = readFileSync(new URL('../web/index.html', import.meta.url), 'utf8');
const code = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const event = {store: 'nagamachiminami', day: '2026-09-29', name: '超探す楽しみ'};
const record = {
  store: 'nagamachiminami', day: '2026-09-29', machine: 'テスト機種', rack: 101,
  games: 5000, bb: 20, rb: 10,
  graph_measurement: {
    preview_image: 'large-image-not-retained', preview_stored: true, curve_stored: true,
    curve: [[0, 0], [1, 100]], end_hold: 100,
  },
};
const candidate = {machine: 'テスト機種', racks: [101]};
const head = {format: 'database-backup', version: 1, source: 'android', date_events: [event]};
const start = `${JSON.stringify(head).slice(0, -1)}, "records": [\n`;
const row = JSON.stringify(record);

async function parse(text, chunkSize = 17) {
  const bytes = new TextEncoder().encode(text);
  const body = new ReadableStream({
    start(controller) {
      for (let offset = 0; offset < bytes.length; offset += chunkSize) {
        controller.enqueue(bytes.subarray(offset, offset + chunkSize));
      }
      controller.close();
    },
  });
  const context = {window: {}, TextDecoderStream, fetch: async () => ({ok: true, body})};
  vm.runInNewContext(code, context);
  return JSON.parse(await context.window.databaseViewer.fromUrl('fixture.json'));
}

function check(result, {candidates = [candidate], events = [event]} = {}) {
  assert.equal(result.header.format, 'database-backup');
  assert.equal(result.records.length, 1);
  assert.equal(result.records[0].machine, record.machine);
  assert.deepEqual(result.records[0].graph_measurement, {curve: [[0, 0], [1, 100]], end_hold: 100});
  assert.deepEqual(result.candidates, candidates);
  assert.deepEqual(result.date_events, events);
}

test('Android and PC line backups retain candidates, events and curve, dropping images', async () => {
  for (const source of ['android', 'pc', 'pc-viewer']) {
    const prefix = start.replace('"android"', JSON.stringify(source));
    const tail = source === 'pc-viewer' ? '\n]}' : `\n], "candidate_snapshots": [\n${JSON.stringify(candidate)}\n]}\n`;
    check(await parse(prefix + row + tail, 1), {candidates: source === 'pc-viewer' ? [] : [candidate]});
  }
});

test('older compact and pretty JSON exports use the same contract', async () => {
  const doc = {...head, records: [record], candidate_snapshots: [candidate]};
  check(await parse(JSON.stringify(doc)));
  check(await parse(JSON.stringify(doc, null, 2)));
});

test('empty valid backups are accepted', async () => {
  const result = await parse(start + ']}');
  assert.deepEqual(result.records, []);
  assert.deepEqual(result.date_events, [event]);
});

test('nonstreamed trailing metadata is retained', async () => {
  const prefix = `${JSON.stringify({format: head.format, version: 1}).slice(0, -1)}, "records": [\n`;
  check(await parse(prefix + row + `\n], "date_events": ${JSON.stringify([event])}, "candidate_snapshots": ${JSON.stringify([candidate])}}`));
});

test('pretty candidate tail after a separate records closing line is retained', async () => {
  check(await parse(start + row + `\n]\n, "candidate_snapshots": [\n${JSON.stringify(candidate)}\n]\n}\n`));
});

test('a streamed duplicate records field cannot replace the actual record values', async () => {
  await assert.rejects(parse(start + row + '\n], "records": []}'));
});

for (const [name, text] of [
  ['record array truncated', start + row],
  ['candidate array truncated', start + row + `\n], "candidate_snapshots": [\n${JSON.stringify(candidate)}`],
  ['outer closing brace missing', start + row + '\n]'],
  ['record comma missing', start + row + '\n' + row + '\n]}'],
  ['trailing comma', start + row + ',\n]}'],
  ['extra trailing content', start + row + '\n]}\nwrong'],
  ['unrelated compact format', JSON.stringify({format: 'other', records: [record]})],
  ['unrelated compact format with newline', JSON.stringify({format: 'other', records: [record]}) + '\n'],
  ['missing compact format', JSON.stringify({records: [record]})],
  ['missing compact format with newline', JSON.stringify({records: [record]}) + '\n'],
  ['malformed events array', JSON.stringify({...head, date_events: {}, records: [record]})],
]) {
  test(`rejects ${name}`, async () => {
    await assert.rejects(parse(text));
  });
}

test('Drive errors are reported verbatim without importing records', async () => {
  await assert.rejects(parse(JSON.stringify({error: 'fixture Drive error'})), /fixture Drive error/);
});

test('unknown or missing version is rejected in every JSON layout', async () => {
  for (const version of [undefined, 99, '1', true]) {
    const doc = {...head, version, records: [record]};
    for (const text of [JSON.stringify(doc), JSON.stringify(doc, null, 2),
      `${JSON.stringify({...head, version}).slice(0, -1)}, "records": [\n${row}\n]}`]) {
      await assert.rejects(parse(text), /バージョン/);
    }
  }
});

// Googleドライブ（スクリプト）から読む場合。本文は少しずつ渡し、何回渡したか、
// 途中で打ち切られたかを数える。
const REMOTE = 'https://script.google.com/macros/s/fixture_ID-1/exec';
const exportedAt = '2026-09-30T01:19:50.746423+09:00';
const remoteHead = {...head, source: 'pc-viewer', exported_at: exportedAt};
const remoteText = `${JSON.stringify(remoteHead).slice(0, -1)}, "records": [\n` +
  Array(200).fill(row).join(',\n') + '\n]}';

function remote(text, {chunkSize = 64, timers = {setTimeout, clearTimeout}, fetchImpl, document} = {}) {
  const bytes = new TextEncoder().encode(text);
  const stats = {pulled: 0, cancelled: false, total: Math.ceil(bytes.length / chunkSize)};
  let offset = 0;
  const body = new ReadableStream({
    pull(controller) {
      if (offset >= bytes.length) {
        controller.close();
        return;
      }
      controller.enqueue(bytes.subarray(offset, offset + chunkSize));
      offset += chunkSize;
      stats.pulled++;
    },
    cancel() {
      stats.cancelled = true;
    },
  });
  const response = {ok: true, status: 200, headers: {get: () => 'application/json'}, body};
  const context = {
    window: {}, TextDecoderStream, TransformStream, AbortController,
    setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout,
    fetch: fetchImpl ?? (async () => response),
    ...(document ? {document} : {}),
  };
  vm.runInNewContext(code, context);
  return {viewer: context.window.databaseViewer, stats};
}

test('Drive: the same export time stops at the first line and returns null', async () => {
  const {viewer, stats} = remote(remoteText);
  assert.equal(await viewer.fromRemote(REMOTE, exportedAt), null);
  // 残りは読まずに通信を止める。
  assert.ok(stats.cancelled);
  assert.ok(stats.pulled < stats.total / 10, `${stats.pulled} of ${stats.total} chunks read`);
});

test('Drive: a different or unknown export time reads the whole file', async () => {
  for (const known of ['2026-09-29T23:00:00+09:00', null, undefined, '']) {
    const {viewer, stats} = remote(remoteText);
    const result = JSON.parse(await viewer.fromRemote(REMOTE, known));
    assert.equal(result.header.exported_at, exportedAt);
    assert.equal(result.records.length, 200);
    assert.equal(result.file, 'Googleドライブ（自動）');
    assert.equal(stats.pulled, stats.total);
  }
});

test('Drive: an older one-line export with the same time is also skipped', async () => {
  const doc = {...remoteHead, records: [record]};
  const {viewer} = remote(JSON.stringify(doc));
  assert.equal(await viewer.fromRemote(REMOTE, exportedAt), null);
  const {viewer: again} = remote(JSON.stringify(doc));
  assert.equal(JSON.parse(await again.fromRemote(REMOTE, 'other')).records.length, 1);
});

test('Drive: gives up after 30 seconds without any data', async () => {
  const delays = [];
  const timers = {
    // 30秒を待たずに、すぐ時間切れにする。
    setTimeout: (callback, ms) => {
      delays.push(ms);
      return setTimeout(callback, 0);
    },
    clearTimeout,
  };
  const fetchImpl = (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('aborted')));
  });
  const {viewer} = remote('', {timers, fetchImpl});
  await assert.rejects(viewer.fromRemote(REMOTE, exportedAt), /30秒間応答がなかった/);
  assert.deepEqual(delays, [30000]);
});

test('Drive: the 30 seconds restart whenever data arrives', async () => {
  const delays = [];
  let cleared = 0;
  const timers = {
    // 時間切れにはしない。待ち時間を何回数え直したかだけを数える。
    setTimeout: (_callback, ms) => {
      delays.push(ms);
      return delays.length;
    },
    clearTimeout: () => {
      cleared++;
    },
  };
  const {viewer, stats} = remote(remoteText, {timers});
  const result = JSON.parse(await viewer.fromRemote(REMOTE, null));
  assert.equal(result.records.length, 200);
  // 最初、応答の後、そして届くたびに数え直す。最後に止める。
  assert.ok(delays.length >= stats.total + 2, `${delays.length} restarts for ${stats.total} chunks`);
  assert.ok(delays.every((ms) => ms === 30000));
  assert.equal(cleared, delays.length + 1);
});

test('Drive: only the Google script address is read', async () => {
  const {viewer} = remote(remoteText);
  await assert.rejects(viewer.fromRemote('https://example.com/exec', null), /GoogleのスクリプトのURL/);
});

test('Drive: intermittent 404 / 5xx / network failure is retried twice, other errors are not', async () => {
  // やり直しの待ち（1.5秒・3秒）はすぐ進め、30秒の打ち切りはそのままにする。
  const timers = {
    setTimeout: (callback, ms) => setTimeout(callback, ms === 30000 ? ms : 0),
    clearTimeout,
  };
  const ok = () => ({ok: true, status: 200, headers: {get: () => 'application/json'},
    body: new Response(remoteText).body});
  const bad = (status) => ({ok: false, status, headers: {get: () => 'text/html'}, body: null});
  const sequence = (steps) => {
    let i = 0;
    const calls = [];
    return {calls, fetchImpl: async (url) => {
      calls.push(url);
      const step = steps[Math.min(i++, steps.length - 1)];
      if (step === 'net') throw new TypeError('Failed to fetch');
      return step === 200 ? ok() : bad(step);
    }};
  };
  for (const steps of [[404, 200], [503, 404, 200], ['net', 200]]) {
    const s = sequence(steps);
    const {viewer} = remote('', {timers, fetchImpl: s.fetchImpl});
    assert.equal(JSON.parse(await viewer.fromRemote(REMOTE, null)).records.length, 200);
    assert.equal(s.calls.length, steps.length);
  }
  const always = sequence([404]);
  await assert.rejects(remote('', {timers, fetchImpl: always.fetchImpl}).viewer.fromRemote(REMOTE, null), /（404）/);
  assert.equal(always.calls.length, 3);
  const forbidden = sequence([403]);
  await assert.rejects(remote('', {timers, fetchImpl: forbidden.fetchImpl}).viewer.fromRemote(REMOTE, null), /（403）/);
  assert.equal(forbidden.calls.length, 1);
});

test('Drive: time spent with the page hidden (iPhone app switch) is not counted', async () => {
  const listeners = {};
  const document = {
    visibilityState: 'visible',
    addEventListener: (name, fn) => { listeners[name] = fn; },
    removeEventListener: (name, fn) => { if (listeners[name] === fn) delete listeners[name]; },
  };
  const events = [];
  const timers = {
    setTimeout: (_callback, ms) => { events.push(`set ${ms}`); return events.length; },
    clearTimeout: () => { events.push('clear'); },
  };
  let release;
  const response = {ok: true, status: 200, headers: {get: () => 'application/json'}, body: new Response(remoteText).body};
  const fetchImpl = () => new Promise((resolve) => { release = () => resolve(response); });
  const {viewer} = remote('', {timers, fetchImpl, document});
  const pending = viewer.fromRemote(REMOTE, null);
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(typeof listeners.visibilitychange, 'function');
  events.length = 0;
  document.visibilityState = 'hidden';
  listeners.visibilitychange();
  assert.deepEqual(events, ['clear'], '裏に回ったら打ち切りの時計を止める');
  document.visibilityState = 'visible';
  listeners.visibilitychange();
  assert.deepEqual(events, ['clear', 'clear', 'set 30000'], '戻ったら30秒を数え直す');
  release();
  assert.equal(JSON.parse(await pending).records.length, 200);
  assert.equal(listeners.visibilitychange, undefined, '終わったら見張りを外す');
});

test('a P’s CUBE file points to the P’s CUBE page instead of a generic error', async () => {
  const pscube = JSON.stringify({format: 'pscube-viewer', version: 1, kind: 'backup', machines: [], records: []});
  await assert.rejects(parse(pscube), /P’s CUBEのページ/);
  const spread = '{"format": "pscube-viewer", "version": 1, "records": [\n]}';
  await assert.rejects(parse(spread), /P’s CUBEのページ/);
  await assert.rejects(parse(JSON.stringify({format: 'other', records: []})), /databaseのバックアップファイルではありません/);
});
