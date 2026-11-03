// 生成元: tool/build_pscube_cloud_sync.mjs。共通パーサーの検証・統合規則を使用。
// 初回: 別のApps Scriptプロジェクトに全文を貼り、setupPscubeCloudSync を実行。
// 履歴モードの移行はVIEWER_HISTORY_SYNC.mdを参照。

// P’s CUBE PC不要同期。build_pscube_cloud_sync.mjs で検証済みの共通パーサーと結合する。
// 配布するのは pscube_cloud_sync.gs（別のApps Scriptプロジェクトに全文を貼る）。

// 通常は空欄のまま。共有フォルダが複数ある場合だけ、対象フォルダのIDを入れる。
const PSCUBE_FOLDER_ID = '';
const PSCUBE_CLOUD_BACKUP = 'pscube-backup-cloud.json';
const PSCUBE_CLOUD_VIEWER = 'pscube-viewer-drive.json';
// 両ページ用Apps Scriptの更新後にtrueへ変更（VIEWER_INCREMENTAL_SYNC.md）。
const PSCUBE_INCREMENTAL_VIEWER = false;
// 両ページと読み取りGSの更新後にtrue（VIEWER_HISTORY_SYNC.md）。
const PSCUBE_HISTORY_VIEWER = false;
const PSCUBE_CLOUD_BATCH = 10;
const PSCUBE_CLOUD_MAX_BYTES = 48 * 1024 * 1024;
const PSCUBE_CLOUD_HANDLER = 'syncPscubeCloud';
// 上限（共通パーサーの全期間20万件・閲覧ページの10万件）と、上限に近づいたと知らせる割合（2026-10-13）。
const PSCUBE_CLOUD_RECORD_LIMIT = 200000;
const PSCUBE_CLOUD_VIEWER_LIMIT = 100000;
const PSCUBE_CLOUD_WARN = 0.6, PSCUBE_CLOUD_ALERT = 0.8;
// 1回の実行時間の目安（Googleの上限は6分）。これを超えたら残りは次回。
const PSCUBE_CLOUD_TIME_BUDGET_MS = 180000;
// 取り込めなかった入力（ファイルID→名前・理由・版・確認日時。新しい10件）と、直近の実行の状態。スクリプトのプロパティに置く。
const PSCUBE_CLOUD_ERRORS = 'pscubeCloudErrors';
const PSCUBE_CLOUD_STATUS = 'pscubeCloudStatus';
// 取り込めなかった入力すべての版（ファイルID→版）。理由つきの記録（10件）から外れた入力も、版が変わるまで読み直さず、
// 毎回「新しい失敗」として知らせないため（2026-10-13 再発防止）。1件約60バイトで、プロパティ1つ（約9KB）に120件まで。
const PSCUBE_CLOUD_FAILED = 'pscubeCloudFailed';
const PSCUBE_CLOUD_FAILED_MAX = 120;
// 取り込みの規則の版。規則を直して貼り替えた最初の実行で、前に取り込めなかった入力をもう一度読む
// （2026-10-18、アナスロの出典リンクを拒んでPCの閲覧用ファイルが処理されないままだった。版が同じだと再試行されない）。
const PSCUBE_CLOUD_RULES = '2026-10-24-capture-health-browser';
// 書き出しの一時的な失敗（429・5xx・通信の例外）は、同じ実行の中でこの回数まで少し待って試す（1秒・2秒）。
const PSCUBE_CLOUD_WRITE_TRIES = 3;

/** Driveの一時的な障害（読み出しの例外）。入力の不正とは分け、失敗として記録せずに次の実行でやり直す。 */
class PscubeCloudTransient extends Error {}

