// Flutterの実際の入力欄へ一度に設定し、反映と保存可能状態を確認する。
export async function enterEventName(page, name, {timeout = 30000} = {}) {
  const box = page.getByRole('textbox', {name: /イベント名（自由記入）/});
  const save = page.getByRole('button', {name: '保存', exact: true});
  const deadline = Date.now() + timeout;
  let value, enabled, attempts = 0, nextFillAt = 0;
  do {
    // Flutterのフォーカス初期化が直後に値を戻す場合に備え、反映を待ってから最大3回まで設定する。
    // 最後の失敗で欄を消したり、確認できないまま保存へ進んだりしない。
    if (attempts < 3 && Date.now() >= nextFillAt) {
      await box.fill(name, {timeout: Math.max(1, deadline - Date.now())});
      attempts++;
      nextFillAt = Date.now() + 1000;
    }
    // 取得エラーを期待値に置き換えない。読めなければその場で試験を止める。
    value = await box.inputValue({timeout});
    enabled = await save.isEnabled();
    if (value === name && enabled) {
      await save.click({timeout});
      return;
    }
    await page.waitForTimeout(50);
  } while (Date.now() < deadline);
  const focus = await page.evaluate(() => document.activeElement?.tagName ?? null);
  throw new Error(`イベント名の保存準備が整いません: 期待値=${JSON.stringify(name)}, 入力値=${JSON.stringify(value)}, 保存可能=${enabled}, フォーカス=${focus}, 入力試行=${attempts}`);
}
