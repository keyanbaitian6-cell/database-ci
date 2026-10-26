// 台数の多い機種の全台一覧を表示するスクロール処理（database/pscube_import.py の SCROLL_SCRIPT）。
// 実サイトには接続しない。待ち時間は scrollDelayScale で縮める（台数の判定は待ち回数で数える）。
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const source = readFileSync(new URL('../../database/pscube_import.py', import.meta.url), 'utf8');
const scroll = source.match(/SCROLL_SCRIPT = r'''([\s\S]*?)'''/)[1];
const SCALE = 0.1;
// SCROLL_SCRIPT は、取り込み画面の中で expectedCount（設置台数。不明なら未定義）を参照する。
const run = (page, count) => page.evaluate(({script, count, scale}) => {
  const scrollDelayScale = scale;
  const expectedCount = count;   // 未定義(null)のときは台数不明として扱う
  return eval(count === null ? script.replace(/typeof expectedCount === 'number'/, 'false') : script);
}, {script: scroll, count, scale: SCALE});
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined});
try {
  // 1. 最後の台が見えると20台ずつ続きが来る（リストごと入れ替わる）。台数不明でも61台まで読む。
  const page = await browser.newPage({viewport: {width: 1050, height: 780}});
  for (const index of [true, false]) {
    await page.setContent(`<ul ${index ? 'id="ulKI"' : ''}><li id="li-1">1</li></ul><footer>Footer</footer>`);
    await page.evaluate(index => {
      Element.prototype.scrollIntoView = function() {
        const list = index ? document.querySelector('#ulKI') : document.querySelector('li[id^="li-"]').parentElement;
        if (this !== list.lastElementChild || list.children.length >= 61) return;
        const replacement = list.cloneNode(true);
        for (let n = list.children.length + 1; n <= Math.min(list.children.length + 20, 61); n++) {
          const card = document.createElement('li'); card.id = `li-${n}`; replacement.append(card);
        }
        list.replaceWith(replacement);
      };
    }, index);
    await run(page, null);
    assert.equal(await page.locator('li').count(), 61);
  }

  // 1b. 機種一覧（台数不明）：20件ずつ、一番下に着いてから3.5秒（縮めて0.35秒）後に届く61件。
  //     以前は一番下で3秒増えなければ終わり、20件・40件で読み取った（2026-10-24〜26、Android）。
  //     一番下に1回着いただけでは続きが始まらず、着き直したときに始まるサイトでも61件まで読む。
  const tallIndex = (n) => `<div style="height:300px">header</div><ul id="ulKI">${Array.from({length: n}, (_, i) => `<li style="height:150px">${i + 1}</li>`).join('')}</ul><footer style="height:1500px">Footer</footer>`;
  for (const ignoreFirst of [false, true]) {
    const slowIndex = await browser.newPage({viewport: {width: 1050, height: 780}});
    await slowIndex.setContent(tallIndex(20));
    await slowIndex.evaluate(({scale, ignoreFirst}) => {
      let pending = false, ignored = !ignoreFirst, wasBottom = false;
      window.addEventListener('scroll', () => {
        const bottom = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 5;
        const arrived = bottom && !wasBottom;
        wasBottom = bottom;
        const list = document.querySelector('#ulKI');
        if (!arrived || pending || list.children.length >= 61) return;
        if (!ignored) { ignored = true; return; }
        pending = true;
        setTimeout(() => {
          for (let k = 0; k < 20 && list.children.length < 61; k++) {
            const card = document.createElement('li'); card.style.height = '150px'; list.append(card);
          }
          pending = false;
        }, 3500 * scale);
      });
    }, {scale: SCALE, ignoreFirst});
    await run(slowIndex, null);
    assert.equal(await slowIndex.locator('#ulKI li').count(), 61, `遅い続きでも機種一覧を最後まで読む（最初の到着を無視：${ignoreFirst}）`);
    await slowIndex.close();
  }

  // 2. 実サイト（2026-10-02 PC版で表示6台・設置7台）：最後の台が見えても続きは来ず、ページの一番下まで
  //    スクロールしたときだけ次の台が増える。
  const tall = (n) => `<div style="height:300px">header</div><ul>${Array.from({length: n}, (_, i) => `<li id="li-${i + 1}" style="height:150px">${i + 1}</li>`).join('')}</ul><footer style="height:1500px">Footer</footer>`;
  const loadsAtBottom = ([total, batch]) => {
    window.addEventListener('scroll', () => {
      const list = document.querySelector('li[id^="li-"]').parentElement;
      if (list.children.length < total && window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 5) {
        for (let k = 0; k < batch && list.children.length < total; k++) {
          const card = document.createElement('li'); card.id = `li-${list.children.length + 1}`; card.style.height = '150px'; list.append(card);
        }
      }
    });
  };
  const plain = await browser.newPage({viewport: {width: 1050, height: 780}});
  await plain.setContent(tall(6));
  await plain.evaluate(loadsAtBottom, [7, 1]);
  await run(plain, 7);
  assert.equal(await plain.locator('li').count(), 7, '一番下まで進めば7台目が来る');

  // 3. 台数の多い機種：20台ずつ届く64台。台数が分かっていれば届いたところで終わる。
  const many = await browser.newPage({viewport: {width: 1050, height: 780}});
  await many.setContent(tall(20));
  await many.evaluate(loadsAtBottom, [64, 20]);
  await run(many, 64);
  assert.equal(await many.locator('li').count(), 64);

  // 4. 31台のうち6台だけ先に表示され、残りは一番下に着いてから3秒（縮めて0.3秒）後に届く。
  const delayed = await browser.newPage({viewport: {width: 1050, height: 780}});
  await delayed.setContent(tall(6));
  await delayed.evaluate(scale => {
    let requested = false;
    window.addEventListener('scroll', () => {
      if (requested || window.scrollY + window.innerHeight < document.documentElement.scrollHeight - 5) return;
      requested = true;
      setTimeout(() => {
        const list = document.querySelector('ul');
        for (let n = 7; n <= 31; n++) { const card = document.createElement('li'); card.id = `li-${n}`; list.append(card); }
      }, 3000 * scale);
    });
  }, SCALE);
  await run(delayed, 31);
  assert.equal(await delayed.locator('li').count(), 31, '設置台数に届くまで、遅い応答を待つ');

  // 5. 続きが来ない（読み込みが詰まった）ページ：速く何度も下へ押し込まない。
  //    以前は70回、毎回一番下へ飛んでいた。今は着いたときに1回、4秒増えないときだけ少し戻って再度下へ（最大5回）。
  const stalled = await browser.newPage({viewport: {width: 1050, height: 780}});
  await stalled.setContent(tall(6));
  await stalled.evaluate(() => {
    window.__calls = {intoView: 0, to: 0, by: 0};
    const intoView = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function(...args) { window.__calls.intoView++; return intoView.apply(this, args); };
    const to = window.scrollTo.bind(window), by = window.scrollBy.bind(window);
    window.scrollTo = (...args) => { window.__calls.to++; return to(...args); };
    window.scrollBy = (...args) => { window.__calls.by++; return by(...args); };
  });
  const startedAt = Date.now();
  await run(stalled, 31);
  const calls = await stalled.evaluate(() => window.__calls);
  assert.equal(await stalled.locator('li').count(), 6);
  assert.ok(calls.intoView <= 6, `scrollIntoView は着いたときの1回と再試行だけ（${calls.intoView}回）`);
  assert.ok(calls.to <= 6, `一番下へ飛ぶのも、着いたときの1回と再試行だけ（${calls.to}回）`);
  assert.ok(calls.by < 40, `少しずつ進む（${calls.by}回）`);
  console.log(`stalled page: intoView=${calls.intoView} by=${calls.by} elapsed=${Date.now() - startedAt}ms`);

  // 6. 台別など一覧がないページは、そのまま返る。
  await page.setContent('<h2>台別7日履歴</h2>');
  await run(page, null);
  console.log('PASS: replacement lists load all 61 cards; a machine list of unknown size arriving 20 at a time 3.5s late (even when only a second arrival starts it) reaches 61;bottom-only lazy load reaches 7 of 7 and 64 of 64 in batches; delayed 6 -> 31 waits for the installation count; a stalled list is not hammered (few scrolls, at most 5 retries); rack page returns without scrolling');
} finally { await browser.close(); }