// Google Apps ScriptにはブラウザのURLクラスがないため、共通パーサーが使う部分を実装する。
// P’s CUBEのページと、アナスロ履歴の出典（`validateAnasloRecord` が見る ana-slo.com）だけを読む。
// 出典を拒むと、アナスロの記録を含むPCの閲覧用ファイル全体が取り込めなくなる（2026-10-18、10/17以降が共有に出なかった）。
class PscubeCloudUrl {
  constructor(raw) {
    if (typeof raw !== 'string') throw new Error('P’s CUBEのリンクが不正です。');
    const anaslo = raw.match(/^https:\/\/ana-slo\.com(\/[^?#\s]*)(?:\?([^#]*))?(#.*)?$/);
    const match = anaslo || raw.match(/^https:\/\/www\.pscube\.jp(\/dedamajyoho-P-townDMMpachi\/c\d+\/cgi-bin\/nc-v(?:03-001|05-011|06-001)\.php)(?:\?([^#]*))?(#.*)?$/);
    if (!match) throw new Error('P’s CUBEのリンクが不正です。');
    this.origin = anaslo ? 'https://ana-slo.com' : 'https://www.pscube.jp';
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
  for (const line of pscubeCloudStatusLines(status, failures, Object.keys(pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_FAILED)) || {}).length)) {
    console.log(line);
  }
  return {status: status, failures: failures};
}

/** 日別ファイルが消えた・壊れた場合だけ実行。元バックアップは変更しない。 */
function rebuildPscubeViewerParts() {
  if (PSCUBE_HISTORY_VIEWER) PropertiesService.getScriptProperties().setProperty('pscubeHistoryRebuild', '1');
  PropertiesService.getScriptProperties().deleteProperty('pscubeCloudInputs');
  return syncPscubeCloud();
}

function pscubeCloudRun() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return {busy: true, changed: false, pending: 0, failed: [], newFailures: []};
  const props = PropertiesService.getScriptProperties();
  const startedAt = Date.now();
  const previous = pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_STATUS)) || {};
  if (props.getProperty('pscubeCloudRules') !== PSCUBE_CLOUD_RULES) {
    // 規則が変わったら、取り込めなかった版の記録と「変更なし」の目印を捨て、全入力をもう一度確かめる。
    for (const key of [PSCUBE_CLOUD_FAILED, PSCUBE_CLOUD_ERRORS, 'pscubeCloudInputs']) props.deleteProperty(key);
    props.setProperty('pscubeCloudRules', PSCUBE_CLOUD_RULES);
  }
  try {
    const id = props.getProperty('pscubeCloudFolder');
    if (!id) throw new PscubeCloudStop('config', '最初に setupPscubeCloudSync を実行してください。');
    const folder = DriveApp.getFolderById(id);
    if (folder.isTrashed()) throw new PscubeCloudStop('config', '共有フォルダがごみ箱にあります。');
    const backupFile = pscubeCloudUniqueFile(folder, PSCUBE_CLOUD_BACKUP);
    const viewerFile = pscubeCloudUniqueFile(folder, PSCUBE_CLOUD_VIEWER);
    if (PSCUBE_HISTORY_VIEWER) return vhPscube(folder, viewerFile, props, startedAt);
    const inputs = pscubeCloudListInputs([folder, DriveApp.getRootFolder()]);
    const liveIds = new Set(inputs.map(i => i.id));
    const failures = pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_ERRORS)) || {};
    const failedVersions = pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_FAILED)) || {};
    // 前の版の記録（理由つきだけ）からも版を引き継ぐ。
    for (const [key, f] of Object.entries(failures)) if (!failedVersions[key]) failedVersions[key] = f.version;
    // Driveから無くなった入力の失敗記録は消す。
    for (const key of Object.keys(failures)) if (!liveIds.has(key)) delete failures[key];
    for (const key of Object.keys(failedVersions)) if (!liveIds.has(key)) delete failedVersions[key];
    const inputVersion = pscubeCloudDigest(inputs.map(i => [i.id, i.version]));
    const backupVersion = backupFile ? pscubeCloudVersion(backupFile) : '';
    const viewerVersion = viewerFile ? pscubeCloudVersion(viewerFile) : '';
    const partsVersion = PSCUBE_INCREMENTAL_VIEWER ? vpCheckpoint(folder, 'pscube', viewerFile) : 'legacy';
    // 変化がなければ、巨大なJSONを毎回読むことも、書き直すこともしない。
    if (backupFile && viewerFile && props.getProperty('pscubeCloudInputs') === inputVersion &&
        props.getProperty('pscubeCloudBackup') === backupVersion && props.getProperty('pscubeCloudViewer') === viewerVersion && props.getProperty('pscubeCloudParts') === partsVersion) {
      const failed = Object.values(failures), failedCount = Object.keys(failedVersions).length;
      if (PSCUBE_INCREMENTAL_VIEWER) vpMaintain(folder, 'pscube', props);
      const status = {...previous, at: new Date().toISOString(), result: failedCount ? 'unchanged-partial' : 'unchanged',
        message: '変更なし', inputs: inputs.length, failed: failedCount, transient: 0, elapsed_ms: Date.now() - startedAt,
        backup_bytes: backupFile.getSize(), viewer_bytes: viewerFile.getSize()};
      status.warnings = pscubeCloudWarnings(status);
      pscubeCloudSave(props, status, failures, failedVersions);
      console.log(failedCount ? '変更なし（取り込めないファイル ' + failedCount + '件は、更新されたら再試行します）' : '変更なし');
      return {changed: false, pending: 0, failed: failed.map(f => f.name), newFailures: [], status: status};
    }
    let data;
    try {
      data = backupFile ? pscubeCloudRead(backupFile, backupFile.getSize()) : {...emptyData(), rack_captures: []};
    } catch (error) {
      // 読み出しの一時的な障害は、壊れているとは言わずに止め、次の実行でやり直す（何も書かない）。
      if (error instanceof PscubeCloudTransient) {
        throw new PscubeCloudStop('transient', PSCUBE_CLOUD_BACKUP + ' をDriveから読めませんでした（' + error.message +
          '）。一時的な障害とみて、次の自動実行でやり直します。');
      }
      // 統合済みバックアップは入力ではない。壊れていたら上書きせずに止める（入力の不正とは分けて知らせる）。
      throw new PscubeCloudStop('backup', PSCUBE_CLOUD_BACKUP + ' を読めません（' + error.message + '）。上書きせずに止めました。' +
        '共有フォルダから外す（名前を変える）と、次の実行で入力から作り直します。');
    }
    const versions = {...(data.cloud_sync && data.cloud_sync.inputs || {})};
    const browserBaseline = pscubeCloudDigest(inputs.filter(i => !i.browser).map(i => [i.id,i.version]));
    if (data.cloud_sync?.browser_baseline !== browserBaseline) {
      for (const input of inputs.filter(i => i.browser)) delete versions[input.id];
    }
    // 取り込み済みの版・取り込めなかった同じ版は読まない（直したり更新したりすると版が変わり、再試行する）。
    const pending = inputs.filter(i => versions[i.id] !== i.version && failedVersions[i.id] !== i.version);
    if (!backupFile && !inputs.length) {
      throw new PscubeCloudStop('config', '共有フォルダとマイドライブ直下にAndroidまたはPCのP’s CUBEバックアップがありません。先にDriveへ保存してください。');
    }
    const selected = [], newFailures = [], changedWhileReading = [], transient = [];
    let attempted = 0, readBytes = 0, failedNow = 0;
    for (const input of pending.slice(0, PSCUBE_CLOUD_BATCH)) {
      // Googleの実行時間内に書き出しまで終えられるよう、大きい入力は次回へ分ける。
      if (attempted && (Date.now() - startedAt > PSCUBE_CLOUD_TIME_BUDGET_MS || readBytes + input.size > 64 * 1024 * 1024)) break;
      attempted++;
      readBytes += input.size;
      let merged;
      try {
        const incoming = pscubeCloudRead(input.file, input.size, input.browser ? 'browser' : null);
        merged = input.browser ? {...mergeNetSupplement(data,incoming,input.report || (input.report={})),rack_captures:data.rack_captures || []} : pscubeCloudMerge(data,incoming);
        merged={...merged,sync_status:vhSourceStatus(data,incoming,input)};
      } catch (error) {
        // Driveの一時的な障害で読めなかった入力は、壊れたファイルとして記録しない。この回は取り込まず、次の実行で
        // 同じ版のまま読み直す（2026-10-13 再発防止：以前は失敗として記録し、ファイルが更新されるまで読み直さなかった）。
        if (error instanceof PscubeCloudTransient) { transient.push(input.name); continue; }
        // 入力1つ分だけ取り消す。元ファイルは消さない・移さない・書き換えない。
        const failure = {name: input.name, reason: String(error.message || error).slice(0, 120), version: input.version,
          checked_at: new Date().toISOString(), size: input.size};
        if (failedVersions[input.id] !== input.version) newFailures.push(failure);
        failures[input.id] = failure;
        // 末尾へ入れ直す（上限で古い方から外すとき、新しく確認したものを残す）。
        delete failedVersions[input.id];
        failedVersions[input.id] = input.version;
        failedNow++;
        continue;
      }
      // 読み込み中の変更（アップロード途中など）は、この回は取り込まず次回やり直す（失敗とはしない）。
      if (input.version !== pscubeCloudVersion(input.file)) { changedWhileReading.push(input.name); continue; }
      data = merged;
      versions[input.id] = input.version;
      delete failures[input.id];
      delete failedVersions[input.id];
      selected.push(input);
    }
    // 未取り込みのまま次回へ残す入力：この回に試さなかったもの・読み込み中に変わったもの・一時的な障害で読めなかったもの。
    const remaining = pending.length - selected.length - failedNow;
    if (!backupFile && !selected.length) {
      pscubeCloudSave(props, {...previous, at: new Date().toISOString(), result: 'error', message: '取り込めるバックアップがありません'},
        failures, failedVersions);
      if (transient.length) {
        throw new PscubeCloudStop('transient', 'Driveから一時的に読めませんでした（' + transient.join('、') + '）。次の自動実行でやり直します。');
      }
      throw new PscubeCloudStop('config', '取り込めるP’s CUBEバックアップがありません：' +
        (Object.values(failures).map(f => f.name + '（' + f.reason + '）').join('、') || 'Driveへの保存を待っています'));
    }
    // 過去に処理した入力がDriveから移動・削除されても、統合済みの台は消さない。
    for (const key of Object.keys(versions)) if (!liveIds.has(key)) delete versions[key];
    const writeBackup = Boolean(selected.length) || !backupFile;
    // 閲覧用は、新しい記録があるとき・無いとき・PCなどが書き直したとき・前回の閲覧用の更新が失敗して全期間だけ
    // 新しくなっているとき（確定した版と違う）に作り直す。
    const writeViewer = writeBackup || !viewerFile || props.getProperty('pscubeCloudViewer') !== viewerVersion ||
      props.getProperty('pscubeCloudBackup') !== backupVersion || props.getProperty('pscubeCloudParts') !== partsVersion;
    const exportedAt = new Date().toISOString();
    const reports=selected.filter(i=>i.report).map(i=>i.report);
    const health=mergeSyncStatus(data.sync_status,{version:1,writes:[],processed_at:exportedAt,processor_release:SCRIPT_RELEASE,pending:remaining,failed_inputs:Object.keys(failedVersions).length,supplement_supported:true,
      ...(reports.length ? {supplement:{at:exportedAt,...Object.fromEntries(['applied','unmatched','mismatched','known'].map(k=>[k,reports.reduce((n,r)=>n+(r[k] || 0),0)]))}} : {})});
    const backup = {...data, kind: 'backup', source: 'cloud', exported_at: exportedAt,sync_status:health,
      cloud_sync: {version: 1, inputs: versions, browser_baseline:browserBaseline}};
    const viewer = pscubeCloudViewer(backup, exportedAt);
    const backupText = writeBackup ? JSON.stringify(backup) : null, viewerText = writeViewer ? JSON.stringify(viewer) : null;
    const backupBytes = backupText ? pscubeCloudCheckSize(backupText) : backupFile.getSize();
    const viewerBytes = viewerText ? pscubeCloudCheckSize(viewerText) : viewerFile.getSize();
    // 入力の失敗は、出力に失敗しても残す（同じ版を何度も読まない）。
    pscubeCloudSave(props, null, failures, failedVersions);
    let savedBackup = backupFile, savedViewer = viewerFile;
    // バックアップを先に確定。閲覧用の更新が失敗しても次回このバックアップから復旧できる。
    if (writeBackup) savedBackup = pscubeCloudWrite(folder, backupFile, PSCUBE_CLOUD_BACKUP, backupText);
    // PCが古い閲覧用ファイルを書き直した場合も、統合済みの内容から再生成する。
    let incremental = null;
    if (PSCUBE_INCREMENTAL_VIEWER) {
      // 初回の旧形式ファイルだけは作り、PC書き出しとの世代照合に使う。
      if (!savedViewer) savedViewer = pscubeCloudWrite(folder, null, PSCUBE_CLOUD_VIEWER, JSON.stringify(viewer));
      incremental = vpPublish(folder, savedViewer, 'pscube', viewer, pscubeCloudWrite, viewerFile ? viewerFile.getId() + ':' + viewerVersion : undefined);
    } else if (writeViewer) savedViewer = pscubeCloudWrite(folder, viewerFile, PSCUBE_CLOUD_VIEWER, viewerText);
    props.setProperty('pscubeCloudParts', PSCUBE_INCREMENTAL_VIEWER ? vpCheckpoint(folder, 'pscube', savedViewer) : 'legacy');
    if (PSCUBE_INCREMENTAL_VIEWER) vpMaintain(folder, 'pscube', props);
    props.setProperties({pscubeCloudBackup: pscubeCloudVersion(savedBackup), pscubeCloudViewer: pscubeCloudVersion(savedViewer)});
    // 取り込めなかった入力は版ごと記録済みなので、残りが無ければチェックポイントを確定する。未取り込みの入力（次回分・
    // 読み込み中に変わった入力・一時的な障害で読めなかった入力）が残る間は確定しない。
    if (!remaining) props.setProperty('pscubeCloudInputs', inputVersion);
    else props.deleteProperty('pscubeCloudInputs');
    const failed = Object.values(failures), failedCount = Object.keys(failedVersions).length;
    const status = {at: new Date().toISOString(), result: failedCount ? 'partial' : 'ok',
      message: (selected.length ? selected.length + 'ファイルを取り込み' : '閲覧用を作り直し') +
        (transient.length ? '・一時的に読めなかった' + transient.length + 'ファイルは次回' : ''),
      processed: selected.length, failed: failedCount, new_failures: newFailures.length, remaining: remaining,
      changed_while_reading: changedWhileReading.length, transient: transient.length, inputs: inputs.length,
      records: backup.records.length, viewer_records: viewer.records.length,
      incremental: incremental, backup_bytes: backupBytes, viewer_bytes: viewerBytes, elapsed_ms: Date.now() - startedAt};
    status.warnings = pscubeCloudWarnings(status);
    pscubeCloudSave(props, status, failures, failedVersions);
    for (const line of pscubeCloudStatusLines(status, failed, failedCount)) console.log(line);
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
    // スマホが自動取り込みの終わりに送る当日分 pscube-day-android-YYYY-MM-DD.json（自分用スクリプトの postPscubeDay が
    // 書く。中身はその日だけの普通の backup）も読む（2026-11-02 利用者「スクリプト追記をお願いします」。以前はPC版だけが
    // 読み、PCを開くまで閲覧ページ・共有カレンダーに出なかった）。
    const files = folder.searchFiles("trashed = false and (title contains 'pscube-backup-' or title contains 'pscube-day-android-')");
    while (files.hasNext()) {
      const file = files.next(), name = file.getName();
      if (!/^(?:pscube-backup-(?:auto|(?:android|pc|browser)-\d{8}-\d{6})|pscube-day-android-\d{4}-\d{2}-\d{2})\.json$/.test(name)) continue;
      const id = file.getId();
      if (byId.has(id)) continue;
      const updated = file.getLastUpdated().getTime(), size = file.getSize();
      byId.set(id, {file: file, id: id, name: name, updated: updated, size: size, version: updated + '-' + size,
        browser:name.startsWith('pscube-backup-browser-')});
    }
  }
  // 当日分も今までどおり古い順（機種タイプは後で処理した入力の指定を優先するため、順番は変えない）。
  return [...byId.values()].sort((a, b) => Number(a.browser)-Number(b.browser) || a.updated - b.updated || a.id.localeCompare(b.id));
}

