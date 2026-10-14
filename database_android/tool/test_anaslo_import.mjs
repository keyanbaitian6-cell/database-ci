import test from 'node:test';
import assert from 'node:assert/strict';
import {emptyData, validateData, mergeData} from '../web/pscube/data.mjs';
import {scoreRecord, comparisonPool, nextDayEvidence} from '../web/pscube/scoring.mjs';

const m = {store:'c740601', rate:'20', machine:'マイジャグラーV', expected_count:null, machine_type:null,
  url:null, source_site:'anaslo'};
const r = {store:m.store, rate:m.rate, machine:m.machine, rack:101, day:'2026-09-15', games:3000, bb:8, rb:4, at_art:0,
  my:null, detail_url:null, observed_at:null, graph:null, net_medals:null, source_site:'anaslo',
  source_url:'https://ana-slo.com/2026-09-15-p-stationii-data/', source_sha256:'a'.repeat(64), source_machine:m.machine,
  source_graph:{kind:'source_coordinates', points:[[0,100],[1,80]], zero_y:100},
  source_probabilities:{bb:{display:'1/375.0', denominator:375.0}}};
const doc = () => ({...emptyData(), machines:[{...m}], records:[structuredClone(r)]});
const native = () => ({...r, source_site:undefined, my:1000, games:1000,
  detail_url:'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=101#20260915'});

test('unknown values and provenance survive validation and JSON roundtrip', () => {
  const parsed = validateData(doc());
  assert.equal(parsed.records[0].my, null);
  assert.deepEqual(validateData(JSON.parse(JSON.stringify(parsed))), parsed);
  assert.deepEqual(parsed.records[0].source_graph, r.source_graph);
});
test('external rows do not overwrite existing native racks, even across aliases', () => {
  const old = doc(); old.records[0] = native();
  const fresh = doc(); fresh.records[0].machine = '別表記'; fresh.machines[0].machine = '別表記';
  const result = mergeData(old, fresh);
  assert.equal(result.records.length, 1);
  assert.equal(result.records[0].my, 1000);
});
test('native data supersedes external rows even with fewer games', () => {
  const fresh = doc(); fresh.records[0] = native();
  const result = mergeData(doc(), fresh);
  assert.equal(result.records[0].my, 1000);
  assert.equal(mergeData(result, doc()).records[0].my, 1000);
});
test('invalid native MY and invented external MY are rejected', () => {
  for (const row of [{...r, my:0}, {...native(), my:null}, {...r, source_url:'https://example.com/'}, {...r, source_sha256:'x'}]) {
    const d = doc(); d.records[0] = row;
    assert.throws(() => validateData(d));
  }
});
test('external rows are not scored or used as forecast evidence', () => {
  const d = validateData(doc());
  assert.equal(scoreRecord(d.records[0], d).total, null);
  assert.equal(comparisonPool({...d.records[0], day:'2026-09-16'}, d).length, 0);
  assert.equal(nextDayEvidence(d.records[0], d).usedDays, 0);
});
