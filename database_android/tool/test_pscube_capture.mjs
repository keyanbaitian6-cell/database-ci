// Live-page extractor smoke test against the three browser archive examples.
import assert from 'node:assert/strict';
import {existsSync, readFileSync, writeFileSync} from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const script = readFileSync(new URL('../assets/pscube_capture.js', import.meta.url), 'utf8');
const examples = [
  ['pscube-machine-index-archive', 'nc-v03-001.php?cd_ps=2', 61, 0],
  ['pscube-tokyo-full-archive', 'nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=L%25E6%259D%25B1%25E4%25BA%25AC%25E5%2596%25B0%25E7%25A8%25AE', 1, 24],
  ['pscube-1526-archive', 'nc-v06-001.php?cd_dai=1526#20261001', 1, 7],
];
const archiveRoot = process.env.PSCUBE_ARCHIVE_DIR || '/workspace';
if (examples.some(([folder]) => !existsSync(`${archiveRoot}/${folder}/main.html`))) {
  console.log('SKIP: set PSCUBE_ARCHIVE_DIR to the private archive directory');
  process.exit(0);
}
const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH || undefined, args:['--no-sandbox']});
try {
  for (const [folder, suffix, machines, records] of examples) {
    const page = await browser.newPage();
    const url = `https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/${suffix}`;
    // Remove active scripts: the capture reads DOM, while real site JS may call APIs.
    const html = readFileSync(`${archiveRoot}/${folder}/main.html`, 'utf8')
      .replace(/<script\b[^>]*>[\s\S]*?<\/script\s*>/gi, '');
    await page.route('**/*', route => route.request().isNavigationRequest()
      ? route.fulfill({status:200, contentType:'text/html', body:html}) : route.abort());
    await page.goto(url, {waitUntil:'domcontentloaded'});
    const result = JSON.parse(await page.evaluate(script));
    assert.equal(result.error, undefined, result.error);
    assert.equal(result.source_url, url);
    assert.equal(result.machines.length, machines);
    assert.equal(result.records.length, records);
    if (process.env.PSCUBE_CAPTURE_OUTPUT_DIR) {
      writeFileSync(`${process.env.PSCUBE_CAPTURE_OUTPUT_DIR}/${folder}.json`, JSON.stringify(result));
    }
    await page.close();
  }
  console.log('PASS: live capture reads machine index, full rack list and seven-day rack archive');
} finally { await browser.close(); }
