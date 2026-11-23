// 合成データだけで共有カレンダーの長期履歴と更新の中断を確かめる。
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import {after, before, test} from 'node:test';
import {fileURLToPath} from 'node:url';
import {RECOMMENDATION_DEFAULT} from '../../share_viewer/recommendations.mjs';

const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(process.env.SHARE_WEB_ROOT || fileURLToPath(new URL('../../share_viewer/', import.meta.url)));
const server = http.createServer(async (request, response) => {
  const name = new URL(request.url, 'http://local').pathname.slice(1);
  const file = path.resolve(root, name || 'index.html');
  if (!file.startsWith(root + path.sep)) return response.writeHead(403).end();
  try {
    const body = await fs.readFile(file);
    const type = name.endsWith('.mjs') ? 'text/javascript' : name.endsWith('.json') ? 'application/json' : 'text/html; charset=utf-8';
    response.writeHead(200, {'content-type': type}).end(body);
  } catch { response.writeHead(404).end(); }
});
let browser, origin;
before(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
});
after(async () => {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
});

const start = Date.parse('2026-10-31T21:00:00Z');
const id = 'AKfycbLONGHISTORY' + 'x'.repeat(35);
const alternateId = 'AKfycbOTHERHISTORY' + 'x'.repeat(35);
const sixHours = 6 * 60 * 60 * 1000;
const lastDay = '2026-11-01';
const history = {format: 'database-event-history', version: 1,
  base: {version: 2, store: 'nagamachiminami', symbols: ['😍', '😀', '😌', '🥶', '😇'], weeks: []},
  cells: [], links: [], weeks: [],
  recommendations: [{...RECOMMENDATION_DEFAULT, week: '2026-10-19'}]};
const meruhenRow = (day, rack, machine, store = 'nagamachiminami') =>
  ({store, day, rack, machine, games: rack === 700 ? 300 : 3000, bb: 12, rb: 8, jo_net: rack === 1 ? 1200 : -250});
const small = {meruhen: [meruhenRow(lastDay, 1, '試験機')], pscube: []};

async function session(data = small) {
  const context = await browser.newContext({viewport: {width: 393, height: 852}, serviceWorkers: 'block'});
  let mode = 'success';
  const calls = [];
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin === origin) return route.continue();
    if (url.origin !== 'https://script.google.com') return route.abort();
    calls.push(url.pathname);
    if (mode === 'interrupt') return; // 通信中のままページを閉じる。
    const file = url.searchParams.get('file');
    const body = mode === 'fail' ? {error: '試験用の通信失敗'} :
      !file ? {format: 'database-backup', version: 1, records: data.meruhen} :
      file === 'pscube' ? {format: 'pscube-viewer', version: 1, records: data.pscube} :
      file === 'event-history' ? history : {events: [], marks: []};
    await route.fulfill({json: body, headers: {'access-control-allow-origin': '*'}});
  });
  return {
    context, setMode: next => { mode = next; }, callsFor: id => calls.filter(p => p.includes(`/${id}/`)).length,
    async navigate(page, now, scriptId) {
      await page.clock.setFixedTime(now);
      await page.goto(`${origin}/#s=${scriptId}`);
    },
    async open(now = start, scriptId = id) {
      const page = await context.newPage();
      await this.navigate(page, now, scriptId);
      return page;
    },
  };
}

async function measureHeap(page, action) {
  const cdp = await page.context().newCDPSession(page);
  let peak = 0, samples = 0, pending;
  const sample = async () => {
    const {usedSize} = await cdp.send('Runtime.getHeapUsage');
    peak = Math.max(peak, usedSize);
    samples++;
  };
  await sample();
  const timer = setInterval(() => {
    pending ??= sample().catch(() => { /* ページが移動中の観測は次に試す。 */ }).finally(() => { pending = null; });
  }, 10);
  try {
    await action();
    await sample();
  } finally {
    clearInterval(timer);
    await pending;
    await cdp.detach();
  }
  return {peakMiB: +(peak / 1048576).toFixed(1), samples};
}

test('更新中断後6時間は同じ共有先の起動時だけ止める', async () => {
  const env = await session();
  try {
    env.setMode('interrupt');
    const pending = env.context.waitForEvent('request', r => r.url().includes(`/${id}/`));
    let page = await env.open();
    await page.getByText('Googleドライブから読み込んでいます…', {exact: false}).waitFor();
    await pending;
    await page.close();
    const interrupted = env.callsFor(id);
    assert.ok(interrupted > 0);
    env.setMode('success');

    page = await env.open(start + sixHours - 1);
    await page.getByText(/前回の更新が途中で止まったため/).waitFor({timeout: 5000});
    assert.equal(env.callsFor(id), interrupted);
    const other = await env.open(start + 1000, alternateId);
    await other.locator('.grid').waitFor();
    assert.ok(env.callsFor(alternateId) > 0, '別の共有先の起動を止めない');
    await other.close();
    await page.close();

    page = await env.open(start + sixHours);
    await page.locator('.grid').waitFor();
    assert.ok(env.callsFor(id) > interrupted, '6時間ちょうどで起動時の更新を再開する');
  } finally { await env.context.close(); }
});

