// 模擬Drive・既存読み込みとの互換試験済み。Googleでの初回設定・実機反映は MERUHEN_CLOUD_SYNC.md に沿って確認する。
// メルヘン（幸町・長町南）PC不要同期（2026-10-13 利用者「メルヘンもやってください」）。
// 初回: 別のApps Scriptプロジェクトに全文を貼り、setupMeruhenCloudSync を実行。手順は MERUHEN_CLOUD_SYNC.md。
// 既存の閲覧用・共有用スクリプト、P’s CUBEの自動反映プロジェクトは変更不要。ウェブ公開も不要。
//
// Androidの「バックアップを書き出す（共有）」で保存した database-backup-android-….json を読み、
// PCが書き出す閲覧用ファイル database-viewer.json（iPhone閲覧・共有ページが読む）へ足し込む。
// 読んだAndroidの記録は database-android-cloud.json（画像なし）に貯め、PCが閲覧用ファイルを書き直したら次の実行で足し直す。
// PCの記録（database.sqlite3）は変えない。PCへはこれまでどおり「バックアップを読み込む」で取り込む。

// 通常は空欄のまま。database-viewer.json が複数のフォルダにある場合だけ、「database共有」のフォルダIDを入れる。
const MERUHEN_FOLDER_ID = '';
// 自分用・共有用の両Apps Scriptを更新してから true にする（VIEWER_INCREMENTAL_SYNC.md）。
const MERUHEN_INCREMENTAL_VIEWER = false;
const MERUHEN_CLOUD_VIEWER = 'database-viewer.json';
const MERUHEN_CLOUD_STORE = 'database-android-cloud.json';
const MERUHEN_CLOUD_HANDLER = 'syncMeruhenCloud';
const MERUHEN_CLOUD_BATCH = 10;
const MERUHEN_CLOUD_MAX_BYTES = 48 * 1024 * 1024;
const MERUHEN_CLOUD_TIME_BUDGET_MS = 180000;
// PCの閲覧用ファイルと同じ：最新の記録日から60日（core.VIEWER_DAYS）、出す項目（core.VIEWER_KEYS）。
const MERUHEN_VIEWER_DAYS = 60;
const MERUHEN_VIEWER_KEYS = ['store', 'kind_code', 'day', 'machine', 'rack', 'games', 'bb', 'rb', 'max_hold',
  'graph_measurement', 'captured_at', 'confirmed_setting', 'rainbow', 'rainbow_at', 'jo_net'];
// 貯める項目：閲覧用の項目＋比べるための取得時刻（ジャグラーオンライン）。
const MERUHEN_STORE_KEYS = [...MERUHEN_VIEWER_KEYS, 'jo_captured_at'];
const MERUHEN_NUMBERS = ['games', 'bb', 'rb', 'max_hold'];
const MERUHEN_STORES = ['nagamachiminami', 'saiwaichou'];
const MERUHEN_SETTINGS = ['4以上', '5以上', '6'];
// 表示しない機種（core.HIDDEN_MACHINE_WORDS と同じ）。
const MERUHEN_HIDDEN = {saiwaichou: ['聖闘士星矢海皇覚醒']};
const MERUHEN_CLOUD_ERRORS = 'meruhenCloudErrors';
const MERUHEN_CLOUD_FAILED = 'meruhenCloudFailed';
const MERUHEN_CLOUD_FAILED_MAX = 120;
const MERUHEN_CLOUD_STATUS = 'meruhenCloudStatus';
const MERUHEN_CLOUD_WRITE_TRIES = 3;

/** Driveの一時的な障害（読み出しの例外）。壊れたファイルとして記録せず、次の実行でやり直す。 */
class MeruhenCloudTransient extends Error {}
/** 入力ではなく、同期そのものを止める失敗（設定・閲覧用ファイル・出力）。保存済みの蓄積から次回再試行する。 */
class MeruhenCloudStop extends Error {
  constructor(kind, message) { super(message); this.kind = kind; }
}

/** 初回にエディタから実行。フォルダ確認→同期→30分おきの自動実行を設定する。 */
function setupMeruhenCloudSync() {
  const properties = PropertiesService.getScriptProperties();
  let folder;
  if (MERUHEN_FOLDER_ID) folder = DriveApp.getFolderById(MERUHEN_FOLDER_ID);
  else if (properties.getProperty('meruhenCloudFolder')) folder = DriveApp.getFolderById(properties.getProperty('meruhenCloudFolder'));
  else {
    const folders = new Map();
    const files = DriveApp.getFilesByName(MERUHEN_CLOUD_VIEWER);
    while (files.hasNext()) {
      const file = files.next();
      if (file.isTrashed()) continue;
      const parents = file.getParents();
      while (parents.hasNext()) {
        const parent = parents.next();
        if (!parent.isTrashed()) folders.set(parent.getId(), parent);
      }
    }
    if (folders.size !== 1) throw new Error('閲覧用ファイル（database-viewer.json）のフォルダを一意に決められません。MERUHEN_FOLDER_ID に「database共有」のフォルダIDを入れてください。');
    folder = [...folders.values()][0];
  }
  if (folder.isTrashed()) throw new Error('共有フォルダがごみ箱にあります。');
  properties.setProperty('meruhenCloudFolder', folder.getId());
  // 一部のバックアップが不正でも、正常な分を反映したうえで自動実行は設定する（失敗はログと状態に残る）。
  const result = meruhenCloudRun();
  const triggers = ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === MERUHEN_CLOUD_HANDLER);
  ScriptApp.newTrigger(MERUHEN_CLOUD_HANDLER).timeBased().everyMinutes(30).create();
  for (const trigger of triggers) ScriptApp.deleteTrigger(trigger);
  console.log('設定完了：30分おきにメルヘン（幸町・長町南）のAndroidバックアップを閲覧・共有へ反映します。残りの未処理ファイル：' + result.pending);
  return result;
}

