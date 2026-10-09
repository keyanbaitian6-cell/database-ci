// リリース版APKの最適化（R8）の決まり。2026-10-09、ML Kit の部品の作り方（引数なしのコンストラクタ）を
// R8 が消し、配布版で文字の読み取りがすべて失敗した（VisionCommonRegistrar を作れず NullPointerException）。
// その決まりが消えていないこと、リリースのビルドがその決まりのファイルを使っていることを確かめる。
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';

const rules = await fs.readFile(new URL('../android/app/proguard-rules.pro', import.meta.url), 'utf8');
const gradle = await fs.readFile(new URL('../android/app/build.gradle.kts', import.meta.url), 'utf8');

test('ML Kit を最適化で削らない（部品の作り方を残す）', () => {
  const lines = rules.split(/\r?\n/).map(l => l.trim()).filter(l => l && !l.startsWith('#'));
  assert.ok(lines.includes('-keep class com.google.mlkit.** { *; }'));
  assert.ok(lines.some(l => l.startsWith('-keepclassmembers class * implements com.google.firebase.components.ComponentRegistrar')));
  assert.ok(lines.some(l => l.startsWith('-keep class com.google.android.gms.internal.mlkit_vision_common.')));
});

test('リリースのビルドがこの決まりのファイルを使う', () => {
  assert.match(gradle, /proguardFiles\([\s\S]*"proguard-rules\.pro"/);
});