test('保存済み表示と手動更新を中断後も使え、正常に処理した失敗で停止を解除する', async () => {
  const env = await session();
  try {
    let page = await env.open();
    await page.locator('.grid').waitFor();
    env.setMode('interrupt');
    const pending = page.waitForRequest(r => r.url().includes(`/${id}/`));
    await page.locator('#reload').click();
    await pending;
    await page.close();
    const interrupted = env.callsFor(id);

    page = await env.open(start + 1000);
    await page.locator('.grid').waitFor();
    await page.getByText(/前回の更新が途中で止まったため/).waitFor({timeout: 5000});
    assert.equal(env.callsFor(id), interrupted);
    env.setMode('fail');
    await page.locator('#reload').click();
    await page.getByText(/更新できませんでした/).waitFor();
    assert.ok(env.callsFor(id) > interrupted, '保留中でも手動更新を受け付ける');
    await page.close();

    page = await env.open(start + 2000);
    await page.getByText(/端末に保存したデータを表示しています/).waitFor();
    assert.equal(await page.getByText(/前回の更新が途中で止まったため/).count(), 0);
  } finally { await env.context.close(); }
});

test('180日分の初回取得・手動更新・再起動のヒープを測り、4大オススメの表示と再描画を確かめる', async () => {
  const data = {meruhen: [], pscube: []};
  const first = Date.parse(lastDay) - 179 * 86400000;
  for (let offset = 0; offset < 180; offset++) {
    const day = new Date(first + offset * 86400000).toISOString().slice(0, 10);
    for (let rack = 1; rack <= 380; rack++) {
      const machine = RECOMMENDATION_DEFAULT.machines[Math.floor((rack - 1) / 7)] ?? '主力';
      if (rack !== 1 || day !== '2026-10-27') data.meruhen.push(meruhenRow(day, rack, machine));
    }
    for (let rack = 381; rack <= 699; rack++) data.meruhen.push(meruhenRow(day, rack, '主力', 'saiwaichou'));
    data.meruhen.push(meruhenRow(day, 700, '低回転'));
    for (let rack = 701; rack <= 970; rack++) {
      data.pscube.push({store: 'c740601', rate: '20', day, machine: '長期試験機', rack,
        games: 3000, bb: 12, rb: 8, net_medals: 100});
    }
  }
  const env = await session(data);
  try {
    await env.context.addInitScript(() => {
      const {get, values} = Map.prototype;
      globalThis.recommendationReads = {days: 0, all: 0};
      Map.prototype.get = function (key) {
        if (Object.hasOwn(this, 'issues') && String(key).startsWith('nagamachiminami|')) recommendationReads.days++;
        return get.call(this, key);
      };
      Map.prototype.values = function () {
        if (Object.hasOwn(this, 'issues')) recommendationReads.all++;
        return values.call(this);
      };
    });
    let page = await env.context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const open = async () => {
      await env.navigate(page, start, id);
      await page.locator('.grid').waitFor({timeout: 60000});
    };
    const initial = await measureHeap(page, open);
    const manual = await measureHeap(page, async () => {
      await page.locator('#reload').click();
      await page.locator('#reload:enabled').waitFor({timeout: 60000});
    });
    await page.close();
    page = await env.context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    const reopen = await measureHeap(page, open);
    console.log(JSON.stringify({days: 180, records: data.meruhen.length + data.pscube.length, initial, manual, reopen}));

    await page.getByRole('button', {name: 'バラエティの回っていない台'}).click();
    assert.match(await page.locator('.sheet').innerText(), /700番\s*低回転\s*180日間/);
    await page.getByRole('button', {name: '閉じる', exact: true}).click();
    await page.getByRole('button', {name: 'イベント履歴', exact: true}).click();
    await page.evaluate(() => { recommendationReads.days = 0; recommendationReads.all = 0; });
    await page.getByRole('button', {name: '4大オススメ', exact: true}).click();
    const row = page.locator('.recommendation-table').first().locator('tbody tr').first();
    assert.equal(await row.locator('th').innerText(), '1番');
    assert.deepEqual(await row.locator('td .num').allInnerTexts(), ['+1,200', '—', '+1,200', '+1,200', '+1,200', '+1,200', '+1,200']);
    const week = page.locator('[data-recommendation-week]');
    const firstRead = await page.evaluate(() => ({...recommendationReads}));
    assert.equal(firstRead.all, 0, '全日・全店舗の行を並べ直さない');
    assert.ok(firstRead.days <= 7, '対象週の7日だけを参照する');
    await week.dispatchEvent('change');
    assert.deepEqual(await page.evaluate(() => ({...recommendationReads})), firstRead, '同じ週の再描画で結果を再利用する');
    await week.selectOption('2026-10-19');
    assert.deepEqual(await row.locator('td .num').allInnerTexts(), Array(7).fill('+1,200'));
    for (const value of [initial, manual, reopen]) {
      assert.ok(value.peakMiB > 0 && value.samples > 1, '各工程のヒープを複数回観測した');
    }
    assert.deepEqual(errors, []);
  } finally { await env.context.close(); }
});