/** 上限に近づいたときの知らせ（全期間・閲覧用の容量と件数、処理時間、入力の数）。 */
function pscubeCloudWarnings(s) {
  if (s.history) return [];
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

function pscubeCloudStatusLines(status, failures, failedCount = failures.length) {
  const label = {ok: '正常に完了', partial: '一部失敗（ほかは反映済み）', unchanged: '変更なし',
    'unchanged-partial': '変更なし（取り込めないファイルあり）', error: '停止（既存の出力はそのまま）'}[status.result] || 'まだ実行していません';
  const lines = ['状態：' + label + (status.at ? '（' + status.at + '）' : '') + (status.message ? '・' + status.message : '')];
  if (status.records != null) {
    lines.push('全期間 ' + status.records + '件・' + ((status.backup_bytes || 0) / 1048576).toFixed(1) + 'MB／閲覧用 ' +
      status.viewer_records + '件・' + ((status.viewer_bytes || 0) / 1048576).toFixed(1) + (status.history ? 'MB（日別履歴・合計48MiB制限なし）' : 'MB（上限48MB）'));
  }
  if (status.incremental) lines.push((['ok', 'partial'].includes(status.result) ? '今回' : '前回確定時') +
    'の差分出力：' + status.incremental.parts + 'パーツ・' + (status.incremental.bytes / 1024).toFixed(1) + 'KB');
  if (status.remaining) lines.push('次回に回したファイル：' + status.remaining);
  if (failedCount > failures.length) lines.push('取り込めないファイル：全部で' + failedCount + '件（理由は新しい' + failures.length + '件）');
  for (const f of failures) lines.push('取り込めないファイル：' + f.name + '（' + f.reason + '、確認 ' + f.checked_at + '）');
  for (const w of status.warnings || []) lines.push('注意：' + w);
  return lines;
}

function pscubeCloudSave(props, status, failures, failedVersions) {
  // プロパティ1つの上限（約9KB）に収める（理由は120字まで・10件。日本語は1字3バイト）。新しく確認したものを残す。
  // 理由つきの記録から外れた入力も、版は PSCUBE_CLOUD_FAILED に残すので、版が変わるまで読み直さない。
  const list = Object.entries(failures).sort((a, b) => String(b[1].checked_at).localeCompare(String(a[1].checked_at))).slice(0, 10);
  props.setProperty(PSCUBE_CLOUD_ERRORS, JSON.stringify(Object.fromEntries(list)));
  if (failedVersions) {
    // すべての失敗の版（新しく確認した順に末尾。上限を超えたら古い方から外す）。
    props.setProperty(PSCUBE_CLOUD_FAILED, JSON.stringify(Object.fromEntries(Object.entries(failedVersions).slice(-PSCUBE_CLOUD_FAILED_MAX))));
  }
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
function pscubeCloudRead(file, size, expectedSource) {
  if (size > PSCUBE_CLOUD_MAX_BYTES) throw new Error('ファイルが48MiBを超えています。記録は変更していません。');
  let text;
  // Driveからの読み出しの例外は一時的な障害（通信・Drive側）とみなし、中身の不正（下の解析・検査）と分ける。
  try { text = file.getBlob().getDataAsString('UTF-8'); }
  catch (error) { throw new PscubeCloudTransient(String(error && error.message || error).slice(0, 120)); }
  const raw = JSON.parse(text.replace(/^\uFEFF/, ''));
  if (expectedSource === 'browser' && (raw.source !== 'browser' || raw.kind !== 'backup')) throw new Error('ブラウザ補完用バックアップの形式が不正です。');
  if (raw.kind === 'viewer') throw new Error('軽量な閲覧用ファイルは全期間バックアップとして使えません。');
  const validated = validateData(raw);
  // バックアップは足し込み。閲覧用の完成日メタデータで保存済み原本を削除しない。
  const {history_days, history, ...data} = validated;
  if (data.records.length > PSCUBE_CLOUD_RECORD_LIMIT) throw new Error('入力バックアップの記録が20万件を超えています。期間を分けてください。');
  const keys = new Set(data.records.map(recordKey));
  const captures = raw.rack_captures == null ? data.records.filter(r => r.graph && r.graph.kind === 'daily').map(recordKey) : raw.rack_captures;
  if (!Array.isArray(captures) || captures.some(k => typeof k !== 'string' || !keys.has(k))) throw new Error('取り込み済みの印が不正です。');
  return {...data, source:raw.source, exported_at:raw.exported_at, rack_captures: [...new Set(captures)], ...(raw.cloud_sync ? {cloud_sync: raw.cloud_sync} : {})};
}
function pscubeCloudMerge(stored, incoming) {
  const merged = mergeData(stored, incoming);
  const records = new Map(merged.records.map(r => [recordKey(r), r]));
  const sameNumbers = (a, b) => !!b && ['bb', 'rb', 'at_art', 'games', 'my'].every(k => a[k] === b[k]);
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
  const sourceRecords=backup.records.map(r=>({...r,...(r.net_capture ? {net_capture:validateNetCapture(r.net_capture)} : {})}));
  trimNetProbes(sourceRecords);
  const latest = sourceRecords.reduce((day, r) => r.day > day ? r.day : day, '');
  const first = latest ? new Date(Date.parse(latest) - 30 * 86400000).toISOString().slice(0, 10) : '';
  const records = sourceRecords.filter(r => r.day >= first).map(r => ({...r, graph: pscubeCloudThinGraph(r.graph),
    ...(r.net_capture ? {net_capture:viewerNetCapture(r.net_capture)} : {})}));
  if (records.length > PSCUBE_CLOUD_VIEWER_LIMIT) throw new PscubeCloudStop('output', '直近31日の記録が閲覧ページの上限10万件を超えています。');
  return {format: FORMAT, version: 1, kind: 'viewer', source: 'cloud', exported_at: exportedAt,
    machines: backup.machines, records: records, ...(backup.date_events ? {date_events: backup.date_events} : {}),
    ...(backup.sync_status ? {sync_status:backup.sync_status} : {})};
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
  // 一時的な失敗（429・5xx・通信の例外）は少し待って試し直す（2026-10-13 再発防止：以前は1回の503で止めていた）。
  // 権限などの失敗（403など）は待っても直らないので、すぐ止めて次の自動実行に任せる。
  let last = '';
  for (let attempt = 1; attempt <= PSCUBE_CLOUD_WRITE_TRIES; attempt++) {
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
    if (!retry || attempt === PSCUBE_CLOUD_WRITE_TRIES) break;
    Utilities.sleep(1000 * attempt);
  }
  throw new PscubeCloudStop('output', name + ' の更新に失敗しました（' + last + '）。次の自動実行でやり直します。');
}

const APPLICATION_RELEASE = '541fd63e6aa4';
// 取得診断には固定の理由と数値だけを残す。認証値・HTML・自由文の応答は保存しない。
const NET_PROBE_MAX = 64 * 1024;
const NET_PROBE_BUDGET = 3 * 1024 * 1024;
const NET_PROBE_DAYS = 7;
const ND_STATUSES = new Set(['ok','empty','invalid','network','unavailable','unknown']);
const ND_REASONS = new Set(['ok','missing_series','empty','short_series','invalid_points','invalid_net','invalid_response','network','not_ready']);
const ND_OMITTED = new Set(['size','unsafe','expired','budget']);
const ND_NUMBERS = ['bb','rb','at_art','games','my'];
const ndError = () => { throw new Error('差枚の取得診断が不正です。'); };
const ndDay = s => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s) &&
  Number.isFinite(Date.parse(s)) && new Date(s).toISOString().slice(0,10) === s;
const ndScalar = v => v == null || (typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= 1e12) ||
  (typeof v === 'string' && v.length <= 32 && /^[-+\d.eE]*$/.test(v));

function ndProbe(raw) {
  if (!raw || raw.version !== 1 || !Number.isSafeInteger(raw.rack) || raw.rack < 1 ||
      typeof raw.day !== 'string' || !/^\d{8}$/.test(raw.day) || !ndDay(`${raw.day.slice(0,4)}-${raw.day.slice(4,6)}-${raw.day.slice(6)}`) ||
      !Array.isArray(raw.numbers) || raw.numbers.length < 1 || raw.numbers.length > 7 ||
      !Array.isArray(raw.graph?.datas?.g) || raw.graph.datas.g.length > 7 ||
      !Array.isArray(raw.graph.datas.p) || raw.graph.datas.p.length > 50000 ||
      !ndScalar(raw.graph.anjYUnit ?? 1)) ndError();
  const numbers = raw.numbers.map(r => {
    if (!r || !ndDay(r.day) || ND_NUMBERS.some(k => !Number.isSafeInteger(r[k]) || r[k] < 0)) ndError();
    return {day:r.day,...Object.fromEntries(ND_NUMBERS.map(k => [k,r[k]]))};
  });
  const fields = new Set();
  const g = raw.graph.datas.g.map(line => {
    if (!line || !ndScalar(line.YMD_biz) || !/^\d{8}$/.test(String(line.YMD_biz)) ||
        !/^out-\d{1,5}$/.test(line.xField ?? '') || !/^value-\d{1,5}$/.test(line.yField ?? '')) ndError();
    fields.add(line.xField); fields.add(line.yField);
    return {YMD_biz:line.YMD_biz,xField:line.xField,yField:line.yField};
  });
  const p = raw.graph.datas.p.map(point => {
    if (!point || typeof point !== 'object' || Array.isArray(point)) ndError();
    return Object.fromEntries([...fields].filter(k => Object.hasOwn(point,k)).map(k => {
      if (!ndScalar(point[k])) ndError();
      return [k,point[k]];
    }));
  });
  const probe = {version:1,rack:raw.rack,day:raw.day,numbers,graph:{anjYUnit:raw.graph.anjYUnit ?? 1,datas:{g,p}}};
  if (JSON.stringify(probe).length > NET_PROBE_MAX) throw new Error('診断用の元数値が上限を超えています。');
  return probe;
}

function makeNetProbe(raw, records) {
  try {
    if (Array.isArray(raw?.graph?.datas?.p) && !raw.graph.datas.p.length) return {};
    const probe=ndProbe({version:1,...raw,numbers:records.map(r => ({day:r.day,
      ...Object.fromEntries(ND_NUMBERS.map(k => [k,r[k]]))}))});
    // 他言語のJSON数値表記に少し余裕を残す。受け側の上限は64KiB。
    return JSON.stringify(probe).length>60*1024 ? {probe_omitted:"size"} : {probe};
  } catch (error) {
    return {probe_omitted:error.message.includes('上限') ? 'size' : 'unsafe'};
  }
}

function validateNetCapture(value) {
  if (value == null) return null;
  if (value.version !== 1 || !ND_STATUSES.has(value.status) || !ND_REASONS.has(value.reason) ||
      typeof value.checked_at !== 'string' || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value.checked_at) ||
      !Number.isFinite(Date.parse(value.checked_at))) ndError();
  const result = {version:1,status:value.status,reason:value.reason,checked_at:value.checked_at};
  if (value.http_status != null) {
    if (!Number.isSafeInteger(value.http_status) || value.http_status < 0 || value.http_status > 599) ndError();
    result.http_status = value.http_status;
  }
  if (value.probe_omitted != null) {
    if (!ND_OMITTED.has(value.probe_omitted)) ndError();
    result.probe_omitted = value.probe_omitted;
  }
  if (value.probe != null) result.probe = ndProbe(value.probe);
  if (value.probe_available != null) {
    if (typeof value.probe_available !== 'boolean') ndError();
    result.probe_available=value.probe_available;
  }
  return result;
}

function trimNetProbes(records, now = Date.now()) {
  let remaining = NET_PROBE_BUDGET;
  const samples = records.filter(r => r.net_capture?.probe)
    .sort((a,b) => Date.parse(b.net_capture.checked_at)-Date.parse(a.net_capture.checked_at));
  for (const r of samples) {
    const at = Date.parse(r.net_capture.checked_at), size = JSON.stringify(r.net_capture.probe).length;
    const omitted = at < now-NET_PROBE_DAYS*86400000 || at > now+300000 ? 'expired' : size > remaining ? 'budget' : null;
    if (omitted) {
      const {probe,...rest} = r.net_capture;
      delete rest.probe_available;
      r.net_capture = {...rest,probe_omitted:omitted};
    } else remaining -= size;
  }
  return records;
}

function mergeNetCapture(chosen, alternate, sameNumbers) {
  if (!sameNumbers) return chosen.net_capture;
  const a = chosen.net_capture, b = alternate.net_capture;
  return !a || (b && (Date.parse(b.checked_at) > Date.parse(a.checked_at) ||
    (b.checked_at===a.checked_at && b.probe && !a.probe))) ? b : a;
}

function viewerNetCapture(value) {
  const cap=validateNetCapture(value);if(!cap)return null;
  const {probe,probe_available,...rest}=cap;
  return {...rest,...((probe || probe_available!=null) ? {probe_available:!!probe || probe_available===true} : {})};
}

function netCaptureLabel(record) {
  if (Number.isSafeInteger(record.net_medals)) return record.net_medals === 0 ? '取得済み（0枚）' : '取得済み';
  if (record.source_site === 'anaslo') return '出典に差枚なし';
  const reason = record.net_capture?.reason;
  return ({missing_series:'日別の系列なし',empty:'元数値が空',short_series:'元数値の点が不足',
    invalid_points:'元数値の形式不正',invalid_net:'差枚の範囲不正',invalid_response:'応答の形式不正',
    network:'差枚の通信失敗',not_ready:'サイトの通信準備前'})[reason] || '未取得（理由未記録）';
}

function netHealth(records) {
  const known = records.filter(r => Number.isSafeInteger(r.net_medals));
  return {total:records.length,known:known.length,zero:known.filter(r => r.net_medals===0).length,
    missing:records.filter(r => !Number.isSafeInteger(r.net_medals)).map(r =>
      ({rack:r.rack,day:r.day,machine:r.machine,reason:netCaptureLabel(r),
        checked_at:r.net_capture?.checked_at ?? null,replayable:!!(r.net_capture?.probe || r.net_capture?.probe_available) &&
          Date.parse(r.net_capture.checked_at)>=Date.now()-NET_PROBE_DAYS*86400000 && Date.parse(r.net_capture.checked_at)<=Date.now()+300000}))};
}