/** 30分おきの自動実行・手動実行。新しく取り込めない入力が見つかった回だけ、反映後にエラーにする（Googleから通知）。 */
function syncMeruhenCloud() {
  const result = meruhenCloudRun();
  if (result.newFailures && result.newFailures.length) {
    throw new Error('一部のバックアップを取り込めませんでした（ほかは反映済み）：' +
      result.newFailures.map(f => f.name + '（' + f.reason + '）').join('、'));
  }
  return result;
}

/** 直近の実行の状態をログに出す。何も書き換えない。 */
function showMeruhenCloudStatus() {
  const props = PropertiesService.getScriptProperties();
  const status = meruhenParse(props.getProperty(MERUHEN_CLOUD_STATUS)) || {};
  const failures = Object.values(meruhenParse(props.getProperty(MERUHEN_CLOUD_ERRORS)) || {});
  const failedCount = Object.keys(meruhenParse(props.getProperty(MERUHEN_CLOUD_FAILED)) || {}).length;
  for (const line of meruhenStatusLines(status, failures, failedCount)) console.log(line);
  return {status: status, failures: failures};
}

/** 日別ファイルが消えた・壊れた場合だけ実行。元バックアップは変更しない。 */
function rebuildMeruhenViewerParts() {
  PropertiesService.getScriptProperties().deleteProperty('meruhenCloudInputs');
  return syncMeruhenCloud();
}

