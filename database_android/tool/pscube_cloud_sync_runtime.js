// P’s CUBE PC不要同期。build_pscube_cloud_sync.mjs で検証済みの共通パーサーと結合する。
// 配布するのは pscube_cloud_sync.gs（別のApps Scriptプロジェクトに全文を貼る）。

// 通常は空欄のまま。共有フォルダが複数ある場合だけ、対象フォルダのIDを入れる。
const PSCUBE_FOLDER_ID = '';
const PSCUBE_CLOUD_BACKUP = 'pscube-backup-cloud.json';
const PSCUBE_CLOUD_VIEWER = 'pscube-viewer-drive.json';
// 両ページ用Apps Scriptの更新後にtrueへ変更（VIEWER_INCREMENTAL_SYNC.md）。
const PSCUBE_INCREMENTAL_VIEWER = false;
// 履歴方式（日別に保存。VIEWER_HISTORY_SYNC.md）。初期値 true（2026-11-07 利用者「trueのほうがよさそう」→ 初期値を変更。利用者のGoogleプロジェクトは10月から true で運用中で、貼り替えのたびに1行を直していた）。
const PSCUBE_HISTORY_VIEWER = true;
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
const PSCUBE_CLOUD_RULES = '2026-11-08-site777-final';
// 書き出しの一時的な失敗（429・5xx・通信の例外）は、同じ実行の中でこの回数まで少し待って試す（1秒・2秒）。
const PSCUBE_CLOUD_WRITE_TRIES = 3;

/** Driveの一時的な障害（読み出しの例外）。入力の不正とは分け、失敗として記録せずに次の実行でやり直す。 */
class PscubeCloudTransient extends Error {}

// Google Apps ScriptにはブラウザのURLクラスがないため、共通パーサーが使う部分を実装する。
// P’s CUBEのページ、アナスロの出典、サイトセブンのP-STATION全台表の出典だけを検証する。
// 出典URLをここから取得する処理はない。
// 出典を拒むと、アナスロの記録を含むPCの閲覧用ファイル全体が取り込めなくなる（2026-10-18、10/17以降が共有に出なかった）。
class PscubeCloudUrl {
  constructor(raw) {
    if (typeof raw !== 'string') throw new Error('P’s CUBEのリンクが不正です。');
    const anaslo = raw.match(/^https:\/\/ana-slo\.com(\/[^?#\s]*)(?:\?([^#]*))?(#.*)?$/);
    const site777 = raw.match(/^https:\/\/m\.site777\.jp(\/f\/D3300\.do)(?:\?([^#]*))?(#.*)?$/);
    const match = anaslo || site777 || raw.match(/^https:\/\/www\.pscube\.jp(\/dedamajyoho-P-townDMMpachi\/c\d+\/cgi-bin\/nc-v(?:03-001|05-011|06-001)\.php)(?:\?([^#]*))?(#.*)?$/);
    if (!match) throw new Error('P’s CUBEのリンクが不正です。');
    this.origin = anaslo ? 'https://ana-slo.com' : site777 ? 'https://m.site777.jp' : 'https://www.pscube.jp';
    this.username = this.password = '';
    this.pathname = match[1]; this.hash = match[3] || ''; this.href = raw;
    const params = new Map(), all = new Map();
    for (const pair of (match[2] || '').split('&')) {
      if (!pair) continue;
      const at = pair.indexOf('=');
      const decode = s => decodeURIComponent(s.replace(/\+/g, ' '));
      const key = decode(at < 0 ? pair : pair.slice(0, at));
      const value=decode(at < 0 ? '' : pair.slice(at + 1));
      if (!params.has(key)) params.set(key, value);
      if (!all.has(key)) all.set(key,[]);
      all.get(key).push(value);
    }
    this.searchParams = {get: key => params.has(key) ? params.get(key) : null, has: key => params.has(key),getAll:key=>all.get(key)||[]};
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
/** 履歴方式（PSCUBE_HISTORY_VIEWER）を本当に切り替えるときだけ実行（2026-11-05）。次の同期で今の値を覚える。 */
function changePscubeCloudMode() {
  PropertiesService.getScriptProperties().deleteProperty('pscubeCloudMode');
  return '次の同期で、今の PSCUBE_HISTORY_VIEWER の値を覚えます。';
}

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
    const modeProblem = vhModeProblem(folder, 'pscube', props, PSCUBE_HISTORY_VIEWER, 'PSCUBE_HISTORY_VIEWER', 'changePscubeCloudMode');
    if (modeProblem) throw new PscubeCloudStop('config', modeProblem);
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
