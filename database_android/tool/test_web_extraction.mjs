import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../lib/web_import_page.dart', import.meta.url), 'utf8');
const script = name => source.match(new RegExp(`const ${name} = r'''([\\s\\S]*?)'''`))[1];
const tableScript = script('_extractTableScript');
const graphScript = script('_extractGraphScript');
const bridge = script('_extractionBridgeScript');
// Exercise the exact embedded JS and asynchronous channel contract, not Dart parsing alone.
for (const code of [tableScript, graphScript, `(${bridge})`]) new vm.Script(code);
const location = new URL('https://meruhenworld.pt.teramoba2.com/nagamachiminami/standlist_slot?machine_name=Test&target_date=2026-09-14');
const header = ['台番号', 'BB', 'RB', '総回転数', '最大持玉', '前日最終'];
function fixture(rows, {offline = false, graph = false} = {}) {
  const lines = [header, ...rows].map(cells => ({querySelectorAll: () => cells.map(value => ({innerText: String(value)}))}));
  const svgValues = {'.info_soukaiten': '3000', '.info_big': '20', '.info_reg': '4', '.info_max_mochidama': '1500'};
  const svg = {
    viewBox: {baseVal: {width: 400, height: 400}},
    querySelector(selector) {
      if (selector === '.path-slump path') return {getAttribute: () => 'M 0 200 L 100 250 L 200 80 L 300 150'};
      if (selector === '.back-line-middle line') return {getAttribute: () => '200'};
      return {textContent: svgValues[selector]};
    },
  };
  return {
    location, URL, AbortController, setTimeout, clearTimeout,
    document: {
      body: {innerText: '2026/09/17 更新\n235番台'},
      querySelector: () => graph ? svg : null,
      querySelectorAll: selector => selector === 'table' ? [{querySelectorAll: () => lines}] : [],
    },
    fetch: async () => {
      await new Promise(resolve => setTimeout(resolve, 10));
      if (offline) throw new Error('offline');
      return {ok: true, text: async () => 'fixture'};
    },
    DOMParser: class {
      parseFromString() {
        return {querySelectorAll: () => [{href: location.href, closest: () => ({textContent: 'Test 2台'})}]};
      }
    },
  };
}
function execute(code, context) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Channel did not return a result')), 1500);
    context.DatabaseExtraction = {postMessage(message) {clearTimeout(timer); resolve(JSON.parse(message));}};
    vm.runInNewContext(`(${bridge})(${JSON.stringify(code)}, 7)`, context);
  });
}
const zeroRows = [[235, 0, 0, 0, 0, 12], [236, 0, 0, 0, 0, 13]];
let reply = await execute(tableScript, fixture(zeroRows));
assert.equal(reply.id, 7);
assert.equal(reply.error, undefined);
assert.equal(typeof reply.value, 'string');
assert.deepEqual(JSON.parse(reply.value).rows.map(row => row.rack), [235, 236]);
// The table reader intentionally performs no background list fetch now.
assert.equal(JSON.parse(reply.value).expected_count, null);
assert.equal(JSON.parse(reply.value).day, '2026-09-14');
reply = await execute(tableScript, fixture(zeroRows, {offline: true}));
assert.equal(JSON.parse(reply.value).rows.length, 2);
assert.equal(JSON.parse(reply.value).expected_count, null);
reply = await execute(tableScript, fixture([zeroRows[0], zeroRows[0]]));
assert.equal(JSON.parse(reply.value).rows.length, 1);
reply = await execute(tableScript, fixture([zeroRows[0], [235, 1, 0, 0, 0, 12]]));
assert.match(reply.error, /235/);
reply = await execute(graphScript, fixture([], {graph: true}));
const result = JSON.parse(reply.value);
assert.equal(result.day, '2026-09-14');
assert.equal(result.rack, 235);
assert.equal(result.games, 3000);
assert.deepEqual(result.auto_points, [[340, 200], [200, 80], [100, 250], [300, 150]]);
reply = await execute('throw new Error("test failure")', fixture([]));
assert.match(reply.error, /test failure/);
console.log('PASS: table, async count, offline fallback, distinct zero rows, duplicate rack, graph points/date, error channel');