function meruhenCloudRun() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return {busy: true, changed: false, pending: 0, newFailures: []};
  const props = PropertiesService.getScriptProperties();
  const startedAt = Date.now();
  const previous = meruhenParse(props.getProperty(MERUHEN_CLOUD_STATUS)) || {};
  try {
    const id = props.getProperty('meruhenCloudFolder');
    if (!id) throw new MeruhenCloudStop('config', '最初に setupMeruhenCloudSync を実行してください。');
    const folder = DriveApp.getFolderById(id);
    if (folder.isTrashed()) throw new MeruhenCloudStop('config', '共有フォルダがごみ箱にあります。');
    const viewerFile = meruhenUniqueFile(folder, MERUHEN_CLOUD_VIEWER);
    if (!viewerFile) throw new MeruhenCloudStop('config', MERUHEN_CLOUD_VIEWER + ' が共有フォルダにありません。PC版で一度取り込むと作られます。');
    const storeFile = meruhenUniqueFile(folder, MERUHEN_CLOUD_STORE);
    const inputs = meruhenListInputs([folder, DriveApp.getRootFolder()]);
    const liveIds = new Set(inputs.map(i => i.id));
    const failures = meruhenParse(props.getProperty(MERUHEN_CLOUD_ERRORS)) || {};
    const failedVersions = meruhenParse(props.getProperty(MERUHEN_CLOUD_FAILED)) || {};
    for (const [key, f] of Object.entries(failures)) if (!failedVersions[key]) failedVersions[key] = f.version;
    for (const key of Object.keys(failures)) if (!liveIds.has(key)) delete failures[key];
    for (const key of Object.keys(failedVersions)) if (!liveIds.has(key)) delete failedVersions[key];
    const inputVersion = meruhenDigest(inputs.map(i => [i.id, i.version]));
    const viewerVersion = meruhenVersion(viewerFile);
    const storeVersion = storeFile ? meruhenVersion(storeFile) : '';
    const partsVersion = MERUHEN_INCREMENTAL_VIEWER ? vpCheckpoint(folder, 'meruhen', viewerFile) : 'legacy';
    // 入力も閲覧用ファイルも前回のままなら、大きいJSONを読まず、書き直さない。
    if (props.getProperty('meruhenCloudInputs') === inputVersion && props.getProperty('meruhenCloudViewer') === viewerVersion &&
        props.getProperty('meruhenCloudStore') === storeVersion &&
        props.getProperty('meruhenCloudParts') === partsVersion) {
      const failedCount = Object.keys(failedVersions).length;
      if (MERUHEN_INCREMENTAL_VIEWER) vpMaintain(folder, 'meruhen', props);
      const status = {...previous, at: new Date().toISOString(), result: failedCount ? 'unchanged-partial' : 'unchanged',
        message: '変更なし', inputs: inputs.length, failed: failedCount, elapsed_ms: Date.now() - startedAt};
      meruhenSave(props, status, failures, failedVersions);
      console.log(failedCount ? '変更なし（取り込めないファイル ' + failedCount + '件は、更新されたら再試行します）' : '変更なし');
      return {changed: false, pending: 0, newFailures: [], status: status};
    }
    let stored;
    try {
      stored = storeFile ? meruhenReadStore(storeFile) : {inputs: {}, records: []};
    } catch (error) {
      if (error instanceof MeruhenCloudTransient) {
        throw new MeruhenCloudStop('transient', MERUHEN_CLOUD_STORE + ' をDriveから読めませんでした（' + error.message + '）。次の自動実行でやり直します。');
      }
      throw new MeruhenCloudStop('store', MERUHEN_CLOUD_STORE + ' を読めません（' + error.message + '）。上書きせずに止めました。' +
        '共有フォルダから外す（名前を変える）と、次の実行でAndroidのバックアップから作り直します。');
    }
    const versions = {...stored.inputs};
    const records = new Map(stored.records.map(r => [meruhenKey(r), r]));
    const pending = inputs.filter(i => versions[i.id] !== i.version && failedVersions[i.id] !== i.version);
    const newFailures = [], transient = [], changedWhileReading = [];
    let attempted = 0, readBytes = 0, processed = 0, failedNow = 0, storeChanged = false;
    for (const input of pending.slice(0, MERUHEN_CLOUD_BATCH)) {
      if (attempted && (Date.now() - startedAt > MERUHEN_CLOUD_TIME_BUDGET_MS || readBytes + input.size > 64 * 1024 * 1024)) break;
      attempted++;
      readBytes += input.size;
      let incoming;
      try {
        incoming = meruhenReadBackup(input.file, input.size);
      } catch (error) {
        if (error instanceof MeruhenCloudTransient) { transient.push(input.name); continue; }
        const failure = {name: input.name, reason: String(error.message || error).slice(0, 120), version: input.version,
          checked_at: new Date().toISOString(), size: input.size};
        if (failedVersions[input.id] !== input.version) newFailures.push(failure);
        failures[input.id] = failure;
        delete failedVersions[input.id];
        failedVersions[input.id] = input.version;
        failedNow++;
        continue;
      }
      // 読み込み中の変更（アップロード途中など）は、この回は取り込まず次回やり直す（失敗とはしない）。
      if (input.version !== meruhenVersion(input.file)) { changedWhileReading.push(input.name); continue; }
      for (const r of incoming) {
        const key = meruhenKey(r), current = records.get(key);
        const next = current ? meruhenPick(current, r) : r;
        if (next !== current) { records.set(key, next); storeChanged = true; }
      }
      versions[input.id] = input.version;
      delete failures[input.id];
      delete failedVersions[input.id];
      processed++;
      storeChanged = true;
    }
    const remaining = pending.length - processed - failedNow;
    for (const key of Object.keys(versions)) if (!liveIds.has(key)) { delete versions[key]; storeChanged = true; }

    // 閲覧用ファイル（PCの書き出し、または前回この同期で足し込んだもの）へ足し込む。
    if (viewerFile.getSize() > MERUHEN_CLOUD_MAX_BYTES) {
      throw new MeruhenCloudStop('viewer', MERUHEN_CLOUD_VIEWER + ' が48MiBを超えます。書き換えずに止めました。');
    }
    let viewerText;
    try { viewerText = viewerFile.getBlob().getDataAsString('UTF-8'); }
    catch (error) {
      throw new MeruhenCloudStop('transient', MERUHEN_CLOUD_VIEWER + ' をDriveから読めませんでした（' +
        String(error && error.message || error).slice(0, 120) + '）。次の自動実行でやり直します。');
    }
    let viewer;
    try { viewer = JSON.parse(viewerText.replace(/^﻿/, '')); }
    catch (error) { throw new MeruhenCloudStop('viewer', MERUHEN_CLOUD_VIEWER + ' を読めません（書き出し途中の可能性）。次の自動実行でやり直します。'); }
    if (!viewer || viewer.format !== 'database-backup' || viewer.version !== 1 || viewer.source !== 'pc-viewer' ||
        !Array.isArray(viewer.records) || !viewer.records.every(meruhenValidRecord)) {
      throw new MeruhenCloudStop('viewer', MERUHEN_CLOUD_VIEWER + ' がPC版の閲覧用ファイルの形ではありません。書き換えずに止めました。');
    }
    const merged = meruhenApply(viewer, [...records.values()]);
    // 期間（60日）より古いAndroidの記録は貯めない。
    for (const [key, r] of records) if (r.day < merged.cutoff) { records.delete(key); storeChanged = true; }
    // 両方の出力を容量検査してから保存を始める。
    const leavingParts = !MERUHEN_INCREMENTAL_VIEWER && props.getProperty('meruhenCloudParts') && props.getProperty('meruhenCloudParts') !== 'legacy';
    const outputText = merged.changed || leavingParts ? meruhenViewerText(viewer, merged.records, merged.changed) : null;
    let savedViewer = viewerFile, viewerBytes = outputText == null ? viewerFile.getSize() : meruhenCheckSize(outputText, MERUHEN_CLOUD_VIEWER);
    if (storeChanged || !storeFile) {
      const storeText = JSON.stringify({format: 'database-android-cloud', version: 1, exported_at: new Date().toISOString(),
        note: 'メルヘンのPC不要同期が貯めたAndroidの記録（画像なし）。PCのバックアップとしては読み込まない。',
        inputs: versions, records: [...records.values()]});
      meruhenCheckSize(storeText, MERUHEN_CLOUD_STORE);
      meruhenSave(props, null, failures, failedVersions);
      const savedStore = meruhenWrite(folder, storeFile, MERUHEN_CLOUD_STORE, storeText);
      props.setProperty('meruhenCloudStore', meruhenVersion(savedStore));
    } else {
      meruhenSave(props, null, failures, failedVersions);
    }
    // PCの書き出しは別プロセス・別ロック。読み始めてから変わった版を上書きしない。
    if (viewerVersion !== meruhenVersion(viewerFile)) {
      throw new MeruhenCloudStop('transient', MERUHEN_CLOUD_VIEWER + ' が処理中に変更されました。次の自動実行で新しいPCの記録へ足し直します。');
    }
    let incremental = null;
    if (MERUHEN_INCREMENTAL_VIEWER) {
      incremental = vpPublish(folder, viewerFile, 'meruhen', outputText ? JSON.parse(outputText) : viewer, meruhenWrite, viewerFile.getId() + ':' + viewerVersion);
      viewerBytes = incremental.total;
    } else if (outputText) {
      savedViewer = meruhenWrite(folder, viewerFile, MERUHEN_CLOUD_VIEWER, outputText);
    }
    props.setProperty('meruhenCloudParts', MERUHEN_INCREMENTAL_VIEWER ? vpCheckpoint(folder, 'meruhen', savedViewer) : 'legacy');
    if (MERUHEN_INCREMENTAL_VIEWER) vpMaintain(folder, 'meruhen', props);
    props.setProperty('meruhenCloudViewer', meruhenVersion(savedViewer));
    if (!remaining) props.setProperty('meruhenCloudInputs', inputVersion);
    else props.deleteProperty('meruhenCloudInputs');
    const failedCount = Object.keys(failedVersions).length;
    const status = {at: new Date().toISOString(), result: failedCount ? 'partial' : 'ok',
      message: (processed ? processed + 'ファイルを取り込み・' : '') + (merged.changed ? '閲覧用に' + merged.changed + '台を反映' : '閲覧用は変更なし') +
        (transient.length ? '・一時的に読めなかった' + transient.length + 'ファイルは次回' : ''),
      processed: processed, failed: failedCount, new_failures: newFailures.length, remaining: remaining,
      changed_while_reading: changedWhileReading.length, transient: transient.length, inputs: inputs.length,
      android_records: records.size, viewer_records: merged.records.length, viewer_changed: merged.changed,
      incremental: incremental, viewer_bytes: viewerBytes, elapsed_ms: Date.now() - startedAt};
    meruhenSave(props, status, failures, failedVersions);
    for (const line of meruhenStatusLines(status, Object.values(failures), failedCount)) console.log(line);
    return {changed: Boolean(merged.changed), pending: remaining, newFailures: newFailures, status: status};
  } catch (error) {
    const kind = error instanceof MeruhenCloudStop ? error.kind : 'other';
    const status = {...previous, at: new Date().toISOString(), result: 'error', stop: kind, message: String(error.message || error).slice(0, 300)};
    try { props.setProperty(MERUHEN_CLOUD_STATUS, JSON.stringify(status)); } catch (_) { /* 状態を残せなくても元のエラーを返す */ }
    throw error;
  } finally { lock.releaseLock(); }
}

