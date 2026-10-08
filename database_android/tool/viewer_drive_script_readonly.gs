// 閲覧専用の共有用スクリプト（お試し、2026-10-09）。人に database 閲覧ページを見せるための、
// 読むだけのGoogle Apps Script。自分用のスクリプト（tool/viewer_drive_script.gs）とは別のプロジェクトにする。
//
// 自分用と同じファイル（database-viewer.json・pscube-viewer-drive.json・共有カレンダーの
// database-events-shared.json・pscube-events-shared.json）を読んで返すだけで、何も書かない。
// 送られてきたイベント（POST）は断るので、このURLを渡した人がイベントを入れても、
// 自分のカレンダー・記録・自分用スクリプトには何も届かない（入れた人の端末の中に残るだけ）。
//
// 使い方：
//   1. https://script.google.com で「新しいプロジェクト」を作り（自分用とは別）、このファイルの中身を貼る。
//      プロジェクト名は「database 閲覧専用」など、自分用と見分けられる名前にする。
//   2. 「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」
//        次のユーザーとして実行：自分 ／ アクセスできるユーザー：全員
//   3. 許可を求められたら「詳細」→「（プロジェクト名）に移動」で許可する。読むだけなので、
//      求められるのはGoogleドライブを「参照」する許可だけ（自分用のような編集の許可は要らない）。
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

function doGet(e) {
  const key = (e && e.parameter && e.parameter.file) || '';
  if (key === '' && !(e && e.parameter && e.parameter.check)) logAccess(e && e.parameter && e.parameter.u);
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

// 閲覧専用：イベントの書き込みは受け付けない（何も読まず、何も書かない）。
function doPost(_e) {
  return respond(JSON.stringify({ error: 'このURLは閲覧専用です。イベントは共有されません（この端末の中にだけ残ります）。' }));
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
