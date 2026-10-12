// PC版のパチンコの記録のページ（database/pachinko_report.py、2026-10-12）。作った記録でページを作り、
// 実際のブラウザで開いて、数字・末尾の絞り込み・台のくわしい表示・スマホ幅ではみ出さないことを確かめる。
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {rmSync} from 'node:fs';
import {dirname} from 'node:path';
import {pathToFileURL} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');

const build = `
import json, tempfile, pachinko, pachinko_report
from pathlib import Path
folder = Path(tempfile.mkdtemp())
slot = folder / 'database.sqlite3'
rows = [[str(r), str(r % 7 + 1), '1/250.0', str(1000 + r * 10 + (900 if r % 10 == 0 else 0))] for r in range(75, 107)]
pachinko.save_table(dict(store='saiwaichou', machine='テスト機', target_date='2026-10-10', kind_code='4',
    matrix=[pachinko.PACHI_HEADERS] + rows, links=['https://example.invalid/'] * len(rows)), slot)
pachinko.save_table(dict(store='saiwaichou', machine='テスト機', target_date='2026-10-20', kind_code='4',
    matrix=[pachinko.PACHI_HEADERS] + rows[:3], links=['https://example.invalid/'] * 3), slot)
text = '\\n'.join(['当り履歴', '2026/10/10 (2日前)'] + [str(n) for n in range(10, 0, -1)] + ['1', '186', '2', '26', 'グラフ表示'])
text = '\\n'.join(['台データ情報', '初当り', '888888', '2', '最大持玉', '888888', '5000']) + '\\n' + text
pachinko.save_graph(dict(store='saiwaichou', rack=80, target_date='2026-10-10', page_text=text, max_hold=5000),
    slot, dict(baseline_y=200.5, curve=[[0.5, 200.5], [100.5, 250.5], [200.5, 150.5], [300.5, 180.5]]))
print(pachinko_report.build_report(slot, folder / 'reports'))
`;
const path = execFileSync(process.env.PYTHON || 'python', ['-c', build],
  {cwd: new URL('../../database/', import.meta.url), encoding: 'utf8'}).trim();

const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || undefined});
try {
  for (const [width, scheme] of [[1200, 'light'], [390, 'dark'], [320, 'light']]) {
    const page = await browser.newPage({viewport: {width, height: 900}, colorScheme: scheme});
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto(pathToFileURL(path).href);
    assert.equal(await page.locator('#day').inputValue(), '2026-10-20', '最新の日から');
    await page.selectOption('#day', '2026-10-10');
    assert.match(await page.locator('#kpis').innerText(), /32台/);
    assert.match(await page.locator('#kpis').innerText(), /末尾0の平均総回転数/);
    await page.click('.digit[data-d="0"]');
    assert.match(await page.locator('#listTitle').innerText(), /3台・末尾0だけ/);
    await page.click('tr.rack[data-r="80"]');
    await page.locator('.detail svg.graph').waitFor();
    assert.equal(await page.locator('.hist > div').count(), 2, '当り履歴2回');
    assert.match(await page.locator('.detail').innerText(), /5,000/);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 0, `${width}px で横にはみ出さない（${overflow}px）`);
    await page.click('#prev', {force: true}).catch(() => {});
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log('OK: パチンコの記録のページ（数字・末尾0の絞り込み・台のくわしい表示・1200/390/320px）');
} finally {
  await browser.close();
  rmSync(dirname(dirname(path)), {recursive: true, force: true});
}
