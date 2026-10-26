import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {validateSyncStatus,mergeSyncStatus,updateStatusLines,APPLICATION_RELEASE} from '../web/capture_health.mjs';
const root=new URL('../../',import.meta.url);
test('4画面とGoogle生成物の照合用の版が一致する',()=>{
  assert.match(APPLICATION_RELEASE,/^[a-f0-9]{12}$/);
  for(const file of ['database/release_info.py','database_android/lib/release_info.dart','share_viewer/capture_health.mjs','database_android/tool/viewer_drive_script.gs','database_android/tool/viewer_drive_script_readonly.gs','database_android/tool/meruhen_cloud_sync.gs','database_android/tool/pscube_cloud_sync.gs']) {
    assert.ok(fs.readFileSync(new URL(file,root),'utf8').includes(APPLICATION_RELEASE),file);
  }
});
test('Google側の版は確認した情報だけを引き継ぎ、旧版では未確認にする',()=>{
  const status={version:1,writes:[],processed_at:'2026-10-26T00:00:00Z',processor_release:APPLICATION_RELEASE};
  assert.equal(validateSyncStatus(status).processor_release,APPLICATION_RELEASE);
  assert.equal(mergeSyncStatus(status).processor_release,APPLICATION_RELEASE);
  assert.ok(updateStatusLines(status).some(s=>s===`Google処理の版：${APPLICATION_RELEASE}`));
  assert.ok(updateStatusLines(null).includes('Google処理の版：未確認'));
});
