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
  await page.setContent('<h2>台別7日履歴</h2>');
  await page.evaluate(scroll);
  console.log('PASS: replacement lists load all 61 cards; rack page returns without scrolling');
} finally { await browser.close(); }
