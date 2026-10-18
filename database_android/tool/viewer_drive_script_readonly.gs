// 閲覧専用の共有用スクリプト（お試し、2026-10-09）。人に database 閲覧ページを見せるための、
// 読むだけのGoogle Apps Script。自分用のスクリプト（tool/viewer_drive_script.gs）とは別のプロジェクトにする。
//
// 自分用と同じファイル（database-viewer.json・pscube-viewer-drive.json・共有カレンダーの
// database-events-shared.json・pscube-events-shared.json・🌈の database-rainbow-shared.json）を読んで返す。
// 送られてきたイベント（POST）は断るので、このURLを渡した人がイベントを入れても、
// 自分のカレンダー・記録・自分用スクリプトには何も届かない（入れた人の端末の中に残るだけ）。
//
// 書けるのは、確定が出た台の印🌈だけ（2026-10-11 利用者「この虹マークを付けるだけの機能なら共有の方にもつけたい」、
// RAINBOW.md「共有ページから付ける」）。共有ページで付け外しした🌈を、自分用スクリプトと同じ
// database-rainbow-shared.json に足し込む（台ごとに付け外しした時刻の新しい方。形式・件数を検査）。PC版はこのファイルを
// 取り込むので、このURLを渡した人が付け外しした🌈は自分の記録にも入る。台の数値・イベントは書き換えられない。
// この部分を足したら「デプロイを管理」→ 編集 →「新バージョン」で更新する。ファイルを書くので、Googleドライブの
// 「すべてのファイルの参照、編集、作成、削除」の許可を求められる（読むだけの許可のままだと🌈の保存が失敗する。
// そのときは自分用スクリプトの説明と同じ手順で許可し直す）。
//
// 使い方：
//   1. https://script.google.com で「新しいプロジェクト」を作り（自分用とは別）、このファイルの中身を貼る。
//      プロジェクト名は「database 閲覧専用」など、自分用と見分けられる名前にする。
//   2. 「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」
//        次のユーザーとして実行：自分 ／ アクセスできるユーザー：全員
//   3. 許可を求められたら「詳細」→「（プロジェクト名）に移動」で許可する。🌈を書くので、
//      Googleドライブの編集の許可も求められる（2026-10-11から）。
//   4. 表示された「ウェブアプリのURL」（…/exec）を相手に渡す。相手は閲覧ページ
//      （https://keyanbaitian6-cell.github.io/database-viewer/）の「Googleドライブの自動読み込み」に貼る。
//
// 渡したURLでは、直近60日の記録とイベントが読める。見せるのをやめるときは、このプロジェクトの
// 「デプロイを管理」でデプロイをアーカイブする（自分用のURLはそのまま使える）。
// 自分用のスクリプトのURLは、今までどおり人に渡さない（そちらはイベントを書き込める）。
//
// アクセスの記録（2026-10-09）：閲覧専用ページ（share_viewer/）は、最初の読み込み（メルヘンの閲覧用ファイル）にだけ
// 渡したリンクの呼び名（u=、英数字と - _ だけ）を付ける。このスクリプトはそれを console.log に書くので、
// このプロジェクトの「実行数」で、いつ・どのリンクで開かれたかを見られる（持ち主だけ。Driveには何も書かない）。
// 呼び名の無い読み込み（自分用の閲覧ページに貼った場合など）は「名前なし」。
//
// 返す中身は自分用スクリプトの doGet と同じ（閲覧ページはどちらでも同じように読める）。
// 自分用の doGet を変えたときは、こちらも合わせる（tool/test_viewer_drive_script_readonly.mjs で確かめる）。

const FILES = { '': 'database-viewer.json', pscube: 'pscube-viewer-drive.json' };
const EVENT_FILES = {
  events: { name: 'database-events-shared.json', kind: 'meruhen' },
  'pscube-events': { name: 'pscube-events-shared.json', kind: 'pscube' },
};
// 🌈のファイル（自分用スクリプトと同じ。?file=rainbow で読む、POSTで足し込む）。
const RAINBOW_FILE = { name: 'database-rainbow-shared.json', beside: 'database-viewer.json' };
const RAINBOW_MAX = 5000;
const EVENT_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$/;