const ndTime = value => typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const ndMillis = value => {const n=Date.parse(value || '');return Number.isFinite(n) ? n : -Infinity;};
function validateSyncStatus(raw) {
  if (raw == null) return null;
  if (raw.version !== 1 || !Array.isArray(raw.writes) || raw.writes.length > 3) throw new Error('更新状況の形式が不正です。');
  const writes = raw.writes.map(w => {
    if (!w || !['pc','android','browser'].includes(w.source) || !ndTime(w.at) ||
        !Array.isArray(w.stores) || w.stores.length > 100 || (w.drive_at != null && !ndTime(w.drive_at))) throw new Error('更新状況の形式が不正です。');
    return {source:w.source,at:w.at,...(w.drive_at ? {drive_at:w.drive_at} : {}),stores:w.stores.map(s => {
      if (!s || !/^[A-Za-z0-9_-]{1,80}$/.test(s.store ?? '') ||
          (s.rate != null && !/^\d+(?:\.\d+)?$/.test(s.rate)) || !ndDay(s.day) ||
          !Number.isSafeInteger(s.count) || s.count < 0) throw new Error('更新状況の店舗情報が不正です。');
      return {store:s.store,...(s.rate != null ? {rate:s.rate} : {}),day:s.day,count:s.count};
    })};
  });
  if (new Set(writes.map(w => w.source)).size !== writes.length || (raw.processed_at != null && !ndTime(raw.processed_at))) throw new Error('更新状況の形式が不正です。');
  const result={version:1,writes,...(typeof raw.processor_release==='string'&&/^[a-f0-9]{12}$/.test(raw.processor_release)?{processor_release:raw.processor_release}:{}),...(raw.processed_at ? {processed_at:raw.processed_at} : {})};
  for (const key of ['pending','failed_inputs']) if (raw[key]!=null) {
    if (!Number.isSafeInteger(raw[key]) || raw[key]<0 || raw[key]>1000000) throw new Error('更新状況の形式が不正です。');
    result[key]=raw[key];
  }
  if (raw.supplement!=null) {
    const s=raw.supplement;
    if (!ndTime(s.at) || ['applied','unmatched','mismatched','known'].some(k=>!Number.isSafeInteger(s[k]) || s[k]<0 || s[k]>1000000)) throw new Error('補完結果の形式が不正です。');
    result.supplement={at:s.at,...Object.fromEntries(['applied','unmatched','mismatched','known'].map(k=>[k,s[k]]))};
  }
  if (raw.supplement_supported!=null) {
    if (typeof raw.supplement_supported!=='boolean') throw new Error('更新状況の形式が不正です。');
    result.supplement_supported=raw.supplement_supported;
  }
  return result;
}

function makeSyncWrite(source, at, records, driveAt) {
  if (['pc-viewer','pc-deleted'].includes(source)) source='pc';
  if (!['pc','android','browser'].includes(source) || !ndTime(at)) return null;
  const stores = new Map();
  for (const r of records) {
    const store=r.store || 'nagamachiminami';
    if (!ndDay(r.day) || !/^[A-Za-z0-9_-]{1,80}$/.test(store)) continue;
    const key=JSON.stringify([store,r.rate ?? null]), old=stores.get(key);
    if (!old) stores.set(key,{store,...(r.rate != null ? {rate:r.rate} : {}),day:r.day,count:1});
    else if(r.day>old.day) {old.day=r.day;old.count=1;}
    else if(r.day===old.day) old.count++;
  }
  return validateSyncStatus({version:1,writes:[{source,at,...(ndTime(driveAt) ? {drive_at:driveAt} : {}),stores:[...stores.values()]}]});
}

function updateStatusLines(status, {exportedAt,loadedAt,checkedAt} = {}) {
  const value=validateSyncStatus(status);
  const when=s=>ndTime(s) ? new Date(s).toLocaleString('ja-JP') : '未確認';
  const storeName=s=>({nagamachiminami:'長町南',saiwaichou:'幸町'})[s.store] || `${/^c\d+$/.test(s.store) ? 'P’s CUBE' : s.store}${s.rate==null ? '' : '（'+s.rate+'スロ）'}`;
  const lines=(value?.writes || []).flatMap(w=>[
    `${({pc:'PC',android:'Android',browser:'iPhone・ブラウザ'})[w.source]}の書き出し：${when(w.at)}／Driveファイルの更新：${when(w.drive_at)}`,
    ...w.stores.map(s=>`この出力の最新日：${storeName(s)} ${s.day}・${s.count}台`)]);
  if (!lines.length) lines.push('元ファイルの書き出し：未確認');
  lines.push(`このページの版：${APPLICATION_RELEASE}`,`Google処理の版：${value?.processor_release || '未確認'}`);
  lines.push(`Google側の処理：${when(value?.processed_at)}`);
  if (value?.pending || value?.failed_inputs) lines.push(`Google側の処理待ち ${value.pending || 0}件・入力失敗 ${value.failed_inputs || 0}件`);
  lines.push(`閲覧データの書き出し：${when(exportedAt)}`,`この端末の読み込み：${when(loadedAt)}`);
  if (checkedAt) lines.push(`この端末で最新か確認：${when(checkedAt)}`);
  if (value?.supplement) {
    const s=value.supplement;
    lines.push(`スマホ補完：反映 ${s.applied}件・取得済み ${s.known}件・数値不一致 ${s.mismatched}件・元記録なし ${s.unmatched}件（${when(s.at)}）`);
  }
  return lines;
}

