// 配布する.gsは従来どおり全文を1枚貼れる。生成部分はここで同期する。
import {readFileSync, writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {buildCloudScript} from './build_pscube_cloud_sync.mjs';
const read = name => readFileSync(new URL(name, import.meta.url), 'utf8').replaceAll('\r\n', '\n');
export const partsCore = () => read('./viewer_parts_core.js');
export const partsDrive = () => partsCore() + '\n' + read('./viewer_parts_drive.js');
export const partsPublisher = () => partsDrive() + '\n' + read('./viewer_parts_publish.js') + '\n' +
  read('./viewer_history_cloud.js') + '\n' + read('./viewer_history_adapters.js');
export const partsClient = () => '// 生成元: tool/build_viewer_parts.mjs\n' + partsCore() + '\n' + read('./viewer_parts_client.js') +
  '\nexport {fetchViewerParts, fetchViewerDocument, rememberViewerHistory, readViewerHistory};\n';
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
}
if (process.argv[1] === fileURLToPath(import.meta.url)) buildPartsFiles();
