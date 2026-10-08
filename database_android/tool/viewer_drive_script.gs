// database 閲覧ページ（https://keyanbaitian6-cell.github.io/database-viewer/）が
// Googleドライブの最新の記録を自動で読むための、Google Apps Script。
//
// PC版が「database共有」フォルダに書く database-viewer.json（画像なし・直近60日）と、
// P’s CUBE用の pscube-viewer-drive.json の中身を返す。書くのは共有カレンダーのファイル（下）だけで、
// 記録のファイルを書き換えたり消したりはしない。
//
// 使い方（初回だけ）：
//   1. https://script.google.com で「新しいプロジェクト」を作り、このファイルの中身を貼る。
//   2. 「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」
//        次のユーザーとして実行：自分 ／ アクセスできるユーザー：全員
//   3. 初回はGoogleドライブの許可を求められる（自分のスクリプトなので「詳細」→
//      「（プロジェクト名）に移動」で許可してよい）。共有カレンダーのファイルを書くので、
//      「すべてのファイルの参照、編集、作成、削除」の許可が要る。読むだけの許可のまま残っていると
//      POSTが「DriveApp.Folder.createFile を呼び出す権限がありません」で失敗する。そのときは
//      Googleアカウントの「サードパーティ製のアプリとサービス」でこのプロジェクトの接続を削除し、
//      エディタで doGet を一度実行して許可し直してから、「新バージョン」でデプロイし直す（2026-10-08）。
//   4. 表示された「ウェブアプリのURL」（…/exec）を、閲覧ページの「Driveの自動読み込み」に貼る。
//
// URLを知っている人は、このファイルの中身（直近60日の記録）を読める。URLは人に教えない。
// 読ませたくなくなったら、「デプロイを管理」からこのデプロイをアーカイブする。
//
// 共有カレンダー（2026-10-08、EVENT_CALENDAR.md）：閲覧ページで入れたイベントを、このスクリプトが
// 「database共有」フォルダの database-events-shared.json（メルヘン）・pscube-events-shared.json（P’s CUBE）に
// 足し込む（入力時刻の新しい方が残る）。PC版は同期フォルダに届いたこのファイルを読んで取り込む。
// 合言葉は付けない（利用者の選択、2026-10-08）。URLを知っている人はイベントを書き込める（台の記録は
// 書き換えられない。形式と件数は検査する）。URLは人に教えない。

// 返すファイルは、名前（file=）で決まる許可リストの中からだけ選ぶ。
//   （指定なし）  → database-viewer.json   … メルヘンの閲覧ページ
//   ?file=pscube → pscube-viewer-drive.json … P’s CUBEの閲覧ページ（database/PSCUBE_SYNC.md）
// 既存のURLのまま使うには、「デプロイを管理」→ 編集 → 「新バージョン」で更新する。
// （2026-10-04：?check=1 を追加。更新しなくても閲覧ページは動くが、更新すると、変わっていないとき
//  ファイルを読み直さず、Googleの返事が固まる回数も減らせる。）
const FILES = { '': 'database-viewer.json', pscube: 'pscube-viewer-drive.json' };
// 共有カレンダーのファイル（?file=events・?file=pscube-events で読む、POSTで足し込む）と、置く場所の目印。
const EVENT_FILES = {
  events: { name: 'database-events-shared.json', kind: 'meruhen', beside: 'database-viewer.json' },
  'pscube-events': { name: 'pscube-events-shared.json', kind: 'pscube', beside: 'pscube-viewer-drive.json' },
};
const EVENT_MAX = 5000;

