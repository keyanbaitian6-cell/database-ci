import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const source = readFileSync(new URL('../../database/pscube_import.py', import.meta.url), 'utf8');
const scroll = source.match(/SCROLL_SCRIPT = r'''([\s\S]*?)'''/)[1];
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined});
try {
  const page = await browser.newPage();
  for (const index of [true, false]) {
    await page.setContent(`<ul ${index ? 'id="ulKI"' : ''}><li id="li-1">1</li></ul><footer>Footer</footer>`);
    await page.evaluate(index => {
      const delay = window.setTimeout.bind(window);
      window.setTimeout = (fn, ms) => delay(fn, ms === 350 ? 1 : ms);
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
    await page.evaluate(scroll);
    assert.equal(await page.locator('li').count(), 61);
  }
  // 実サイト（2026-10-02 PC版で表示6台・設置7台）：最後の台が見えても続きは来ず、ページの一番下まで
  // スクロールしたときだけ次の台が増える。最後の台へのスクロールだけでは6台のまま止まっていた。
  const bottomOnly = `<div style="height:300px">header</div><ul>${[1, 2, 3, 4, 5, 6].map(n => `<li id="li-${n}" style="height:150px">${n}</li>`).join('')}</ul><footer style="height:1500px">Footer</footer>`;
  const loadsAtBottom = () => {
    const delay = window.setTimeout.bind(window);
    window.setTimeout = (fn, ms) => delay(fn, ms === 350 ? 20 : ms);
    window.addEventListener('scroll', () => {
      const list = document.querySelector('li[id^="li-"]').parentElement;
      if (list.children.length < 7 && window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 5) {
        const card = document.createElement('li'); card.id = 'li-7'; list.append(card);
      }
    });
  };
  // 前の試験の scrollIntoView の差し替えが残らないよう、新しいページで試す。
  const plain = await browser.newPage({viewport: {width: 1050, height: 780}});
  await plain.setContent(bottomOnly);
  await plain.evaluate(loadsAtBottom);
  await plain.evaluate(scroll);
  assert.equal(await plain.locator('li').count(), 7, 'the show-all script must reach the bottom of the page');
  const oldScroll = scroll.replace(/^\s*window\.scrollTo\(0, document\.documentElement\.scrollHeight\);\r?\n/m, '');
  assert.notEqual(oldScroll, scroll);
  await plain.setContent(bottomOnly);
  await plain.evaluate(loadsAtBottom);
  await plain.evaluate(oldScroll);
  assert.equal(await plain.locator('li').count(), 6, 'fixture reproduces the old stall');
  // 31台のうち6台だけ先に表示され、残りの応答に3秒かかるページ。
  // 6回(2.1秒)の台数安定だけで終了すると、全台表示前に保存して3回失敗する。
  const delayed = await browser.newPage();
  await delayed.setContent(`<ul>${Array.from({length: 6}, (_, n) => `<li id="li-${n + 1}">${n + 1}</li>`).join('')}</ul>`);
  await delayed.evaluate(() => {
    let requested = false;
    window.scrollTo = () => {
      if (requested) return;
      requested = true;
      setTimeout(() => {
        const list = document.querySelector('ul');
        for (let n = 7; n <= 31; n++) {
          const card = document.createElement('li'); card.id = `li-${n}`; list.append(card);
        }
      }, 3000);
    };
  });
  await delayed.evaluate(script => { const expectedCount = 31; return eval(script); }, scroll);
  assert.equal(await delayed.locator('li').count(), 31, 'known installation count must outlast a 3-second lazy response');
  await page.setContent('<h2>台別7日履歴</h2>');
  await page.evaluate(scroll);
  console.log('PASS: replacement lists load all 61 cards; bottom-only lazy load reaches 7 of 7; delayed 6 -> 31 waits for the installation count; rack page returns without scrolling');
} finally { await browser.close(); }
