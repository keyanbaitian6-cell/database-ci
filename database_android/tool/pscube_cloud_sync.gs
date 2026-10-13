// 生成元: tool/build_pscube_cloud_sync.mjs。共通パーサーの検証・統合規則を使用。
// 初回: 別のApps Scriptプロジェクトに全文を貼り、setupPscubeCloudSync を実行。
// 既存の閲覧用・共有用スクリプトは変更不要。ウェブ公開も不要。

// P’s CUBE PC不要同期。build_pscube_cloud_sync.mjs で検証済みの共通パーサーと結合する。
// 配布するのは pscube_cloud_sync.gs（別のApps Scriptプロジェクトに全文を貼る）。

// 通常は空欄のまま。共有フォルダが複数ある場合だけ、対象フォルダのIDを入れる。
const PSCUBE_FOLDER_ID = '';
const PSCUBE_CLOUD_BACKUP = 'pscube-backup-cloud.json';
const PSCUBE_CLOUD_VIEWER = 'pscube-viewer-drive.json';
const PSCUBE_CLOUD_BATCH = 10;
const PSCUBE_CLOUD_MAX_BYTES = 48 * 1024 * 1024;
const PSCUBE_CLOUD_HANDLER = 'syncPscubeCloud';
// 上限（共通パーサーの全期間20万件・閲覧ページの10万件）と、上限に近づいたと知らせる割合（2026-10-13）。
const PSCUBE_CLOUD_RECORD_LIMIT = 200000;
const PSCUBE_CLOUD_VIEWER_LIMIT = 100000;
const PSCUBE_CLOUD_WARN = 0.6, PSCUBE_CLOUD_ALERT = 0.8;
// 1回の実行時間の目安（Googleの上限は6分）。これを超えたら残りは次回。
const PSCUBE_CLOUD_TIME_BUDGET_MS = 180000;
// 取り込めなかった入力（ファイルID→名前・理由・版・確認日時）と、直近の実行の状態。スクリプトのプロパティに置く。
const PSCUBE_CLOUD_ERRORS = 'pscubeCloudErrors';
const PSCUBE_CLOUD_STATUS = 'pscubeCloudStatus';

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

/** 入力ではなく、同期そのものを止める失敗（統合済みバックアップが読めない・出力できない・設定）。 */
class PscubeCloudStop extends Error {
  constructor(kind, message) { super(message); this.kind = kind; }
}

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
  // 一部のバックアップが不正でも、正常な分を反映したうえで自動実行は設定する（失敗はログと状態に残る）。
  const result = pscubeCloudRun();
  const triggers = ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === PSCUBE_CLOUD_HANDLER);
  // 新しいトリガーを作ってから古いものを外す。作成失敗時には既存の自動実行を残す。
  ScriptApp.newTrigger(PSCUBE_CLOUD_HANDLER).timeBased().everyMinutes(30).create();
  // 再設定で旧5分トリガーも置き換える。他の関数のトリガーには触らない。
  for (const trigger of triggers) ScriptApp.deleteTrigger(trigger);
  console.log('設定完了：30分おきにP’s CUBEを共有へ反映します。残りの未処理ファイル：' + result.pending);
  return result;
}

/**
 * 30分おきの自動実行・エディタからの手動実行。ウェブ公開・デプロイは不要。
 * 不正な入力があっても、ほかの正常な入力は反映する。新しく取り込めない入力が見つかった回だけ、反映を済ませたあとで
 * エラーにして「実行数」に失敗として残す（Googleから失敗の通知が届く）。同じ版のファイルでは繰り返さない。
 */
function syncPscubeCloud() {
  const result = pscubeCloudRun();
  if (result.newFailures && result.newFailures.length) {
    throw new Error('一部のバックアップを取り込めませんでした（ほかは反映済み）：' +
      result.newFailures.map(f => f.name + '（' + f.reason + '）').join('、'));
  }
  return result;
}

