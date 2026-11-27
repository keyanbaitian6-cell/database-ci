// 共有カレンダーの機能1（台詳細の直近7日推移）・機能4（機種・台番号クイック検索）・機能5（最新営業日の3店舗比較）の
// 隔離ブラウザ試験（2026-11-27）。外部通信なし・モック応答のみ。320/393/1280px で横はみ出し・エラー・追加通信が無いことを検証する。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');

const root = process.env.SHARE_WEB_ROOT || fileURLToPath(new URL('../../share_viewer/', import.meta.url));
const server = http.createServer(async (req, res) => {
  const name = new URL(req.url, 'http://x').pathname.replace(/^\/share\//, '') || 'index.html';
  const local = path.resolve(root, name);
  if (!local.startsWith(path.resolve(root))) { res.writeHead(403).end(); return; }
  try {
    const body = await fs.readFile(local);
    res.setHeader('content-type', local.endsWith('.mjs') ? 'text/javascript' : 'text/html; charset=utf-8');
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const pageUrl = process.env.SHARE_PUBLIC_URL || `http://127.0.0.1:${server.address().port}/share/index.html`;

const FIXED_NOW = Date.parse('2026-11-27T12:00:00+09:00');
const id = 'AKfycbINSIGHT' + 'y'.repeat(37);

// 長町南 101番台に8営業日分（うち古い1日は別機種、さらに90日前の記録も1件）を配置。
const meruhen = {
  format: 'database-backup', version: 1, exported_at: '2026-11-27T06:30:00+09:00',
  records: [
    // 長町南 101番台：直近8日＋90日前（期間切替「全期間」の検証用）
    {store: 'nagamachiminami', day: '2026-11-26', machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 101, games: 7200, bb: 32, rb: 28, max_hold: 2600, jo_net: 2400, rainbow: true},
    {store: 'nagamachiminami', day: '2026-11-26', machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 102, games: 5500, bb: 20, rb: 16, max_hold: 1500, jo_net: -600},
    {store: 'nagamachiminami', day: '2026-11-26', machine: '北斗の拳', rack: 201, games: 6400, bb: 25, rb: 10, max_hold: 3200, jo_net: 1800},
    {store: 'nagamachiminami', day: '2026-11-25', machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 101, games: 5100, bb: 14, rb: 11, max_hold: 900, jo_net: -1200},
    {store: 'nagamachiminami', day: '2026-11-24', machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 101, games: 6800, bb: 27, rb: 22, max_hold: 2100, jo_net: 1500},
    {store: 'nagamachiminami', day: '2026-11-23', machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 101, games: 4300, bb: 12, rb: 9, max_hold: 800, jo_net: -850},
    {store: 'nagamachiminami', day: '2026-11-22', machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 101, games: 6200, bb: 24, rb: 20, max_hold: 1900, jo_net: 900},
    {store: 'nagamachiminami', day: '2026-11-21', machine: '旧機種テスト', rack: 101, games: 3100, bb: 8, rb: 6, max_hold: 700, jo_net: -500},
    {store: 'nagamachiminami', day: '2026-11-20', machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 101, games: 5900, bb: 22, rb: 18, max_hold: 1600, jo_net: 600},
    // 8営業日前（直近7日推移には入らない）
    {store: 'nagamachiminami', day: '2026-11-19', machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', rack: 101, games: 4000, bb: 10, rb: 10, max_hold: 1000, jo_net: 100},
    // 全期間のみで出る古い記録（2026-08-15）
    {store: 'nagamachiminami', day: '2026-08-15', machine: '夏の特別機種', rack: 101, games: 8000, bb: 40, rb: 30, max_hold: 4500, jo_net: 4200},
    // 幸町：25日は台データ、26日はアナスロHTML集計のみ（最新営業日は26日の勝率表示）
    {store: 'saiwaichou', day: '2026-11-25', machine: 'ハナハナ', rack: 10, games: 6000, bb: 25, rb: 20, jo_net: 1100},
  ],
  date_events: [
    {store: 'nagamachiminami', day: '2026-11-26', name: '特日<b>', updated_at: '2026-11-25T10:00:00+09:00'},
    {store: 'nagamachiminami', day: '2026-11-24', name: '並びイベ', updated_at: '2026-11-23T10:00:00+09:00'},
  ],
  day_summaries: [
    {store: 'saiwaichou', day: '2026-11-26', racks: 520, judged: 500, won: 185},
  ],
};

const pscube = {
  format: 'pscube-viewer', version: 1, exported_at: '2026-11-27T06:20:00+09:00', machines: [],
  records: [
    {store: 'c740601', rate: '20', day: '2026-11-25', machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', rack: 55, games: 6500, bb: 28, rb: 25, my: 3100, net_medals: 2800},
    {store: 'c740601', rate: '20', day: '2026-11-25', machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', rack: 56, games: 4000, bb: 10, rb: 8, my: 900, net_medals: -900},
    {store: 'c740601', rate: '20', day: '2026-11-24', machine: 'マイジャグラーV', rack: 55, games: 5200, bb: 18, rb: 15, my: 1800, net_medals: 700},
  ],
};

const pscubeEvents = {
  format: 'database-events', version: 1, kind: 'pscube',
  events: [{store: 'c740601', rate: '20', day: '2026-11-25', name: '末尾強化', updated_at: '2026-11-24T12:00:00+09:00'}],
};

const responses = {
  '': meruhen,
  pscube,
  events: {format: 'database-events', version: 1, kind: 'meruhen', events: []},
  'pscube-events': pscubeEvents,
  rainbow: {marks: []},
  'event-history': {format: 'database-event-history', version: 1, base: {version: 2, store: 'nagamachiminami', symbols: ['😀'], weeks: []}},
};

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  for (const width of [320, 393, 1280]) {
    const context = await browser.newContext({viewport: {width, height: 860}});
    await context.clock.setFixedTime(FIXED_NOW);
    const methods = [];
    let requests = 0;
    await context.route('https://script.google.com/**', route => {
      methods.push(route.request().method());
      requests++;
      const file = new URL(route.request().url()).searchParams.get('file') ?? '';
      route.fulfill({status: 200, contentType: 'application/json', headers: {'access-control-allow-origin': '*'},
        body: JSON.stringify(responses[file] ?? {error: 'no'})});
    });
    await context.route('**/character_birthdays.json*', route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({entries: []})}));
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(`${pageUrl}#s=${id}`);
    await page.waitForSelector('.grid');

    // --- 機能5：最新営業日の3店舗比較コンパクトカード ---
    const compare = page.locator('.store-compare');
    await compare.waitFor();
    const cards = compare.locator('.store-compare-card');
    assert.equal(await cards.count(), 3, '3店舗すべてを比較カードに表示');
    assert.equal(await page.locator('b').count(), 0, 'イベント名のHTMLはエスケープする');
    assert.equal(await page.locator('i').count(), 0, 'iタグは使わない');
    assert.equal(await page.getByText(/P’s CUBE/).count(), 0, 'P-STATION表記を守る');
    assert.match(await cards.nth(0).innerText(), /長町南\s*11\/26\s*特日<b>\s*\+3,600/);
    assert.match(await cards.nth(1).innerText(), /幸町\s*11\/26.*勝率37%\s*185\/500台/s);
    assert.match(await cards.nth(2).innerText(), /P-STATION\s*11\/25\s*末尾強化\s*\+1,900/);
    assert.ok(await cards.nth(0).evaluate(e => e.classList.contains('active')), '選択中の長町南がactive');
    assert.ok(await compare.evaluate(e => e.scrollWidth <= e.clientWidth), `3店舗比較が横にはみ出す（${width}px）`);

    const requestsAfterLoad = requests;
    // 選択中の長町南カードを押すと最新営業日（11/26）の詳細が開く
    await cards.nth(0).locator('.store-compare-cta').click();
    await page.waitForSelector('.sheet');
    assert.equal(await page.locator('#sheet-title').innerText(), '11月26日（木）');

    // --- 機能1：台詳細画面の直近7日間の推移 ---
    await page.locator('.sheet .row', {hasText: '101番'}).first().click();
    await page.locator('.sheet .row', {hasText: '101番'}).first().click();
    assert.equal(await page.locator('#sheet-title').innerText(), '101番台 🌈');
    const trend = page.locator('.rack-trend');
    await trend.waitFor();
    assert.equal(await trend.locator('.rack-trend-list > li').count(), 7, '直近7営業日だけ表示（8日前の11/19は含めない）');
    assert.doesNotMatch(await trend.innerText(), /11\/19/);
    assert.match(await trend.locator('.rack-trend-summary').innerText(), /記録 7日 ・ プラス 4\/7日 ・ 合計 \+2,850枚 ・ 平均 5,514G/);
    assert.match(await trend.locator('.rack-trend-item.current').innerText(), /11\/26.*表示中.*特日<b>/s);
    assert.match(await trend.innerText(), /並びイベ/);
    assert.match(await trend.locator('.rack-trend-item.other-machine').innerText(), /11\/21.*別機種：旧機種テスト/s);
    assert.equal(await trend.locator('[data-rack-history-day="2026-11-21"]').count(), 0, '別機種の日はジャンプボタンにしない');
    assert.ok(await trend.locator('.rack-trend-fill.plus').count() >= 1, 'プラスのミニバーを描画');
    assert.ok(await trend.locator('.rack-trend-fill.minus').count() >= 1, 'マイナスのミニバーを描画');
    assert.ok(await page.locator('.sheet').evaluate(e => e.scrollWidth <= e.clientWidth), `台詳細の直近7日推移が横にはみ出す（${width}px）`);
    // 同機種の別の日（11/24）を押すとその日の詳細へ移動する
    await trend.locator('[data-rack-history-day="2026-11-24"]').click();
    assert.equal(await page.getByRole('combobox', {name: '表示する日付'}).inputValue(), '2026-11-24');
    assert.match(await page.locator('.sheet .total .value').innerText(), /\+1,500/);
    assert.match(await page.locator('.rack-trend-item.current').innerText(), /11\/24.*表示中/s);
    // 戻る→戻る→閉じる
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    await page.getByRole('button', {name: '閉じる'}).click();
    await page.waitForSelector('.sheet', {state: 'detached'});

    // 機能5：未選択店舗（幸町）を押すと店舗切替 → もう一度押すとアナスロ集計（summary）シートが開く
    await page.locator('[data-compare-card="saiwaichou"] .store-compare-cta').click();
    assert.equal(await page.locator('.anchor[aria-pressed="true"]').innerText(), '幸町');
    await page.locator('[data-compare-card="saiwaichou"] .store-compare-cta').click();
    await page.waitForSelector('.sheet');
    assert.match(await page.locator('.sheet').innerText(), /勝率37%.*500台中185台プラス/s);
    await page.getByRole('button', {name: '閉じる'}).click();
    await page.waitForSelector('.sheet', {state: 'detached'});

    // 機能5：P-STATIONへ切替して「まいじゃぐ」で半角・全角カナ統合検索を検証
    await page.locator('[data-compare-card="pscube:c740601:20"] .store-compare-cta').click();
    assert.equal(await page.locator('.anchor[aria-pressed="true"]').innerText(), 'P-STATION');

    // --- 機能4：機種名・台番号のクイック検索シート ---
    await page.getByRole('button', {name: '機種・台番を検索'}).click();
    await page.waitForSelector('.sheet');
    assert.ok(await page.locator('.search-chip').count() >= 1, '空欄時は主要機種チップを表示');
    assert.equal(await page.locator('[data-search-clear]').isVisible(), false, '空欄時はクリアボタンを隠す');
    const input = page.locator('[data-search-input]');
    await input.click();
    await input.pressSequentially('まいじゃぐ');
    assert.equal(await page.locator('[data-search-clear]').isVisible(), true, '入力中はクリアボタンを表示');
    assert.ok(await input.evaluate(el => document.activeElement === el), '1文字ずつ打ってもフォーカスが外れない');
    assert.match(await page.locator('[data-search-results]').innerText(), /マイジャグラーV.*記録2日/s, '半角カナと全角カナを統合しひらがな検索で一致');
    // 機種を押して日別推移 → 11/25の台一覧 → 55番台の台詳細へ
    await page.locator('[data-search-machine="マイジャグラーV"]').first().click();
    assert.equal(await page.locator('#sheet-title').innerText(), 'マイジャグラーV');
    assert.match(await page.locator('.sheet .total').innerText(), /\+2,600.*記録2日/s);
    await page.locator('[data-search-machine-day="2026-11-25"]').click();
    assert.equal(await page.locator('.sheet .list .row').count(), 2);
    await page.locator('[data-search-day-rack="0"]').click();
    assert.equal(await page.locator('#sheet-title').innerText(), '55番台');
    assert.equal(await page.locator('.rack-trend-list > li').count(), 2, '検索経由の台詳細にも直近推移が出る');
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    await page.getByRole('button', {name: '閉じる'}).click();
    await page.waitForSelector('.sheet', {state: 'detached'});

    // 長町南に戻して、台番号検索・×クリア・期間切替（全期間）を検証
    await page.getByRole('button', {name: '長町南', exact: true}).click();
    await page.getByRole('button', {name: '機種・台番を検索'}).click();
    await page.waitForSelector('.sheet');
    await page.locator('[data-search-input]').fill('101番');
    assert.match(await page.locator('[data-search-results]').innerText(), /台番号の一致.*101番台/s);
    await page.locator('[data-search-rack="101"]').click();
    assert.equal(await page.locator('#sheet-title').innerText(), '101番台');
    // 「全期間」へ切り替えると8月の記録（夏の特別機種）も出る
    await page.locator('[data-search-period="all"]').click();
    assert.match(await page.locator('.sheet').innerText(), /夏の特別機種/);
    // 「差枚の高い順」へ並べ替えると+4,200の8/15が先頭になる
    await page.locator('[data-search-sort="net"]').click();
    assert.match(await page.locator('.sheet .list .row').first().innerText(), /8\/15.*夏の特別機種.*\+4,200/s);
    // 台別推移から詳細を開いたときは変な「前の台（同じ台番）」ボタンを出さない
    await page.locator('[data-search-rack-entry="0"]').click();
    assert.equal(await page.locator('#sheet-title').innerText(), '101番台');
    assert.equal(await page.locator('[data-rack-step]').count(), 0);
    assert.ok(await page.locator('.sheet').evaluate(e => e.scrollWidth <= e.clientWidth), `検索経由の台詳細が横にはみ出す（${width}px）`);
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    await page.getByRole('button', {name: '‹ 戻る'}).click();
    // ×ボタンで検索文字を消し、フォーカスが戻る
    await page.locator('[data-search-clear]').click();
    assert.equal(await page.locator('[data-search-input]').inputValue(), '');
    assert.ok(await page.locator('[data-search-input]').evaluate(el => document.activeElement === el), 'クリア後に検索入力欄へフォーカスが戻る');
    assert.ok(await page.locator('.sheet').evaluate(e => e.scrollWidth <= e.clientWidth), `検索シートが横にはみ出す（${width}px）`);
    await page.getByRole('button', {name: '閉じる'}).click();
    await page.waitForSelector('.sheet', {state: 'detached'});

    // 追加通信ゼロ・GETのみ・横はみ出し0px・エラー0件・localStorage余計なキーなし
    assert.equal(requests, requestsAfterLoad, '機能1・4・5の操作でGoogleへ追加通信しない');
    assert.deepEqual([...new Set(methods)], ['GET'], 'すべてGETのみ');
    const storageKeys = await page.evaluate(() => Object.keys(localStorage).sort());
    assert.deepEqual(storageKeys, ['database-share-script-id', 'database-share-store'], '検索や比較で余計なlocalStorageキーを増やさない');
    const overflow = await page.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 0, `メイン画面が横にはみ出す（${width}px、${overflow}px）`);
    assert.deepEqual(errors, []);
    await context.close();
  }

  // 1店舗しかないときは店舗比較カードを出さない
  {
    const context = await browser.newContext({viewport: {width: 393, height: 860}});
    await context.clock.setFixedTime(FIXED_NOW);
    const singleMeruhen = {...meruhen, records: meruhen.records.filter(r => r.store === 'nagamachiminami'), day_summaries: []};
    await context.route('https://script.google.com/**', route => {
      const file = new URL(route.request().url()).searchParams.get('file') ?? '';
      const body = file === '' ? singleMeruhen : file === 'pscube' ? {...pscube, records: []} : responses[file] ?? {error: 'no'};
      route.fulfill({status: 200, contentType: 'application/json', headers: {'access-control-allow-origin': '*'}, body: JSON.stringify(body)});
    });
    await context.route('**/character_birthdays.json*', route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({entries: []})}));
    const page = await context.newPage();
    await page.goto(`${pageUrl}#s=${id}`);
    await page.waitForSelector('.grid');
    assert.equal(await page.locator('.store-compare').count(), 0, '1店舗のみのときは店舗比較カードを表示しない');
    await context.close();
  }
  console.log('PASS: share viewer rack trend (7d), quick search (machine/rack), 3-store comparison card (320/393/1280px)');
} finally {
  await browser.close();
  server.close();
}