function doGet(e) {
  const key = (e && e.parameter && e.parameter.file) || '';
  if (key === '' && !(e && e.parameter && (e.parameter.parts || e.parameter.check))) logAccess(e && e.parameter && e.parameter.u);
  // 履歴の書き手はPCだけ。公開共有URLからも読み取りだけを許可する。
  if (key === 'event-history') {
    const file = latestFile('database-event-history.json');
    return respond(file ? file.getBlob().getDataAsString('UTF-8') : JSON.stringify({error: 'PCでイベント履歴を共有へ反映してください。'}));
  }
  if (key === 'rainbow') {
    const file = latestFile(RAINBOW_FILE.name);
    return respond(file ? file.getBlob().getDataAsString('UTF-8') : JSON.stringify(rainbowDocument([])));
  }
  if (Object.prototype.hasOwnProperty.call(EVENT_FILES, key)) {
    const spec = EVENT_FILES[key];
    const file = latestFile(spec.name);
    return respond(file ? file.getBlob().getDataAsString('UTF-8') : JSON.stringify(eventDocument(spec.kind, [])));
  }
  const fileName = Object.prototype.hasOwnProperty.call(FILES, key) ? FILES[key] : null;
  if (!fileName) return respond(JSON.stringify({ error: '指定できないファイルです。' }));
  const latest = latestFile(fileName);
  if (!latest) {
    return respond(JSON.stringify({ error: fileName + ' がGoogleドライブに見つかりません。' }));
  }
  try {
    const parts = vpGet(latest, key === 'pscube' ? 'pscube' : 'meruhen', (e && e.parameter) || {});
    if (parts) {
      // 日別版ではcheckが閲覧1回。全件版では後続の通常GETで記録し、移行中も二重に数えない。
      if (key === '' && e && e.parameter && e.parameter.check && e.parameter.access === '1') logAccess(e.parameter.u);
      return respond(JSON.stringify(parts));
    }
  } catch (error) { return respond(JSON.stringify({error: String(error.message || error)})); }
  // ?check=1 のときは、中身を読まず「更新の目印」（更新時刻とサイズ）だけを返す（自分用と同じ）。
  if (e && e.parameter && e.parameter.check) {
    return respond(JSON.stringify({
      format: 'drive-check',
      version: latest.getLastUpdated().getTime() + '-' + latest.getSize(),
      name: fileName,
    }));
  }
  return respond(latest.getBlob().getDataAsString('UTF-8'));
}

// 閲覧専用：イベントの書き込みは受け付けない（何も読まず、何も書かない）。書けるのは🌈（{file: 'rainbow', marks}）だけ。
function doPost(e) {
  let body = null;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (_) {
    body = null;
  }
  if (body && body.file === 'rainbow') return postRainbow(body.marks);
  return respond(JSON.stringify({ error: 'このURLは閲覧専用です。イベントは共有されません（この端末の中にだけ残ります）。' }));
}

