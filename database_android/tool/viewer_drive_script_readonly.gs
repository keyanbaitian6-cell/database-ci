// 閲覧専用の共有用スクリプト（お試し、2026-10-09）。人に database 閲覧ページを見せるための、
// 読むだけのGoogle Apps Script。自分用のスクリプト（tool/viewer_drive_script.gs）とは別のプロジェクトにする。
//
// 自分用と同じファイル（database-viewer.json・pscube-viewer-drive.json・共有カレンダーの
// database-events-shared.json・pscube-events-shared.json・🌈の database-rainbow-shared.json）を読んで返す。
// 送られてきたイベント（POST）は断るので、このURLを渡した人がイベントを入れても、
// 自分のカレンダー・記録・自分用スクリプトには何も届かない（入れた人の端末の中に残るだけ）。
//
// 書けるのは、確定が出た台の印🌈と、既存のイベント履歴の結果記号（2026-10-20利用者指定）。
// 履歴の記号は database-event-history-shared.json に保存し、PCの週の構成・台の数値は変更しない。
// 確定が出た台の印🌈（2026-10-11 利用者「この虹マークを付けるだけの機能なら共有の方にもつけたい」、
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
// 1回の要求と保存全体の上限を分ける。古い印・外した印も削らない。
const RAINBOW_MAX = 5000;
const RAINBOW_STORED_MAX = 100000;
const EVENT_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$/;