/** 直近の実行の状態をログに出す（スマホのエディタで選んで実行）。何も書き換えない。 */
function showPscubeCloudStatus() {
  const props = PropertiesService.getScriptProperties();
  const status = pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_STATUS)) || {};
  const failures = Object.values(pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_ERRORS)) || {});
  for (const line of pscubeCloudStatusLines(status, failures)) console.log(line);
  return {status: status, failures: failures};
}

function pscubeCloudRun() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return {busy: true, changed: false, pending: 0, failed: [], newFailures: []};
  const props = PropertiesService.getScriptProperties();
  const startedAt = Date.now();
  const previous = pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_STATUS)) || {};
  try {
    const id = props.getProperty('pscubeCloudFolder');
    if (!id) throw new PscubeCloudStop('config', '最初に setupPscubeCloudSync を実行してください。');
    const folder = DriveApp.getFolderById(id);
    if (folder.isTrashed()) throw new PscubeCloudStop('config', '共有フォルダがごみ箱にあります。');
    const backupFile = pscubeCloudUniqueFile(folder, PSCUBE_CLOUD_BACKUP);
    const viewerFile = pscubeCloudUniqueFile(folder, PSCUBE_CLOUD_VIEWER);
    const inputs = pscubeCloudListInputs([folder, DriveApp.getRootFolder()]);
    const liveIds = new Set(inputs.map(i => i.id));
    const failures = pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_ERRORS)) || {};
    // Driveから無くなった入力の失敗記録は消す。
    for (const key of Object.keys(failures)) if (!liveIds.has(key)) delete failures[key];
    const inputVersion = pscubeCloudDigest(inputs.map(i => [i.id, i.version]));
    const backupVersion = backupFile ? pscubeCloudVersion(backupFile) : '';
    const viewerVersion = viewerFile ? pscubeCloudVersion(viewerFile) : '';
    // 変化がなければ、巨大なJSONを毎回読むことも、書き直すこともしない。
    if (backupFile && viewerFile && props.getProperty('pscubeCloudInputs') === inputVersion &&
        props.getProperty('pscubeCloudBackup') === backupVersion && props.getProperty('pscubeCloudViewer') === viewerVersion) {
      const failed = Object.values(failures);
      const status = {...previous, at: new Date().toISOString(), result: failed.length ? 'unchanged-partial' : 'unchanged',
        message: '変更なし', inputs: inputs.length, failed: failed.length, elapsed_ms: Date.now() - startedAt,
        backup_bytes: backupFile.getSize(), viewer_bytes: viewerFile.getSize()};
      status.warnings = pscubeCloudWarnings(status);
      pscubeCloudSave(props, status, failures);
      console.log(failed.length ? '変更なし（取り込めないファイル ' + failed.length + '件は、更新されたら再試行します）' : '変更なし');
      return {changed: false, pending: 0, failed: failed.map(f => f.name), newFailures: [], status: status};
    }
    let data;
    try {
      data = backupFile ? pscubeCloudRead(backupFile, backupFile.getSize()) : {...emptyData(), rack_captures: []};
    } catch (error) {
      // 統合済みバックアップは入力ではない。壊れていたら上書きせずに止める（入力の不正とは分けて知らせる）。
      throw new PscubeCloudStop('backup', PSCUBE_CLOUD_BACKUP + ' を読めません（' + error.message + '）。上書きせずに止めました。' +
        '共有フォルダから外す（名前を変える）と、次の実行で入力から作り直します。');
    }
    const versions = {...(data.cloud_sync && data.cloud_sync.inputs || {})};
    // 取り込み済みの版・取り込めなかった同じ版は読まない（直したり更新したりすると版が変わり、再試行する）。
    const pending = inputs.filter(i => versions[i.id] !== i.version && !(failures[i.id] && failures[i.id].version === i.version));
    if (!backupFile && !inputs.length) {
      throw new PscubeCloudStop('config', '共有フォルダとマイドライブ直下にAndroidまたはPCのP’s CUBEバックアップがありません。先にDriveへ保存してください。');
    }
    const selected = [], newFailures = [], changedWhileReading = [];
    let attempted = 0, readBytes = 0;
    for (const input of pending.slice(0, PSCUBE_CLOUD_BATCH)) {
      // Googleの実行時間内に書き出しまで終えられるよう、大きい入力は次回へ分ける。
      if (attempted && (Date.now() - startedAt > PSCUBE_CLOUD_TIME_BUDGET_MS || readBytes + input.size > 64 * 1024 * 1024)) break;
      attempted++;
      readBytes += input.size;
      let merged;
      try {
        merged = pscubeCloudMerge(data, pscubeCloudRead(input.file, input.size));
      } catch (error) {
        // 入力1つ分だけ取り消す。元ファイルは消さない・移さない・書き換えない。
        const failure = {name: input.name, reason: String(error.message || error).slice(0, 120), version: input.version,
          checked_at: new Date().toISOString(), size: input.size};
        if (!failures[input.id] || failures[input.id].version !== input.version) newFailures.push(failure);
        failures[input.id] = failure;
        continue;
      }
      // 読み込み中の変更（アップロード途中など）は、この回は取り込まず次回やり直す（失敗とはしない）。
      if (input.version !== pscubeCloudVersion(input.file)) { changedWhileReading.push(input.name); continue; }
      data = merged;
      versions[input.id] = input.version;
      delete failures[input.id];
      selected.push(input);
    }
    const remaining = pending.length - selected.length - (attempted - selected.length - changedWhileReading.length);
    if (!backupFile && !selected.length) {
      pscubeCloudSave(props, {...previous, at: new Date().toISOString(), result: 'error', message: '取り込めるバックアップがありません'}, failures);
      throw new PscubeCloudStop('config', '取り込めるP’s CUBEバックアップがありません：' +
        (Object.values(failures).map(f => f.name + '（' + f.reason + '）').join('、') || 'Driveへの保存を待っています'));
    }
    // 過去に処理した入力がDriveから移動・削除されても、統合済みの台は消さない。
    for (const key of Object.keys(versions)) if (!liveIds.has(key)) delete versions[key];
    const writeBackup = Boolean(selected.length) || !backupFile;
    // 閲覧用は、新しい記録があるとき・無いとき・PCなどが書き直したとき・前回の閲覧用の更新が失敗して全期間だけ
    // 新しくなっているとき（確定した版と違う）に作り直す。
    const writeViewer = writeBackup || !viewerFile || props.getProperty('pscubeCloudViewer') !== viewerVersion ||
      props.getProperty('pscubeCloudBackup') !== backupVersion;
    const exportedAt = new Date().toISOString();
    const backup = {...data, kind: 'backup', source: 'cloud', exported_at: exportedAt, cloud_sync: {version: 1, inputs: versions}};
    const viewer = pscubeCloudViewer(backup, exportedAt);
    const backupText = writeBackup ? JSON.stringify(backup) : null, viewerText = writeViewer ? JSON.stringify(viewer) : null;
    const backupBytes = backupText ? pscubeCloudCheckSize(backupText) : backupFile.getSize();
    const viewerBytes = viewerText ? pscubeCloudCheckSize(viewerText) : viewerFile.getSize();
    // 入力の失敗は、出力に失敗しても残す（同じ版を何度も読まない）。
    pscubeCloudSave(props, null, failures);
    let savedBackup = backupFile, savedViewer = viewerFile;
    // バックアップを先に確定。閲覧用の更新が失敗しても次回このバックアップから復旧できる。
    if (writeBackup) savedBackup = pscubeCloudWrite(folder, backupFile, PSCUBE_CLOUD_BACKUP, backupText);
    // PCが古い閲覧用ファイルを書き直した場合も、統合済みの内容から再生成する。
    if (writeViewer) savedViewer = pscubeCloudWrite(folder, viewerFile, PSCUBE_CLOUD_VIEWER, viewerText);
    props.setProperties({pscubeCloudBackup: pscubeCloudVersion(savedBackup), pscubeCloudViewer: pscubeCloudVersion(savedViewer)});
    // 取り込めなかった入力は版ごと記録済みなので、残りが無ければチェックポイントを確定する。未取り込みの入力（次回分・
    // 読み込み中に変わった入力）が残る間は確定しない。
    if (!remaining) props.setProperty('pscubeCloudInputs', inputVersion);
    else props.deleteProperty('pscubeCloudInputs');
    const failed = Object.values(failures);
    const status = {at: new Date().toISOString(), result: failed.length ? 'partial' : 'ok',
      message: selected.length ? selected.length + 'ファイルを取り込み' : '閲覧用を作り直し',
      processed: selected.length, failed: failed.length, new_failures: newFailures.length, remaining: remaining,
      changed_while_reading: changedWhileReading.length, inputs: inputs.length,
      records: backup.records.length, viewer_records: viewer.records.length,
      backup_bytes: backupBytes, viewer_bytes: viewerBytes, elapsed_ms: Date.now() - startedAt};
    status.warnings = pscubeCloudWarnings(status);
    pscubeCloudSave(props, status, failures);
    for (const line of pscubeCloudStatusLines(status, failed)) console.log(line);
    return {changed: true, records: backup.records.length, viewerRecords: viewer.records.length, pending: remaining,
      failed: failed.map(f => f.name), newFailures: newFailures, status: status};
  } catch (error) {
    // 同期そのものを止めた失敗は、入力の失敗と分けて状態に残す（既存の出力は書き換えていない）。
    // 想定した停止（設定・統合済みバックアップ・出力）と、Drive側の予期しない例外など（other）を分ける。
    const kind = error instanceof PscubeCloudStop ? error.kind : 'other';
    const status = {...previous, at: new Date().toISOString(), result: 'error', stop: kind, message: String(error.message || error).slice(0, 300)};
    try { props.setProperty(PSCUBE_CLOUD_STATUS, JSON.stringify(status)); } catch (_) { /* 状態を残せなくても元のエラーを返す */ }
    throw error;
  } finally { lock.releaseLock(); }
}

