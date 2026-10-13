// 共通の検証・統合規則をApps Scriptへ同梱する。生成物はそのまま1ファイルで貼れる。
import {readFileSync, writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

export function buildCloudScript() {
  const parser = readFileSync(new URL('../web/pscube/data.mjs', import.meta.url), 'utf8');
  const slice = (start, end) => {
    const a = parser.indexOf(start), b = parser.indexOf(end, a);
    if (a < 0 || b < 0) throw new Error('P’s CUBEパーサーの構成が変わりました。生成規則を更新してください。');
    return parser.slice(a, b);
  };
  const core = [slice('export const FORMAT', 'const graphSafe'),
    slice('export function siteUrl', 'const text ='),
    slice('export const dateEventKey', '/** 沖ドキ')].join('\n')
    .replace(/^export /gm, '').replace('raw.records.length > 100000', 'raw.records.length > 200000');
  const runtime = readFileSync(new URL('./pscube_cloud_sync_runtime.js', import.meta.url), 'utf8');
  return '// 生成元: tool/build_pscube_cloud_sync.mjs。共通パーサーの検証・統合規則を使用。\n' +
    '// 初回: 別のApps Scriptプロジェクトに全文を貼り、setupPscubeCloudSync を実行。\n' +
    '// 既存の閲覧用・共有用スクリプトは変更不要。ウェブ公開も不要。\n\n' + runtime + '\n' + core.trimEnd() + '\n';
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  writeFileSync(new URL('./pscube_cloud_sync.gs', import.meta.url), buildCloudScript());
}
