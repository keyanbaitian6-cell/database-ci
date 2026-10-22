// ボタンを連打してもダブルタップで拡大しない（2026-10-22 利用者「次の台連打していくとズームされるからやめたい」「二本指で拡大機能だけでOK」）。
// iPhoneの設定では止められないため、ページの html・body に touch-action: manipulation を付ける。2本指の拡大を止める書き方
// （user-scalable=no・maximum-scale）は使わない。共有ページの実際の表示は test_share_viewer_browser.mjs でも確かめる。
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';

const pages = {
  '共有ページ': '../../share_viewer/index.html',
  '閲覧ページ': '../web/index.html',
  '閲覧ページ（P’s CUBE）': '../web/pscube/index.html',
};

for (const [name, file] of Object.entries(pages)) {
  test(`${name}：ダブルタップ拡大を止め、2本指の拡大は残す`, async () => {
    const html = await fs.readFile(new URL(file, import.meta.url), 'utf8');
    assert.match(html, /html, body \{ touch-action: manipulation; \}/);
    const viewport = html.match(/<meta name="viewport" content="([^"]+)"/)?.[1];
    assert.ok(viewport, 'viewport がある');
    assert.doesNotMatch(viewport, /user-scalable|maximum-scale/, '2本指の拡大を止めない');
  });
}