/** 入力の候補。ID・名前・更新時刻・サイズを一度だけ読み、以降（並べ替え・版の比較）でDriveへ問い合わせない。 */
function pscubeCloudListInputs(folders) {
  const byId = new Map(), seen = new Set();
  for (const folder of folders) {
    if (seen.has(folder.getId())) continue;
    seen.add(folder.getId());
    // Drive側で名前とごみ箱を絞る。マイドライブにある無関係のファイルは列挙・読取しない。
    // Folder.searchFiles はDrive API v2形式の title を使う。
    const files = folder.searchFiles("trashed = false and title contains 'pscube-backup-'");
    while (files.hasNext()) {
      const file = files.next(), name = file.getName();
      if (!/^pscube-backup-(?:auto|(?:android|pc)-\d{8}-\d{6})\.json$/.test(name)) continue;
      const id = file.getId();
      if (byId.has(id)) continue;
      const updated = file.getLastUpdated().getTime(), size = file.getSize();
      byId.set(id, {file: file, id: id, name: name, updated: updated, size: size, version: updated + '-' + size});
    }
  }
  return [...byId.values()].sort((a, b) => a.updated - b.updated || a.id.localeCompare(b.id));
}

/** 上限に近づいたときの知らせ（全期間・閲覧用の容量と件数、処理時間、入力の数）。 */
function pscubeCloudWarnings(s) {
  const out = [];
  const share = (value, limit) => (value || 0) / limit;
  const mb = n => (n / 1048576).toFixed(1) + 'MB';
  const check = (value, limit, label, unit) => {
    const r = share(value, limit);
    if (r >= PSCUBE_CLOUD_ALERT) out.push(label + 'が上限の' + Math.round(r * 100) + '%（' + unit(value) + '）。まもなく上限です。分割方式への切り替えを相談してください。');
    else if (r >= PSCUBE_CLOUD_WARN) out.push(label + 'が上限の' + Math.round(r * 100) + '%（' + unit(value) + '）。分割方式の検討を始める目安です。');
  };
  check(s.backup_bytes, PSCUBE_CLOUD_MAX_BYTES, '全期間バックアップの容量', mb);
  check(s.viewer_bytes, PSCUBE_CLOUD_MAX_BYTES, '閲覧用の容量', mb);
  check(s.records, PSCUBE_CLOUD_RECORD_LIMIT, '全期間の件数', n => n + '件');
  check(s.viewer_records, PSCUBE_CLOUD_VIEWER_LIMIT, '閲覧用の件数', n => n + '件');
  if ((s.elapsed_ms || 0) >= 120000) out.push('処理に' + Math.round(s.elapsed_ms / 1000) + '秒かかりました（Googleの上限は6分）。');
  if ((s.inputs || 0) >= 300) out.push('読み込み対象のバックアップが' + s.inputs + '個あります（毎回の確認が増えます。古いファイルの整理を検討してください）。');
  return out;
}

