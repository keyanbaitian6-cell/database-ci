// 配布する.gsは従来どおり全文を1枚貼れる。生成部分はここで同期する。
import {readFileSync, writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {buildCloudScript, netModule} from './build_pscube_cloud_sync.mjs';
const read = name => readFileSync(new URL(name, import.meta.url), 'utf8').replaceAll('\r\n', '\n');
export const partsCore = () => read('./viewer_parts_core.js');
export const partsDrive = () => partsCore() + '\n' + read('./viewer_parts_drive.js');
export const partsPublisher = () => partsDrive() + '\n' + read('./viewer_parts_publish.js') + '\n' +
  read('../web/capture_health.mjs').replace(/^export /gm,'') + '\n' +
  read('./viewer_history_cloud.js') + '\n' + read('./viewer_history_adapters.js') + '\n' +
  read('./viewer_curves_split.js') + '\n' + netModule();
export const partsClient = () => '// 生成元: tool/build_viewer_parts.mjs\n' + partsCore() + '\n' + read('./viewer_parts_client.js') + '\n' + read('./viewer_day_store.js') +
  '\nexport {fetchViewerParts, fetchViewerDocument, fetchViewerCurves, rememberViewerHistory, viewerHistoryCovers, viewerHistoryExists, compareViewerHistory, readViewerDays, readViewerHistory, createViewerDayStore};\n';
// 共有カレンダーの capture_health.mjs は、閲覧ページの同名ファイルから netHealth だけを外した写し（2026-11-15 に共有
// ページで「○台中○台差枚取得済み」の表示を消した）。2026-11-22：手で外した写しのままだと、このスクリプトを流すたびに
// 戻す手間が要り、照合の試験の外にあったので、ここで作る（Claudeの点検 #8・Gemini H-12①）。
const SHARE_NET_HEALTH_NOTE = '// netHealth（P’s CUBEの「○台中○台差枚取得済み」）は、共有ページでその表示を 2026-11-15 に消したので外した。\n' +
  '// database_android/web/capture_health.mjs の同名の関数は、取り込みカード・Googleの同期スクリプトに組み込まれる生成物の元なので残している。\n';
export function shareCaptureHealth() {
  const text = read('../web/capture_health.mjs'), start = text.indexOf('export function netHealth(');
  const end = text.indexOf('\n}\n', start);
  if (start < 0 || end < 0) throw new Error('capture_health.mjs に netHealth が見つかりません。共有ページの写しの作り方を見直してください。');
  return text.slice(0, start) + SHARE_NET_HEALTH_NOTE + text.slice(end + 3);
}
const marker = '\n// BEGIN GENERATED VIEWER PARTS\n';
export function buildPartsFiles() {
  for (const name of ['viewer_drive_script.gs', 'viewer_drive_script_readonly.gs', 'meruhen_cloud_sync.gs']) {
    const body = read('./' + name).split(marker)[0].trimEnd();
    writeFileSync(new URL('./' + name, import.meta.url), body + marker + (name.startsWith('meruhen') ? partsPublisher() : partsDrive()));
  }
  writeFileSync(new URL('./pscube_cloud_sync.gs', import.meta.url), buildCloudScript());
  for (const name of ['../web/viewer_parts.mjs', '../../share_viewer/viewer_parts.mjs']) {
    writeFileSync(new URL(name, import.meta.url), partsClient());
  }
  writeFileSync(new URL('../../share_viewer/capture_health.mjs',import.meta.url),shareCaptureHealth());
}
if (process.argv[1] === fileURLToPath(import.meta.url)) buildPartsFiles();
