import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import vm from 'node:vm';
import {test} from 'node:test';

const source = readFileSync(new URL('../lib/web_import_page.dart', import.meta.url), 'utf8');
const script = name => source.match(new RegExp(`const ${name} = r'''([\\s\\S]*?)'''`))[1];
const pc = spawnSync('python', ['-c', 'import json,browser_import as b; print(json.dumps([b.GRAPH_EXTRACT_BODY,b.TABLE_EXTRACT_BODY]))'],
  {cwd: new URL('../../database/', import.meta.url), encoding: 'utf8'});
assert.equal(pc.status, 0, pc.stderr);
const [pcGraph, pcTable] = JSON.parse(pc.stdout).map(body => `(() => {${body}})()`);
function fixture({zero = true, zeroY = '200', values = {}, kind = '21', day = '2026-09-22', linkDay = '', pickedDay = '', scopeEntries = {}} = {}) {
  const svg = {
    viewBox: {baseVal: {width: 400, height: 400}},
    querySelector(selector) {
      if (selector === '.path-slump path') return {getAttribute: () => 'M0 200 L100 250 L200 80 L300 150'};
      if (selector === '.back-line-middle line') return zero ? {getAttribute: () => zeroY} : null;
      return Object.hasOwn(values, selector) ? {textContent: values[selector]} : null;
    },
  };
  const sessionEntries = new Map(Object.entries(scopeEntries).map(([key, value]) => [key, JSON.stringify(value)]));
  return {
    sessionStorage: {get length() { return sessionEntries.size; }, key: index => [...sessionEntries.keys()][index] ?? null,
      getItem: key => sessionEntries.get(key) ?? null},
    location: new URL(`https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph?kind_code=${kind}&rack_no=703${day ? '&target_date=' + day : ''}`),
    URL, document: {body: {innerText: '更新日時 2030/01/01'}, querySelector: () => svg, querySelectorAll(selector) {
      if (selector === 'a[href*="target_date="]' && linkDay) return [{href: `https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph?rack_no=703&target_date=${linkDay}`}];
      if (selector === 'select option:checked' && pickedDay) return [{textContent: pickedDay}];
      return [];
    }},
  };
}
const result = async (code, options) => JSON.parse(await vm.runInNewContext(code, fixture(options)));
test('Android: ゼロ線が無ければ0座標を捏造せずエラー', async () => {
  assert.match((await result(script('_extractGraphScript'), {zero: false})).error, /ゼロ線/);
});
for (const [name, code] of [['Android', script('_extractGraphScript')], ['PC', pcGraph]]) {
  test(`${name}: 欠損した数値は0ではなくnull`, async () => {
    const r = await result(code, {});
    assert.equal(r.games, null); assert.equal(r.max_hold, null);
  });
  test(`${name}: 実測0とカンマ付き数字を読める`, async () => {
    const r = await result(code, {values: {'.info_soukaiten': '3,500', '.info_big': '0'}});
    assert.equal(r.games, 3500); assert.equal(r.bb, 0);
  });
  test(`${name}: ゼロ線のy座標属性が欠けていたら拒否`, async () => {
    assert.match((await result(code, {zeroY: null})).error, /ゼロ線/);
  });
  test(`${name}: 日付はURL、台リンク、選択欄の順で本文を使わない`, async () => {
    const read = async options => { const r = await result(code, options); return r.target_date ?? r.day ?? null; };
    assert.equal(await read({day: '2026-12-31', linkDay: '2027-01-01', pickedDay: '2027/01/02'}), '2026-12-31');
    assert.equal(await read({day: '', linkDay: '2026-12-31', pickedDay: '2027/01/02'}), '2026-12-31');
    assert.equal(await read({day: '', pickedDay: '2024/02/29'}), '2024-02-29');
    assert.equal(await read({day: ''}), null);
  });
}
for (const name of ['_extractTableScript', '_extractGraphScript']) {
  test(`Android: ${name}は低貸しを直接開いても拒否`, async () => {
    for (const kind of ['5', '10']) assert.match((await result(script(name), {kind})).error, /46|対象外/);
  });
}

test('PC: 表のURLと台リンクに日付が無ければ選択欄を使う', async () => {
  const context = fixture({day: '', pickedDay: '2024/02/29'});
  const headers = ['台番号', 'BB', 'RB', '総回転数', '合成確率', '前日最終スタート', '最大持玉'];
  const rows = [headers, ['703', '20', '5', '3000', '1/120', '50', '2000']];
  const table = {querySelectorAll(selector) {
    if (selector === 'tr') return rows.map(cells => ({querySelectorAll: () => cells.map(textContent => ({textContent}))}));
    if (selector === 'td a') return [{href: 'https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph?rack_no=703'}];
    return [];
  }};
  const query = context.document.querySelectorAll;
  context.document.querySelectorAll = selector => selector === 'table' ? [table] : query(selector);
  assert.equal(JSON.parse(vm.runInNewContext(pcTable, context)).target_date, '2024-02-29');
});

