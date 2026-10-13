// P’s CUBE PC不要同期。build_pscube_cloud_sync.mjs で検証済みの共通パーサーと結合する。
// 配布するのは pscube_cloud_sync.gs（別のApps Scriptプロジェクトに全文を貼る）。

// 通常は空欄のまま。共有フォルダが複数ある場合だけ、対象フォルダのIDを入れる。
const PSCUBE_FOLDER_ID = '';
const PSCUBE_CLOUD_BACKUP = 'pscube-backup-cloud.json';
const PSCUBE_CLOUD_VIEWER = 'pscube-viewer-drive.json';
const PSCUBE_CLOUD_BATCH = 10;
const PSCUBE_CLOUD_MAX_BYTES = 48 * 1024 * 1024;
const PSCUBE_CLOUD_HANDLER = 'syncPscubeCloud';

// Google Apps ScriptにはブラウザのURLクラスがないため、共通パーサーが使う部分を実装する。
class PscubeCloudUrl {
  constructor(raw) {
    if (typeof raw !== 'string') throw new Error('P’s CUBEのリンクが不正です。');
    const match = raw.match(/^https:\/\/www\.pscube\.jp(\/dedamajyoho-P-townDMMpachi\/c\d+\/cgi-bin\/nc-v(?:03-001|05-011|06-001)\.php)(?:\?([^#]*))?(#.*)?$/);
    if (!match) throw new Error('P’s CUBEのリンクが不正です。');
    this.origin = 'https://www.pscube.jp';
    this.username = this.password = '';
    this.pathname = match[1]; this.hash = match[3] || ''; this.href = raw;
    const params = new Map();
    for (const pair of (match[2] || '').split('&')) {
      if (!pair) continue;
      const at = pair.indexOf('=');
      const decode = s => decodeURIComponent(s.replace(/\+/g, ' '));
      const key = decode(at < 0 ? pair : pair.slice(0, at));
      if (!params.has(key)) params.set(key, decode(at < 0 ? '' : pair.slice(at + 1)));
    }
    this.searchParams = {get: key => params.has(key) ? params.get(key) : null, has: key => params.has(key)};
  }
}
const URL = PscubeCloudUrl;

/** 初回・間隔変更時にエディタから実行。フォルダ確認→同期→30分おきの自動実行を設定する。 */
function setupPscubeCloudSync() {
  const properties = PropertiesService.getScriptProperties();
  let folder;
  if (PSCUBE_FOLDER_ID) folder = DriveApp.getFolderById(PSCUBE_FOLDER_ID);
  else if (properties.getProperty('pscubeCloudFolder')) folder = DriveApp.getFolderById(properties.getProperty('pscubeCloudFolder'));
  else {
    const folders = new Map();
    const files = DriveApp.getFilesByName(PSCUBE_CLOUD_VIEWER);
    while (files.hasNext()) {
      const file = files.next();
      if (file.isTrashed()) continue;
      const parents = file.getParents();
      while (parents.hasNext()) {
        const parent = parents.next();
        if (!parent.isTrashed()) folders.set(parent.getId(), parent);
      }
    }
    if (folders.size !== 1) throw new Error('閲覧用ファイルの共有フォルダを一意に決められません。PSCUBE_FOLDER_ID に「database共有」のフォルダIDを入れてください。');
    folder = [...folders.values()][0];
  }
  if (folder.isTrashed()) throw new Error('共有フォルダがごみ箱にあります。');
  properties.setProperty('pscubeCloudFolder', folder.getId());
  const result = syncPscubeCloud();
  const triggers = ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === PSCUBE_CLOUD_HANDLER);
  // 新しいトリガーを作ってから古いものを外す。作成失敗時には既存の自動実行を残す。
  ScriptApp.newTrigger(PSCUBE_CLOUD_HANDLER).timeBased().everyMinutes(30).create();
  // 再設定で旧5分トリガーも置き換える。他の関数のトリガーには触らない。
  for (const trigger of triggers) ScriptApp.deleteTrigger(trigger);
  console.log('設定完了：30分おきにP’s CUBEを共有へ反映します。残りの未処理ファイル：' + result.pending);
  return result;
}

/** エディタからの手動実行も可。ウェブ公開・デプロイは不要。 */
function syncPscubeCloud() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return {busy: true, pending: 0};
  try {
    const props = PropertiesService.getScriptProperties();
    const id = props.getProperty('pscubeCloudFolder');
    if (!id) throw new Error('最初に setupPscubeCloudSync を実行してください。');
    const folder = DriveApp.getFolderById(id);
    if (folder.isTrashed()) throw new Error('共有フォルダがごみ箱にあります。');
    const backupFile = pscubeCloudUniqueFile(folder, PSCUBE_CLOUD_BACKUP);
    const viewerFile = pscubeCloudUniqueFile(folder, PSCUBE_CLOUD_VIEWER);
    const inputsById = new Map();
    const sources = new Map([folder, DriveApp.getRootFolder()].map(f => [f.getId(), f]));
    for (const sourceFolder of sources.values()) {
      // Drive側で名前を絞る。マイドライブにある無関係のファイルは列挙・読取しない。
      // Folder.searchFiles はDrive API v2形式の title を使う。
      const files = sourceFolder.searchFiles("trashed = false and title contains 'pscube-backup-'");
      while (files.hasNext()) {
        const file = files.next(), name = file.getName(), fileId = file.getId();
        if (!file.isTrashed() && !inputsById.has(fileId) && /^pscube-backup-(?:auto|(?:android|pc)-\d{8}-\d{6})\.json$/.test(name)) {
          inputsById.set(fileId, {file: file, id: fileId, version: pscubeCloudVersion(file)});
        }
      }
    }
    const inputs = [...inputsById.values()];
    inputs.sort((a, b) => a.file.getLastUpdated().getTime() - b.file.getLastUpdated().getTime() || a.id.localeCompare(b.id));
    const inputVersion = pscubeCloudDigest(inputs.map(i => [i.id, i.version]));
    const backupVersion = backupFile ? pscubeCloudVersion(backupFile) : '';
    const viewerVersion = viewerFile ? pscubeCloudVersion(viewerFile) : '';
    // 変化がなければ、巨大なJSONを毎回読むことも、書き直すこともしない。
    if (backupFile && viewerFile && props.getProperty('pscubeCloudInputs') === inputVersion &&
        props.getProperty('pscubeCloudBackup') === backupVersion && props.getProperty('pscubeCloudViewer') === viewerVersion) {
      console.log('変更なし');
      return {changed: false, pending: 0};
    }
    let data = backupFile ? pscubeCloudRead(backupFile) : {...emptyData(), rack_captures: []};
    const versions = {...(data.cloud_sync && data.cloud_sync.inputs || {})};
    const pending = inputs.filter(i => versions[i.id] !== i.version);
    if (!backupFile && !pending.length) throw new Error('共有フォルダとマイドライブ直下にAndroidまたはPCのP’s CUBEバックアップがありません。先にDriveへ保存してください。');
    const selected = [];
    const startedAt = Date.now();
    let readBytes = 0;
    // 全件検証してから書く。不正・アップロード途中のファイルで正常な記録を置き換えない。
    for (const input of pending.slice(0, PSCUBE_CLOUD_BATCH)) {
      // Googleの実行時間内に書き出しまで終えられるよう、大きい入力は次回へ分ける。
      if (selected.length && (Date.now() - startedAt > 180000 || readBytes + input.file.getSize() > 64 * 1024 * 1024)) break;
      try { data = pscubeCloudMerge(data, pscubeCloudRead(input.file)); }
      catch (error) { throw new Error(input.file.getName() + '：' + error.message); }
      if (input.version !== pscubeCloudVersion(input.file)) throw new Error('読み込み中にバックアップが変わりました。次の自動実行でやり直します。');
      versions[input.id] = input.version;
      readBytes += input.file.getSize();
      selected.push(input);
    }
    // 過去に処理した入力がDriveから移動・削除されても、統合済みの台は消さない。
    const liveIds = new Set(inputs.map(i => i.id));
    for (const key of Object.keys(versions)) if (!liveIds.has(key)) delete versions[key];
    const exportedAt = new Date().toISOString();
    const backup = {...data, kind: 'backup', source: 'cloud', exported_at: exportedAt, cloud_sync: {version: 1, inputs: versions}};
    const viewer = pscubeCloudViewer(backup, exportedAt);
    const backupText = JSON.stringify(backup), viewerText = JSON.stringify(viewer);
    pscubeCloudCheckSize(backupText); pscubeCloudCheckSize(viewerText);
    // バックアップを先に確定。閲覧用の更新が失敗しても次回このバックアップから復旧できる。
    let savedBackup = backupFile;
    if (selected.length || !backupFile) savedBackup = pscubeCloudWrite(folder, backupFile, PSCUBE_CLOUD_BACKUP, backupText);
    // PCが古い閲覧用ファイルを書き直した場合も、統合済みの内容から再生成する。
    const savedViewer = pscubeCloudWrite(folder, viewerFile, PSCUBE_CLOUD_VIEWER, viewerText);
    const remaining = pending.length - selected.length;
    props.setProperties({pscubeCloudBackup: pscubeCloudVersion(savedBackup), pscubeCloudViewer: pscubeCloudVersion(savedViewer)});
    if (!remaining) props.setProperty('pscubeCloudInputs', inputVersion);
    else props.deleteProperty('pscubeCloudInputs');
    console.log('共有へ反映：' + viewer.records.length + '台分の記録、全期間：' + backup.records.length + '件、未処理ファイル：' + remaining);
    return {changed: true, records: backup.records.length, viewerRecords: viewer.records.length, pending: remaining};
  } finally { lock.releaseLock(); }
}

function pscubeCloudUniqueFile(folder, name) {
  const files = folder.getFilesByName(name), found = [];
  while (files.hasNext()) { const file = files.next(); if (!file.isTrashed()) found.push(file); }
  if (found.length > 1) throw new Error(name + ' が共有フォルダに複数あります。重複を解消してから実行してください。');
  return found[0] || null;
}
function pscubeCloudVersion(file) { return file.getLastUpdated().getTime() + '-' + file.getSize(); }
function pscubeCloudDigest(value) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, JSON.stringify(value))
    .map(b => ('0' + ((b + 256) % 256).toString(16)).slice(-2)).join('');
}
function pscubeCloudRead(file) {
  if (file.getSize() > PSCUBE_CLOUD_MAX_BYTES) throw new Error('ファイルが48MiBを超えています。記録は変更していません。');
  const raw = JSON.parse(file.getBlob().getDataAsString('UTF-8').replace(/^\uFEFF/, ''));
  if (raw.kind === 'viewer') throw new Error('軽量な閲覧用ファイルは全期間バックアップとして使えません。');
  const data = validateData(raw);
  const keys = new Set(data.records.map(recordKey));
  const captures = raw.rack_captures == null ? data.records.filter(r => r.graph && r.graph.kind === 'daily').map(recordKey) : raw.rack_captures;
  if (!Array.isArray(captures) || captures.some(k => typeof k !== 'string' || !keys.has(k))) throw new Error('取り込み済みの印が不正です。');
  return {...data, rack_captures: [...new Set(captures)], ...(raw.cloud_sync ? {cloud_sync: raw.cloud_sync} : {})};
}
function pscubeCloudMerge(stored, incoming) {
  const merged = mergeData(stored, incoming);
  const records = new Map(merged.records.map(r => [recordKey(r), r]));
  const sameNumbers = (a, b) => ['bb', 'rb', 'at_art', 'games', 'my'].every(k => a[k] === b[k]);
  const captures = new Set();
  for (const document of [stored, incoming]) {
    const wanted = new Set(document.rack_captures || []);
    for (const r of document.records) {
      const key = recordKey(r);
      if (wanted.has(key) && sameNumbers(r, records.get(key))) captures.add(key);
    }
  }
  return {...merged, rack_captures: [...captures]};
}
function pscubeCloudViewer(backup, exportedAt) {
  const latest = backup.records.reduce((day, r) => r.day > day ? r.day : day, '');
  const first = latest ? new Date(Date.parse(latest) - 30 * 86400000).toISOString().slice(0, 10) : '';
  const records = backup.records.filter(r => r.day >= first).map(r => ({...r, graph: pscubeCloudThinGraph(r.graph)}));
  if (records.length > 100000) throw new Error('直近31日の記録が閲覧ページの上限10万件を超えています。');
  return {format: FORMAT, version: 1, kind: 'viewer', source: 'cloud', exported_at: exportedAt,
    machines: backup.machines, records: records, ...(backup.date_events ? {date_events: backup.date_events} : {})};
}
function pscubeCloudThinGraph(graph) {
  if (!graph || graph.points.length <= 16) return graph;
  const points = graph.points;
  let min = 0, max = 0;
  points.forEach((p, i) => { if (p[1] < points[min][1]) min = i; if (p[1] > points[max][1]) max = i; });
  const required = new Set([0, points.length - 1, min, max]);
  const others = points.map((_, i) => i).filter(i => !required.has(i));
  const slots = 16 - required.size;
  // Pythonのround（偶数への丸め）と同じ。PCと同じ点を残す。
  const round = n => n % 1 === 0.5 ? 2 * Math.round(n / 2) : Math.round(n);
  for (let k = 0; k < slots; k++) required.add(others[round(k * (others.length - 1) / (slots - 1))]);
  return {...graph, points: [...required].sort((a, b) => a - b).map(i => points[i])};
}
function pscubeCloudCheckSize(text) {
  // getBytes() の巨大な数値配列を作らず、UTF-8のバイト数を数える。
  let size = 0;
  for (const char of text) { const n = char.codePointAt(0); size += n < 128 ? 1 : n < 2048 ? 2 : n < 65536 ? 3 : 4; }
  if (size > PSCUBE_CLOUD_MAX_BYTES) throw new Error('統合ファイルが48MiBを超えています。分割対応が必要です。');
}
function pscubeCloudWrite(folder, file, name, text) {
  const blob = Utilities.newBlob(text, 'application/json', name);
  if (!file) return folder.createFile(blob);
  // DriveApp.File.setContent/createFile(name, text, mime) は10MB制限があるため、
  // 既存ファイルはDrive APIのメディア更新を使い、ファイルID・共有設定を維持する。
  const response = UrlFetchApp.fetch('https://www.googleapis.com/upload/drive/v3/files/' + encodeURIComponent(file.getId()) + '?uploadType=media', {
    method: 'patch', contentType: 'application/json', payload: blob,
    headers: {Authorization: 'Bearer ' + ScriptApp.getOAuthToken()}, muteHttpExceptions: true,
  });
  if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) {
    throw new Error(name + ' の更新に失敗しました（HTTP ' + response.getResponseCode() + '）。次の自動実行でやり直します。');
  }
  return DriveApp.getFileById(file.getId());
}
