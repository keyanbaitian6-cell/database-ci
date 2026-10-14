import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import test, {after} from 'node:test';
import {fileURLToPath} from 'node:url';

const repository = fileURLToPath(new URL('../../', import.meta.url));
const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'share-android-stage-'));
const staged = spawnSync(process.env.PYTHON || 'python', ['database_android/tool/stage_share_viewer.py', temp],
  {cwd: repository, encoding: 'utf8'});
assert.equal(staged.status, 0, staged.stderr);
after(() => fs.rm(temp, {recursive: true, force: true}));
const read = name => fs.readFile(path.join(temp, name), 'utf8');
const normal = await read('index.html'), android = await read('android.html');
const originalManifest = JSON.parse(await fs.readFile(path.join(repository, 'share_viewer/manifest.json'), 'utf8'));
const manifest = JSON.parse(await read('manifest.json'));
const androidManifest = JSON.parse(await read('manifest-android.json'));
const base = new URL('https://example.com/database-share/');
const stripVersions = text => text.replace(/\?v=[a-f0-9]{12}/g, '');

test('Android入口は共通HTMLのmanifest参照だけを変更し、通常入口の起動設定を維持する', async () => {
  assert.equal(android, normal.replace('./manifest.json?', './manifest-android.json?'));
  assert.equal(stripVersions(normal), await fs.readFile(path.join(repository, 'share_viewer/index.html'), 'utf8'));
  assert.deepEqual(JSON.parse(stripVersions(JSON.stringify(manifest))), originalManifest);
  assert.equal(manifest.display, 'browser');
  assert.equal(androidManifest.display, 'standalone');
  assert.equal(androidManifest.start_url, './android.html');
  assert.equal(androidManifest.id, './android.html');
  assert.notEqual(new URL(manifest.id, base).href, new URL(androidManifest.id, base).href);
  assert.equal(androidManifest.scope, './');
  assert.equal(new URL(androidManifest.start_url, base).pathname, '/database-share/android.html');
  assert.ok(new URL(androidManifest.start_url, base).href.startsWith(new URL(androidManifest.scope, base).href));
  assert.deepEqual(androidManifest.icons, manifest.icons);
});

test('両入口・両manifest・共通モジュール・共用画像の参照には同じ更新版を付け、実ファイルを参照する', async () => {
  const references = [normal, android].flatMap(html => [...html.matchAll(/(?:src|href)="(\.\/[^"\s]+)"/g)].map(m => m[1]));
  references.push(...manifest.icons.map(i => i.src), ...androidManifest.icons.map(i => i.src));
  for (const name of ['app.mjs', 'data.mjs']) {
    references.push(...[...(await read(name)).matchAll(/from '(\.\/[^']+)'/g)].map(m => m[1]));
  }
  const versions = [];
  for (const ref of references) {
    const url = new URL(ref, base);
    assert.equal(url.origin, base.origin);
    assert.ok(url.pathname.startsWith(base.pathname));
    assert.ok((await fs.stat(path.join(temp, url.pathname.slice(base.pathname.length)))).isFile());
    assert.match(url.searchParams.get('v'), /^[a-f0-9]{12}$/);
    versions.push(url.searchParams.get('v'));
  }
  assert.equal(new Set(versions).size, 1);
});

test('公開対象は許可した静的ファイルだけで、元写真・記録・接続情報を含めない', async () => {
  assert.deepEqual((await fs.readdir(temp)).sort(), ['.nojekyll', 'README.md', 'android.html', 'app.mjs',
    'apple-touch-icon.png', 'data.mjs', 'favicon.png', 'icon-192.png', 'icon-512.png', 'index.html',
    'manifest-android.json', 'manifest.json', 'net.mjs', 'offline.mjs', 'sw.js', 'viewer_parts.mjs'].sort());
  for (const name of ['icon-192.png', 'icon-512.png', 'favicon.png', 'apple-touch-icon.png']) {
    assert.deepEqual(await fs.readFile(path.join(temp, name)), await fs.readFile(path.join(repository, 'share_viewer', name)));
  }
  for (const text of [normal, android, JSON.stringify(manifest), JSON.stringify(androidManifest)]) {
    assert.doesNotMatch(text, /AKfyc[A-Za-z0-9_-]{20,}|\/macros\/s\/[A-Za-z0-9_-]{20,}|source\.png|database_seed/);
  }
});
