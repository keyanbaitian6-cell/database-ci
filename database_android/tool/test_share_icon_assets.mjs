import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

const source = fileURLToPath(new URL('../../share_viewer/', import.meta.url));
const root = process.env.SHARE_WEB_ROOT || source;
const html = await fs.readFile(path.join(root, 'index.html'), 'utf8');
const manifest = JSON.parse(await fs.readFile(path.join(root, 'manifest.json'), 'utf8'));
const refs = [
  ...['apple-touch-icon', 'icon', 'manifest'].map(rel => {
    const tag = html.match(new RegExp(`<link rel="${rel}"[^>]*>`))?.[0];
    assert.ok(tag, `${rel} link exists`);
    return tag.match(/href="([^"]+)"/)[1];
  }),
  ...manifest.icons.map(icon => icon.src),
];

test('共有アイコンの参照・公開時の版・アプリの起動先', () => {
  assert.equal(manifest.start_url, './index.html');
  assert.equal(manifest.scope, './');
  assert.equal(manifest.display, 'browser');
  assert.deepEqual(manifest.icons.map(icon => icon.sizes), ['192x192', '512x512']);
  if (process.env.SHARE_WEB_ROOT) {
    const versions = refs.map(ref => new URL(ref, 'https://example.com/share/').searchParams.get('v'));
    assert.ok(versions.every(version => /^[0-9a-f]{12}$/.test(version)));
    assert.equal(new Set(versions).size, 1);
    assert.ok(html.includes(`./app.mjs?v=${versions[0]}`));
  }
});

test('共有アイコン4画像のPNG寸法と公開時のバイナリ保持', async () => {
  for (const [name, size] of Object.entries({
    'favicon.png': 32, 'apple-touch-icon.png': 180, 'icon-192.png': 192, 'icon-512.png': 512,
  })) {
    const data = await fs.readFile(path.join(root, name));
    assert.equal(data.subarray(0, 8).toString('hex'), '89504e470d0a1a0a', name);
    assert.equal(data.readUInt32BE(16), size, name);
    assert.equal(data.readUInt32BE(20), size, name);
    assert.deepEqual(data, await fs.readFile(path.join(source, name)), name);
    assert.ok(refs.some(ref => new URL(ref, 'https://example.com/').pathname === `/${name}`), name);
  }
});