function mergeSyncStatus(...items) {
  const writes = new Map(); let processed_at,meta={},supplement;
  for (const item of items) {
    const status=validateSyncStatus(item);if(!status)continue;
    for (const w of status.writes) {
      const old=writes.get(w.source);
      if (!old || Date.parse(w.at)>Date.parse(old.at) || (Date.parse(w.at)===Date.parse(old.at) &&
          ndMillis(w.drive_at)>ndMillis(old.drive_at))) writes.set(w.source,w);
    }
    if (status.processed_at && (!processed_at || Date.parse(status.processed_at)>=Date.parse(processed_at))) {
      processed_at=status.processed_at;
      meta=Object.fromEntries(['pending','failed_inputs','supplement_supported','processor_release'].filter(k=>status[k]!=null).map(k=>[k,status[k]]));
    }
    if (status.supplement && (!supplement || Date.parse(status.supplement.at)>=Date.parse(supplement.at))) supplement=status.supplement;
  }
  return writes.size || processed_at || supplement ? {version:1,writes:[...writes.values()],...(processed_at ? {processed_at,...meta} : {}),...(supplement ? {supplement} : {})} : null;
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
/** 全台一覧に並ぶ日付タブ（YYYY-MM-DD、古い順）。読めなければ空。保存の判定には使わず、取り込み日の
 * タブが無い機種（入れ替えで入った新台など）を見分けるためだけに返す。新台はその日からのタブしか無く、
 * 前日を指定して開くとサイトは最新のタブを選ぶ（2026-10-19 利用者が実サイトで確認）。 */
function tableDays(root) {
  try {
    const days = [...root.querySelectorAll('[data-ymd]')].map(n => n.getAttribute('data-ymd'))
      .filter(v => /^\d{8}$/.test(v || '')).map(v => `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6)}`).filter(validDay);
    return [...new Set(days)].sort();
  } catch {
    return [];
  }
}
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

function validateAnasloRecord(r) {
  let url; try { url = new URL(r.source_url); } catch { fail('アナスロ履歴の出典が不正です。'); }
  if (url.origin !== 'https://ana-slo.com' || url.username || url.password || !url.pathname.startsWith(`/${r.day}-`) ||
      !/^[0-9a-f]{64}$/.test(r.source_sha256) || typeof r.source_machine !== 'string' || !r.source_machine.trim() ||
      ['my', 'detail_url', 'observed_at', 'graph', 'net_medals'].some(k => !Object.hasOwn(r, k) || r[k] !== null)) fail('アナスロ履歴の出典または欠損値が不正です。');
}

function validateData(raw) {
  if (raw?.format !== FORMAT || raw.version !== 1 || !Array.isArray(raw.machines) || !Array.isArray(raw.records) || (raw.history !== true && raw.records.length > 200000) || raw.machines.length > 10000) fail('P’s CUBEの保存ファイルではありません。');
  if (raw.history === true) {
    const days = new Map();
    for (const r of raw.records) { const n = (days.get(r?.day) || 0) + 1; if (n > 100000) fail('1日分の記録が多すぎます。'); days.set(r?.day, n); }
  }
  const basic = r => {
    if (!r || !/^c\d+$/.test(r.store) || typeof r.rate !== 'string' || !/^\d+(?:\.\d+)?$/.test(r.rate) ||
        typeof r.machine !== 'string' || !r.machine.trim() || r.machine.length > 200) fail('店舗・貸玉・機種名が不正です。');
    return { store: r.store, rate: r.rate, machine: r.machine.trim() };
  };
  const machines = raw.machines.map(m => {
    const base = basic(m), external = m.source_site === 'anaslo' && m.url == null;
    const url = external ? null : sameStore(m.url, base.store);
    if ((!external && (!url.pathname.endsWith('nc-v05-011.php') || url.searchParams.get('bai') !== base.rate ||
        (url.searchParams.has('cd_ps') && url.searchParams.get('cd_ps') !== '2'))) ||
        (m.expected_count !== null && (!integer(m.expected_count) || m.expected_count < 1 || m.expected_count > 5000))) fail('機種情報が不正です。');
    if (m.machine_type != null && !['normal', 'other'].includes(m.machine_type)) fail('機種タイプが不正です。');
    return { ...base, url: url?.href ?? null, expected_count: m.expected_count, machine_type: m.machine_type ?? null,
      ...(external ? {source_site: 'anaslo'} : {}) };
  });
  const records = raw.records.map(r => {
    const base = basic(r), external = r.source_site === 'anaslo';
    const url = external ? null : sameStore(r.detail_url, base.store);
    if (!integer(r.rack) || r.rack < 1 || !validDay(r.day) || (!external && (!url.pathname.endsWith('nc-v06-001.php') ||
        url.searchParams.get('cd_dai') !== String(r.rack) || url.hash !== `#${r.day.replaceAll('-', '')}`))) fail('台番号・営業日・リンクが一致しません。');
    if (external) validateAnasloRecord(r);
    for (const k of external ? ['bb', 'rb', 'at_art', 'games'] : ['bb', 'rb', 'at_art', 'games', 'my']) if (!integer(r[k])) fail('台の数値が不正です。');
    if (r.net_medals != null && (!Number.isSafeInteger(r.net_medals) || Math.abs(r.net_medals) > 1000000)) fail('差枚の数値が不正です。');
    let graph = null;
    if (r.graph != null) {
      const g = r.graph;
      if (!['overview', 'daily'].includes(g.kind) || !Number.isFinite(g.zero_y) || !Array.isArray(g.points) || g.points.length < 2 || g.points.length > 50000 ||
          g.points.some((p, i) => !Array.isArray(p) || p.length !== 2 || p.some(v => !Number.isFinite(v) || Math.abs(v) > 1e7) || (i && p[0] < g.points[i - 1][0]))) fail('保存グラフが不正です。');
      graph = { kind: g.kind, zero_y: g.zero_y, points: g.points.map(p => [...p]) };
    }
    if (r.observed_at != null && (typeof r.observed_at !== 'string' || !Number.isFinite(Date.parse(r.observed_at)))) fail('更新時刻が不正です。');
    const netCapture = validateNetCapture(r.net_capture);
    if (netCapture?.probe && (netCapture.probe.rack !== r.rack || !netCapture.probe.numbers.some(n => n.day===r.day &&
        ['bb','rb','at_art','games','my'].every(k => n[k]===r[k])))) fail('差枚の取得診断と台の数値が一致しません。');
    return { ...base, rack: r.rack, day: r.day, bb: r.bb, rb: r.rb, at_art: r.at_art, games: r.games, my: r.my,
      detail_url: url?.href ?? null, observed_at: r.observed_at ?? null, graph,
      ...(external ? {source_site:'anaslo', source_url:r.source_url, source_sha256:r.source_sha256,
        source_machine:r.source_machine, source_probabilities:r.source_probabilities, source_graph:r.source_graph} : {}),
      ...(external ? {net_medals:null} : r.net_medals == null ? {} : {net_medals: r.net_medals}),
      ...(netCapture ? {net_capture:netCapture} : {}) };
  });
  if (new Set(machines.map(machineKey)).size !== machines.length || new Set(records.map(recordKey)).size !== records.length) fail('同じ機種・台が重複しています。');
  const known = new Set(machines.map(machineKey));
  if (records.some(r => !known.has(machineKey(r)))) fail('台に対応する機種情報がありません。');
  trimNetProbes(records);
  const dateEvents = validateDateEvents(raw.date_events, raw.suffix_events);
  if (raw.history_days != null && (!Array.isArray(raw.history_days) || !raw.history_days.every(validDay) ||
      new Set(raw.history_days).size !== raw.history_days.length)) fail('履歴の日付一覧が不正です。');
  const syncStatus = mergeSyncStatus(raw.sync_status,makeSyncWrite(raw.source,raw.exported_at,records));
  return { format: FORMAT, version: 1, machines, records, ...(syncStatus ? {sync_status:syncStatus} : {}), ...(raw.history === true ? {history: true} : {}),
    ...(raw.history_days ? {history_days: raw.history_days} : {}),
    ...(dateEvents.length ? {date_events:dateEvents} : {}) };
}

function mergeData(stored, incoming) {
  const old = validateData(stored), fresh = validateData(incoming);
  const machines = new Map(old.machines.map(m => [machineKey(m), m]));
  for (const m of fresh.machines) {
    const previous = machines.get(machineKey(m));
    if (previous && m.source_site === 'anaslo') continue;
    machines.set(machineKey(m), { ...m, expected_count: m.expected_count ?? previous?.expected_count ?? null,
      machine_type: m.machine_type ?? previous?.machine_type ?? null });
  }
  const completeDays = new Set(fresh.history_days || []), freshKeys = new Set(fresh.records.map(recordKey));
  const records = new Map(old.records.filter(r => !completeDays.has(r.day) || freshKeys.has(recordKey(r))).map(r => [recordKey(r), r]));
  const rackDayKey = r => JSON.stringify([r.store, r.rate, r.rack, r.day]);
  const occupied = new Set([...records.values()].map(rackDayKey));
  for (const r of fresh.records) {
    const key = recordKey(r), previous = records.get(key);
    if (r.source_site === 'anaslo' && occupied.has(rackDayKey(r))) continue;
    occupied.add(rackDayKey(r));
    if (!previous) { records.set(key, r); continue; }
    if (previous.source_site === 'anaslo' && r.source_site !== 'anaslo') { records.set(key, r); continue; }
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
    const netCapture = mergeNetCapture(preferred,alternate,sameNumbers);
    records.set(key, { ...preferred, graph, ...(netCapture ? {net_capture:netCapture} : {}),
      ...(sameNumbers && preferred.net_medals == null && alternate.net_medals != null ? {net_medals:alternate.net_medals} : {}) });
  }
  // Events are independent of machine/rack data. A removal is retained as a dated
  // null name so an older backup cannot bring the event back.
  return validateData({ ...emptyData(), ...(old.history || fresh.history ? {history: true} : {}), machines: [...machines.values()], records: [...records.values()],
    sync_status:mergeSyncStatus(old.sync_status,fresh.sync_status),
    ...(old.history_days || fresh.history_days ? {history_days: [...new Set([...(old.history_days || []), ...(fresh.history_days || [])])]} : {}),
    date_events:mergeDateEvents(old.date_events, fresh.date_events) });
}

/** ブラウザの補完は既存の同じ台・日・数値の欠測差枚だけ。記録の追加や上書きを行わない。 */
function mergeNetSupplement(stored, incoming, report = {}) {
  const old=validateData(stored), fresh=validateData(incoming), records=new Map(old.records.map(r=>[recordKey(r),r]));
  for(const key of ['applied','unmatched','mismatched','known']) if (report[key]==null) report[key]=0;
  for (const value of fresh.records.filter(r=>r.net_medals!=null)) {
    const key=recordKey(value),r=records.get(key);
    if (!r) {report.unmatched++;continue;}
    if (r.source_site==='anaslo' || value.source_site==='anaslo' || !['bb','rb','at_art','games','my'].every(k=>r[k]===value[k])) {report.mismatched++;continue;}
    if (r.net_medals!=null) {report.known++;continue;}
    report.applied++;
    records.set(key,{...r,net_medals:value.net_medals,...(value.net_capture ? {net_capture:value.net_capture} : {})});
  }
  return validateData({...old,records:[...records.values()],sync_status:mergeSyncStatus(old.sync_status,fresh.sync_status)});
}
const SCRIPT_RELEASE = '541fd63e6aa4';
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
  if (!m || m.format !== VP_FORMAT || ![1, 2].includes(m.version) || m.site !== site ||
      !['meruhen', 'pscube'].includes(site) || !/^[a-f0-9]{64}$/.test(m.revision) ||
      !m.header || typeof m.header !== 'object' || Array.isArray(m.header) || 'records' in m.header ||
      m.header.version !== 1 || m.header.format !== (site === 'meruhen' ? 'database-backup' : 'pscube-viewer') ||
      typeof m.header.exported_at !== 'string' || !Array.isArray(m.parts) || m.parts.length > (m.version === 2 ? 16384 : 1024)) fail();
  const seen = new Set(), days = new Map(); let bytes = 0, count = 0;
  for (const p of m.parts) {
    if (!p || !/^[a-f0-9]{64}$/.test(p.hash) || seen.has(p.hash) ||
        !/^\d{4}-\d{2}-\d{2}$/.test(p.day) || !Number.isSafeInteger(p.count) || p.count < 1 ||
        !Number.isSafeInteger(p.bytes) || p.bytes < 2 || p.bytes > VP_PART_BYTES) fail();
    seen.add(p.hash); bytes += p.bytes; count += p.count;
    const d = days.get(p.day) || {bytes: 0, count: 0}; d.bytes += p.bytes; d.count += p.count; days.set(p.day, d);
  }
  if (count !== m.count || !Number.isSafeInteger(count)) fail();
  if (m.version === 1 && (bytes > VP_MAX_BYTES || count > 100000)) fail();
  if (m.version === 2 && (!Array.isArray(m.days) || new Set(m.days).size !== m.days.length ||
      m.days.some(day => !/^\d{4}-\d{2}-\d{2}$/.test(day)) ||
      [...days].some(([day, d]) => !m.days.includes(day) || d.bytes > VP_MAX_BYTES || d.count > 100000))) fail();
  if (m.curve_parts !== undefined) {
    if (m.version !== 2 || !Array.isArray(m.curve_parts) || m.curve_parts.length > 16384) fail();
    const curves = new Set();
    for (const c of m.curve_parts) {
      if (!c || !/^[a-f0-9]{64}$/.test(c.hash) || curves.has(c.hash) || !/^\d{4}-\d{2}-\d{2}$/.test(c.day) ||
          !m.days.includes(c.day) || !Number.isSafeInteger(c.count) || c.count < 1 ||
          !Number.isSafeInteger(c.bytes) || c.bytes < 2 || c.bytes > VP_PART_BYTES) fail();
      curves.add(c.hash);
    }
  }
  return m;
}
function vpPublicCurves(m) {
  return m.curve_parts ? {curve_parts: m.curve_parts.map(({hash, day, count, bytes}) => ({hash, day, count, bytes}))} : {};
}
function vpPublic(m) {
  return {format: m.format, version: m.version, site: m.site, revision: m.revision,
    header: m.header, count: m.count, ...(m.version === 2 ? {days: m.days, history: true} : {}),
    parts: m.parts.map(({hash, day, count, bytes}) => ({hash, day, count, bytes})), ...vpPublicCurves(m)};
}
// メルヘンのグラフの線は、閲覧用の記録から外して日ごとの線パーツに置く（2026-10-25、iPhoneのメモリ）。
// 記録の graph_measurement.curve_index（その日の中の通し番号）と、線パーツの [番号, 線] を結ぶ。
// 中身に日付を含め、別の日と同じ内容（同じハッシュ）にならないようにする。
const VP_CURVES_FORMAT = 'database-viewer-curves';
function vpCurveName(site, hash) { return 'database-viewer-curves-' + site + '-' + hash + '.json'; }
function vpCurveRows(text, ref) {
  const doc = JSON.parse(text), rows = doc && doc.curves;
  if (!doc || doc.day !== ref.day || !Array.isArray(rows) || rows.length !== ref.count ||
      rows.some(r => !Array.isArray(r) || r.length !== 2 || !Number.isSafeInteger(r[0]) || r[0] < 0 || !Array.isArray(r[1]))) {
    throw new Error('グラフの線のデータが更新一覧と一致しません。');
  }
  return rows;
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
function vpReadCurves(site, ref) {
  const file = DriveApp.getFileById(ref.id);
  if (file.isTrashed() || file.getName() !== vpCurveName(site, ref.hash) || file.getSize() !== ref.bytes) {
    throw new Error('グラフの線のファイルが見つかりません。同期を再実行してください。');
  }
  const text = file.getBlob().getDataAsString('UTF-8');
  if (vpHash(text) !== ref.hash) throw new Error('グラフの線のファイルが破損しています。');
  vpCurveRows(text, ref);
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
    if (params.parts || params.curves) throw new Error('閲覧用が更新されました。もう一度読み込んでください。');
    return null;
  }
  // 台の画面を開いたときのグラフの線（一覧にある線パーツだけ。中身はハッシュで決まるので版は問わない）。
  if (params.curves) {
    const ref = (manifest.curve_parts || []).find(c => c.hash === params.curves);
    if (!ref) throw new Error('グラフの線が更新されました。最新を読み込んでから開き直してください。');
    return {format: VP_CURVES_FORMAT, hash: ref.hash, text: vpReadCurves(site, ref)};
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
  // 旧クライアントの全件GETを無制限に組み立てない。新版はcheckとパーツを使う。
  if (manifest.version === 2 && (manifest.count > 100000 || manifest.parts.reduce((n, p) => n + p.bytes, 0) > VP_MAX_BYTES)) {
    throw new Error('履歴データは新しい閲覧ページで開いてください（全件GETの上限を超えています）。');
  }
  return {...manifest.header, ...(manifest.version === 2 ? {history: true} : {}), records: manifest.parts.flatMap(p => vpRows(vpReadPart(site, p), p))};
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
  const active = new Set([...manifest.parts, ...(manifest.curve_parts || [])].map(p => p.id));
  const pattern = new RegExp('^database-viewer-(part|curves)-' + site + '-[a-f0-9]{64}\\.json$');
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

// 履歴モード。全期間のレコードを組み立てず、入力1本と変更日の完成版だけを扱う。
// 確定点は閲覧一覧1本。日別の原本と閲覧パーツは不変で、一覧を最後に書く。
function vhBytes(text) { return Utilities.newBlob(text).getBytes().length; }
function vhRead(ref) {
  const f = DriveApp.getFileById(ref.id);
  if (f.isTrashed() || f.getName() !== ref.name || f.getSize() !== ref.bytes || ref.bytes > VP_MAX_BYTES) {
    throw new Error('履歴の日別原本が見つかりません。元バックアップからの復旧が必要です。');
  }
  const text = f.getBlob().getDataAsString('UTF-8');
  if (vpHash(text) !== ref.hash) throw new Error('履歴の日別原本が破損しています。上書きせず停止しました。');
  const value = JSON.parse(text);
  if (value.day !== ref.day || value.site !== ref.site) throw new Error('履歴の日別原本の日付が不正です。');
  return value;
}
function vhImmutable(folder, name, text, write) {
  const hash = vpHash(text), bytes = vhBytes(text);
  if (bytes > VP_MAX_BYTES) throw new Error('1日分の統合原本が48MiBを超えます。既存の履歴は保持しました。');
  const matches = folder.getFilesByName(name); let file = null;
  while (matches.hasNext()) {
    const f = matches.next();
    if (!f.isTrashed() && f.getSize() === bytes && vpHash(f.getBlob().getDataAsString('UTF-8')) === hash) { file = f; break; }
  }
  const created = !file;
  if (!file) file = write(folder, null, name, text);
  return {id: file.getId(), name, hash, bytes, created};
}
function vhDayParts(folder, site, day, rows, write) {
  const parts = [], curveParts = []; let batch = [], size = 2, written = 0, writtenBytes = 0;
  const flush = () => {
    if (!batch.length) return;
    const text = '[' + batch.join(',') + ']', hash = vpHash(text), name = vpPartName(site, hash);
    const ref = vhImmutable(folder, name, text, write);
    parts.push({day, hash, count: batch.length, bytes: ref.bytes, id: ref.id,
      file_version: vpVersion(DriveApp.getFileById(ref.id))});
    if (ref.created) { written++; writtenBytes += ref.bytes; }
    batch = []; size = 2;
  };
  // メルヘンは線を外した軽い記録を日別パーツに、線は線パーツに置く（viewer_curves_split.js）。
  // 1本で線パーツの上限を超える線は外さない。
  const split = site === 'meruhen'
    ? vpSplitCurves(rows, curve => vhBytes(vpCanonical(curve)) + 64 <= VP_PART_BYTES)
    : {rows, curves: []};
  for (const row of split.rows.map(vpCanonical).sort()) {
    const bytes = vhBytes(row);
    if (bytes + 2 > VP_PART_BYTES) throw new Error('1台の閲覧用データが1MiBを超えています。');
    if (size + bytes + (batch.length ? 1 : 0) > VP_PART_BYTES) flush();
    size += bytes + (batch.length ? 1 : 0); batch.push(row);
  }
  flush();
  let curveBatch = [], curveSize = 0;
  const head = '{"curves":[', tail = '],"day":' + JSON.stringify(day) + '}';
  const flushCurves = () => {
    if (!curveBatch.length) return;
    const text = head + curveBatch.join(',') + tail, hash = vpHash(text);
    const ref = vhImmutable(folder, vpCurveName(site, hash), text, write);
    curveParts.push({day, hash, count: curveBatch.length, bytes: ref.bytes, id: ref.id});
    if (ref.created) { written++; writtenBytes += ref.bytes; }
    curveBatch = []; curveSize = 0;
  };
  for (const entry of split.curves) {
    const text = vpCanonical(entry), bytes = vhBytes(text);
    if (vhBytes(head + tail) + curveSize + bytes + (curveBatch.length ? 1 : 0) > VP_PART_BYTES) flushCurves();
    curveSize += bytes + (curveBatch.length ? 1 : 0); curveBatch.push(text);
  }
  flushCurves();
  return {parts, curveParts, written, writtenBytes};
}

function vhSync(folder, base, props, adapter, startedAt) {
  const {site, write} = adapter, indexName = vpManifestName(site);
  const indexFile = vpUnique(folder, indexName);
  const old = indexFile ? vpReadManifest(indexFile, site) : null;
  const baseVersion = base ? vpVersion(base) : '';
  // v1の閲覧パーツも消さずに引き継ぐ。原本が無い日は最初の更新時だけパーツから戻す。
  const m = old ? JSON.parse(JSON.stringify(old)) : {header: adapter.header(), parts: [], count: 0};
  m.format = VP_FORMAT; m.version = 2; m.site = site; m.base = baseVersion;
  // Apps Scriptの保存時に解釈できる通常の代入で初期化する。
  if (!m.history_inputs) m.history_inputs = {};
  if (!m.history_progress) m.history_progress = {};
  if (!m.history_baselines) m.history_baselines = {};
  if (!m.cloud_days) m.cloud_days = [];
  const days = new Map(m.cloud_days.map(d => [d.day, d]));
  const parts = new Map(), curves = new Map();
  for (const p of m.parts) { if (!parts.has(p.day)) parts.set(p.day, []); parts.get(p.day).push(p); }
  for (const c of m.curve_parts || []) { if (!curves.has(c.day)) curves.set(c.day, []); curves.get(c.day).push(c); }
  const loadDay = day => {
    if (days.has(day)) return vhRead(days.get(day));
    // 日別原本の無い古い日は閲覧用パーツから戻す。外した線も戻す。
    const rows = (parts.get(day) || []).flatMap(p => vpRows(vpReadPart(site, p), p));
    const saved = (curves.get(day) || []).flatMap(c => vpCurveRows(vpReadCurves(site, c), c));
    return adapter.fromViewer(day, m.header, vpRestoreCurves(rows, saved));
  };
  // 線を外す前に作った閲覧用パーツは、日別原本から1回だけ作り直す（30分ごとに24日分ずつ）。
  // 新しく作る一覧は最初から線を外すので作り直さない。
  if (site === 'meruhen' && !props.getProperty('meruhenCurvesSplit')) {
    if (old && old.parts.length) { props.setProperty(site + 'HistoryRebuild', '1'); m.history_rebuild_next = 0; }
    props.setProperty('meruhenCurvesSplit', '1');
  }
  // 移行元・PC再出力も版が変わった場合だけ読む。入力原本は変更・削除しない。
  const inputs = adapter.inputs();
  const failures = adapter.failures();
  const live = new Set(inputs.map(i => i.id));
  for (const table of [m.history_inputs, m.history_progress, m.history_baselines, failures.reasons, failures.versions]) {
    for (const id of Object.keys(table)) if (!live.has(id)) delete table[id];
  }
  const newFailures = []; let processed = 0, changedDays = 0, written = 0, bytes = 0, readBytes = 0;
  const saveDay=(day,value)=>{
    if (site==='pscube') trimNetProbes(value.data.records);
    const rawText=vpCanonical(value),rawHash=vpHash(rawText);
    if (days.get(day)?.hash===rawHash) return false;
    const rows=adapter.viewer(value);
    if (rows.length>100000) throw new Error('1日分の閲覧記録が10万件を超えています。');
    const published=vhDayParts(folder,site,day,rows,write);
    const rawName='database-history-day-'+site+'-'+day+'-'+rawHash+'.json';
    const {created,...rawRef}=vhImmutable(folder,rawName,rawText,write);
    const probes=site==='pscube' ? value.data.records.filter(r=>r.net_capture?.probe) : [];
    const probeInfo=probes.length ? {probe_bytes:probes.reduce((n,r)=>n+JSON.stringify(r.net_capture.probe).length,0),
      probe_next_expiry:Math.min(...probes.map(r=>Date.parse(r.net_capture.checked_at)+NET_PROBE_DAYS*86400000))} : {};
    days.set(day,{...rawRef,day,site,count:rows.length,...probeInfo});parts.set(day,published.parts);curves.set(day,published.curveParts);
    written+=published.written;bytes+=published.writtenBytes;changedDays++;
    return true;
  };
  const needsInput = i => (m.history_inputs[i.id] !== i.version || (i.baseline && m.history_baselines[i.id] !== i.baseline)) && failures.versions[i.id] !== i.version;
  const pending = inputs.filter(needsInput);
  for (const input of pending.slice(0, 10)) {
    if (readBytes && (Date.now() - startedAt > 150000 || readBytes + input.size > 64 * 1024 * 1024)) break;
    let incoming;
    try { incoming = adapter.read(input); }
    catch (error) {
      if (adapter.transient(error)) continue;
      const f = {name: input.name, reason: String(error.message || error).slice(0, 120), version: input.version,
        checked_at: new Date().toISOString(), size: input.size};
      failures.reasons[input.id] = f; failures.versions[input.id] = input.version; newFailures.push(f);
      continue;
    }
    readBytes += input.size;
    if (vpVersion(input.file) !== input.version) continue;
    const grouped = adapter.group(incoming), allDays = [...grouped.keys()].sort();
    const savedProgress = m.history_progress[input.id];
    const resume = savedProgress?.version === input.version ? savedProgress : null;
    const start = resume?.next || 0;
    let next = start;
    // 大きい初回入力は日付単位で途中確定し、次の30分実行で続きから処理する。
    for (; next < allDays.length; next++) {
      if (changedDays >= 24 || (next > start && Date.now() - startedAt > 150000)) break;
      const day = allDays[next], prior = loadDay(day);
      const value = adapter.merge(prior, grouped.get(day), input);
      if (value.day !== day || value.site !== site) throw new Error('統合後の日付が不正です。');
      saveDay(day,value);
    }
    if (next < allDays.length) m.history_progress[input.id] = {version: input.version, next,
      ...(input.baseline ? {baseline:resume?.baseline || input.baseline} : {})};
    else {
      m.history_inputs[input.id] = input.version;
      if (input.baseline) m.history_baselines[input.id] = resume?.baseline || input.baseline;
      delete m.history_progress[input.id];
      delete failures.versions[input.id]; delete failures.reasons[input.id]; processed++;
    }
    m.header = adapter.mergeHeader(m.header, incoming, input);
    if (next < allDays.length) break;
  }
  if (site==='pscube') for (const [day,ref] of days) {
    if (changedDays>=24 || Date.now()-startedAt>150000) break;
    if (Number.isFinite(ref.probe_next_expiry) && ref.probe_next_expiry<=Date.now()) saveDay(day,loadDay(day));
  }
  if (props.getProperty(site + 'HistoryRebuild')) {
    let next = m.history_rebuild_next || 0;
    const ordered = [...days.keys()].sort();
    for (; next < ordered.length; next++) {
      if (changedDays >= 24 || Date.now() - startedAt > 150000) break;
      const day = ordered[next], value = vhRead(days.get(day));
      const published = vhDayParts(folder, site, day, adapter.viewer(value), write);
      parts.set(day, published.parts); curves.set(day, published.curveParts);
      written += published.written; bytes += published.writtenBytes; changedDays++;
    }
    m.history_rebuild_next = next < ordered.length ? next : null;
  }
  if (base && vpVersion(base) !== baseVersion) throw new Error('PCの閲覧用が処理中に変更されました。次回やり直します。');
  m.parts = [...parts].sort(([a], [b]) => a.localeCompare(b)).flatMap(([, p]) => p);
  const curveParts = [...curves].sort(([a], [b]) => a.localeCompare(b)).flatMap(([, c]) => c);
  if (curveParts.length) m.curve_parts = curveParts; else delete m.curve_parts;
  m.cloud_days = [...days.values()].sort((a, b) => a.day.localeCompare(b.day));
  m.days = [...new Set([...parts.keys(), ...days.keys()])].sort();
  m.count = m.parts.reduce((n, p) => n + p.count, 0);
  const health=mergeSyncStatus(m.header.sync_status);
  const remainingNow=inputs.filter(needsInput).length+(m.history_rebuild_next != null ? 1 : 0);
  const failuresNow=Object.keys(failures.versions).length;
  const browserReports=pending.filter(i=>i.report).map(i=>i.report);
  const supplement=browserReports.length ? {at:new Date().toISOString(),
    ...Object.fromEntries(['applied','unmatched','mismatched','known'].map(k=>[k,browserReports.reduce((n,r)=>n+(r[k] || 0),0)]))} : null;
  m.header.sync_status={version:1,writes:[],...health,processor_release:SCRIPT_RELEASE,pending:remainingNow,failed_inputs:failuresNow,
    ...(site==='pscube' ? {supplement_supported:true} : {}),
    ...((changedDays || processed || !health?.processed_at) ? {processed_at:new Date().toISOString()} : {}),...(supplement ? {supplement} : {})};
  const {exported_at, ...stableHeader} = m.header;
  m.signature = vpHash(vpCanonical({parts: m.parts.map(({day, hash}) => ({day, hash})), days: m.days, header: stableHeader,
    ...(m.curve_parts ? {curves: m.curve_parts.map(({day, hash}) => ({day, hash}))} : {})}));
  if (old?.signature !== m.signature) m.header.exported_at = new Date(Math.max(Date.now(), Date.parse(old?.header?.exported_at || '') + 1 || 0)).toISOString();
  m.revision = vpHash(vpCanonical({base: m.base, parts: m.parts, days: m.days, header: m.header,
    ...(m.curve_parts ? {curve_parts: m.curve_parts} : {})}));
  vpValidManifest(m, site);
  const text = JSON.stringify(m);
  // 一覧だけに独立した上限。レコード総容量の48MiB制限は適用しない。
  if (vhBytes(text) > 1024 * 1024) throw new Error('履歴の更新一覧が1MiBを超えます。元データを保持して停止しました。');
  if (!old || vpCanonical(old) !== vpCanonical(m)) write(folder, indexFile, indexName, text);
  if (props.getProperty(site + 'HistoryRebuild') && m.history_rebuild_next === null) props.deleteProperty(site + 'HistoryRebuild');
  // 故障した原本の自動削除はしない。未参照の生成物だけ7日後に整理する。
  vpMaintain(folder, site, props);
  vhMaintain(folder, site, props);
  const remaining = inputs.filter(needsInput).length + (m.history_rebuild_next != null ? 1 : 0);
  const status = {at: new Date().toISOString(), result: Object.keys(failures.versions).length ? 'partial' : 'ok', history: true,
    message: '履歴を日別に保存・' + changedDays + '日更新', processed, remaining,
    viewer_records: m.count, android_records: m.count, backup_records: m.count, records: m.count,
    viewer_bytes: m.parts.reduce((n, p) => n + p.bytes, 0),
    backup_bytes: m.cloud_days.reduce((n, d) => n + d.bytes, 0),
    incremental: {parts: written, bytes}, elapsed_ms: Date.now() - startedAt};
  adapter.save(status, failures);
  return {changed: changedDays > 0, pending: remaining, newFailures, status};
}

// 元バックアップ・現行の全日原本・移行用控えは対象外。未参照の生成原本だけ7日後に整理。
function vhMaintain(folder, site, props) {
  const key = site + 'HistoryCleaned';
  if (Date.now() - Number(props.getProperty(key) || 0) < 6 * 3600000) return;
  try {
    const index = vpUnique(folder, vpManifestName(site)), revision = vpVersion(index);
    const m = vpReadManifest(index, site), active = new Set((m.cloud_days || []).map(d => d.id));
    const pattern = new RegExp('^database-history-day-' + site + '-\\d{4}-\\d{2}-\\d{2}-[a-f0-9]{64}\\.json$');
    const files = folder.getFiles(), cutoff = Date.now() - 7 * 86400000; let removed = 0;
    while (files.hasNext() && removed < 200) {
      const file = files.next();
      if (!file.isTrashed() && pattern.test(file.getName()) && !active.has(file.getId()) && file.getLastUpdated().getTime() < cutoff) {
        if (vpVersion(index) !== revision) throw new Error('履歴一覧が更新されました。');
        file.setTrashed(true); removed++;
      }
    }
    props.setProperty(key, String(Date.now()));
  } catch (error) { console.log('古い日別原本の整理は次回再試行します：' + String(error.message || error)); }
}

function vhInput(file, kind) {
  return {file, kind, id: kind + ':' + file.getId(), name: file.getName(), size: file.getSize(), version: vpVersion(file)};
}
function vhSourceStatus(old,fresh,input) {
  // Driveの更新時刻は、その入力自身の書き出しにだけ結び付ける。
  // 古いPC出力の読み込みで、別ファイルにある新しいPC出力の時刻を偽って更新しない。
  const own=fresh.cloud_merged ? null : makeSyncWrite(fresh.source,fresh.exported_at,fresh.records || [],
    input?.file ? input.file.getLastUpdated().toISOString() : undefined);
  return mergeSyncStatus(old.sync_status,fresh.sync_status,own);
}
// A missing day may have aged out of the PC's 60-day view. Only an explicit,
// timestamped operation can remove a record from the permanent cloud history.
function vhDeletions(doc) {
  const marks = doc.record_deletions === undefined ? [] : doc.record_deletions;
  if (!Array.isArray(marks) || marks.some(m => !m || !MERUHEN_STORES.includes(m.store) ||
      !meruhenValidDay(m.day) || typeof m.machine !== 'string' || !m.machine.trim() ||
      !Number.isSafeInteger(m.rack) || m.rack < 1 || meruhenTime(m.deleted_at) === null ||
      !/(?:Z|[+-]\d{2}:\d{2})$/.test(m.deleted_at))) throw new Error('削除記録が不正です。');
  return marks;
}
function vhNotDeleted(row, deletions) {
  const mark = deletions.get(meruhenKey(row));
  return !mark || Math.max(meruhenTime(row.record_updated_at) || 0, meruhenTime(row.captured_at) || 0) > meruhenTime(mark.deleted_at);
}
function vhMergeMeruhen(old, fresh, kind) {
  const marks = new Map(vhDeletions(old).map(m => [meruhenKey(m), m]));
  for (const m of vhDeletions(fresh)) {
    const key = meruhenKey(m), prior = marks.get(key);
    if (!prior || meruhenTime(m.deleted_at) > meruhenTime(prior.deleted_at)) marks.set(key, m);
  }
  const android = new Map(old.android.map(r => [meruhenKey(r), r]));
  if (kind !== 'pc') for (const r of fresh.records) {
    const key = meruhenKey(r), prior = android.get(key);
    android.set(key, prior ? meruhenPick(prior, r) : r);
  }
  // PCの閲覧用入力に記録が1件も無い日（削除印・イベントだけの日。60日より前の削除印の日など）は、
  // その日の記録を出していないだけ。置き換えると、残っているPCの記録が消える（2026-10-17、8/1〜8/17だけの
  // 入力で9/14〜9/20などの30日が消えた）。残した記録にも削除印を当てるので、本当に消した台は消える。
  const pc = kind === 'pc' && fresh.records.length ? fresh.records : old.pc;
  return {...old, record_deletions: [...marks.values()],
    pc: pc.filter(r => vhNotDeleted(r, marks)),
    android: [...android.values()].filter(r => vhNotDeleted(r, marks))};
}
function vhGroup(doc, site) {
  const grouped = new Map();
  for (const r of doc.records) {
    if (!grouped.has(r.day)) grouped.set(r.day, []); grouped.get(r.day).push(r);
  }
  // イベントだけのバックアップも日付単位で処理する。
  for (const e of doc.date_events || []) if (!grouped.has(e.day)) grouped.set(e.day, []);
  if (site === 'meruhen') for (const m of vhDeletions(doc)) if (!grouped.has(m.day)) grouped.set(m.day, []);
  const captures = new Set(doc.rack_captures || []);
  return new Map([...grouped].map(([day, records]) => [day, {...doc, site, day, records,
    ...(doc.date_events ? {date_events: doc.date_events.filter(e => e.day === day)} : {}),
    ...(site === 'meruhen' ? {record_deletions: vhDeletions(doc).filter(m => m.day === day)} : {}),
    ...(doc.rack_captures ? {rack_captures: records.map(recordKey).filter(k => captures.has(k))} : {})}]));
}
function vhMeruhen(folder, base, props, startedAt) {
  return vhSync(folder, base, props, {
    site: 'meruhen', write: meruhenWrite,
    header: () => ({format: 'database-backup', version: 1, source: 'pc-viewer', exported_at: new Date().toISOString()}),
    inputs: () => {
      const legacy = meruhenUniqueFile(folder, MERUHEN_CLOUD_STORE);
      return [vhInput(base, 'pc'), ...(legacy ? [vhInput(legacy, 'legacy')] : []),
        ...meruhenListInputs([folder, DriveApp.getRootFolder()]).map(i => vhInput(i.file, 'android'))];
    },
    read: input => {
      if (input.kind === 'android') return meruhenReadBackup(input.file, input.size, true);
      if (input.kind === 'legacy') return meruhenReadStore(input.file);
      if (input.size > MERUHEN_CLOUD_MAX_BYTES) throw new Error('PC閲覧用入力が48MiBを超えています。期間を分けてください。');
      let text;
      try { text = input.file.getBlob().getDataAsString('UTF-8'); } catch (e) { throw new MeruhenCloudTransient(e.message); }
      const doc = JSON.parse(text.replace(/^\uFEFF/, ''));
      if (doc.format !== 'database-backup' || doc.version !== 1 || doc.source !== 'pc-viewer' ||
          !Array.isArray(doc.records) || !doc.records.every(meruhenValidRecord)) throw new Error('PC閲覧用の形式が不正です。');
      vhDeletions(doc); return doc;
    },
    group: doc => vhGroup(doc, 'meruhen'),
    fromViewer: (day, header, records) => ({site: 'meruhen', day, pc: records, android: []}),
    merge: (old, fresh, input) => {
      if (!Array.isArray(old.pc) || !Array.isArray(old.android) || ![...old.pc, ...old.android].every(meruhenValidRecord)) {
        throw new Error('メルヘンの日別原本が不正です。');
      }
      return vhMergeMeruhen(old, fresh, input.kind);
    },
    viewer: value => meruhenApply({records: value.pc}, value.android).records,
    mergeHeader: (old, fresh, input) => {
      const events = new Map((old.date_events || []).map(e => [e.store + '|' + e.day, e]));
      for (const e of fresh.date_events || []) {
        const key = e.store + '|' + e.day, prior = events.get(key);
        if (!prior || !prior.updated_at || Date.parse(e.updated_at) >= Date.parse(prior.updated_at)) events.set(key, e);
      }
      // PCの閲覧用の日ごとの「何台中何台プラス」（day_summaries、2026-10-18 html_day_summary.py）は、
      // PCの最新の出力のものに置き換える。Androidのバックアップには無いので前のまま。
      const summaries = Array.isArray(fresh.day_summaries) ? {day_summaries: fresh.day_summaries} : {};
      // 当時の翌日候補（answer_candidates、2026-11-04 閲覧ページの答え合わせ用、core.py saved_answer_candidates）も
      // PCの最新の出力のものに置き換える。Androidのバックアップには無いので前のまま。
      const answers = fresh.answer_candidates && typeof fresh.answer_candidates === 'object' && !Array.isArray(fresh.answer_candidates)
        ? {answer_candidates: fresh.answer_candidates} : {};
      return {...old, ...summaries, ...answers, date_events: [...events.values()],sync_status:vhSourceStatus(old,fresh,input)};
    },
    failures: () => ({reasons: meruhenParse(props.getProperty(MERUHEN_CLOUD_ERRORS)) || {},
      versions: meruhenParse(props.getProperty(MERUHEN_CLOUD_FAILED)) || {}}),
    transient: e => e instanceof MeruhenCloudTransient,
    save: (status, f) => { meruhenSave(props, status, f.reasons, f.versions);
      for (const line of meruhenStatusLines(status, Object.values(f.reasons), Object.keys(f.versions).length)) console.log(line); },
  }, startedAt);
}
function vhPscube(folder, base, props, startedAt) {
  if (!base) base = pscubeCloudWrite(folder, null, PSCUBE_CLOUD_VIEWER,
    JSON.stringify({...emptyData(), kind: 'viewer', source: 'cloud', exported_at: new Date().toISOString()}));
  return vhSync(folder, base, props, {
    site: 'pscube', write: pscubeCloudWrite,
    header: () => { const {records, ...header} = emptyData(); return {...header, kind: 'viewer', source: 'cloud', exported_at: new Date().toISOString()}; },
    inputs: () => {
      const legacy = pscubeCloudUniqueFile(folder, PSCUBE_CLOUD_BACKUP);
      const inputs = [vhInput(base, 'pc'), ...(legacy ? [vhInput(legacy, 'legacy')] : []),
        ...pscubeCloudListInputs([folder, DriveApp.getRootFolder()]).map(i => vhInput(i.file, i.browser ? 'browser' : 'backup'))];
      const baseline = vpHash(vpCanonical(inputs.filter(i=>i.kind!=='browser').map(i=>[i.id,i.version])));
      for (const input of inputs) if (input.kind==='browser') input.baseline=baseline;
      return inputs;
    },
    read: input => {
      if (input.kind !== 'pc') return pscubeCloudRead(input.file, input.size,input.kind==='browser' ? 'browser' : null);
      if (input.size > PSCUBE_CLOUD_MAX_BYTES) throw new Error('PC閲覧用入力が48MiBを超えています。期間を分けてください。');
      let text;
      try { text = input.file.getBlob().getDataAsString('UTF-8'); } catch (e) { throw new PscubeCloudTransient(e.message); }
      const raw=JSON.parse(text);
      return {...validateData(raw),source:raw.source,exported_at:raw.exported_at};
    },
    group: doc => vhGroup(doc, 'pscube'),
    fromViewer: (day, header, records) => ({site: 'pscube', day, data: {...emptyData(), machines: header.machines || [], records}}),
    merge: (old, fresh, input) => {
      if (input.kind === 'pc') {
        // PC閲覧用の16点グラフを、日別原本の完全グラフへ逆流させない。一覧のグラフ（overview、多くは17点）も同じ
        // （2026-10-25：16点と17点を行き来して、同じ日の原本を同期のたびに書き直していた）。
        const previous = new Map(old.data.records.map(r => [recordKey(r), r]));
        fresh = {...fresh, records: fresh.records.map(r => {
          const prior = previous.get(recordKey(r));
          const same = prior && ['bb', 'rb', 'at_art', 'games', 'my'].every(k => prior[k] === r[k]);
          // 新旧ともグラフなしならkindも両方undefinedになる。点列のある原本だけを保護する。
          const previousPoints = prior?.graph?.points;
          const incomingPoints = r.graph?.points;
          return same && Array.isArray(previousPoints) &&
            (prior.graph.kind === 'daily' || prior.graph.kind === r.graph?.kind) &&
            previousPoints.length > (Array.isArray(incomingPoints) ? incomingPoints.length : 0)
            ? {...r, graph: prior.graph} : r;
        })};
      }
      const report=input.kind==='browser' ? (input.report || (input.report={})) : null;
      const merged = input.kind==='browser' ? mergeNetSupplement(old.data,fresh,report) : pscubeCloudMerge(old.data,fresh);
      // 更新経路は一覧の見出しに保持し、同じ情報だけで全日別原本を再生成しない。
      const {sync_status,...data}=merged;
      return {site: 'pscube', day: fresh.day, data};
    },
    viewer: value => pscubeCloudViewer(value.data, '').records,
    mergeHeader: (old, fresh, input) => {
      if (input?.kind==='browser') return {...old,sync_status:vhSourceStatus(old,fresh,input)};
      const machines = new Map((old.machines || []).map(m => [machineKey(m), m]));
      for (const m of fresh.machines) {
        const prior = machines.get(machineKey(m)); machines.set(machineKey(m), {...m, machine_type: m.machine_type ?? prior?.machine_type ?? null});
      }
      return {...old, machines: [...machines.values()], date_events: mergeDateEvents(old.date_events, fresh.date_events),sync_status:vhSourceStatus(old,fresh,input)};
    },
    failures: () => ({reasons: pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_ERRORS)) || {},
      versions: pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_FAILED)) || {}}),
    transient: e => e instanceof PscubeCloudTransient,
    save: (status, f) => { pscubeCloudSave(props, status, f.reasons, f.versions);
      for (const line of pscubeCloudStatusLines(status, Object.values(f.reasons), Object.keys(f.versions).length)) console.log(line); },
  }, startedAt);
}