function pscubeCloudStatusLines(status, failures) {
  const label = {ok: '正常に完了', partial: '一部失敗（ほかは反映済み）', unchanged: '変更なし',
    'unchanged-partial': '変更なし（取り込めないファイルあり）', error: '停止（既存の出力はそのまま）'}[status.result] || 'まだ実行していません';
  const lines = ['状態：' + label + (status.at ? '（' + status.at + '）' : '') + (status.message ? '・' + status.message : '')];
  if (status.records != null) {
    lines.push('全期間 ' + status.records + '件・' + ((status.backup_bytes || 0) / 1048576).toFixed(1) + 'MB／閲覧用 ' +
      status.viewer_records + '件・' + ((status.viewer_bytes || 0) / 1048576).toFixed(1) + 'MB（上限48MB）');
  }
  if (status.remaining) lines.push('次回に回したファイル：' + status.remaining);
  for (const f of failures) lines.push('取り込めないファイル：' + f.name + '（' + f.reason + '、確認 ' + f.checked_at + '）');
  for (const w of status.warnings || []) lines.push('注意：' + w);
  return lines;
}

function pscubeCloudSave(props, status, failures) {
  // プロパティ1つの上限（約9KB）に収める（理由は120字まで・10件。日本語は1字3バイト）。新しく確認したものを残す。
  // 外れた古い失敗は記録から消えるが、その入力は取り込み済みにしないので、次の実行で読み直して改めて記録する。
  const list = Object.entries(failures).sort((a, b) => String(b[1].checked_at).localeCompare(String(a[1].checked_at))).slice(0, 10);
  props.setProperty(PSCUBE_CLOUD_ERRORS, JSON.stringify(Object.fromEntries(list)));
  if (status) props.setProperty(PSCUBE_CLOUD_STATUS, JSON.stringify(status));
}
function pscubeCloudParse(text) { try { return text ? JSON.parse(text) : null; } catch (_) { return null; } }