/** Androidのバックアップの候補（共有フォルダ直下とマイドライブ直下）。名前・ID・更新時刻・サイズを1回ずつ読む。 */
function meruhenListInputs(folders) {
  const byId = new Map(), seen = new Set();
  for (const folder of folders) {
    if (seen.has(folder.getId())) continue;
    seen.add(folder.getId());
    const files = folder.searchFiles("trashed = false and title contains 'database-backup-android'");
    while (files.hasNext()) {
      const file = files.next(), name = file.getName();
      if (!/^database-backup-android(?:-\d{8}-\d{6})?\.json$/.test(name)) continue;
      const id = file.getId();
      if (byId.has(id)) continue;
      const updated = file.getLastUpdated().getTime(), size = file.getSize();
      byId.set(id, {file: file, id: id, name: name, updated: updated, size: size, version: updated + '-' + size});
    }
  }
  return [...byId.values()].sort((a, b) => a.updated - b.updated || a.id.localeCompare(b.id));
}

/** Androidのバックアップ1つを読み、PCの読み込み（core._valid_backup_record）と同じ検査を通った記録を、貯める形で返す。 */
function meruhenReadBackup(file, size) {
  if (size > MERUHEN_CLOUD_MAX_BYTES) throw new Error('ファイルが48MiBを超えています（PCの「バックアップを読み込む」で取り込んでください）。');
  let text;
  try { text = file.getBlob().getDataAsString('UTF-8'); }
  catch (error) { throw new MeruhenCloudTransient(String(error && error.message || error).slice(0, 120)); }
  const raw = JSON.parse(text.replace(/^﻿/, ''));
  if (!raw || typeof raw !== 'object' || raw.format !== 'database-backup' || raw.version !== 1 || !Array.isArray(raw.records)) {
    throw new Error('databaseのバックアップの形ではありません。');
  }
  if (raw.source === 'pc-viewer') throw new Error('閲覧用の軽いファイルはバックアップとして使えません。');
  const out = new Map();
  for (const record of raw.records) {
    if (!meruhenValidRecord(record)) continue;
    const r = meruhenSlim({...record, machine: meruhenMachineName(record.machine)});
    if (meruhenHidden(r.store, r.machine)) continue;
    const key = meruhenKey(r), current = out.get(key);
    out.set(key, current ? meruhenPick(current, r) : r);
  }
  return [...out.values()];
}

function meruhenReadStore(file) {
  if (file.getSize() > MERUHEN_CLOUD_MAX_BYTES) throw new Error('48MiBを超えています');
  let text;
  try { text = file.getBlob().getDataAsString('UTF-8'); }
  catch (error) { throw new MeruhenCloudTransient(String(error && error.message || error).slice(0, 120)); }
  const raw = JSON.parse(text);
  if (!raw || raw.format !== 'database-android-cloud' || raw.version !== 1 || !Array.isArray(raw.records) ||
      !raw.records.every(meruhenValidRecord) || !raw.inputs || typeof raw.inputs !== 'object' || Array.isArray(raw.inputs) ||
      !Object.values(raw.inputs).every(v => typeof v === 'string')) {
    throw new Error('形式が不正です');
  }
  return {inputs: raw.inputs, records: raw.records};
}

function meruhenValidDay(day) {
  if (typeof day !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(day) || day.startsWith('0000-')) return false;
  const time = Date.parse(day + 'T00:00:00Z');
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === day;
}
function meruhenValidRecord(r) {
  const whole = x => Number.isSafeInteger(x) && x >= 0;
  return !!r && typeof r === 'object' && r.kind_code === 21 && MERUHEN_STORES.includes(r.store) &&
    typeof r.machine === 'string' && r.machine.trim() !== '' && whole(r.rack) && r.rack > 0 &&
    ['games', 'bb', 'rb'].every(k => whole(r[k])) && ['max_hold', 'previous_start'].every(k => r[k] == null || whole(r[k])) &&
    (r.confirmed_setting == null || MERUHEN_SETTINGS.includes(r.confirmed_setting)) &&
    meruhenValidDay(r.day);
}

/** 閲覧用の項目だけ（グラフの画像は外し、曲線は残す。PCの export_viewer と同じ）＋取得時刻。 */
function meruhenSlim(record) {
  const r = {};
  for (const key of MERUHEN_STORE_KEYS) if (record[key] !== undefined) r[key] = record[key];
  if (r.graph_measurement && typeof r.graph_measurement === 'object') {
    const graph = {...r.graph_measurement};
    delete graph.preview_image; delete graph.preview_stored; delete graph.curve_stored;
    r.graph_measurement = graph;
  }
  return r;
}

