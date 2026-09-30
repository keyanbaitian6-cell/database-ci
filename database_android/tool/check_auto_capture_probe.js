// Run the actual embedded JavaScript against synthetic DOM states, without a site.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../lib/web_import_page.dart'), 'utf8');
const match = source.match(/const _autoProbeScript = r'''([\s\S]*?)''';/);
assert.ok(match, 'auto probe script is present');

function probe({kind = 'machines', ready = 'complete', busy = false,
                dialog = false, captcha = false, text = '対象データ', content = true} = {}) {
  const root = 'https://example.test/nagamachiminami/';
  const url = root + (kind === 'machines' ? 'rack_info_kt?kind_code=21' :
    kind === 'table' ? 'standlist_slot?kind_code=21&machine_name=TEST' :
    'graph?kind_code=21&rack_no=1');
  const element = (value = 'one') => ({
    innerText: value, textContent: value, tagName: 'TR',
    getClientRects: () => [1], getAttribute: () => value,
  });
  const selections = {
    '[aria-busy="true"], .loading, .spinner': busy ? [element()] : [],
    'dialog[open], [role="dialog"], [aria-modal="true"]': dialog ? [element()] : [],
    'iframe[src*="captcha"], iframe[src*="recaptcha"], iframe[src*="hcaptcha"]': captcha ? [element()] : [],
    tr: content ? [element('1 2 3')] : [],
    'svg path, svg polyline': content && kind === 'graph' ? [element('M 0 0')] : [],
    'canvas, img': [],
  };
  const document = {
    readyState: ready,
    body: {innerText: text},
    querySelectorAll: selector => selections[selector] || [],
    querySelector: selector => selector === 'tr.teram2-link-block, a[href*="machine_name"]' && content
      ? element() : null,
  };
  return JSON.parse(vm.runInNewContext(match[1], {
    document, location: {href: url}, window: {jQuery: {active: 0}},
  }));
}

assert.equal(probe({ready: 'loading'}).ready, false);
assert.equal(probe({busy: true}).ready, false);
assert.equal(probe({dialog: true}).ready, false);
assert.equal(probe({captcha: true}).ready, false);
assert.equal(probe({text: 'ロボットではありません'}).ready, false);
assert.equal(probe({content: false}).ready, false);
for (const kind of ['machines', 'table', 'graph']) {
  const result = probe({kind});
  assert.equal(result.ready, true, kind);
  assert.ok(result.signature.includes(result.url));
}
console.log('auto probe: 9 synthetic cases passed');