function pscubeCloudUniqueFile(folder, name) {
  const files = folder.getFilesByName(name), found = [];
  while (files.hasNext()) { const file = files.next(); if (!file.isTrashed()) found.push(file); }
  if (found.length > 1) throw new PscubeCloudStop('config', name + ' が共有フォルダに複数あります。重複を解消してから実行してください。');
  return found[0] || null;
}
function pscubeCloudVersion(file) { return file.getLastUpdated().getTime() + '-' + file.getSize(); }
function pscubeCloudDigest(value) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, JSON.stringify(value))
    .map(b => ('0' + ((b + 256) % 256).toString(16)).slice(-2)).join('');
}
function pscubeCloudRead(file, size) {
  if (size > PSCUBE_CLOUD_MAX_BYTES) throw new Error('ファイルが48MiBを超えています。記録は変更していません。');
  const raw = JSON.parse(file.getBlob().getDataAsString('UTF-8').replace(/^﻿/, ''));
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
  if (records.length > PSCUBE_CLOUD_VIEWER_LIMIT) throw new PscubeCloudStop('output', '直近31日の記録が閲覧ページの上限10万件を超えています。');
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
/** UTF-8のバイト数（getBytes() の巨大な数値配列を作らずに数える）。48MiBを超えたら出力しないで止める。 */
function pscubeCloudCheckSize(text) {
  let size = 0;
  for (const char of text) { const n = char.codePointAt(0); size += n < 128 ? 1 : n < 2048 ? 2 : n < 65536 ? 3 : 4; }
  if (size > PSCUBE_CLOUD_MAX_BYTES) throw new PscubeCloudStop('output', '統合ファイルが48MiBを超えています。既存の出力はそのままです。分割方式への切り替えが必要です。');
  return size;
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
    throw new PscubeCloudStop('output', name + ' の更新に失敗しました（HTTP ' + response.getResponseCode() + '）。次の自動実行でやり直します。');
  }
  return DriveApp.getFileById(file.getId());
}