/** core.normalize_machine_name：「+」と続く空白を1つの空白に。 */
function meruhenMachineName(value) { return String(value || '').replace(/\+/g, ' ').split(/\s+/).filter(Boolean).join(' '); }
function meruhenHidden(store, machine) {
  const text = String(machine || '').normalize('NFKC').replace(/\s+/g, '');
  return (MERUHEN_HIDDEN[store] || []).some(word => text.includes(word));
}
function meruhenKey(r) { return JSON.stringify([r.store, r.day, meruhenMachineName(r.machine), r.rack]); }

/** 取得時刻（タイムゾーンの無い時刻は日本時間）。読めなければ null。 */
function meruhenTime(value) {
  if (typeof value !== 'string' || !value) return null;
  const m = value.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$/);
  if (!m) return null;
  const t = Date.parse(m[1] + (m[2] ? m[2].slice(0, 4) : '') + (m[3] || '+09:00'));
  return Number.isFinite(t) ? t : null;
}
const meruhenSameNumbers = (a, b) => MERUHEN_NUMBERS.every(k => a[k] == null || b[k] == null || a[k] === b[k]);
const meruhenHasGraph = r => !!(r.graph_measurement && typeof r.graph_measurement === 'object');

/**
 * 同じ台の2つの記録から表示に使うもの。数値が違えば取得時刻（captured_at）の新しい方の数値・グラフ・時刻を使う
 * （同じか分からなければ [base] のまま）。数値が同じならグラフ・確定設定の無い方を補う。ジャグラーオンラインの差枚は
 * 取得時刻（jo_captured_at）の新しい方、[base] に無ければ足す。変わらなければ [base] そのものを返す。
 */
function meruhenPick(base, other) {
  let out = base;
  const set = (patch) => { out = out === base ? {...base, ...patch} : {...out, ...patch}; };
  const mine = meruhenTime(base.captured_at), theirs = meruhenTime(other.captured_at);
  if (!meruhenSameNumbers(base, other)) {
    if (theirs != null && (mine == null || theirs > mine)) {
      out = {...out};
      for (const key of [...MERUHEN_NUMBERS, 'captured_at', 'graph_measurement']) {
        if (other[key] === undefined) delete out[key];
        else out[key] = other[key];
      }
    }
  } else {
    if (!meruhenHasGraph(base) && meruhenHasGraph(other)) set({graph_measurement: other.graph_measurement});
    if (base.max_hold == null && other.max_hold != null) set({max_hold: other.max_hold});
    // 同じ数値を新しく観測した場合も時刻を残す。後で届いた中間時刻の数値に巻き戻さない。
    if (theirs != null && (mine == null || theirs > mine)) set({captured_at: other.captured_at});
  }
  if (base.confirmed_setting == null && other.confirmed_setting != null) set({confirmed_setting: other.confirmed_setting});
  if (Number.isSafeInteger(other.jo_net)) {
    const mine = meruhenTime(base.jo_captured_at), theirs = meruhenTime(other.jo_captured_at);
    if (!Number.isSafeInteger(base.jo_net) || (theirs != null && (mine == null || theirs > mine))) {
      set({jo_net: other.jo_net});
      if (other.jo_captured_at) set({jo_captured_at: other.jo_captured_at});
      else if ('jo_captured_at' in out) { out = {...out}; delete out.jo_captured_at; }
    }
  }
  return out;
}

/**
 * PCの閲覧用ファイル [viewer] の記録に、Androidの記録 [android] を足し込む。閲覧用ファイルは
 * ジャグラーオンラインの取得時刻を持たないため、差枚はAndroidの値を使う（PCの差枚もAndroidから来たもの）。
 * 🌈は閲覧用ファイル（PC・共有の印）のまま。最新の記録日から60日より前は出さない。
 */
function meruhenApply(viewer, android) {
  const byKey = new Map();
  for (const r of viewer.records) if (r && typeof r === 'object') byKey.set(meruhenKey(r), r);
  for (const a of android) {
    const key = meruhenKey(a), local = byKey.get(key);
    if (!local) { byKey.set(key, meruhenViewerRecord(a)); continue; }
    let next = meruhenPick(local, {...a, jo_captured_at: undefined});
    if (Number.isSafeInteger(a.jo_net) && next.jo_net !== a.jo_net) next = {...next, jo_net: a.jo_net};
    if (next !== local) {
      const out = meruhenViewerRecord(next);
      if (JSON.stringify(out) !== JSON.stringify(meruhenViewerRecord(local))) byKey.set(key, out);
    }
  }
  const latest = [...byKey.values()].reduce((day, r) => typeof r.day === 'string' && r.day > day ? r.day : day, '');
  const cutoff = latest ? new Date(Date.parse(latest + 'T00:00:00Z') - (MERUHEN_VIEWER_DAYS - 1) * 86400000).toISOString().slice(0, 10) : '';
  const records = [...byKey.values()].filter(r => !cutoff || !(typeof r.day === 'string') || r.day >= cutoff);
  // PCと同じ並び（日付・店舗・台番号）。
  records.sort((a, b) => String(a.day).localeCompare(String(b.day)) || String(a.store).localeCompare(String(b.store)) || (a.rack || 0) - (b.rack || 0));
  // 範囲外の古い入力を足してから除いただけでは、閲覧用を更新しない。
  const previous = new Map(viewer.records.map(r => [meruhenKey(r), JSON.stringify(meruhenViewerRecord(r))]));
  let changed = 0;
  for (const r of records) {
    const key = meruhenKey(r);
    if (previous.get(key) !== JSON.stringify(meruhenViewerRecord(r))) changed++;
    previous.delete(key);
  }
  changed += previous.size;
  return {records: records, changed: changed, cutoff: cutoff};
}
function meruhenViewerRecord(r) {
  const out = {};
  for (const key of MERUHEN_VIEWER_KEYS) {
    const value = r[key];
    if (value === undefined || (key === 'jo_net' && !Number.isSafeInteger(value))) continue;
    out[key] = value;
  }
  return out;
}