function doGet(e) {
  if (e?.parameter?.file === 'diagnostic') return respond(JSON.stringify({format:'database-release', release:SCRIPT_RELEASE, capabilities:['rainbow-storage-v2','recommendation-results','remote-curves']}));
  const key = (e && e.parameter && e.parameter.file) || '';
  if (key === '' && !(e && e.parameter && (e.parameter.parts || e.parameter.check))) logAccess(e && e.parameter && e.parameter.u);
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

// イベント名の書き込みは受け付けない。🌈と既存週表の結果記号だけを保存する。
function doPost(e) {
  let body = null;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (_) {
    body = null;
  }
  if (body && body.file === 'rainbow') return postRainbow(body.marks);
  if (body && body.file === 'event-history') return postEventHistory(body.cells,body.recommendations,body.recommendation_results);
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
        const saved = JSON.parse(file.getBlob().getDataAsString('UTF-8'));
        current = saved && saved.format === 'database-rainbow' && saved.version === 1
          ? validMarks(saved.marks, Infinity) : null;
      } catch (_) {
        current = null;
      }
      if (!current) return respond(JSON.stringify({error: '保存済みの🌈を確認できません。元のファイルを保持して送信を止めました。'}));
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
    if (merged.length > RAINBOW_STORED_MAX) return respond(JSON.stringify({error: '共有の🌈が保存上限に達しました。元のファイルと端末の印を保持しています。'}));
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

function validMarks(marks, max = RAINBOW_MAX) {
  if (!Array.isArray(marks) || marks.length > max) return null;
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

// BEGIN EVENT_HISTORY_SHARED
const EVENT_HISTORY_API=(function(){
// 週イベント履歴は接続先からだけ読む。公開ファイルには機種名・記号一覧を同梱しない。
const STORE = 'nagamachiminami';
const HISTORY_TYPES = ['4台構成', '半列', 'バラエティ'];

// 表示週の最終記録日を基準に5暦日を見る。空欄は日数に含み、前週の評価も参照する。
function historyGradeGap(weeks, machine, lastDay) {
  if (!lastDay) return false;
  const end = day(lastDay);
  for (let offset = 0; offset < 5; offset++) {
    const target = new Date(end - offset * 86400000).toISOString().slice(0, 10);
    for (const week of weeks) {
      if (week.type !== 'バラエティ' || target < week.from || target > week.to) continue;
      const saved = week.machines.find(m => m.name === machine.name ||
        (machine.record_name && m.record_name === machine.record_name));
      const value = saved?.results[Math.round((day(target) - day(week.from)) / 86400000)];
      if (value === '優' || value === '良') return false;
    }
  }
  return true;
}
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
function parsePrivateHistory(doc, store = STORE) {
  if (![STORE, 'saiwaichou'].includes(store)) throw Error('対応していない店舗です。');
  const types = store === STORE ? HISTORY_TYPES : ['バラエティ'];
  const maxRacks = store === STORE ? 3 : 2;
  if (!doc || doc.format !== 'database-event-history' || doc.version !== 1) throw Error('履歴の形式が違います。');
  const base = doc.base;
  if (!base) throw Error('履歴の反映には、PCで共有用ファイルの更新とApps Scriptの更新が必要です。');
  if (base.version !== 2 || base.store !== store || !Array.isArray(base.symbols) || !base.symbols.length ||
      base.symbols.some(v => !name(v) || [...v].length > 16) || new Set(base.symbols).size !== base.symbols.length || !Array.isArray(base.weeks)) throw Error('履歴の基準が読めません。');
  if (store === 'saiwaichou' && JSON.stringify(base.symbols)!==JSON.stringify(['優','良'])) throw Error('幸町の評価は優・良だけです。');
  if (base.user_blank_days != null && !Array.isArray(base.user_blank_days)) throw Error('空欄の日付が不正です。');
  for (const d of base.user_blank_days ?? []) day(d);
  const weeks = new Map(), occupied = new Map();
  for (const w of base.weeks) {
    if (!w || !types.includes(w.type) || new Date(day(w.from)).getUTCDay() !== 1 || day(w.to) - day(w.from) !== 6 * 86400000 || occupied.has(w.from) || !Array.isArray(w.machines)) throw Error('履歴の週が重複または不正です。');
    const machines = w.machines.map(m => machine(m, base.symbols));
    if (store === 'saiwaichou' && machines.some(m=>m.count>2)) throw Error('幸町のバラエティは1〜2台機種です。');
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
      if (!w || w.store !== store || w.type !== 'バラエティ' || new Date(day(w.week)).getUTCDay() !== 1 || day(w.lineup_day) < day(w.week) || day(w.lineup_day) > day(w.week) + 6*86400000 || !Array.isArray(w.machines) || (Object.prototype.hasOwnProperty.call(w,'removed') && typeof w.removed !== 'boolean') || (occupied.get(w.week) ?? 'バラエティ') !== 'バラエティ') throw Error();
      stamp(w.updated_at);
      const machines=w.machines.map(m=>machine(m,base.symbols,false));
      if (!machines.length || machines.some(m=>m.count>maxRacks) || new Set(machines.map(m=>m.name)).size!==machines.length) throw Error();
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
        if (!c || c.store !== store || !name(c.machine)) throw Error();
        stamp(c.updated_at);
        const scoped=group==='cells' || Object.prototype.hasOwnProperty.call(c,'week') || Object.prototype.hasOwnProperty.call(c,'type');
        if(scoped) {
          if(!types.includes(c.type)) throw Error();
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
  return {store, symbols:[...base.symbols], weeks:[...weeks.values()].filter(w => !w.removed).sort((a,b) => b.from.localeCompare(a.from)), rejected};
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

// 長町南の4大オススメ。既存の週表・結果記号と独立した4枠を週ごとに保存する。
const RECOMMENDATION_TYPE = '4大オススメ';
const RECOMMENDATION_DEFAULT = {
  store:'nagamachiminami', week:'2026-10-26',
  machines:['L 甲鉄城のｶﾊﾞﾈﾘ 海門決戦 XX','L戦国乙女5L8','L戦国乙女4S3','Lﾓﾝｷｰﾀｰﾝ5CE'],
  updated_at:'2026-10-24T00:00:00Z',device:'pc',
};
function recommendationWeek(raw) {
  if(typeof raw!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(raw)) throw Error('週開始日は月曜日を指定してください。');
  const d=new Date(raw+'T00:00:00Z');
  if(!Number.isFinite(+d)||d.toISOString().slice(0,10)!==raw||d.getUTCDay()!==1||raw.startsWith('0000')) throw Error('週開始日は月曜日を指定してください。');
  return raw;
}
const recommendationDays = week => Array.from({length:7},(_,i)=>new Date(Date.parse(recommendationWeek(week)+'T00:00:00Z')+i*86400000).toISOString().slice(0,10));
const validName=n=>typeof n==='string'&&n.trim().length>0&&[...n].length<=300&&!/[\x00-\x1f]/.test(n);
const normal=n=>n.replaceAll('+',' ').replace(/\s+/g,'').toLowerCase();
function recommendationPlan(raw) {
  if(!raw||raw.store!=='nagamachiminami'||!Array.isArray(raw.machines)||raw.machines.length!==4||raw.machines.some(n=>!validName(n))||new Set(raw.machines.map(normal)).size!==4) throw Error('異なる4機種を選んでください。');
  recommendationWeek(raw.week);
  if(typeof raw.updated_at!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(raw.updated_at)) throw Error('4機種の編集時刻が不正です。');
  const at=raw.updated_at.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/);
  const date=new Date(at[1]+'T00:00:00Z');
  if(!Number.isFinite(+date)||date.toISOString().slice(0,10)!==at[1]||at[1].startsWith('0000')||+at[2]>23||+at[3]>59||+at[4]>59||(at[5]!=='Z'&&(+at[5].slice(1,3)>23||+at[5].slice(4,6)>59)))throw Error('4機種の編集時刻が不正です。');
  return {store:raw.store,week:raw.week,machines:[...raw.machines],updated_at:raw.updated_at,device:['pc','android','shared'].includes(raw.device)?raw.device:'pc'};
}
// 小数秒6桁の編集順を落とさず比較する（Apps Scriptの生成時にも使用）。
const recommendationStamp = s => {
  const m = typeof s === 'string' && /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(s);
  if (!m || +m[2]>23 || +m[3]>59 || +m[4]>59) throw Error('履歴の編集時刻が不正です。');
  let offset=0;
  if(m[6]!=='Z'){
    const h=+m[6].slice(1,3), n=+m[6].slice(4,6);
    if(h>23 || n>59) throw Error('履歴の時差が不正です。');
    offset=(h*60+n)*(m[6][0]==='+'?1:-1);
  }
  return BigInt(Date.parse(m[1]+'T00:00:00Z')+(+m[2]*3600 + +m[3]*60 + +m[4]-offset*60)*1000)*BigInt("1000") + BigInt((m[5]??'').padEnd(6,'0'));
};
const time=p=>recommendationStamp(p.updated_at);
function mergeRecommendations(stored=[],incoming=[],{strict=true}={}) {
  if(!Array.isArray(stored)||!Array.isArray(incoming)||stored.length>3000||incoming.length>3000) throw Error('4機種の週一覧が不正です。');
  const plans=new Map(),orphans=[];
  for(const [items,check] of [[stored,false],[incoming,strict]]) for(const raw of items) {
    try {const p=recommendationPlan(raw),old=plans.get(p.week);if(!old||time(p)>=time(old)) plans.set(p.week,p);}
    catch(e){if(check) throw e;orphans.push(raw);}
  }
  const result=[...plans.values()].sort((a,b)=>b.week.localeCompare(a.week)).concat(orphans);
  if(result.length>3000) throw Error('4機種の週一覧が上限に達しています。');
  return result;
}
function recommendationPlans(raw=[]) {
  return mergeRecommendations([RECOMMENDATION_DEFAULT],raw,{strict:false}).flatMap(p=>{try{return [recommendationPlan(p)];}catch{return [];}});
}
function recommendationName(selected,names) {
  if(names.includes(selected))return selected;
  const hits=names.filter(n=>normal(n)===normal(selected));
  return hits.length===1?hits[0]:null;
}
function recommendationCandidates(records,week) {
  const end=recommendationDays(week)[6];
  const rows=records.filter(r=>r.store==='nagamachiminami'&&r.day<=end);
  const day=rows.map(r=>r.day).sort().at(-1)??null,groups=new Map();
  for(const r of rows)if(r.day===day){if(!groups.has(r.machine))groups.set(r.machine,new Set());groups.get(r.machine).add(r.rack);}
  return {day,machines:[...groups].filter(([,racks])=>racks.size>=7).map(([name,racks])=>({name,count:racks.size})).sort((a,b)=>a.name.localeCompare(b.name,'ja'))};
}
function recommendationRows(records,week,selected) {
  const days=recommendationDays(week),rows=records.filter(r=>r.store==='nagamachiminami'&&days.includes(r.day));
  const names=new Map(days.map(day=>[day,recommendationName(selected,[...new Set(rows.filter(r=>r.day===day).map(r=>r.machine))]) ]));
  const cells=rows.filter(r=>r.machine===names.get(r.day)),racks=[...new Set(cells.map(r=>r.rack))].sort((a,b)=>a-b);
  // 同一日に同じ台が重複していたら、どちらかを推測で採用しない。
  return racks.map(rack=>({rack,cells:days.map(day=>{const hits=cells.filter(r=>r.rack===rack&&r.day===day);return hits.length===1?hits[0]:null;})}));
}
function recommendationFace(net) {
  return typeof net!=='number'||!Number.isFinite(net)?'':net>=3000?'😍':net>=1000?'😀':net>=0?'😌':'🥶';
}

const RECOMMENDATION_FACES=['😀','😍','🥶','😌','😇'];
const recommendationResultKey=r=>JSON.stringify([r?.store,r?.week,r?.machine,r?.rack,r?.day]);
function recommendationResult(raw) {
  if(!raw||typeof raw!=='object'||!['store','week','machine','rack','day','value','updated_at'].every(k=>Object.prototype.hasOwnProperty.call(raw,k)))throw Error('台ごとの顔文字が不正です。');
  // 店舗・週・時刻の検証は構成と同じ。結果から機種構成を変更することはない。
  recommendationPlan({...RECOMMENDATION_DEFAULT,...raw,machines:RECOMMENDATION_DEFAULT.machines});
  if(!validName(raw.machine)||!Number.isSafeInteger(raw.rack)||raw.rack<0||raw.rack>99999||!recommendationDays(raw.week).includes(raw.day)||![null,'',...RECOMMENDATION_FACES].includes(raw.value))throw Error('台ごとの顔文字が不正です。');
  return {store:raw.store,week:raw.week,machine:raw.machine,rack:raw.rack,day:raw.day,value:raw.value,updated_at:raw.updated_at,device:['pc','android','shared'].includes(raw.device)?raw.device:'pc'};
}
function mergeRecommendationResults(stored=[],incoming=[],{strict=true}={}) {
  if(!Array.isArray(stored)||!Array.isArray(incoming)||stored.length>30000||incoming.length>30000)throw Error('台ごとの結果一覧が不正です。');
  const results=new Map(),orphans=[];
  for(const [items,check] of [[stored,false],[incoming,strict]])for(const raw of items){
    try {const r=recommendationResult(raw),k=recommendationResultKey(r),old=results.get(k);if(!old||time(r)>=time(old))results.set(k,r);}
    catch(e){if(check)throw e;orphans.push(raw);}
  }
  const out=[...results.values()].sort((a,b)=>recommendationResultKey(a).localeCompare(recommendationResultKey(b))).concat(orphans);
  if(out.length>30000)throw Error('台ごとの結果一覧が上限に達しています。');
  return out;
}
function recommendationResultValue(results,fields,automatic) {
  const key=recommendationResultKey(fields);
  const r=mergeRecommendationResults(results,[],{strict:false}).find(r=>{try{return recommendationResultKey(recommendationResult(r))===key;}catch{return false;}});
  return !r||r.value===null?automatic:r.value;
}

const recommendationNotOlder=(a,b)=>time(a)>=time(b);

const recommendationEditMs=r=>Number(time(recommendationResult(r)) / BigInt("1000"));

return {parsePrivateHistory,historyCell,historyEditKey,mergeHistoryCells,mergeRecommendations,recommendationPlan,recommendationPlans,mergeRecommendationResults,recommendationResult};
})();
// 共有ページの記号だけを保存する。4大オススメも構成はPCのみ、台ごとの顔文字は共有で編集する。
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
      !Array.isArray(doc.weeks) || doc.weeks.length || !Array.isArray(doc.links) || doc.links.length ||
      (doc.recommendations != null && (!Array.isArray(doc.recommendations) || doc.recommendations.length>3000)) ||
      (doc.recommendation_results != null && (!Array.isArray(doc.recommendation_results) || doc.recommendation_results.length>30000)))
    throw new Error('共有の履歴ファイルを読めません。元のファイルは変更していません。');
  return {file,doc};
}

function readEventHistory() {
  try {
    const pc=historyPcDocument(), shared=historySharedDocument().doc;
    const doc=EVENT_HISTORY_API.mergeHistoryCells(pc,shared.cells,{strict:false});
    const recommendation_results=EVENT_HISTORY_API.mergeRecommendationResults(pc.recommendation_results??[],shared.recommendation_results??[],{strict:false});
    return respond(JSON.stringify({...doc,recommendation_results,shared_editing:true,recommendations_editing:false,recommendation_results_editing:true}));
  } catch(e) { return respond(JSON.stringify({error:String(e.message||e)})); }
}

function postEventHistory(cells=[],recommendations=[],results=[]) {
  if(!Array.isArray(recommendations) || recommendations.length)
    return respond(JSON.stringify({error:'イベントの機種構成はPCで変更してください。'}));
  if(!Array.isArray(cells) || !Array.isArray(results) || cells.length+results.length<1 || cells.length+results.length>100)
    return respond(JSON.stringify({error:'結果記号は1〜100件ずつ保存してください。'}));
  const lock=LockService.getScriptLock();
  let locked=false;
  try {
    lock.waitLock(20000); locked=true;
    const pc=historyPcDocument(), model=EVENT_HISTORY_API.parsePrivateHistory(pc);
    const incoming=cells.map(c=>({...EVENT_HISTORY_API.historyCell(c,model),device:'shared'}));
    const plans=EVENT_HISTORY_API.recommendationPlans(pc.recommendations??[]);
    const selected=results.map(raw=>{
      const r=EVENT_HISTORY_API.recommendationResult(raw);
      if(!plans.some(p=>p.week===r.week && p.machines.includes(r.machine)))throw new Error('対象の週・機種が4大オススメの選定にありません。');
      return {...r,device:'shared'};
    });
    if([...incoming,...selected].some(c=>Date.parse(c.updated_at)>Date.now()+5*60*1000))
      throw new Error('端末の日時が先に進んでいます。日時を確認してから再送してください。');
    const current=historySharedDocument();
    const shared=EVENT_HISTORY_API.mergeHistoryCells({...pc,cells:current.doc.cells},incoming);
    const history=EVENT_HISTORY_API.mergeHistoryCells(pc,shared.cells,{strict:false});
    const savedResults=EVENT_HISTORY_API.mergeRecommendationResults(current.doc.recommendation_results??[],selected);
    history.recommendation_results=EVENT_HISTORY_API.mergeRecommendationResults(pc.recommendation_results??[],savedResults,{strict:false});
    const doc={...current.doc,format:'database-event-history',version:1,cells:shared.cells,weeks:[],links:[],recommendation_results:savedResults,updated_at:new Date().toISOString()};
    const text=JSON.stringify(doc);
    if(current.file) {
      if(JSON.stringify(shared.cells)!==JSON.stringify(current.doc.cells) || JSON.stringify(savedResults)!==JSON.stringify(current.doc.recommendation_results??[])) current.file.setContent(text);
    } else folderBeside(HISTORY_PC_NAME).createFile(HISTORY_SHARED_NAME,text,'application/json');
    const keptNewer=incoming.filter(c=>history.cells.some(old=>old && EVENT_HISTORY_API.historyEditKey(old)===EVENT_HISTORY_API.historyEditKey(c) && old.updated_at!==c.updated_at && old.value!==c.value)).length;
    return respond(JSON.stringify({ok:true,history:{...history,shared_editing:true,recommendations_editing:false,recommendation_results_editing:true},keptNewer}));
  } catch(e) { return respond(JSON.stringify({error:String(e.message||e)})); }
  finally { if(locked) lock.releaseLock(); }
}

// END EVENT_HISTORY_SHARED
// BEGIN GENERATED VIEWER PARTS
const SCRIPT_RELEASE = '0949e413425a';
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
