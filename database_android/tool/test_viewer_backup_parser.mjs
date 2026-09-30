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
