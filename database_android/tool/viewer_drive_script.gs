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
//
// 確定が出た台の印🌈（2026-10-11、RAINBOW.md「iPhoneから付ける」）：閲覧ページの台の画面で付け外しした🌈を、
// 同じフォルダの database-rainbow-shared.json に足し込む（店舗・日付・台番号ごとに、付け外しした時刻の
// 新しい方が残る）。?file=rainbow で読む。PC版は同期フォルダに届いたこのファイルを読んで記録に取り込む。
// この部分を足したら、「デプロイを管理」→ 編集 →「新バージョン」で更新する（URLは変わらない）。

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
// 🌈のファイル（?file=rainbow で読む、POSTで足し込む）。
const RAINBOW_FILE = { name: 'database-rainbow-shared.json', beside: 'database-viewer.json' };
const RAINBOW_MAX = 5000;

function doGet(e) {
  const key = (e && e.parameter && e.parameter.file) || '';
  // 週の構成はPCが作り、共有で編集した記号を重ねて返す。
  if (key === 'event-history') {
    return readEventHistory();
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
  try {
    const parts = vpGet(latest, key === 'pscube' ? 'pscube' : 'meruhen', (e && e.parameter) || {});
    if (parts) return respond(JSON.stringify(parts));
  } catch (error) { return respond(JSON.stringify({error: String(error.message || error)})); }
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
  if (body.file === 'rainbow') return postRainbow(body.marks);
  if (body.file === 'event-history') return postEventHistory(body.cells);
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

// 閲覧ページからの🌈の書き込み：{file: 'rainbow', marks: [{store, day, rack, on, updated_at}]}。
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

// 付け外しした時刻のある🌈だけを受け付ける。1つでも不正なら null。
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

// BEGIN EVENT_HISTORY_SHARED
const EVENT_HISTORY_API=(function(){
// 週イベント履歴は接続先からだけ読む。公開ファイルには機種名・記号一覧を同梱しない。
const STORE = 'nagamachiminami';
const HISTORY_TYPES = ['4台構成', '半列', 'バラエティ'];
const name = s => typeof s === 'string' && s.trim().length > 0 && [...s].length <= 300 && !/[\x00-\x1f]/.test(s);
function day(s) {
  if (typeof s !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(s)) throw Error('履歴の日付が読めません。');
  const d = new Date(s + 'T00:00:00Z');
  if (s.startsWith('0000-') || !Number.isFinite(+d) || d.toISOString().slice(0,10) !== s) throw Error('履歴の日付が不正です。');
  return +d;
}
// SafariのDate.parseに小数秒の解釈を委ねず、マイクロ秒まで比較する。
const stamp = s => {
  const m = typeof s === 'string' && /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(s);
  if (!m || +m[2]>23 || +m[3]>59 || +m[4]>59) throw Error('履歴の編集時刻が不正です。');
  let offset=0;
  if(m[6]!=='Z'){
    const h=+m[6].slice(1,3), n=+m[6].slice(4,6);
    if(h>23 || n>59) throw Error('履歴の時差が不正です。');
    offset=(h*60+n)*(m[6][0]==='+'?1:-1);
  }
  return BigInt(day(m[1])+(+m[2]*3600 + +m[3]*60 + +m[4]-offset*60)*1000)*BigInt("1000") + BigInt((m[5]??'').padEnd(6,'0'));
};
const machine = (m, symbols, results = true) => {
  if (!m || !name(m.name) || !Number.isInteger(m.count) || m.count < 1 || m.count > 9999 || (m.record_name != null && !name(m.record_name))) throw Error('履歴の機種情報が読めません。');
  if (results && (!Array.isArray(m.results) || m.results.length !== 7 || m.results.some(v => typeof v !== 'string' || (v !== '' && !symbols.includes(v))))) throw Error('履歴の記号が不正です。');
  return {name:m.name, count:m.count, record_name:m.record_name ?? null, results:results ? [...m.results] : Array(7).fill('')};
};
const historyDay = (first, i) => new Date(day(first) + i * 86400000).toISOString().slice(0,10);
function parsePrivateHistory(doc) {
  if (!doc || doc.format !== 'database-event-history' || doc.version !== 1) throw Error('履歴の形式が違います。');
  const base = doc.base;
  if (!base) throw Error('履歴の反映には、PCで共有用ファイルの更新とApps Scriptの更新が必要です。');
  if (base.version !== 2 || base.store !== STORE || !Array.isArray(base.symbols) || !base.symbols.length ||
      base.symbols.some(v => !name(v) || [...v].length > 16) || new Set(base.symbols).size !== base.symbols.length || !Array.isArray(base.weeks)) throw Error('履歴の基準が読めません。');
  if (base.user_blank_days != null && !Array.isArray(base.user_blank_days)) throw Error('空欄の日付が不正です。');
  for (const d of base.user_blank_days ?? []) day(d);
  const weeks = new Map(), occupied = new Map();
  for (const w of base.weeks) {
    if (!w || !HISTORY_TYPES.includes(w.type) || new Date(day(w.from)).getUTCDay() !== 1 || day(w.to) - day(w.from) !== 6 * 86400000 || occupied.has(w.from) || !Array.isArray(w.machines)) throw Error('履歴の週が重複または不正です。');
    const machines = w.machines.map(m => machine(m, base.symbols));
    if (new Set(machines.map(m => m.name)).size !== machines.length) throw Error('機種名が重複しています。');
    weeks.set(`${w.type}|${w.from}`, {...w, machines}); occupied.set(w.from, w.type);
  }
  for (const key of ['weeks','cells','links']) if (Object.prototype.hasOwnProperty.call(doc,key) && (!Array.isArray(doc[key]) || doc[key].length > 30000)) throw Error('履歴編集の形式が違います。');
  const latest = (items, key) => {
    const values = new Map();
    for (const c of items) {
      const k = key(c), old = values.get(k);
      if (!old || stamp(c.updated_at) >= stamp(old.updated_at)) values.set(k,c);
    }
    return [...values.values()];
  };
  let rejected = Number.isInteger(doc.rejected) && doc.rejected>0 ? doc.rejected : 0;
  const definitions=[];
  for(const w of doc.weeks??[]) {
    try {
      if (!w || w.store !== STORE || w.type !== 'バラエティ' || new Date(day(w.week)).getUTCDay() !== 1 || day(w.lineup_day) < day(w.week) || day(w.lineup_day) > day(w.week) + 6*86400000 || !Array.isArray(w.machines) || (Object.prototype.hasOwnProperty.call(w,'removed') && typeof w.removed !== 'boolean') || (occupied.get(w.week) ?? 'バラエティ') !== 'バラエティ') throw Error();
      stamp(w.updated_at);
      const machines=w.machines.map(m=>machine(m,base.symbols,false));
      if (!machines.length || machines.some(m=>m.count>3) || new Set(machines.map(m=>m.name)).size!==machines.length) throw Error();
      definitions.push({...w,machines}); occupied.set(w.week,w.type);
    } catch { rejected++; }
  }
  for(const w of latest(definitions,w=>`${w.type}|${w.week}`))
    weeks.set(`${w.type}|${w.week}`,{type:w.type,from:w.week,to:historyDay(w.week,6),lineup_day:w.lineup_day,machines:w.machines,removed:w.removed});
  const names=new Set([...weeks.values()].flatMap(w=>w.machines.map(m=>m.name)));
  for (const group of ['links','cells']) {
    const valid = [];
    for (const c of doc[group] ?? []) {
      try {
        if (!c || c.store !== STORE || !name(c.machine)) throw Error();
        stamp(c.updated_at);
        const scoped=group==='cells' || Object.prototype.hasOwnProperty.call(c,'week') || Object.prototype.hasOwnProperty.call(c,'type');
        if(scoped) {
          if(!HISTORY_TYPES.includes(c.type)) throw Error();
          day(c.week);
          const w=weeks.get(`${c.type}|${c.week}`);
          if(!w || !w.machines.some(m=>m.name===c.machine)) throw Error();
        } else if(!names.has(c.machine)) throw Error();
        if (group === 'cells' && (day(c.day) < day(c.week) || day(c.day) > day(c.week) + 6*86400000 || typeof c.value !== 'string' || (c.value !== '' && !base.symbols.includes(c.value)))) throw Error();
        if (group === 'links' && c.record_name != null && !name(c.record_name)) throw Error();
        valid.push(c);
      } catch { rejected++; }
    }
    const entries=latest(valid,c=>JSON.stringify([c.type??'',c.week??'',c.machine,...(group==='cells'?[c.day]:[])]));
    // 機種共通の対応を適用してから、週ごとの対応で上書きする。
    entries.sort((a,b)=>Number(Object.prototype.hasOwnProperty.call(a,'week'))-Number(Object.prototype.hasOwnProperty.call(b,'week')));
    for(const c of entries) {
      const targets=Object.prototype.hasOwnProperty.call(c,'week')?[weeks.get(`${c.type}|${c.week}`)]:weeks.values();
      for(const w of targets) {
        const m=w.machines.find(m=>m.name===c.machine); if(!m) continue;
        if(group==='links') m.record_name=c.record_name??null;
        else m.results[(day(c.day)-day(c.week))/86400000]=c.value;
      }
    }
  }
  return {store:STORE, symbols:[...base.symbols], weeks:[...weeks.values()].filter(w => !w.removed).sort((a,b) => b.from.localeCompare(a.from)), rejected};
}
function historySavedName(m, names) {
  if (m.record_name != null) return names.has(m.record_name) ? m.record_name : null;
  const normalized = s => String(s).replaceAll('+',' ').replace(/\s+/g,' ').trim();
  const hits = [...names].filter(n => normalized(n) === normalized(m.name));
  return hits.length === 1 ? hits[0] : null;
}

const historyEditKey = c => JSON.stringify([c.store,c.type,c.week,c.machine,c.day]);

/** 共有では既存の週・機種の結果記号だけを変更できる。 */
function historyCell(raw, model) {
  if (!raw || raw.store !== STORE || !HISTORY_TYPES.includes(raw.type) || !name(raw.machine) ||
      typeof raw.value !== 'string' || !['',...model.symbols].includes(raw.value)) throw Error('履歴の記号が不正です。');
  const w = model.weeks.find(w=>w.type===raw.type && w.from===raw.week);
  if (!w || !w.machines.some(m=>m.name===raw.machine) || day(raw.day)<day(w.from) || day(raw.day)>day(w.to))
    throw Error('対象の週・機種・日付が履歴にありません。');
  stamp(raw.updated_at);
  return {store:STORE,type:raw.type,week:raw.week,machine:raw.machine,day:raw.day,value:raw.value,
    updated_at:raw.updated_at,device:['pc','android','shared'].includes(raw.device)?raw.device:'pc'};
}

/** PCの文書は書き換えず、記号の編集時刻が新しい方を重ねる。不正な原文は残す。 */
function mergeHistoryCells(doc, incoming, {strict=true}={}) {
  if (!Array.isArray(incoming) || incoming.length>30000) throw Error('履歴の件数が不正です。');
  const model=parsePrivateHistory(doc), entries=new Map(), orphans=[];
  for (const [items,check] of [[doc.cells??[],false],[incoming,strict]]) for (const raw of items) {
    try {
      const c=historyCell(raw,model), k=historyEditKey(c), old=entries.get(k);
      if (!old || stamp(c.updated_at)>=stamp(old.updated_at)) entries.set(k,c);
    } catch (e) { if(check) throw e; orphans.push(raw); }
  }
  const cells=[...entries.values(),...orphans];
  if(cells.length>30000) throw Error('履歴の保存件数の上限に達しています。');
  return {...doc,cells};
}

function newHistoryCell(doc, fields, value, now=Date.now()) {
  let time=BigInt(Math.trunc(now))*BigInt("1000");
  for(const c of doc.cells??[]) {
    if(c && historyEditKey(c)===historyEditKey({...fields,store:STORE})) {
      try { if(stamp(c.updated_at)>=time) time=stamp(c.updated_at)+BigInt("1000"); } catch { /* 原文は残す。 */ }
    }
  }
  const updated_at=new Date(Number(time/BigInt("1000"))).toISOString().replace(/\d{3}Z$/,String(time%BigInt("1000000")).padStart(6,'0')+'Z');
  return historyCell({...fields,store:STORE,value,updated_at,device:'shared'},parsePrivateHistory(doc));
}

return {parsePrivateHistory,historyCell,historyEditKey,mergeHistoryCells};
})();
// 共有ページの記号だけを保存する。PCの基準・数値記録・週の構成には書き込まない。
const HISTORY_SHARED_NAME = 'database-event-history-shared.json';
const HISTORY_PC_NAME = 'database-event-history.json';

function historyPcDocument() {
  const file=latestFile(HISTORY_PC_NAME);
  if(!file) throw new Error('PCでイベント履歴を共有へ反映してください。');
  const doc=JSON.parse(file.getBlob().getDataAsString('UTF-8'));
  EVENT_HISTORY_API.parsePrivateHistory(doc);
  return doc;
}

function historySharedDocument() {
  const file=latestFile(HISTORY_SHARED_NAME);
  if(!file) return {file:null,doc:{format:'database-event-history',version:1,cells:[],weeks:[],links:[]}};
  const doc=JSON.parse(file.getBlob().getDataAsString('UTF-8'));
  if(!doc || doc.format!=='database-event-history' || doc.version!==1 || !Array.isArray(doc.cells) || doc.cells.length>30000 ||
      !Array.isArray(doc.weeks) || doc.weeks.length || !Array.isArray(doc.links) || doc.links.length)
    throw new Error('共有の履歴ファイルを読めません。元のファイルは変更していません。');
  return {file,doc};
}

function readEventHistory() {
  try {
    const doc=EVENT_HISTORY_API.mergeHistoryCells(historyPcDocument(),historySharedDocument().doc.cells,{strict:false});
    return respond(JSON.stringify({...doc,shared_editing:true}));
  } catch(e) { return respond(JSON.stringify({error:String(e.message||e)})); }
}

function postEventHistory(cells) {
  if(!Array.isArray(cells) || !cells.length || cells.length>100)
    return respond(JSON.stringify({error:'履歴の記号は1〜100件ずつ保存してください。'}));
  const lock=LockService.getScriptLock();
  let locked=false;
  try {
    lock.waitLock(20000); locked=true;
    const pc=historyPcDocument(), model=EVENT_HISTORY_API.parsePrivateHistory(pc);
    const incoming=cells.map(c=>({...EVENT_HISTORY_API.historyCell(c,model),device:'shared'}));
    if(incoming.some(c=>Date.parse(c.updated_at)>Date.now()+5*60*1000))
      throw new Error('端末の日時が先に進んでいます。日時を確認してから再送してください。');
    const current=historySharedDocument();
    const shared=EVENT_HISTORY_API.mergeHistoryCells({...pc,cells:current.doc.cells},incoming);
    const history=EVENT_HISTORY_API.mergeHistoryCells(pc,shared.cells,{strict:false});
    const doc={format:'database-event-history',version:1,cells:shared.cells,weeks:[],links:[],updated_at:new Date().toISOString()};
    const text=JSON.stringify(doc);
    if(current.file) {
      if(JSON.stringify(shared.cells)!==JSON.stringify(current.doc.cells)) current.file.setContent(text);
    } else folderBeside(HISTORY_PC_NAME).createFile(HISTORY_SHARED_NAME,text,'application/json');
    const keptNewer=incoming.filter(c=>history.cells.some(old=>old && EVENT_HISTORY_API.historyEditKey(old)===EVENT_HISTORY_API.historyEditKey(c) && old.updated_at!==c.updated_at && old.value!==c.value)).length;
    return respond(JSON.stringify({ok:true,history:{...history,shared_editing:true},keptNewer}));
  } catch(e) { return respond(JSON.stringify({error:String(e.message||e)})); }
  finally { if(locked) lock.releaseLock(); }
}

// END EVENT_HISTORY_SHARED
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