// メルヘンの閲覧用：グラフの線を記録から外し、線があるうちに推定差枚を計算して添える（2026-10-25）。
// iPhoneの閲覧ページが起動のたびに全日分の線をメモリに載せて落ちていたため。線の正本は日別原本に残す。
// 差枚は閲覧ページ（Dart の meruhenNetEstimateDetail）と同じ入力で計算する。Dart は最大持玉・回転数を
// 整数に直してから使い、共有カレンダー（net.mjs）は元の値を使うため、両方が同じ値になる記録
// （最大持玉・回転数が整数、座標がすべて有限の数）だけ線を外す。それ以外は今までどおり線を残す。
function vpCurveSplittable(r) {
  const g = r && r.graph_measurement, finite = v => typeof v === 'number' && Number.isFinite(v);
  if (!g || typeof g !== 'object' || Array.isArray(g) || !Array.isArray(g.curve) || g.curve.length < 2) return false;
  if (!['baseline_y', 'peak_y', 'end_y'].every(k => finite(g[k]))) return false;
  if (['trough_y', 'baseline_x', 'peak_x', 'trough_x', 'end_x'].some(k => g[k] != null && !finite(g[k]))) return false;
  if (g.curve.some(p => !Array.isArray(p) || p.length < 2 || !p.every(finite))) return false;
  if (r.max_hold != null && !Number.isSafeInteger(r.max_hold)) return false;
  if (r.games != null && !Number.isSafeInteger(r.games)) return false;
  return !('net_estimate' in g) && !('curve_index' in g) && !('curve_remote' in g);
}
// 1日分の閲覧用の記録から線を外す。rows は日別パーツへ、curves は [通し番号, 線] の一覧。
// 通し番号は記録の並べ方（vpCanonical の文字順）で決まり、同じ内容なら毎回同じになる。
function vpSplitCurves(rows, fits) {
  const ordered = rows.map(r => [vpCanonical(r), r]).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([, r]) => r);
  const light = [], curves = [];
  for (const r of ordered) {
    if (!vpCurveSplittable(r) || !fits(r.graph_measurement.curve)) { light.push(r); continue; }
    const {curve, ...graph} = r.graph_measurement;
    const net = VP_NET.meruhenNetDetail(r.graph_measurement, r.max_hold ?? null, r.games ?? null);
    const index = curves.length;
    curves.push([index, curve]);
    light.push({...r, graph_measurement: {...graph, curve_remote: true, curve_index: index,
      net_estimate: {value: net.value, needs_check: net.needsCheck, max_hold: r.max_hold ?? null, games: r.games ?? 0}}});
  }
  return {rows: light, curves};
}
// 線を外した記録へ線を戻す（日別原本の無い古い日を閲覧用パーツから組み立て直すとき）。
function vpRestoreCurves(rows, curves) {
  const byIndex = new Map(curves);
  return rows.map(r => {
    const g = r && r.graph_measurement;
    if (!g || g.curve_remote !== true) return r;
    if (!byIndex.has(g.curve_index)) throw new Error('グラフの線が見つかりません。元バックアップからの復旧が必要です。');
    const {curve_remote, curve_index, net_estimate, ...graph} = g;
    return {...r, graph_measurement: {...graph, curve: byIndex.get(g.curve_index)}};
  });
}