// 以下、🌈の足し込みは自分用スクリプト（viewer_drive_script.gs）と同じ（tool/test_viewer_drive_script_readonly.mjs で確かめる）。
function postRainbow(marks) {
  const incoming = validMarks(marks);
  if (!incoming) return respond(JSON.stringify({ error: '🌈の形式が不正です。' }));
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const file = latestFile(RAINBOW_FILE.name);
    let current = [];
    if (file) {
      try {
        current = validMarks(JSON.parse(file.getBlob().getDataAsString('UTF-8')).marks) || [];
      } catch (_) {
        current = [];
      }
    }
    const marksByKey = {};
    for (const m of current) marksByKey[markKey(m)] = m;
    let changed = 0;
    for (const m of incoming) {
      const old = marksByKey[markKey(m)];
      if (old && Date.parse(m.updated_at) < Date.parse(old.updated_at)) continue;
      if (old && old.on === m.on && old.updated_at === m.updated_at) continue;
      marksByKey[markKey(m)] = m;
      changed++;
    }
    const merged = Object.keys(marksByKey).sort().map(k => marksByKey[k]);
    if (changed === 0 && file) return respond(JSON.stringify({ ok: true, marks: merged.length, changed: 0 }));
    const text = JSON.stringify(rainbowDocument(merged));
    if (file) file.setContent(text);
    else folderBeside(RAINBOW_FILE.beside).createFile(RAINBOW_FILE.name, text, 'application/json');
    return respond(JSON.stringify({ ok: true, marks: merged.length, changed: changed }));
  } finally {
    lock.releaseLock();
  }
}

function rainbowDocument(marks) {
  return { format: 'database-rainbow', version: 1, updated_at: new Date().toISOString(), marks: marks };
}

function markKey(m) {
  return m.store + '|' + m.day + '|' + ('00000' + m.rack).slice(-5);
}

function validMarks(marks) {
  if (!Array.isArray(marks) || marks.length > RAINBOW_MAX) return null;
  const result = [];
  for (const m of marks) {
    if (!m || typeof m !== 'object') return null;
    if (typeof m.store !== 'string' || !/^[a-z0-9]{1,40}$/.test(m.store)) return null;
    if (typeof m.day !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(m.day)) return null;
    if (typeof m.rack !== 'number' || !Number.isInteger(m.rack) || m.rack < 1 || m.rack > 99999) return null;
    if (typeof m.on !== 'boolean') return null;
    if (typeof m.updated_at !== 'string' || !EVENT_TIME.test(m.updated_at) || isNaN(Date.parse(m.updated_at))) return null;
    result.push({ store: m.store, day: m.day, rack: m.rack, on: m.on, updated_at: m.updated_at });
  }
  return result;
}

// 閲覧用ファイルと同じフォルダ（database共有）。見つからなければマイドライブの一番上。
function folderBeside(name) {
  const file = latestFile(name);
  const parents = file ? file.getParents() : null;
  return parents && parents.hasNext() ? parents.next() : DriveApp.getRootFolder();
}

function logAccess(raw) {
  const name = typeof raw === 'string' && /^[A-Za-z0-9_-]{1,40}$/.test(raw) ? raw : '名前なし';
  console.log('閲覧：' + name);
}

function eventDocument(kind, events) {
  return { format: 'database-events', version: 1, kind: kind, updated_at: new Date().toISOString(), events: events };
}

function latestFile(name) {
  const files = DriveApp.getFilesByName(name);
  let latest = null;
  while (files.hasNext()) {
    const file = files.next();
    if (file.isTrashed()) continue;
    if (!latest || file.getLastUpdated() > latest.getLastUpdated()) latest = file;
  }
  return latest;
}

function respond(body) {
  return ContentService.createTextOutput(body).setMimeType(ContentService.MimeType.JSON);
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
  return m;
}
function vpPublic(m) {
  return {format: m.format, version: m.version, site: m.site, revision: m.revision,
    header: m.header, count: m.count, ...(m.version === 2 ? {days: m.days, history: true} : {}),
    parts: m.parts.map(({hash, day, count, bytes}) => ({hash, day, count, bytes}))};
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
  // 旧クライアントの全件GETを無制限に組み立てない。新版はcheckとパーツを使う。
  if (manifest.version === 2 && (manifest.count > 100000 || manifest.parts.reduce((n, p) => n + p.bytes, 0) > VP_MAX_BYTES)) {
    throw new Error('履歴データは新しい閲覧ページで開いてください（全件GETの上限を超えています）。');
  }
  return {...manifest.header, ...(manifest.version === 2 ? {history: true} : {}), records: manifest.parts.flatMap(p => vpRows(vpReadPart(site, p), p))};
}