/** PCの export_viewer と同じ並び（1行目に見出し、1台1行）。閲覧ページは1行目の書き出し時刻で読み直しを決める。 */
function meruhenViewerText(viewer, records, changed) {
  const header = {};
  for (const [key, value] of Object.entries(viewer)) if (key !== 'records') header[key] = value;
  header.exported_at = new Date().toISOString();
  header.cloud_merged = {at: header.exported_at, racks: changed, note: 'AndroidのバックアップをGoogle側で足し込み（MERUHEN_CLOUD_SYNC.md）'};
  const head = JSON.stringify(header);
  return head.slice(0, -1) + ', "records": [' + records.map((r, i) => (i ? ',\n' : '\n') + JSON.stringify(r)).join('') + '\n]}';
}

function meruhenStatusLines(status, failures, failedCount = failures.length) {
  const label = {ok: '正常に完了', partial: '一部失敗（ほかは反映済み）', unchanged: '変更なし',
    'unchanged-partial': '変更なし（取り込めないファイルあり）', error: '停止（次の実行で再試行）'}[status.result] || 'まだ実行していません';
  const lines = ['状態：' + label + (status.at ? '（' + status.at + '）' : '') + (status.message ? '・' + status.message : '')];
  if (status.viewer_records != null) {
    lines.push('閲覧用 ' + status.viewer_records + '件・' + ((status.viewer_bytes || 0) / 1048576).toFixed(1) + 'MB（上限48MB）／貯めたAndroidの記録 ' + status.android_records + '件');
  }
  if (status.incremental) lines.push((['ok', 'partial'].includes(status.result) ? '今回' : '前回確定時') +
    'の差分出力：' + status.incremental.parts + 'パーツ・' + (status.incremental.bytes / 1024).toFixed(1) + 'KB');
  if (status.remaining) lines.push('次回に回したファイル：' + status.remaining);
  if (failedCount > failures.length) lines.push('取り込めないファイル：全部で' + failedCount + '件（理由は新しい' + failures.length + '件）');
  for (const f of failures) lines.push('取り込めないファイル：' + f.name + '（' + f.reason + '、確認 ' + f.checked_at + '）');
  if ((status.viewer_bytes || 0) >= MERUHEN_CLOUD_MAX_BYTES * 0.6) lines.push('注意：閲覧用の容量が上限の60%を超えました。');
  if ((status.elapsed_ms || 0) >= 120000) lines.push('注意：処理に' + Math.round(status.elapsed_ms / 1000) + '秒かかりました（Googleの上限は6分）。');
  return lines;
}

