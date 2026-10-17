import assert from 'node:assert/strict';
import test from 'node:test';
import {enterEventName} from './browser_event_input.mjs';

const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox']});

async function form(t, {dropInputs = 0, disabled = false, delay = 0, editable = false} = {}) {
  const context = await browser.newContext();
  t.after(() => context.close());
  const page = await context.newPage();
  await page.setContent(`${editable
    ? '<div contenteditable="true" role="textbox" aria-label="イベント名（自由記入）"></div>'
    : '<label>イベント名（自由記入）<input value="以前の名前"></label>'}
    <button type="button" ${disabled || delay ? 'disabled' : ''}>保存</button>`);
  await page.evaluate(({dropInputs, disabled, delay}) => {
    window.saved = [];
    window.inputs = [];
    const field = document.querySelector('input, [contenteditable]');
    const save = document.querySelector('button');
    field.addEventListener('input', () => {
      if (window.inputs.length < dropInputs) field.value = field.value.slice(1);
      window.inputs.push(field.value ?? field.textContent);
      if (delay) setTimeout(() => {save.disabled = disabled;}, delay);
    });
    save.addEventListener('click', () => window.saved.push(field.value ?? field.textContent));
  }, {dropInputs, disabled, delay});
  return page;
}

try {
  await test('日本語を一度に置き換え、保存が有効になるまで待つ', async t => {
    const page = await form(t, {delay: 150});
    await enterEventName(page, '半列');
    assert.deepEqual(await page.evaluate(() => window.inputs), ['半列']);
    assert.deepEqual(await page.evaluate(() => window.saved), ['半列']);
  });
  await test('最初の入力が欠けても、値を確認してから再設定する', async t => {
    const page = await form(t, {dropInputs: 1});
    await enterEventName(page, '半列', {timeout: 5000});
    assert.deepEqual(await page.evaluate(() => window.inputs), ['列', '半列']);
    assert.deepEqual(await page.evaluate(() => window.saved), ['半列']);
  });
  for (const disabled of [false, true]) {
    await test(`入力が3回欠けても空にせず停止する（保存ボタン${disabled ? '無効' : '有効'}）`, async t => {
      const page = await form(t, {dropInputs: 3, disabled});
      await assert.rejects(enterEventName(page, '半列', {timeout: 4000}),
        new RegExp(`入力値="列", 保存可能=${!disabled}`));
      assert.deepEqual(await page.evaluate(() => window.inputs), ['列', '列', '列']);
      assert.equal(await page.getByRole('textbox').inputValue(), '列');
      assert.deepEqual(await page.evaluate(() => window.saved), []);
    });
  }
  await test('入力値の取得に失敗した場合は成功扱いにせず保存しない', async t => {
    const page = await form(t, {editable: true});
    await assert.rejects(enterEventName(page, '半列', {timeout: 3000}), /input|textarea|select/);
    assert.deepEqual(await page.evaluate(() => window.saved), []);
  });
  await test('値が正しくても保存が無効なら、状態を記録して停止する', async t => {
    const page = await form(t, {disabled: true});
    await assert.rejects(enterEventName(page, '半列', {timeout: 3000}), /入力値="半列", 保存可能=false/);
    assert.deepEqual(await page.evaluate(() => window.saved), []);
  });
} finally {
  await browser.close();
}