const VP_NET = (function () {
// メルヘンの推定差枚（グラフの座標と最大持玉から計算）。database_android/lib/meruhen_net.dart・
// PC core.meruhen_net_estimate と同じ規則をそのまま移したもの（閲覧専用の共有ページ用、2026-10-09）。
// 規則を変えるときは3つを一緒に変え、database_android/tool/test_share_viewer.mjs の例も合わせる。

// 推定差枚を出さない店・日（ジャグラーオンラインの差枚は出す）。長町南の10/7は、サイトのグラフが全台「始点と終点を
// 結んだ直線」で途中の推移が無く、推定が正しく決められないため（2026-10-12 利用者「長町南10/7だけ消す」）。
// PC core.MERUHEN_NET_HIDDEN_DAYS・database_android/lib/meruhen_net.dart の meruhenNetHiddenDays と同じ。
const NET_HIDDEN_DAYS = {nagamachiminami: ['2026-10-07']};

/** その店・日の推定差枚を出さないか。 */
function meruhenNetHidden(store, day) {
  return (NET_HIDDEN_DAYS[store] ?? []).includes(day);
}

const AXIS_STEPS = [1000, 2000, 4000, 6000, 8000, 10000, 12000, 14000, 16000, 18000, 20000,
  22000, 24000, 26000, 28000, 30000, 32000, 34000, 36000, 38000, 40000];
const PLAUSIBLE_USE_PER_GAME = 1.75;
const MAX_USE_PER_GAME = 3.0;
const ZERO_Y = 200.5, TOP_Y = 20.5;
const HALF = ZERO_Y - TOP_Y;
// 幸町の正確なjo_netとの照合（旧推定の誤差100枚未満の6,875組）で確認した終点の半px補正。
const END_PIXEL_CORRECTION = 0.5;

function rise(values) {
  let low = 0, result = 0;
  for (const v of values) {
    if (v < low) low = v;
    if (v - low > result) result = v - low;
  }
  return result;
}

// Dartの round()（0.5は0から遠い方）と同じ丸め。
function roundHalfAway(x) {
  return x < 0 ? -Math.round(-x) : Math.round(x);
}

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** 推定差枚と要確認の印。計算できないときは {value: null, needsCheck: false}。 */
function meruhenNetDetail(measurement, maxHold, games) {
  const none = {value: null, needsCheck: false};
  if (!measurement || typeof measurement !== 'object') return none;
  const baselineY = num(measurement.baseline_y), peakY = num(measurement.peak_y);
  const endY = num(measurement.end_y);
  const troughY = num(measurement.trough_y ?? measurement.end_y);
  if (baselineY == null || peakY == null || endY == null || troughY == null) return none;
  if (Math.abs(baselineY - ZERO_Y) > 0.01) return none;
  if (maxHold == null || maxHold < 0 || maxHold > 100000) return none;
  const peak = baselineY - peakY, trough = baselineY - troughY, end = baselineY - endY;
  const amp = Math.max(Math.abs(peak), Math.abs(trough), Math.abs(end));
  if (amp === 0) return {value: 0, needsCheck: false};

  const fits = (index) => {
    const range = AXIS_STEPS[index];
    const previous = index === 0 ? 0 : AXIS_STEPS[index - 1];
    const unit = range / HALF;
    return amp * unit > previous - unit / 2 && amp * unit <= range + unit / 2;
  };

  let chosen = null, needsCheck = false;
  const curve = Array.isArray(measurement.curve) ? measurement.curve : null;
  if (curve && curve.length >= 2) {
    const values = curve.map(p => baselineY - p[1]);
    const r = rise(values);
    if (r <= 0) return none;
    const candidates = AXIS_STEPS.filter((step, i) => fits(i) && maxHold / (r * step / HALF) >= 0.98);
    let drops = 0;
    for (let i = 1; i < values.length; i++) if (values[i] < values[i - 1]) drops += values[i - 1] - values[i];
    const within = (step, perGame) => games == null || games <= 0 || drops * step / HALF <= perGame * games;
    const plausible = candidates.filter(step => within(step, PLAUSIBLE_USE_PER_GAME));
    needsCheck = plausible.length !== candidates.length;
    if (plausible.length) chosen = plausible[plausible.length - 1];
    else if (candidates.length && within(candidates[0], MAX_USE_PER_GAME)) chosen = candidates[0];
  } else {
    const peakX = num(measurement.peak_x), troughX = num(measurement.trough_x), endX = num(measurement.end_x);
    let low;
    if (peakX == null || troughX == null) {
      low = peak > 0 ? peak : 0;
    } else {
      const points = [[0, 0], [peakX, peak], [troughX, trough], [endX ?? Infinity, end]]
        .map((p, i) => [...p, i]).sort((a, b) => a[0] - b[0] || a[2] - b[2]);
      low = rise(points.map(p => p[1]));
    }
    const high = (peak > 0 ? peak : 0) - (trough < 0 ? trough : 0);
    const feasible = AXIS_STEPS.filter((step, i) => {
      const unit = step / HALF;
      return fits(i) && maxHold >= low * unit * 0.98 - unit && maxHold <= high * unit * 1.3 + unit;
    });
    if (feasible.length === 1) chosen = feasible[0];
  }
  if (chosen == null) return none;
  return {value: roundHalfAway((end - END_PIXEL_CORRECTION) * chosen / HALF), needsCheck};
}

return {meruhenNetDetail};
})();
