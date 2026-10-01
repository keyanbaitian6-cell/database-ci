import test from 'node:test';
import assert from 'node:assert/strict';
import { readBinaryPlist, readWebArchive } from '../web/pscube/archive.mjs';
import { emptyData, validateData, mergeData, progress, siteUrl } from '../web/pscube/data.mjs';

const base = 'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c1/cgi-bin/';
const machine = { store: 'c1', rate: '20', machine: '試験機種', expected_count: 2, url: `${base}nc-v05-011.php?cd_ps=2&bai=20` };
const graph = { kind: 'daily', zero_y: 10, points: [[0, 10], [10, 2]] };
const record = { ...machine, rack: 1, day: '2026-10-01', bb: 3, rb: 1, at_art: 0, games: 600, my: 120,
  observed_at: '2026-10-01T10:00:00+09:00', detail_url: `${base}nc-v06-001.php?cd_dai=1#20261001`, graph };
const data = (patch = {}, machinePatch = {}) => ({ ...emptyData(), machines: [{ ...machine, ...machinePatch }], records: [{ ...record, ...patch }] });

test('MY and source identity survive round trip without max_hold conversion', () => {
  const saved = validateData(JSON.parse(JSON.stringify(data())));
  assert.equal(saved.records[0].my, 120); assert.equal(saved.records[0].max_hold, undefined);
  assert.deepEqual(validateData(saved), saved);
});
test('missing counts, bad date, mismatched rack, shop and graph fail closed', () => {
  for (const patch of [{ my: null }, { day: '2026-02-30' }, { rack: 2 }, { store: 'c2' },
    { graph: { ...graph, points: [[2, 3], [1, 4]] } }, { observed_at: 'invalid' }]) {
    assert.throws(() => validateData(data(patch)));
  }
  assert.throws(() => siteUrl('javascript:alert(1)'));
  assert.throws(() => siteUrl('https://www.pscube.jp.evil.example/'));
});
test('duplicate records and unsupported backup versions are rejected', () => {
  const d = data(); d.records.push(d.records[0]); assert.throws(() => validateData(d));
  assert.throws(() => validateData({ ...data(), version: 2 }));
});
test('older input cannot replace newer numbers or detailed graph', () => {
  const old = data({ games: 500, observed_at: '2026-10-01T09:00:00+09:00' });
  assert.equal(mergeData(data(), old).records[0].games, 600);
  const sameOld = data({ graph: { ...graph, points: [[0, 10], [10, 9]] }, observed_at: '2026-10-01T09:00:00+09:00' });
  assert.deepEqual(mergeData(data(), sameOld).records[0].graph, graph);
});
test('unchanged numbers retain detailed graph; changed numbers require recapture', () => {
  const overview = data({ graph: { ...graph, kind: 'overview' }, observed_at: '2026-10-01T11:00:00+09:00' });
  assert.equal(mergeData(data(), overview).records[0].graph.kind, 'daily');
  const changed = data({ games: 700, graph: { ...graph, kind: 'overview' }, observed_at: '2026-10-01T11:00:00+09:00' });
  const merged = mergeData(data(), changed);
  assert.equal(progress(merged, machine, record.day).pending.length, 1);
});
test('partial lists never appear complete, and no-hit racks remain pending', () => {
  const d = validateData(data({ bb: 0, rb: 0, graph: null }));
  assert.equal(progress(d, machine, record.day).complete, false);
  assert.equal(progress(d, machine, record.day).pending.length, 1);
});
test('reimport is idempotent; category and other days are preserved', () => {
  const first = validateData(data({}, { machine_type: 'normal' }));
  const next = data({ day: '2026-09-30', detail_url: `${base}nc-v06-001.php?cd_dai=1#20260930` }, { expected_count: null });
  const merged = mergeData(first, next);
  assert.equal(merged.records.length, 2); assert.equal(merged.machines[0].expected_count, 2);
  assert.equal(merged.machines[0].machine_type, 'normal');
  assert.deepEqual(mergeData(merged, next), merged);
});
test('different rates cannot merge the same rack into one record', () => {
  const low = data({ rate: '5' }, { rate: '5', url: `${base}nc-v05-011.php?cd_ps=2&bai=5` });
  assert.equal(mergeData(data(), low).records.length, 2);
});
test('binary Safari archive reads Japanese HTML and rejects broken offsets', () => {
  // Synthetic plist generated with Python plistlib; no real site/authentication data.
  const fixture = Buffer.from('62706c6973743030d101025f100f5765624d61696e5265736f75726365d4030405060708090a5f100f5765625265736f75726365446174615f10135765625265736f757263654d494d45547970655f101b5765625265736f7572636554657874456e636f64696e674e616d655e5765625265736f7572636555524c4f10223c68746d6c3e3c7469746c653ee8a9a6e9a8933c2f7469746c653e3c2f68746d6c3e59746578742f68746d6c555554462d385f105268747470733a2f2f7777772e7073637562652e6a702f646564616d616a796f686f2d502d746f776e444d4d70616368692f63312f6367692d62696e2f6e632d7630332d3030312e7068703f63645f70733d320008000b001d00260038004e006c007b00a000aa00b00000000000000201000000000000000b00000000000000000000000000000105', 'hex');
  assert.match(readWebArchive(fixture).html, /試験/);
  const corrupt = Buffer.from(fixture); corrupt.fill(255, corrupt.length - 8);
  assert.throws(() => readBinaryPlist(corrupt));
  assert.throws(() => readBinaryPlist(fixture.subarray(0, 40)));
});