const FORMAT = 'pscube-viewer';
const emptyData = () => ({ format: FORMAT, version: 1, machines: [], records: [] });
const fail = message => { throw new Error(message); };
const integer = x => Number.isSafeInteger(x) && x >= 0;
const machineKey = r => JSON.stringify([r.store, r.rate, r.machine]);
const recordKey = r => JSON.stringify([r.store, r.rate, r.machine, r.rack, r.day]);
function validDay(day) {
  return typeof day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(day) &&
    Number.isFinite(Date.parse(day)) && new Date(day).toISOString().slice(0, 10) === day;
}

function siteUrl(raw, base) {
  const u = new URL(raw, base);
  if (u.origin !== 'https://www.pscube.jp' || u.username || u.password ||
      !/^\/dedamajyoho-P-townDMMpachi\/c\d+\/cgi-bin\/nc-v(?:03-001|05-011|06-001)\.php$/.test(u.pathname)) {
    fail('対象のP’s CUBEページではありません。');
  }
  return u;
}
function storeOf(url) { return url.pathname.match(/\/(c\d+)\//)[1]; }
function sameStore(raw, store) {
  const u = siteUrl(raw);
  if (storeOf(u) !== store) fail('店舗が異なるリンクが含まれています。');
  return u;
}

const dateEventKey = e => JSON.stringify([e.store, e.rate, e.day]);
/** イベント名の最大文字数（メルヘンのイベント名と同じ60文字）。 */
const DATE_EVENT_MAX = 60;
/** 末尾イベの印（以前の形）を読み替えるイベント名。 */
const SUFFIX_EVENT_NAME = '末尾イベ';
const eventTime = v => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const eventScope = e => e && typeof e.store === 'string' && /^c\d+$/.test(e.store) &&
  typeof e.rate === 'string' && /^\d+(?:\.\d+)?$/.test(e.rate) && validDay(e.day);
/** イベント名を整える。空・60文字超・改行などの制御文字は使えない（null は「イベントなし」）。 */
function cleanEventName(name) {
  if (name == null) return null;
  if (typeof name !== 'string') fail('イベント名が不正です。');
  const text = name.trim();
  if (!text) return null;
  if (text.length > DATE_EVENT_MAX || /[\u0000-\u001f\u007f]/.test(text)) fail(`イベント名は1〜${DATE_EVENT_MAX}文字で入力してください。`);
  return text;
}
/** 同じ店舗・貸玉・日付は、更新時刻が新しい方（同じなら後から来た方）を残す。 */
function mergeDateEvents(stored = [], incoming = []) {
  const events = new Map(stored.map(e => [dateEventKey(e), e]));
  for (const e of incoming) {
    const previous = events.get(dateEventKey(e));
    if (!previous || Date.parse(e.updated_at) >= Date.parse(previous.updated_at)) events.set(dateEventKey(e), e);
  }
  return [...events.values()];
}
/**
 * 日付ごとのイベント名（自由記入、2026-10-06）。{store, rate, day, name, updated_at}。name が null の
 * 記録は「イベントを消した」印で、古いバックアップを読んでも消したイベントが戻らないよう残す。
 * 以前の末尾イベの印（suffix_events、enabled）は「末尾イベ」という名前（外した印は null）に読み替える。
 */
function validateDateEvents(raw, legacySuffix) {
  const read = (list, convert, what) => {
    if (list == null) return [];
    if (!Array.isArray(list) || list.length > 100000) fail(`${what}が不正です。`);
    const result = list.map(e => {
      if (!eventScope(e) || !eventTime(e.updated_at)) fail(`${what}が不正です。`);
      return {store:e.store, rate:e.rate, day:e.day, name:convert(e), updated_at:e.updated_at};
    });
    if (new Set(result.map(dateEventKey)).size !== result.length) fail(`${what}が重複しています。`);
    return result;
  };
  const legacy = read(legacySuffix, e => {
    if (typeof e.enabled !== 'boolean') fail('末尾イベの印が不正です。');
    return e.enabled ? SUFFIX_EVENT_NAME : null;
  }, '末尾イベの印');
  const events = read(raw, e => cleanEventName(e.name), 'イベント名');
  return mergeDateEvents(legacy, events);
}
/** 今までに付けたイベント名（新しく使った順、重複なし）。入力欄の候補に使う。 */
function dateEventNames(events = []) {
  const latest = new Map();
  for (const e of events) {
    if (e.name == null) continue;
    const time = Date.parse(e.updated_at);
    if (!latest.has(e.name) || time > latest.get(e.name)) latest.set(e.name, time);
  }
  return [...latest].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ja')).map(([name]) => name);
}

function validateData(raw) {
  if (raw?.format !== FORMAT || raw.version !== 1 || !Array.isArray(raw.machines) || !Array.isArray(raw.records) || raw.records.length > 200000 || raw.machines.length > 10000) fail('P’s CUBEの保存ファイルではありません。');
  const basic = r => {
    if (!r || !/^c\d+$/.test(r.store) || typeof r.rate !== 'string' || !/^\d+(?:\.\d+)?$/.test(r.rate) ||
        typeof r.machine !== 'string' || !r.machine.trim() || r.machine.length > 200) fail('店舗・貸玉・機種名が不正です。');
    return { store: r.store, rate: r.rate, machine: r.machine.trim() };
  };
  const machines = raw.machines.map(m => {
    const base = basic(m), url = sameStore(m.url, base.store);
    if (!url.pathname.endsWith('nc-v05-011.php') || url.searchParams.get('bai') !== base.rate ||
        (url.searchParams.has('cd_ps') && url.searchParams.get('cd_ps') !== '2') ||
        (m.expected_count !== null && (!integer(m.expected_count) || m.expected_count < 1 || m.expected_count > 5000))) fail('機種情報が不正です。');
    if (m.machine_type != null && !['normal', 'other'].includes(m.machine_type)) fail('機種タイプが不正です。');
    return { ...base, url: url.href, expected_count: m.expected_count, machine_type: m.machine_type ?? null };
  });
  const records = raw.records.map(r => {
    const base = basic(r), url = sameStore(r.detail_url, base.store);
    if (!integer(r.rack) || r.rack < 1 || !validDay(r.day) || !url.pathname.endsWith('nc-v06-001.php') ||
        url.searchParams.get('cd_dai') !== String(r.rack) || url.hash !== `#${r.day.replaceAll('-', '')}`) fail('台番号・営業日・リンクが一致しません。');
    for (const k of ['bb', 'rb', 'at_art', 'games', 'my']) if (!integer(r[k])) fail('台の数値が不正です。');
    if (r.net_medals != null && (!Number.isSafeInteger(r.net_medals) || Math.abs(r.net_medals) > 1000000)) fail('差枚の数値が不正です。');
    let graph = null;
    if (r.graph != null) {
      const g = r.graph;
      if (!['overview', 'daily'].includes(g.kind) || !Number.isFinite(g.zero_y) || !Array.isArray(g.points) || g.points.length < 2 || g.points.length > 50000 ||
          g.points.some((p, i) => !Array.isArray(p) || p.length !== 2 || p.some(v => !Number.isFinite(v) || Math.abs(v) > 1e7) || (i && p[0] < g.points[i - 1][0]))) fail('保存グラフが不正です。');
      graph = { kind: g.kind, zero_y: g.zero_y, points: g.points.map(p => [...p]) };
    }
    if (r.observed_at != null && (typeof r.observed_at !== 'string' || !Number.isFinite(Date.parse(r.observed_at)))) fail('更新時刻が不正です。');
    return { ...base, rack: r.rack, day: r.day, bb: r.bb, rb: r.rb, at_art: r.at_art, games: r.games, my: r.my,
      detail_url: url.href, observed_at: r.observed_at ?? null, graph,
      ...(r.net_medals == null ? {} : {net_medals: r.net_medals}) };
  });
  if (new Set(machines.map(machineKey)).size !== machines.length || new Set(records.map(recordKey)).size !== records.length) fail('同じ機種・台が重複しています。');
  const known = new Set(machines.map(machineKey));
  if (records.some(r => !known.has(machineKey(r)))) fail('台に対応する機種情報がありません。');
  const dateEvents = validateDateEvents(raw.date_events, raw.suffix_events);
  return { format: FORMAT, version: 1, machines, records,
    ...(dateEvents.length ? {date_events:dateEvents} : {}) };
}

function mergeData(stored, incoming) {
  const old = validateData(stored), fresh = validateData(incoming);
  const machines = new Map(old.machines.map(m => [machineKey(m), m]));
  for (const m of fresh.machines) {
    const previous = machines.get(machineKey(m));
    machines.set(machineKey(m), { ...m, expected_count: m.expected_count ?? previous?.expected_count ?? null,
      machine_type: m.machine_type ?? previous?.machine_type ?? null });
  }
  const records = new Map(old.records.map(r => [recordKey(r), r]));
  for (const r of fresh.records) {
    const key = recordKey(r), previous = records.get(key);
    if (!previous) { records.set(key, r); continue; }
    const sameNumbers = ['bb', 'rb', 'at_art', 'games', 'my'].every(k => previous[k] === r[k]);
    const oldTime = Date.parse(previous.observed_at), newTime = Date.parse(r.observed_at);
    const older = Number.isFinite(oldTime) && Number.isFinite(newTime)
      ? newTime < oldTime : r.games < previous.games;
    if (older && !sameNumbers) continue;
    const preferred = older ? previous : r;
    let graph = preferred.graph;
    if (sameNumbers) {
      const alternate = older ? r : previous;
      graph = preferred.graph?.kind === 'daily' ? preferred.graph
        : alternate.graph?.kind === 'daily' ? alternate.graph : preferred.graph ?? alternate.graph;
    }
    const alternate = older ? r : previous;
    records.set(key, { ...preferred, graph,
      ...(sameNumbers && preferred.net_medals == null && alternate.net_medals != null ? {net_medals:alternate.net_medals} : {}) });
  }
  // Events are independent of machine/rack data. A removal is retained as a dated
  // null name so an older backup cannot bring the event back.
  return validateData({ ...emptyData(), machines: [...machines.values()], records: [...records.values()],
    date_events:mergeDateEvents(old.date_events, fresh.date_events) });
}
