// database 閲覧ページ（https://keyanbaitian6-cell.github.io/database-viewer/）が
// Googleドライブの最新の記録を自動で読むための、Google Apps Script。
//
// PC版が「database共有」フォルダに書く database-viewer.json（画像なし・直近60日）と、
// P’s CUBE用の pscube-viewer-drive.json の中身を返すだけで、ファイルを書き換えたり消したりはしない。
//
// 使い方（初回だけ）：
//   1. https://script.google.com で「新しいプロジェクト」を作り、このファイルの中身を貼る。
//   2. 「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」
//        次のユーザーとして実行：自分 ／ アクセスできるユーザー：全員
//   3. 初回はGoogleドライブを読む許可を求められる（自分のスクリプトなので「詳細」→
//      「（プロジェクト名）に移動」で許可してよい）。
//   4. 表示された「ウェブアプリのURL」（…/exec）を、閲覧ページの「Driveの自動読み込み」に貼る。
//
// URLを知っている人は、このファイルの中身（直近60日の記録）を読める。URLは人に教えない。
// 読ませたくなくなったら、「デプロイを管理」からこのデプロイをアーカイブする。

// 返すファイルは、名前（file=）で決まる許可リストの中からだけ選ぶ。
//   （指定なし）  → database-viewer.json   … メルヘンの閲覧ページ
//   ?file=pscube → pscube-viewer-drive.json … P’s CUBEの閲覧ページ（database/PSCUBE_SYNC.md）
// 既存のURLのまま使うには、「デプロイを管理」→ 編集 → 「新バージョン」で更新する。
// （2026-10-04：?check=1 を追加。更新しなくても閲覧ページは動くが、更新すると、変わっていないとき
//  ファイルを読み直さず、Googleの返事が固まる回数も減らせる。）
const FILES = { '': 'database-viewer.json', pscube: 'pscube-viewer-drive.json' };

function doGet(e) {
  const key = (e && e.parameter && e.parameter.file) || '';
  const fileName = Object.prototype.hasOwnProperty.call(FILES, key) ? FILES[key] : null;
  if (!fileName) return respond(JSON.stringify({ error: '指定できないファイルです。' }));
  const files = DriveApp.getFilesByName(fileName);
  let latest = null;
  while (files.hasNext()) {
    const file = files.next();
    if (file.isTrashed()) continue;
    if (!latest || file.getLastUpdated() > latest.getLastUpdated()) latest = file;
  }
  if (!latest) {
    return respond(JSON.stringify({ error: fileName + ' がGoogleドライブに見つかりません。PC版で取り込むと作られます。' }));
  }
  // ?check=1 のときは、中身を読まず「更新の目印」だけを返す（閲覧ページが、前に読んだときと
  // 同じなら、ファイルを読み直さないため）。目印はファイルの更新時刻とサイズ。
  // この形（format が drive-check）を返さない古いスクリプトには、閲覧ページは今までどおり全文を読む。
  if (e && e.parameter && e.parameter.check) {
    return respond(JSON.stringify({
      format: 'drive-check',
      version: latest.getLastUpdated().getTime() + '-' + latest.getSize(),
      name: fileName,
    }));
  }
  return respond(latest.getBlob().getDataAsString('UTF-8'));
}

function respond(body) {
  return ContentService.createTextOutput(body).setMimeType(ContentService.MimeType.JSON);
}