function doGet(e) {
  const key = (e && e.parameter && e.parameter.file) || '';
  if (Object.prototype.hasOwnProperty.call(EVENT_FILES, key)) {
    const spec = EVENT_FILES[key];
    const file = latestFile(spec.name);
    return respond(file ? file.getBlob().getDataAsString('UTF-8') : JSON.stringify(eventDocument(spec.kind, [])));
  }
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

// 閲覧ページからのイベントの書き込み：{file: 'events'|'pscube-events', events: [...]}。
function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (_) {
    return respond(JSON.stringify({ error: '送られてきた内容が読めません。' }));
  }
  if (!body || typeof body !== 'object') return respond(JSON.stringify({ error: '送られてきた内容が読めません。' }));
  const spec = Object.prototype.hasOwnProperty.call(EVENT_FILES, body.file) ? EVENT_FILES[body.file] : null;
  if (!spec) return respond(JSON.stringify({ error: '指定できないファイルです。' }));
  const incoming = validEvents(body.events, spec.kind === 'pscube');
  if (!incoming) return respond(JSON.stringify({ error: 'イベントの形式が不正です。' }));
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const file = latestFile(spec.name);
    let current = [];
    if (file) {
      try {
        current = validEvents(JSON.parse(file.getBlob().getDataAsString('UTF-8')).events, spec.kind === 'pscube') || [];
      } catch (_) {
        current = [];
      }
    }
    const merged = mergeEvents(current, incoming);
    const text = JSON.stringify(eventDocument(spec.kind, merged.events));
    if (merged.changed === 0 && file) return respond(JSON.stringify({ ok: true, events: merged.events.length, changed: 0 }));
    if (file) file.setContent(text);
    else folderBeside(spec.beside).createFile(spec.name, text, 'application/json');
    return respond(JSON.stringify({ ok: true, events: merged.events.length, changed: merged.changed }));
  } finally {
    lock.releaseLock();
  }
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

// 閲覧用ファイルと同じフォルダ（database共有）。見つからなければマイドライブの一番上。
function folderBeside(name) {
  const file = latestFile(name);
  const parents = file ? file.getParents() : null;
  return parents && parents.hasNext() ? parents.next() : DriveApp.getRootFolder();
}

const EVENT_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$/;

// 入力時刻のあるイベントだけを受け付ける（各端末の date_events と同じ形）。1つでも不正なら null。
function validEvents(events, pscube) {
  if (!Array.isArray(events) || events.length > EVENT_MAX) return null;
  const result = [];
  for (const e of events) {
    if (!e || typeof e !== 'object') return null;
    if (typeof e.store !== 'string' || !/^[a-z0-9]{1,40}$/.test(e.store)) return null;
    if (typeof e.day !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(e.day)) return null;
    if (typeof e.updated_at !== 'string' || !EVENT_TIME.test(e.updated_at) || isNaN(Date.parse(e.updated_at))) return null;
    if (pscube && (typeof e.rate !== 'string' || !/^\d+(\.\d+)?$/.test(e.rate))) return null;
    const name = e.name === null ? null : typeof e.name === 'string' ? e.name.trim() : undefined;
    if (name === undefined || (name !== null && (!name || name.length > 60 || /[\u0000-\u001f\u007f]/.test(name)))) return null;
    const event = { store: e.store, day: e.day, name: name, updated_at: e.updated_at };
    if (pscube) event.rate = e.rate;
    result.push(event);
  }
  return result;
}

function eventKey(e) {
  return e.store + '|' + (e.rate === undefined ? '' : e.rate) + '|' + e.day;
}

// 同じ店舗・（貸玉・）日付は入力時刻の新しい方、同じなら送られてきた方（各端末の統合と同じ規則）。
function mergeEvents(current, incoming) {
  const events = {};
  for (const e of current) events[eventKey(e)] = e;
  let changed = 0;
  for (const e of incoming) {
    const old = events[eventKey(e)];
    if (old && Date.parse(e.updated_at) < Date.parse(old.updated_at)) continue;
    if (old && old.name === e.name && old.updated_at === e.updated_at) continue;
    events[eventKey(e)] = e;
    changed++;
  }
  return { events: Object.keys(events).sort().map(k => events[k]), changed: changed };
}

function respond(body) {
  return ContentService.createTextOutput(body).setMimeType(ContentService.MimeType.JSON);
}
