import test from 'node:test';
import assert from 'node:assert/strict';
import { readBinaryPlist, readWebArchive } from '../web/pscube/archive.mjs';
import { emptyData, validateData, mergeData, progress, siteUrl, isExcludedMachine } from '../web/pscube/data.mjs';
import {netMedalsOfProbe, applyGraphProbe} from '../web/pscube/graph_probe.mjs';

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
test('source graph gives signed daily net medals and keeps MY independent', () => {
  const probe = {rack:1, day:'20261001', graph:{datas:{
    g:[{YMD_biz:20261001, xField:'out-1', yField:'value-1'}],
    p:[{'out-1':0,'value-1':7092},{'out-1':25,'value-1':21210}],
  }}};
  assert.equal(netMedalsOfProbe(probe).get('2026-10-01'), 14118);
  const updated = applyGraphProbe(data(), probe);
  assert.equal(updated.records[0].net_medals, 14118);
  assert.equal(updated.records[0].my, 120);
  assert.equal(mergeData(updated, data()).records[0].net_medals, 14118);
  assert.equal(mergeData(updated, data({games:700})).records[0].net_medals, undefined,
    'newer changed site numbers require a fresh graph measurement');
  assert.equal(validateData(JSON.parse(JSON.stringify(updated))).records[0].net_medals, 14118);
  for (const bad of [
    {...probe, graph:{datas:{...probe.graph.datas,g:[{...probe.graph.datas.g[0],YMD_biz:20261002}]}}},
    {...probe, graph:{datas:{...probe.graph.datas,p:[{'out-1':0,'value-1':0}]}}},
    {...probe, graph:{...probe.graph,anjYUnit:-1}},
  ]) assert.throws(() => netMedalsOfProbe(bad));
  assert.throws(() => validateData(data({net_medals:1.5})));
});
test('negative day values stay negative; ambiguous rack and missing selected day are rejected', () => {
  const probe={rack:1,day:'20261001',graph:{datas:{
    g:[{YMD_biz:20261001,xField:'out-1',yField:'value-1'}],
    p:[{'out-1':0,'value-1':6000},{'out-1':20,'value-1':5000}],
  },anjYUnit:2}};
  assert.equal(applyGraphProbe(data(),probe).records[0].net_medals,-2000);
  const ambiguous=mergeData(data(),data({rate:'5'},{rate:'5',url:`${base}nc-v05-011.php?cd_ps=2&bai=5`}));
  assert.throws(()=>applyGraphProbe(ambiguous,probe),/複数店舗/);
  assert.throws(()=>applyGraphProbe(data(),{...probe,day:'20261002'}),/選択日のグラフ/);
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
test('partial lists never appear complete; racks without any hit need no seven-day page (2026-10-01 user rule)', () => {
  const d = validateData(data({ bb: 0, rb: 0, at_art: 0, graph: null }));
  assert.equal(progress(d, machine, record.day).complete, false);
  assert.equal(progress(d, machine, record.day).pending.length, 0, '当たりが1回もない台は台別7日分を待たない');
  const at = validateData(data({ bb: 0, rb: 0, at_art: 2, graph: null }));
  assert.equal(progress(at, machine, record.day).pending.length, 1, 'AT/ARTがあれば取る対象');
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

test('Okidoki machines (full- or half-width, either spelling) are excluded like Meruhen', () => {
  for (const name of ['沖ドキ!DUO', '沖ﾄﾞｷ!GOLD-30', 'オキドキ', 'ｵｷﾄﾞｷ!']) assert.equal(isExcludedMachine(name), true, name);
  assert.equal(isExcludedMachine('ﾏｲｼﾞｬｸﾞﾗｰV'), false);
});

const mark = (enabled = true, updated_at = '2026-10-02T00:00:00Z', patch = {}) =>
  ({store:'c1',rate:'20',day:'2026-10-01',enabled,updated_at,...patch});
test('optional suffix marks preserve old backups and validate scope, dates and removals', () => {
  assert.equal(validateData(data()).suffix_events, undefined);
  assert.deepEqual(validateData({...data(),suffix_events:[mark()]}).suffix_events, [mark()]);
  for (const bad of [{day:'2026-02-30'}, {rate:20}, {store:'nagamachiminami'},
    {enabled:'true'}, {updated_at:'bad'}, {updated_at:'2026-10-02'}]) {
    assert.throws(() => validateData({...data(),suffix_events:[mark(true,undefined,bad)]}));
  }
  assert.throws(() => validateData({...data(),suffix_events:{}}));
  assert.throws(() => validateData({...data(),suffix_events:[mark(),mark()]}));
});
test('imports without marks preserve them; newer removals survive older marked backups', () => {
  const marked = {...data(),suffix_events:[mark()]};
  assert.deepEqual(mergeData(marked,data()).suffix_events,[mark()]);
  const removed = {...data(),suffix_events:[mark(false,'2026-10-03T00:00:00Z')]};
  assert.deepEqual(mergeData(removed,marked).suffix_events,removed.suffix_events);
  assert.deepEqual(mergeData(marked,removed).suffix_events,removed.suffix_events);
  const restored = {...data(),suffix_events:[mark(true,'2026-10-04T00:00:00Z')]};
  assert.deepEqual(mergeData(removed,restored).suffix_events,restored.suffix_events);
  assert.deepEqual(mergeData(removed,removed),validateData(removed));
});
test('suffix marks are per store, rate and day and do not change records or scoring inputs', () => {
  const marks=[mark(),mark(true,undefined,{rate:'5'}),mark(true,undefined,{store:'c2'}),mark(true,undefined,{day:'2026-09-30'})];
  const merged=mergeData({...data(),suffix_events:marks},data());
  assert.equal(merged.suffix_events.length,4);
  assert.deepEqual(merged.records,validateData(data()).records);
  assert.deepEqual(merged.machines,validateData(data()).machines);
});