function meruhenSave(props, status, failures, failedVersions) {
  const list = Object.entries(failures).sort((a, b) => String(b[1].checked_at).localeCompare(String(a[1].checked_at))).slice(0, 10);
  props.setProperty(MERUHEN_CLOUD_ERRORS, JSON.stringify(Object.fromEntries(list)));
  props.setProperty(MERUHEN_CLOUD_FAILED, JSON.stringify(Object.fromEntries(Object.entries(failedVersions).slice(-MERUHEN_CLOUD_FAILED_MAX))));
  if (status) props.setProperty(MERUHEN_CLOUD_STATUS, JSON.stringify(status));
}
function meruhenParse(text) { try { return text ? JSON.parse(text) : null; } catch (_) { return null; } }
function meruhenUniqueFile(folder, name) {
  const files = folder.getFilesByName(name), found = [];
  while (files.hasNext()) { const file = files.next(); if (!file.isTrashed()) found.push(file); }
  if (found.length > 1) throw new MeruhenCloudStop('config', name + ' が共有フォルダに複数あります。重複を解消してから実行してください。');
  return found[0] || null;
}
function meruhenVersion(file) { return file.getLastUpdated().getTime() + '-' + file.getSize(); }
function meruhenDigest(value) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, JSON.stringify(value))
    .map(b => ('0' + ((b + 256) % 256).toString(16)).slice(-2)).join('');
}
/** UTF-8のバイト数。48MiBを超えたら出力しないで止める。 */
function meruhenCheckSize(text, name) {
  let size = 0;
  for (const char of text) { const n = char.codePointAt(0); size += n < 128 ? 1 : n < 2048 ? 2 : n < 65536 ? 3 : 4; }
  if (size > MERUHEN_CLOUD_MAX_BYTES) throw new MeruhenCloudStop('output', name + ' が48MiBを超えます。既存の出力はそのままです。');
  return size;
}
/** 既存ファイルはDrive APIのメディア更新（ファイルID・共有設定を維持。10MB制限を避ける）。一時的な失敗は3回まで試す。 */
function meruhenWrite(folder, file, name, text) {
  const blob = Utilities.newBlob(text, 'application/json', name);
  if (!file) return folder.createFile(blob);
  let last = '';
  for (let attempt = 1; attempt <= MERUHEN_CLOUD_WRITE_TRIES; attempt++) {
    let code = 0;
    try {
      const response = UrlFetchApp.fetch('https://www.googleapis.com/upload/drive/v3/files/' + encodeURIComponent(file.getId()) + '?uploadType=media', {
        method: 'patch', contentType: 'application/json', payload: blob,
        headers: {Authorization: 'Bearer ' + ScriptApp.getOAuthToken()}, muteHttpExceptions: true,
      });
      code = response.getResponseCode();
      if (code >= 200 && code < 300) return DriveApp.getFileById(file.getId());
      last = 'HTTP ' + code;
    } catch (error) {
      last = '通信エラー：' + String(error && error.message || error).slice(0, 80);
    }
    const retry = code === 0 || code === 429 || code >= 500;
    if (!retry || attempt === MERUHEN_CLOUD_WRITE_TRIES) break;
    Utilities.sleep(1000 * attempt);
  }
  throw new MeruhenCloudStop('output', name + ' の更新に失敗しました（' + last + '）。次の自動実行でやり直します。');
}
// BEGIN GENERATED VIEWER PARTS
// 日別の不変ファイルと、最後に確定する一覧。Google・ブラウザで同じ検査を使う。
const VP_FORMAT = 'database-viewer-parts';
const VP_MAX_BYTES = 48 * 1024 * 1024;
const VP_PART_BYTES = 1024 * 1024;
const VP_BATCH = 8;
function vpCanonical(value) {
  if (Array.isArray(value)) return '[' + value.map(vpCanonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort()
    .filter(k => value[k] !== undefined).map(k => JSON.stringify(k) + ':' + vpCanonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
function vpManifestName(site) { return 'database-viewer-parts-' + site + '.json'; }
function vpPartName(site, hash) { return 'database-viewer-part-' + site + '-' + hash + '.json'; }
function vpValidManifest(m, site) {
  const fail = () => { throw new Error('閲覧用の更新一覧が不正です。'); };
  if (!m || m.format !== VP_FORMAT || m.version !== 1 || m.site !== site ||
      !['meruhen', 'pscube'].includes(site) || !/^[a-f0-9]{64}$/.test(m.revision) ||
      !m.header || typeof m.header !== 'object' || Array.isArray(m.header) || 'records' in m.header ||
      m.header.version !== 1 || m.header.format !== (site === 'meruhen' ? 'database-backup' : 'pscube-viewer') ||
      typeof m.header.exported_at !== 'string' || !Array.isArray(m.parts) || m.parts.length > 1024) fail();
  const seen = new Set(); let bytes = 0, count = 0;
  for (const p of m.parts) {
    if (!p || !/^[a-f0-9]{64}$/.test(p.hash) || seen.has(p.hash) ||
        !/^\d{4}-\d{2}-\d{2}$/.test(p.day) || !Number.isSafeInteger(p.count) || p.count < 1 ||
        !Number.isSafeInteger(p.bytes) || p.bytes < 2 || p.bytes > VP_PART_BYTES) fail();
    seen.add(p.hash); bytes += p.bytes; count += p.count;
  }
  if (bytes > VP_MAX_BYTES || count > 100000 || count !== m.count) fail();
  return m;
}
function vpPublic(m) {
  return {format: m.format, version: m.version, site: m.site, revision: m.revision,
    header: m.header, count: m.count, parts: m.parts.map(({hash, day, count, bytes}) => ({hash, day, count, bytes}))};
}
function vpRows(text, part) {
  const rows = JSON.parse(text);
  if (!Array.isArray(rows) || rows.length !== part.count || rows.some(r => !r || r.day !== part.day)) {
    throw new Error('閲覧用の日別データが更新一覧と一致しません。');
  }
  return rows;
}

// 読み取り専用。利用者の指定したDrive IDを直接開かず、確定した一覧の中だけを読む。
function vpVersion(file) { return file.getId() + ':' + file.getLastUpdated().getTime() + '-' + file.getSize(); }
function vpHash(text) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8)
    .map(b => ('0' + (b & 255).toString(16)).slice(-2)).join('');
}
function vpUnique(folder, name) {
  const files = folder.getFilesByName(name); let found = null;
  while (files.hasNext()) { const f = files.next(); if (f.isTrashed()) continue;
    if (found) throw new Error(name + ' が複数あります。'); found = f; }
  return found;
}
function vpReadManifest(file, site) {
  if (file.getSize() > 1024 * 1024) throw new Error('閲覧用の更新一覧が大きすぎます。');
  return vpValidManifest(JSON.parse(file.getBlob().getDataAsString('UTF-8')), site);
}
function vpReadPart(site, p) {
  const file = DriveApp.getFileById(p.id);
  if (file.isTrashed() || file.getName() !== vpPartName(site, p.hash) || file.getSize() !== p.bytes) {
    throw new Error('閲覧用の日別ファイルが見つかりません。同期を再実行してください。');
  }
  const text = file.getBlob().getDataAsString('UTF-8');
  if (vpHash(text) !== p.hash) throw new Error('閲覧用の日別ファイルが破損しています。');
  vpRows(text, p);
  return text;
}
function vpGet(latest, site, params) {
  // 旧形式だけの環境では追加の権限・設定は不要。
  const candidates = DriveApp.getFilesByName(vpManifestName(site));
  let manifest = null;
  while (candidates.hasNext()) {
    const file = candidates.next(); if (file.isTrashed()) continue;
    if (file.getSize() > 1024 * 1024) continue;
    const raw = JSON.parse(file.getBlob().getDataAsString('UTF-8'));
    if (raw.base !== vpVersion(latest)) continue;
    const m = vpValidManifest(raw, site);
    if (manifest) throw new Error('閲覧用の更新一覧が複数あります。');
    manifest = m;
  }
  if (!manifest) {
    if (params.parts) throw new Error('閲覧用が更新されました。もう一度読み込んでください。');
    return null;
  }
  if (params.check) return {format: 'drive-check', version: 'parts:' + manifest.revision, parts: vpPublic(manifest)};
  if (params.parts) {
    const hashes = params.parts.split(',');
    if (params.revision !== manifest.revision || hashes.length > VP_BATCH || new Set(hashes).size !== hashes.length) {
      throw new Error('閲覧用が更新されました。もう一度読み込んでください。');
    }
    const allowed = new Map(manifest.parts.map(p => [p.hash, p]));
    if (hashes.some(hash => !allowed.has(hash))) throw new Error('指定できない日別ファイルです。');
    return {format: VP_FORMAT, revision: manifest.revision,
      parts: hashes.map(hash => ({hash, text: vpReadPart(site, allowed.get(hash))}))};
  }
  // 更新前のWebページにも従来の全件JSONを返す。
  return {...manifest.header, records: manifest.parts.flatMap(p => vpRows(vpReadPart(site, p), p))};
}

// 全件のバックアップは従来どおり保持。閲覧用の出力だけを分割する。
function vpCheckpoint(folder, site, base) {
  const file = vpUnique(folder, vpManifestName(site));
  return (file ? vpVersion(file) : '') + (base ? ':' + vpVersion(base) : '');
}
function vpPublish(folder, base, site, doc, write, expectedBase) {
  const name = vpManifestName(site), oldFile = vpUnique(folder, name);
  const old = oldFile ? vpReadManifest(oldFile, site) : null;
  const byDay = new Map();
  for (const r of doc.records) {
    if (!byDay.has(r.day)) byDay.set(r.day, []);
    byDay.get(r.day).push(vpCanonical(r));
  }
  const planned = [];
  for (const day of [...byDay.keys()].sort()) {
    let rows = [], size = 2;
    const flush = () => { if (!rows.length) return; const text = '[' + rows.join(',') + ']';
      planned.push({day, count: rows.length, bytes: size, hash: vpHash(text), text}); rows = []; size = 2; };
    for (const row of byDay.get(day).sort()) {
      const bytes = Utilities.newBlob(row).getBytes().length;
      if (bytes + 2 > VP_PART_BYTES) throw new Error('1台の閲覧用データが1MiBを超えています。');
      if (size + bytes + (rows.length ? 1 : 0) > VP_PART_BYTES) flush();
      size += bytes + (rows.length ? 1 : 0); rows.push(row);
    }
    flush();
  }
  const {records, exported_at, cloud_merged, ...stableHeader} = doc;
  const signature = vpHash(vpCanonical({header: stableHeader, parts: planned.map(({day, hash}) => ({day, hash}))}));
  const header = {...stableHeader, exported_at: old?.signature === signature ? old.header.exported_at : exported_at};
  if (cloud_merged !== undefined) header.cloud_merged = cloud_merged;
  const version = expectedBase || vpVersion(base);
  if (vpVersion(base) !== version) throw new Error('PCの閲覧用が更新されました。次の同期でやり直します。');
  const revision = vpHash(vpCanonical({signature, base: version}));
  const m = {format: VP_FORMAT, version: 1, site, base: version, signature, revision,
    header, count: records.length, parts: planned.map(({text, ...p}) => p)};
  vpValidManifest(m, site); // 全出力の容量を先に検査。途中で失敗しても旧一覧は残る。
  // IDと版の追記分も見込んで、一覧の読み出し上限より余裕を持って止める。
  if (Utilities.newBlob(JSON.stringify(m)).getBytes().length + m.parts.length * 256 > 1024 * 1024) {
    throw new Error('閲覧用の更新一覧が1MiBを超えます。旧一覧を保って停止しました。');
  }
  const oldParts = new Map((old?.parts || []).map(p => [p.hash, p]));
  let written = 0, writtenBytes = 0;
  for (const p of m.parts) {
    const prior = oldParts.get(p.hash);
    let file = null;
    if (prior) { try { file = DriveApp.getFileById(prior.id); } catch (_) { /* 消えた生成ファイルを作り直す */ } }
    else file = vpUnique(folder, vpPartName(site, p.hash));
    // 紛失・手編集された生成ファイルは上書き修復。元バックアップには触れない。
    let valid = false;
    if (file && !file.isTrashed()) {
      valid = file.getName() === vpPartName(site, p.hash) && file.getSize() === p.bytes &&
        (!prior || prior.file_version === vpVersion(file));
      if (valid && !prior) valid = vpHash(file.getBlob().getDataAsString('UTF-8')) === p.hash;
    }
    if (!valid) {
      // 壊れた旧IDは旧一覧で読まれている可能性があるため、別の不変ファイルを作る。
      file = write(folder, null, vpPartName(site, p.hash), planned.find(x => x.hash === p.hash).text);
      written++; writtenBytes += p.bytes;
    }
    p.id = file.getId(); p.file_version = vpVersion(file);
  }
  if (vpVersion(base) !== version) throw new Error('PCの閲覧用が更新されました。次の同期でやり直します。');
  const text = JSON.stringify(m);
  const unchanged = old && vpCanonical(old) === vpCanonical(m);
  if (!unchanged) write(folder, oldFile, name, text); // 一覧を最後に確定する。
  return {parts: written, bytes: writtenBytes, total: planned.reduce((n, p) => n + p.bytes, 0), revision};
}

// 現在の一覧にない生成パーツだけを7日後にごみ箱へ。バックアップや旧形式JSONは対象外。
// 一覧確定後の保守であり、失敗しても確定済みの閲覧データは有効。
function vpPrune(folder, site) {
  const manifest = vpReadManifest(vpUnique(folder, vpManifestName(site)), site);
  const active = new Set(manifest.parts.map(p => p.id));
  const pattern = new RegExp('^database-viewer-part-' + site + '-[a-f0-9]{64}\\.json$');
  const files = folder.getFiles(), cutoff = Date.now() - 7 * 86400000;
  let removed = 0;
  while (files.hasNext() && removed < 200) {
    const f = files.next();
    if (!f.isTrashed() && pattern.test(f.getName()) && !active.has(f.getId()) && f.getLastUpdated().getTime() < cutoff) {
      f.setTrashed(true); removed++;
    }
  }
  return removed;
}
function vpMaintain(folder, site, props) {
  const key = site + 'ViewerPartsCleaned';
  if (Date.now() - Number(props.getProperty(key) || 0) < 6 * 3600000) return;
  try { vpPrune(folder, site); props.setProperty(key, String(Date.now())); }
  catch (error) { console.log('古い閲覧用キャッシュの整理は次回再試行します：' + String(error.message || error)); }
}