test('PC: 4円パチンコの台一覧（台番号・大当り・大当り確率・総回転数）も読む（2026-10-12、pachinko.py）', async () => {
  const context = fixture({day: '2026-10-10'});
  const rows = [['台番号▲', '大当り', '大当り確率', '総回転数'], ['80', '12', '1/222.8', '2673'], ['81', '4', '1/677.5', '2710']];
  const table = {querySelectorAll(selector) {
    if (selector === 'tr') return rows.map(cells => ({querySelectorAll: () => cells.map(textContent => ({textContent}))}));
    if (selector === 'td a') return [80, 81].map(r => ({href: `https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph?rack_no=${r}`}));
    return [];
  }};
  const query = context.document.querySelectorAll;
  context.document.querySelectorAll = selector => selector === 'table' ? [table] : query(selector);
  const r = JSON.parse(vm.runInNewContext(pcTable, context));
  assert.deepEqual(r.matrix, [['台番号', '大当り', '大当り確率', '総回転数'], ['80', '12', '1/222.8', '2673'], ['81', '4', '1/677.5', '2710']]);
  assert.equal(r.links.length, 2);
});

test('PC: 台のページは種別を返し（判定はPython）、グラフの中の数字とページの文字も返す（パチンコ用）', async () => {
  const context = fixture({kind: '1'});
  const svg = context.document.querySelector('svg.today');
  svg.querySelectorAll = selector => selector === '[class*="info_"]'
    ? [{classList: ['info_soukaiten'], textContent: '2673'}, {classList: ['x', 'info_max_mochidama'], textContent: '14030'}] : [];
  context.document.body.innerText = 'メニュー\n台データ情報\n大当り\n12';
  const r = JSON.parse(vm.runInNewContext(pcGraph, context));
  assert.equal(r.error, undefined);
  assert.equal(r.kind_code, '1');
  assert.deepEqual(r.info, {info_soukaiten: '2673', info_max_mochidama: '14030'});
  assert.equal(r.page_text, '台データ情報\n大当り\n12');
});

test('PC: グラフ読み取りは保存済み一覧の台範囲を返す', async () => {
  const scope = [703, 704];
  const context = fixture({scopeEntries: {'database-rack-scope:saiwaichou:2026-09-22:テスト': scope}});
  assert.deepEqual(JSON.parse(vm.runInNewContext(pcGraph, context)).rack_scope, scope);
});

test('Android: 行クリックで半角カナ、空白、+を同じ機種として照合', () => {
  let clicks = 0;
  const row = {textContent: 'L ｶﾊﾞﾈﾘ', querySelector: selector => selector === 'th' ? null : {textContent: 'L ｶﾊﾞﾈﾘ'}, click: () => clicks++};
  const context = {document: {querySelectorAll: selector => selector.startsWith('tr.') ? [row] : []},
    setTimeout: callback => callback(), location: new URL('https://example.invalid'), URL};
  assert.equal(vm.runInNewContext(`(${script('_clickMachineRowScript')})('L+カバネリ')`, context), true);
  assert.equal(clicks, 1);
});

// Minimal DOM for the actual hide script. No network or browser is involved.
class Element {
  constructor(tag, attrs = {}, children = []) {
    this.tagName = tag.toUpperCase(); this.attrs = attrs; this.children = children;
    this.dataset = {}; this.textContent = ''; this.writes = 0;
    this.style = {setProperty: () => this.writes++};
    children.forEach(child => { child.parentElement = this; });
  }
  get attributes() { return Object.entries(this.attrs).map(([name, value]) => ({name, value})); }
  getAttribute(name) { return this.attrs[name] ?? null; }
  matches(selector) {
    if (selector === '[data-database-hidden]') return !!this.dataset.databaseHidden;
    return selector.split(',').map(s => s.trim().toUpperCase()).includes(this.tagName);
  }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) ?? null; }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [child, ...child.querySelectorAll('*')])
      .filter(child => selector === '*' || (selector.startsWith('body *') ? !child.dataset.databaseHidden : child.matches(selector)));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
  contains(child) { return child === this || this.querySelectorAll('*').includes(child); }
  remove() { this.parentElement.children = this.parentElement.children.filter(child => child !== this); }
}

test('Android: YouTubeと同じ親の表・SVG・canvas・日付欄は隠さない', () => {
  for (const tag of ['table', 'svg', 'canvas', 'select']) {
    const frame = new Element('iframe', {src: 'https://www.youtube.com/embed/test'});
    const data = new Element(tag);
    const card = new Element('div', {class: 'youtube-card'}, [frame, data]);
    const body = new Element('body', {}, [card]);
    const context = {document: {body, documentElement: body, querySelectorAll: s => body.querySelectorAll(s)},
      window: {}, MutationObserver: class { observe() {} }, setTimeout: () => {}};
    vm.runInNewContext(script('_hideYouTubeScript'), context);
    assert.equal(body.contains(frame), false, tag);
    assert.equal(card.dataset.databaseHidden, undefined, tag);
    assert.equal(data.dataset.databaseHidden, undefined, tag);
  }
});

test('Android: 非表示にしたYouTubeの子孫へ繰り返しstyleを書かない', () => {
  const thumb = new Element('img', {src: 'https://i.ytimg.com/vi/test/default.jpg'});
  const card = new Element('div', {class: 'youtube-card'}, [thumb]);
  const body = new Element('body', {}, [card]);
  let callback, timer, observers = 0;
  const context = {document: {body, documentElement: body, querySelectorAll: s => body.querySelectorAll(s)},
    window: {}, MutationObserver: class { constructor(cb) {callback = cb; observers++;} observe() {} },
    setTimeout: cb => {timer = cb;}};
  vm.runInNewContext(script('_hideYouTubeScript'), context);
  assert.equal(card.dataset.databaseHidden, '1');
  const writes = card.writes + thumb.writes;
  callback(); callback(); timer();
  vm.runInNewContext(script('_hideYouTubeScript'), context);
  assert.equal(card.writes + thumb.writes, writes);
  assert.equal(observers, 1);
});
