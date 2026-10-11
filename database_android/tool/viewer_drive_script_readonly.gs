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
  if (key === '' && !(e && e.parameter && e.parameter.check)) logAccess(e && e.parameter && e.parameter.u);
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
