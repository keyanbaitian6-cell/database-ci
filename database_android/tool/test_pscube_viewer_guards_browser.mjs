// 閲覧ページのP’s CUBE版（web/pscube/viewer_bootstrap.mjs）にも、メルヘン版（web/index.html）と同じ保険があること
// （2026-11-22、Geminiの点検 H-8）。①前回のGoogleドライブの更新が途中で終わっていたら、6時間は起動時の自動更新を
// 止める期限を返す（autoUpdateHold。Dart側 viewer_main.dart の _start が共通で使う）②保存に失敗したら種類を診断に
// 控え、元の失敗をそのまま返す（成功は数えない）。実ブラウザで bootstrap を読み込む（Flutterは読み込まない）。
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const web = fileURLToPath(new URL('../web/', import.meta.url));
const server = http.createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname === '/setup') { res.setHeader('content-type', 'text/html'); res.end('<!doctype html><body>guards</body>'); return; }
  if (pathname.endsWith('/flutter_bootstrap.js')) { res.setHeader('content-type', 'text/javascript'); res.end(''); return; }
  const local = path.resolve(web, '.' + pathname);
  if (!local.startsWith(web)) { res.writeHead(403).end(); return; }
  try { res.setHeader('content-type', 'text/javascript'); res.end(await fs.readFile(local)); }
  catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = 'http://127.0.0.1:' + server.address().port;
const HOUR = 3600 * 1000;
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(origin + '/setup');
  const start = running => page.evaluate(async running => {
    localStorage.clear();
    if (running) localStorage.setItem('database-viewer-diag', JSON.stringify({version: 1, running: {phase: 'drive', at: running}, phases: {}}));
    await import('/pscube/viewer_bootstrap.mjs?' + Math.random());
    return typeof window.databaseViewer.autoUpdateHold;
  }, running);
  const diag = () => page.evaluate(() => JSON.parse(localStorage.getItem('database-viewer-diag') || 'null'));

  // 1時間前に更新の途中で終わった：診断が始まりを数えた時点で止める期限（始めた時刻＋6時間）が返る。
  const at = new Date(Date.now() - HOUR).toISOString();
  assert.equal(await start(at), 'function', 'P’s CUBE版の橋渡しに autoUpdateHold がある');
  await page.evaluate(() => window.databaseViewer.phase('drive', false));   // 次の更新を始めた＝前の途中を数える
  const held = await page.evaluate(() => window.databaseViewer.autoUpdateHold());
  assert.equal(typeof held, 'string', '途中で終わっていたら期限を返す');
  assert.equal(Date.parse(held), Date.parse((await diag()).drive_halt.at) + 6 * HOUR);
  // 更新が最後まで終われば、止める印は消える。
  await page.evaluate(() => window.databaseViewer.phase('drive', true));
  assert.equal(await page.evaluate(() => window.databaseViewer.autoUpdateHold()), null, '終われば止めない');
  // 7時間前の印は効かない。印なしも止めない。
  await start(new Date(Date.now() - 7 * HOUR).toISOString());
  await page.evaluate(() => window.databaseViewer.phase('drive', false));
  assert.equal(await page.evaluate(() => window.databaseViewer.autoUpdateHold()), null, '6時間を過ぎたら止めない');
  await start(null);
  assert.equal(await page.evaluate(() => window.databaseViewer.autoUpdateHold()), null, '印なしは止めない');

  // 保存の失敗：種類を控え、元の失敗をそのまま返す。前の診断の項目は残す。
  const failed = await page.evaluate(async () => {
    try { await window.databaseViewer.save('{壊れた本文'); return null; }
    catch (error) { return error.name; }
  });
  assert.equal(failed, 'SyntaxError', '元の失敗をそのまま返す');
  const fail = (await diag()).save_fail;
  assert.equal(fail.count, 1);
  assert.equal(fail.stage, 'write');
  assert.equal(fail.name, 'SyntaxError');
  assert.equal(fail.chars, null, 'P’s CUBE版は文字数を控えない（メルヘンの index.html と同じ）');
  assert.equal(fail.hidden, false);
  await page.evaluate(async () => { try { await window.databaseViewer.save('[]'); } catch { /* 2回目の失敗 */ } });
  assert.equal((await diag()).save_fail.count, 2, '失敗のたびに数える');
  // 診断の画面の行に出る（メルヘン版と同じ文言の行）。
  const lines = JSON.parse(await page.evaluate(() => window.databaseViewer.storageReport()));
  assert.ok(lines.some(line => String(line).includes('端末への保存の失敗')), lines.join('\n'));
  assert.deepEqual(errors, []);
  console.log('PASS: P’s CUBE viewer has the drive hold and records save failures like the Meruhen viewer');
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
