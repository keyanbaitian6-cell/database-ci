// ジャグラーオンラインの「取込」ボタン（JugglerCaptureService.kt、JUGGLER_ONLINE.md）。
// 2026-10-10、databaseのパッケージ名から届いた画面の知らせで一律にボタンを消すようにしたところ、
// ボタン自身（重ねた画面）の知らせも同じパッケージ名で届くため、出した直後に消えて出なくなった。
// 自分のパッケージでは MainActivity のときだけ消すこと、通知の引き出しでは消さないことを確かめる。
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';

const source = await fs.readFile(
  new URL('../android/app/src/main/kotlin/com/keyan/database_android/JugglerCaptureService.kt', import.meta.url),
  'utf8',
);
// 改行は LF でも CRLF でも読めるように（Git の設定で変わる）。
const body = /override fun onAccessibilityEvent[\s\S]*?\r?\n {4}\}\r?\n/.exec(source)?.[0] ?? '';
const branches = body.split(/\r?\n/).map(l => l.trim()).filter(l => /->/.test(l) && !l.startsWith('//'));

test('自分のパッケージ名だけでは消さない（MainActivity のときだけ）', () => {
  const own = branches.find(l => /^packageName\b/.test(l) || /,\s*packageName\s*->/.test(l));
  assert.ok(own, '自分のパッケージの分かれ道がある');
  assert.match(own, /\bcls\s*==\s*MainActivity::class\.java\.name[\s\S]*hideButton\(\)/);
  assert.match(body, /val cls = event\.className/);
  assert.ok(!/^packageName\s*->\s*hideButton\(\)/.test(own));
});

test('キーボードが出ても消さない（when より前に抜ける）', () => {
  const ime = body.indexOf('android.inputmethodservice.');
  assert.ok(ime >= 0 && ime < body.indexOf('when (pkg)'));
});

test('ジャグラーオンラインで出し、通知の引き出しでは消さない', () => {
  assert.ok(branches.some(l => /^TARGET\s*->\s*showButton\(\)/.test(l)));
  assert.ok(branches.some(l => /"com\.android\.systemui"\s*->\s*Unit/.test(l)));
  // else（ほかのアプリ）より前に、自分のパッケージの分かれ道があること。
  const ownIndex = branches.findIndex(l => /packageName\s*->/.test(l));
  const elseIndex = branches.findIndex(l => /^else\s*->/.test(l));
  assert.ok(ownIndex >= 0 && elseIndex > ownIndex);
});
