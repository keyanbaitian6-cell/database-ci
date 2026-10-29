// 段階2の保存基盤。既存画面はまだ呼ばない。本文を持たない索引と不変の本文を分離する。
const VD_DB = 'database-viewer-days-v1';
// 参照が外れた本文を消すまでの猶予。読み込みを始めた処理は開始時の索引を固定して本文を読むので、
// この時間より長く古い版を読み続けた処理だけが「missing」になる（空として成功はしない）。
const VD_GRACE_MS = 10 * 60 * 1000;
// Google由来の補助情報のうち、大きくなる印・イベント・削除情報。見出し（書き出し時刻・線の参照など、書き出しの
// たびに変わる小さいもの）と別の本文にして、中身が変わらなければ書き直さない（レビュー指摘2）。
const VD_ANNOTATIONS = 'parts:annotations';
const VD_ANNOTATION_FIELDS = ['date_events', 'rainbow_marks', 'record_deletions'];
// 索引が参照する本文（日の本文・補助情報・移行の受領）。受領が指す本文は移行の再照合に使うので回収しない。
function vdRefs(head) {
  const refs = new Set();
  for (const d of Object.values(head.days || {})) for (const s of d.shards) refs.add(s.hash);
  for (const m of Object.values(head.metadata || {})) refs.add(m.hash);
  for (const r of Object.values(head.migration?.receipts || {})) for (const s of r.shards) refs.add(s.hash);
  if (head.migration?.quarantine) refs.add(head.migration.quarantine.hash);
  return refs;
}
const vdError = (code, message) => Object.assign(new Error(message), {code});
const vdFail = message => { throw vdError('corrupt', message); };
const vdDay = day => typeof day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(day) &&
  Number.isFinite(Date.parse(day)) && new Date(day).toISOString().slice(0, 10) === day;
const vdKey = row => JSON.stringify([row.store, row.day, row.machine, row.rack, row.kind_code ?? null, row.rate ?? null]);
// 時刻を比べられる数（ミリ秒×1000＋マイクロ秒）。小数秒は6桁まで比べる（Date.parse はミリ秒までで、マイクロ秒だけ
// 古い削除時刻・印が新しい方を上書きした、2026-10-29 レビュー指摘4）。Safari に4桁以上の小数秒を渡さないよう、
// Date.parse には3桁に切り詰めた文字を渡す。時差の無い時刻・読めない時刻は NaN。
function vdTime(value) {
  const m = typeof value === 'string' && /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)(?:\.(\d{1,9}))?(Z|[+-]\d{2}:?\d{2})$/.exec(value);
  if (!m) return NaN;
  const fraction = (m[2] || '').padEnd(6, '0'), zone = m[3] === 'Z' ? 'Z' : m[3].replace(/^([+-]\d{2}):?(\d{2})$/, '$1:$2');
  const base = m[1].length === 16 ? `${m[1]}:00` : m[1]; // 秒の無い時刻
  const ms = Date.parse(`${base}.${fraction.slice(0, 3)}${zone}`);
  return Number.isFinite(ms) ? ms * 1000 + Number(fraction.slice(3, 6)) : NaN;
}
// 記録として保存できない理由（旧経路の Dart も表示で飛ばす内容）。問題が無ければ null。
function vdRowProblem(row, day) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return 'not-object';
  if (!vdDay(row.day) || (day !== undefined && row.day !== day)) return 'day';
  if (typeof row.store !== 'string' || !row.store) return 'store';
  if (typeof row.machine !== 'string') return 'machine';
  if (!Number.isSafeInteger(row.rack) || row.rack < 1) return 'rack';
  return null;
}
// 印・イベント・削除情報の1件の識別と、使えない理由（旧経路の Dart もその1件を無視する内容）。問題が無ければ null。
const vdAnnotationId = (field, row) => JSON.stringify(field === 'date_events' ? [row.store, row.day]
  : field === 'rainbow_marks' ? [row.store, row.day, row.rack] : [row.store, row.day, row.machine, row.rack]);
function vdAnnotationProblem(field, row) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return 'not-object';
  if (!vdDay(row.day)) return 'day';
  if (typeof row.store !== 'string') return 'store';
  const clock = field === 'record_deletions' ? 'deleted_at' : 'updated_at', at = vdTime(row[clock]);
  if (row[clock] !== undefined && !Number.isFinite(at)) return 'time';
  if (field === 'rainbow_marks' && (typeof row.on !== 'boolean' || !Number.isSafeInteger(row.rack) || row.rack < 1 || !Number.isFinite(at))) return 'mark';
  if (field === 'record_deletions' && (!Number.isFinite(at) || typeof row.machine !== 'string' || !Number.isSafeInteger(row.rack))) return 'deletion';
  if (field === 'date_events' && !(typeof row.name === 'string' || row.name === null && Number.isFinite(at))) return 'event';
  return null;
}
// 同じキーの記録の余分な件数。
function vdDuplicates(rows) {
  const keys = new Set(); let extra = 0;
  for (const row of rows) { const key = vdKey(row); if (keys.has(key)) extra++; else keys.add(key); }
  return extra;
}
// allowDuplicates：旧本文から移した日だけ、同じキーの記録をそのまま残す（旧経路の Dart は1台にまとめて表示する。
// 2026-10-30 利用者「取り込んだうえで印を付ける」）。新しい書き込み・Googleの部品は従来どおり重複を拒否する。
function vdRows(rows, day, {allowDuplicates = false} = {}) {
  if (!Array.isArray(rows)) vdFail('日別の記録が配列ではありません。');
  for (const row of rows) if (vdRowProblem(row, day)) vdFail('記録のキー・日付が不正です。');
  if (!allowDuplicates && vdDuplicates(rows)) vdFail('同じキーの記録が重複しています。');
  return rows;
}
function vdHead(head) {
  if (!head) return {schema: 1, revision: 0, days: {}, metadata: {}};
  if (head.schema !== 1 || !Number.isSafeInteger(head.revision) || head.revision < 1 ||
      !head.days || Array.isArray(head.days) || !head.metadata || Array.isArray(head.metadata)) vdFail('日別索引が破損しています。');
  for (const [day, value] of Object.entries(head.days)) {
    if (!vdDay(day) || !['complete', 'empty', 'deleted'].includes(value?.state) || !Array.isArray(value.shards)) vdFail('日別索引が破損しています。');
    if (new Set(value.shards.map(s => s.store)).size !== value.shards.length) vdFail('店舗索引が重複しています。');
    for (const shard of value.shards) if (typeof shard.store !== 'string' || !/^[a-f0-9]{64}$/.test(shard.hash) ||
      !Number.isSafeInteger(shard.count) || shard.count < 1 || !Number.isSafeInteger(shard.bytes)) vdFail('本文索引が破損しています。');
    if (value.duplicates !== undefined && (!Number.isSafeInteger(value.duplicates) || value.duplicates < 1)) vdFail('日別索引が破損しています。');
  }
  const q = head.migration?.quarantine;
  if (q !== undefined && (!/^[a-f0-9]{64}$/.test(q?.hash) || !Number.isSafeInteger(q.count) || q.count < 1)) vdFail('保留した記録の索引が破損しています。');
  if (head.released !== undefined && (!Array.isArray(head.released) ||
      head.released.some(r => !/^[a-f0-9]{64}$/.test(r?.hash) || !Number.isFinite(Date.parse(r.at))))) vdFail('回収待ちの一覧が破損しています。');
  return head;
}
// JSONの値の終わりだけ探す。構文検査は各行とrecordsを除いた外枠のJSON.parseで行う。
function vdValueEnd(text, start) {
  let quoted = false, escaped = false, depth = 0;
  for (let i = start; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (escaped) escaped = false;
      else if (c === '\\') escaped = true;
      else if (c === '"') { quoted = false; if (depth === 0) return i + 1; }
    } else if (c === '"') quoted = true;
    else if (c === '{' || c === '[') depth++;
    else if (c === '}' || c === ']') { if (--depth === 0) return i + 1; if (depth < 0) return i; }
    else if (depth === 0 && /[\s,:]/.test(c)) return i;
  }
  return text.length;
}
function vdLegacy(text, site) {
  if (typeof text !== 'string') vdFail('旧本文がありません。');
  const space = i => { while (/\s/.test(text[i] || '') && i < text.length) i++; return i; };
  let i = space(0), recordsStart = -1, recordsEnd = -1;
  if (text[i++] !== '{') vdFail('旧本文の外枠が不正です。');
  const names = new Set();
  while ((i = space(i)) < text.length && text[i] !== '}') {
    if (text[i] !== '"') vdFail('旧本文の項目名が不正です。');
    const end = vdValueEnd(text, i), name = JSON.parse(text.slice(i, end));
    if (names.has(name)) vdFail('旧本文の項目が重複しています。');
    names.add(name); i = space(end);
    if (text[i++] !== ':') vdFail('旧本文の区切りが不正です。');
    i = space(i); const valueEnd = vdValueEnd(text, i);
    if (name === 'records') { recordsStart = i; recordsEnd = valueEnd; }
    i = space(valueEnd);
    if (text[i] === '}') break;
    if (text[i++] !== ',') vdFail('旧本文の区切りが不正です。');
  }
  if (recordsStart < 0 || text[recordsStart] !== '[' || text[recordsEnd - 1] !== ']') vdFail('旧本文に記録配列がありません。');
  const header = JSON.parse(text.slice(0, recordsStart) + '[]' + text.slice(recordsEnd));
  if (header.version !== 1 || header.format !== (site === 'meruhen' ? 'database-backup' : 'pscube-viewer')) vdFail('旧本文の形式・版が不正です。');
  delete header.records;
  // 印・イベント・削除情報は見出しのまま legacy に保存し、表示の時に旧経路と同じ規則で選り分ける。配列でなければ
  // 旧経路も読めないので止めるが、旧経路が無視するだけの1件（時刻なし・存在しない日付など）では止めず、件数を残す
  // （2026-10-30 利用者「取り込んだうえで印を付ける」）。
  const ignored = {};
  for (const field of VD_ANNOTATION_FIELDS) {
    if (header[field] === undefined) continue;
    if (!Array.isArray(header[field])) vdFail('旧本文の印・イベント・削除情報が配列ではありません。');
    const bad = header[field].filter(v => vdAnnotationProblem(field, v)).length;
    if (bad) ignored[field] = bad;
  }
  // 1回目の走査は各記録の形・営業日を確かめ、日ごとに位置（開始・終了の数の並び）だけを控える。日ごとの
  // 重複と内容の指紋は vdLegacyDays が1日ずつ確かめる（全日のキーや解析済みの記録を同時に持たない、
  // 2026-10-29 レビュー指摘3）。どちらも移行を running として確定する前に済ませる（指摘1）。
  // 記録として保存できない行（台番号0・文字列、存在しない日付など、旧経路の Dart も飛ばす行）は捨てずに「保留」へ
  // 位置と理由だけを控える（2026-10-30）。JSONとして読めない行は旧経路も読めないので止める。
  const offsets = new Map(), quarantine = {spans: [], reasons: []}; let count = 0;
  i = space(recordsStart + 1);
  while (i < recordsEnd - 1) {
    const end = vdValueEnd(text, i), row = JSON.parse(text.slice(i, end)), problem = vdRowProblem(row);
    if (problem) { quarantine.spans.push(i, end); quarantine.reasons.push(problem); }
    else {
      if (!offsets.has(row.day)) offsets.set(row.day, []);
      offsets.get(row.day).push(i, end); count++;
    }
    i = space(end);
    if (i === recordsEnd - 1) break;
    if (text[i++] !== ',') vdFail('旧本文の記録区切りが不正です。');
    i = space(i);
    if (i === recordsEnd - 1) vdFail('旧本文の末尾カンマは不正です。');
  }
  // 明示された空の日も移す。期間内の穴から削除や空を推測しない。
  if (header.history_days !== undefined && !Array.isArray(header.history_days)) vdFail('旧本文の日一覧が配列ではありません。');
  for (const day of header.history_days || []) {
    if (!vdDay(day)) { ignored.history_days = (ignored.history_days || 0) + 1; continue; }
    if (!offsets.has(day)) offsets.set(day, []);
  }
  return {header, offsets, count, quarantine, ignored};
}
// 控えた位置から、その日の記録だけを解析する。
const vdDayRows = (text, spans) => {
  const rows = [];
  for (let k = 0; k < spans.length; k += 2) rows.push(JSON.parse(text.slice(spans[k], spans[k + 1])));
  return rows;
};
// 記録キー・件数・全項目（印・削除時刻を含む）の、並び順に依存しない指紋。受領の照合にも使う。
const vdFingerprint = values => vpClientHash(vpCanonical([...values].sort((a, b) => vdKey(a).localeCompare(vdKey(b)))));
// 2回目の走査：1日ずつ解析して重複を確かめ、日ごとの指紋を作る。旧本文の指紋は、見出しと日ごとの指紋から作る
// （全文をUTF-8に複製してハッシュしない。365日の初回移行で全文の写しが山を押し上げていた、レビュー指摘3）。
async function vdLegacyDays(text, parsed) {
  const days = new Map();
  for (const [day, spans] of [...parsed.offsets].sort(([a], [b]) => a.localeCompare(b))) {
    const rows = vdDayRows(text, spans), duplicates = vdDuplicates(rows);
    vdRows(rows, day, {allowDuplicates: true});
    days.set(day, {hash: await vdFingerprint(rows), count: rows.length, ...(duplicates ? {duplicates} : {})});
  }
  // 保留した行は、旧本文の並びのまま理由を添えて1つの本文にする。
  const held = vdDayRows(text, parsed.quarantine.spans).map((row, k) => ({reason: parsed.quarantine.reasons[k], row}));
  const quarantine = held.length ? {rows: held, hash: await vpClientHash(vpCanonical(held))} : null;
  const sourceHash = await vpClientHash(vpCanonical({version: 3, header: parsed.header, days: [...days], quarantine: quarantine?.hash ?? null}));
  return {days, sourceHash, quarantine};
}
function createViewerDayStore({dbName = VD_DB} = {}) {
  async function open() {
    if (!globalThis.indexedDB) throw vdError('unavailable', '端末の保存領域を利用できません。');
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(dbName, 1);
      request.onupgradeneeded = () => { for (const s of ['heads', 'bodies']) request.result.createObjectStore(s); };
      let blocked = false;
      request.onblocked = () => { blocked = true; reject(vdError('blocked', '別のタブが保存領域を使用しています。')); };
      request.onerror = () => reject(request.error);
      request.onsuccess = () => { if (blocked) request.result.close(); else resolve(request.result); };
    });
  }
  async function transaction(names, mode, action) {
    const db = await open();
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction(names, mode); let result, failure;
        const fail = error => { if (failure) return; failure = error; try { tx.abort(); } catch { /* 既に終了 */ } };
        tx.oncomplete = () => resolve(result);
        tx.onabort = () => reject(failure || tx.error || vdError('aborted', '保存処理が中断されました。'));
        tx.onerror = () => { /* abortで失敗を返す。 */ };
        try { action(tx, value => { result = value; }, fail); } catch (error) { fail(error); }
      });
    } finally { db.close(); }
  }
  const read = (store, key) => transaction([store], 'readonly', (tx, done) => {
    const request = tx.objectStore(store).get(key); request.onsuccess = () => done(request.result);
  });
  const inspect = async key => {
    const saved = await read('heads', key);
    if (!saved) return vdHead(null);
    if (!saved.value || await vpClientHash(vpCanonical(saved.value)) !== saved.hash) vdFail('索引の照合値が一致しません。');
    return vdHead(saved.value);
  };
  const bodyKey = (key, hash) => JSON.stringify([key, hash]);
  async function readBody(key, ref) {
    const text = await read('bodies', bodyKey(key, ref.hash));
    if (typeof text !== 'string') throw vdError('missing', '確定済み本文がありません。');
    if (new TextEncoder().encode(text).length !== ref.bytes || await vpClientHash(text) !== ref.hash) vdFail('確定済み本文の照合値が一致しません。');
    return JSON.parse(text);
  }
  async function stage(key, value) {
    const text = vpCanonical(value), ref = {hash: await vpClientHash(text), bytes: new TextEncoder().encode(text).length};
    await transaction(['bodies'], 'readwrite', (tx, done) => { tx.objectStore('bodies').put(text, bodyKey(key, ref.hash)); done(ref); });
    // 書き戻した本文を読み、照合が済んだ参照だけを索引へ公開する。
    if (vpCanonical(await readBody(key, ref)) !== text) vdFail('書き戻した本文が一致しません。');
    return ref;
  }
  // 索引の比較確定。参照が外れた本文は released に時刻つきで控え（collect が猶予後に消す）、新しく参照する
  // 本文は同じトランザクションで実在を確かめる（回収と重なって消えた本文を指す索引を作らない、レビュー指摘2）。
  async function publish(key, expected, next) {
    const before = vpCanonical(expected), oldRefs = vdRefs(expected), newRefs = vdRefs(next), at = new Date().toISOString();
    const released = (expected.released || []).filter(r => !newRefs.has(r.hash)), known = new Set(released.map(r => r.hash));
    for (const hash of oldRefs) if (!newRefs.has(hash) && !known.has(hash)) released.push({hash, at});
    if (released.length) next.released = released; else delete next.released;
    const unchanged = before === vpCanonical(next);
    if (!unchanged) next.revision = expected.revision + 1;
    const hash = await vpClientHash(vpCanonical(next)), added = [...newRefs].filter(h => !oldRefs.has(h));
    return transaction(['heads', 'bodies'], 'readwrite', (tx, done, fail) => {
      const store = tx.objectStore('heads'), bodies = tx.objectStore('bodies'), request = store.get(key);
      request.onsuccess = () => {
        try {
          const current = vdHead(request.result?.value);
          if (vpCanonical(current) !== before) throw vdError('conflict', 'ほかの処理が先に確定しました。再読込が必要です。');
          if (unchanged) { done(next); return; }
          const commit = () => { store.put({value: next, hash}, key); done(next); };
          let pending = added.length;
          if (!pending) { commit(); return; }
          for (const h of added) {
            const check = bodies.getKey(bodyKey(key, h));
            check.onsuccess = () => {
              if (check.result === undefined) fail(vdError('missing', '確定する本文がありません（回収と重なりました）。やり直してください。'));
              else if (--pending === 0) commit();
            };
          }
        } catch (e) { fail(e); }
      };
    });
  }
  // 参照が外れてから graceMs 以上たった本文を消す。索引の比較と本文の削除を1つのトランザクションで行うので、
  // その間に別の確定が同じ本文を参照し直していれば conflict で止まり、何も消さない。旧本文・旧経路には触れない。
  // 確定前に失敗して索引に載らなかった本文（released に無いもの）はここでは消さない。
  async function collect(key, {graceMs = VD_GRACE_MS, now = Date.now()} = {}) {
    const head = await inspect(key), refs = vdRefs(head);
    const due = (head.released || []).filter(r => now - Date.parse(r.at) >= graceMs && !refs.has(r.hash)).map(r => r.hash);
    if (!due.length) return {removed: 0, revision: head.revision};
    const gone = new Set(due), next = structuredClone(head);
    next.released = head.released.filter(r => !gone.has(r.hash));
    if (!next.released.length) delete next.released;
    next.revision = head.revision + 1;
    const before = vpCanonical(head), hash = await vpClientHash(vpCanonical(next));
    return transaction(['heads', 'bodies'], 'readwrite', (tx, done, fail) => {
      const store = tx.objectStore('heads'), request = store.get(key);
      request.onsuccess = () => {
        try {
          if (vpCanonical(vdHead(request.result?.value)) !== before) throw vdError('conflict', 'ほかの処理が先に確定しました。回収は次の機会に行います。');
          for (const h of due) tx.objectStore('bodies').delete(bodyKey(key, h));
          store.put({value: next, hash}, key);
          done({removed: due.length, revision: next.revision});
        } catch (e) { fail(e); }
      };
    });
  }
  async function prepareDay(key, day, update, previous, {allowDuplicates = false} = {}) {
    if (!vdDay(day) || !update || !['complete', 'deleted'].includes(update.state)) vdFail('日別更新の状態が不正です。');
    const rows = vdRows(update.records, day, {allowDuplicates}), groups = new Map(), duplicates = vdDuplicates(rows);
    if (update.state === 'deleted' && (rows.length || !Number.isFinite(vdTime(update.deleted_at)))) vdFail('明示削除には削除時刻（時差つき）と空の本文が必要です。');
    for (const row of rows) { if (!groups.has(row.store)) groups.set(row.store, []); groups.get(row.store).push(row); }
    const shards = [];
    for (const [store, items] of [...groups].sort(([a], [b]) => a.localeCompare(b))) {
      // 入力の順序も本文の一部として保存し、未知の項目や外した印の時刻を削らない。
      const value = {day, store, records: items}, text = vpCanonical(value), hash = await vpClientHash(text);
      const old = previous?.shards.find(s => s.store === store && s.hash === hash);
      shards.push({...old || await stage(key, value), store, count: items.length});
    }
    return {state: update.state === 'deleted' ? 'deleted' : rows.length ? 'complete' : 'empty', shards,
      ...(duplicates ? {duplicates} : {}),
      ...(update.deleted_at ? {deleted_at: update.deleted_at} : {}),
      ...(update.parts ? {parts: update.parts} : {})};
  }
  // 呼出側が統合済みの完成日を渡す。未取得・通信失敗を空配列にして呼んではならない。
  async function writeDays(key, {expectedRevision, updates = {}, metadata = {}}) {
    updates = structuredClone(updates); metadata = structuredClone(metadata);
    const head = await inspect(key);
    if (head.revision !== expectedRevision) throw vdError('conflict', '更新開始時の版が一致しません。');
    if (head.migration?.status === 'running') throw vdError('migration-running', '旧本文の移行が未完了です。旧経路を利用してください。');
    const next = structuredClone(head);
    for (const [day, update] of Object.entries(updates)) next.days[day] = await prepareDay(key, day, update, head.days[day]);
    for (const [source, value] of Object.entries(metadata)) {
      const hash = await vpClientHash(vpCanonical(value));
      next.metadata[source] = head.metadata[source]?.hash === hash ? head.metadata[source] : await stage(key, value);
    }
    return publish(key, head, next);
  }
  function select(head, range) {
    if (!range || (!Array.isArray(range.days) && !(vdDay(range.from) && vdDay(range.to)))) throw vdError('range-required', '日一覧または開始日・終了日を指定してください。');
    if (range.days?.some(d => !vdDay(d)) || (range.from && range.from > range.to)) throw vdError('invalid-range', '読み込む範囲が不正です。');
    if (range.stores !== undefined && (!Array.isArray(range.stores) || range.stores.some(s => typeof s !== 'string'))) throw vdError('invalid-range', '店舗範囲が不正です。');
    return range.days ? [...new Set(range.days)].sort() : Object.keys(head.days).filter(d => d >= range.from && d <= range.to).sort();
  }
  async function* streamRange(key, range) {
    const head = await inspect(key), days = select(head, range);
    // 不変本文への参照を固定するため、途中で他タブが確定しても旧版の一貫した範囲を返せる。
    for (const day of days) {
      const descriptor = head.days[day], records = [];
      if (!descriptor) { yield {day, state: 'unfetched', revision: head.revision, records}; continue; }
      for (const shard of descriptor.shards) {
        if (range.stores && !range.stores.includes(shard.store)) continue;
        const body = await readBody(key, shard);
        if (body.day !== day || body.store !== shard.store || body.records?.length !== shard.count || body.records.some(r => r.store !== shard.store)) vdFail('本文と索引の範囲が一致しません。');
        vdRows(body.records, day, {allowDuplicates: Boolean(descriptor.duplicates)}); records.push(...body.records);
      }
      yield {day, state: descriptor.state, revision: head.revision, records,
        ...(descriptor.duplicates ? {duplicates: descriptor.duplicates} : {}), ...(descriptor.deleted_at ? {deleted_at: descriptor.deleted_at} : {})};
    }
  }
  async function readRange(key, range) { const days = []; for await (const day of streamRange(key, range)) days.push(day); return days; }
  // 移行で保留した行（理由つき、旧本文の並び）。無ければ空の配列。
  async function readQuarantine(key, head) {
    head ||= await inspect(key);
    return head.migration?.quarantine ? readBody(key, head.migration.quarantine) : [];
  }
  async function readMetadata(key, source, head) {
    head ||= await inspect(key);
    const value = head.metadata[source] ? await readBody(key, head.metadata[source]) : null;
    // 'parts' は見出しと印・イベント・削除情報を合わせて返す（分ける前と同じ形）。
    if (source === 'parts' && value && head.metadata[VD_ANNOTATIONS]) return {...value, ...await readBody(key, head.metadata[VD_ANNOTATIONS])};
    return value;
  }
  async function migrateLegacy(key, {text, site, maxDays = Infinity, signal} = {}) {
    if (!['meruhen', 'pscube'].includes(site) || !(maxDays === Infinity || Number.isInteger(maxDays) && maxDays >= 0)) vdFail('移行条件が不正です。');
    const parsed = vdLegacy(text, site);
    const {days: prints, sourceHash, quarantine} = await vdLegacyDays(text, parsed);
    let head = await inspect(key);
    // 版1（全文のハッシュ）・版2（保留・重複の扱いの前）とは指紋の作り方が違い、同じ旧本文でも一致しない。捨ててやり直す。
    if (head.migration && head.migration.version !== 3) throw vdError('migration-version', '古い版の移行です。abandonMigration で捨ててからやり直してください。');
    if (head.migration && head.migration.sourceHash !== sourceHash) throw vdError('source-changed', '旧本文が変わりました。別の移行領域で照合してください。');
    if (!head.migration) {
      // 版の番号ではなく中身で判断する（abandonMigration で捨てた後の空の領域からは始め直せる）。
      if (Object.keys(head.days).length || Object.keys(head.metadata).length) throw vdError('not-empty', '移行先に既存の確定内容があります。');
      const ref = await stage(key, parsed.header);
      // 保留した行（旧経路も表示で飛ばす行）は理由つきで別の本文に残し、件数と理由ごとの数を移行の記録に書く。
      const held = quarantine ? {...await stage(key, quarantine.rows), count: quarantine.rows.length,
        reasons: quarantine.rows.reduce((n, r) => ({...n, [r.reason]: (n[r.reason] || 0) + 1}), {})} : null;
      const duplicates = [...prints.values()].reduce((n, d) => n + (d.duplicates || 0), 0);
      head = await publish(key, head, {...head, metadata: {legacy: ref}, migration: {
        version: 3, sourceHash, status: 'running', totalDays: parsed.offsets.size, totalRecords: parsed.count, receipts: {},
        ...(held ? {quarantine: held} : {}), ...(duplicates ? {duplicates} : {}),
        ...(Object.keys(parsed.ignored).length ? {ignored: parsed.ignored} : {})}});
    }
    const alreadyComplete = head.migration.status === 'complete';
    if (vpCanonical(await readMetadata(key, 'legacy', head)) !== vpCanonical(parsed.header)) vdFail('旧本文の見出しが一致しません。');
    let processed = 0;
    for (const [day, spans] of [...parsed.offsets].sort(([a], [b]) => a.localeCompare(b))) {
      signal?.throwIfAborted();
      const {hash, count} = prints.get(day), receipt = head.migration.receipts[day];
      if (receipt) {
        // 受領済みの日は旧本文を解析し直さず、保存した本文の指紋を確かめる。
        const saved = {records: []};
        for (const ref of receipt.shards) saved.records.push(...(await readBody(key, ref)).records);
        if (receipt.hash !== hash || receipt.count !== count || await vdFingerprint(saved.records) !== hash) vdFail('移行済みの日の照合に失敗しました。');
        continue;
      }
      if (processed >= maxDays) return head;
      const rows = vdDayRows(text, spans);
      if (rows.length !== count || await vdFingerprint(rows) !== hash) vdFail('旧本文が移行中に変わりました。');
      const next = structuredClone(head);
      next.days[day] = await prepareDay(key, day, {state: 'complete', records: rows}, undefined, {allowDuplicates: true});
      next.migration.receipts[day] = {hash, count: rows.length, shards: next.days[day].shards};
      head = await publish(key, head, next); processed++;
    }
    // 本文・見出し・全日の受領がそろったときだけ完了。旧本文は一切書き換えない。
    if (Object.keys(head.migration.receipts).length !== parsed.offsets.size || Object.values(head.migration.receipts).reduce((n, r) => n + r.count, 0) !== parsed.count) vdFail('移行の照合件数が一致しません。');
    if (alreadyComplete) return head;
    const next = structuredClone(head); next.migration.status = 'complete';
    return publish(key, head, next);
  }
  // 未完了の移行領域を捨てて、別の旧本文で始め直せるようにする（2026-10-29 レビュー指摘1）。running の間は
  // 通常更新を拒否しているので、索引にあるのは移行で入れた日と見出しだけ。それを確かめてから空の索引を
  // 比較確定する。旧本文・旧経路には触れない。捨てた本文は released に入り、collect が猶予後に消す。完了した移行は捨てない。
  async function abandonMigration(key) {
    const head = await inspect(key);
    if (!head.migration) throw vdError('no-migration', '捨てる移行がありません。');
    if (head.migration.status !== 'running') throw vdError('migration-complete', '完了した移行は捨てません。');
    const migrated = new Set(Object.keys(head.migration.receipts));
    if (Object.keys(head.days).some(day => !migrated.has(day)) || Object.keys(head.metadata).some(source => source !== 'legacy')) {
      throw vdError('not-migration-only', '移行以外の確定内容があるため捨てられません。');
    }
    return publish(key, head, {schema: 1, revision: head.revision, days: {}, metadata: {},
      abandonedMigration: {sourceHash: head.migration.sourceHash, days: migrated.size, at: new Date().toISOString()}});
  }
  function mergeMetadata(previous, incoming) {
    const result = {...previous, ...incoming};
    for (const field of VD_ANNOTATION_FIELDS) {
      if (previous?.[field] === undefined && incoming[field] === undefined) continue;
      const entries = new Map();
      for (const [which, list] of [[0, previous?.[field]], [1, incoming[field]]]) {
        if (list === undefined) continue;
        if (!Array.isArray(list)) vdFail('印・イベント・削除情報が配列ではありません。');
        for (const row of list) {
          const problem = vdAnnotationProblem(field, row);
          if (problem) vdFail(`印・イベント・削除情報が不正です（${problem}）。`);
          const id = vdAnnotationId(field, row), old = entries.get(id), clock = field === 'record_deletions' ? 'deleted_at' : 'updated_at';
          const at = vdTime(row[clock]), before = vdTime(old?.[clock]);
          // 同じ時刻なら届いた側を採る（既存の mergeRainbowMarks・mergeDateEvents と同じ）。比べるのはマイクロ秒まで。
          if (!old || Number.isFinite(at) && (!Number.isFinite(before) || at >= before) || !which) entries.set(id, row);
        }
      }
      result[field] = [...entries.values()];
    }
    return result;
  }

  // v2日別通信の別入口。既存fetchViewerPartsと異なり、戻り値に全recordsを作らない。
  async function syncParts(url, site, manifest, getJson) {
    const m = vpValidManifest(structuredClone(manifest), site);
    if (m.version !== 2) throw vdError('legacy-manifest', '範囲を明示するv2一覧が必要です。旧経路を利用してください。');
    const key = vpEndpointKey(url, site), head = await inspect(key);
    if (head.migration?.status === 'running') throw vdError('migration-running', '移行中は旧経路を利用してください。');
    const stamp = Date.parse(m.header.exported_at);
    if (!Number.isFinite(stamp)) vdFail('更新一覧の時刻が不正です。');
    if (head.partsSource && (stamp < head.partsSource.at || stamp === head.partsSource.at && m.revision !== head.partsSource.revision)) throw vdError('stale', '古い、または同時刻で異なる一覧は確定できません。');
    const next = structuredClone(head);
    for (const day of m.days) {
      const refs = m.parts.filter(p => p.day === day), signature = refs.map(p => ({hash: p.hash, bytes: p.bytes, count: p.count}));
      if (vpCanonical(head.days[day]?.parts) === vpCanonical(signature)) continue;
      // 端末で明示削除した日（2026-10-29 レビュー指摘5で決めた規則）：Googleも空なら、削除時刻つきの削除を残す
      // （どちらも記録なしで、削除の時刻を失わない）。Googleに記録があっても、書き出しが削除より前なら戻さない。
      // 削除より後の書き出しの記録なら、Googleの内容で置き換える（時刻の新しい方、ほかの印・削除情報と同じ考え方）。
      // 書き出し時刻が読めない（時差なしなど）ときは、新しいと言えないので削除を残す。
      const current = head.days[day];
      if (current?.state === 'deleted' && (!refs.length || !(vdTime(m.header.exported_at) > vdTime(current.deleted_at)))) continue;
      const rows = [];
      for (let i = 0; i < refs.length; i += VP_BATCH) {
        const batch = refs.slice(i, i + VP_BATCH), request = new URL(url); request.search = ''; request.hash = '';
        if (site === 'pscube') request.searchParams.set('file', 'pscube');
        request.searchParams.set('revision', m.revision); request.searchParams.set('parts', batch.map(p => p.hash).join(','));
        const response = await getJson(request.href);
        if (response?.format !== VP_FORMAT || response.revision !== m.revision || response.parts?.length !== batch.length) throw vdError('remote-changed', '取得中に一覧の版が変わりました。');
        for (let j = 0; j < batch.length; j++) {
          const ref = batch[j], item = response.parts[j];
          if (item?.hash !== ref.hash || typeof item.text !== 'string' || new TextEncoder().encode(item.text).length !== ref.bytes || await vpClientHash(item.text) !== ref.hash) vdFail('受信した部品が一致しません。');
          rows.push(...vpRows(item.text, ref));
        }
      }
      next.days[day] = await prepareDay(key, day, {state: 'complete', records: rows, parts: signature}, head.days[day]);
    }
    // 旧本文由来の印・イベント・削除情報は別の見出しに残す。表示時の統合規則は既存側の責務。
    const input = {...m.header, ...vpPublicCurves(m)};
    const inputHash = await vpClientHash(vpCanonical(input));
    if (head.partsSource?.headerHash !== inputHash) {
      // 本文とは別の補助情報。期間外になった印・イベント・削除情報も保持する。見出しと印などを別の本文にし、
      // 中身が同じなら前の本文をそのまま使う（書き出し時刻だけの変化で印などを書き直さない）。
      const merged = mergeMetadata(await readMetadata(key, 'parts', head), input);
      const annotations = Object.fromEntries(VD_ANNOTATION_FIELDS.filter(f => merged[f] !== undefined).map(f => [f, merged[f]]));
      const summary = Object.fromEntries(Object.entries(merged).filter(([f]) => !VD_ANNOTATION_FIELDS.includes(f)));
      for (const [source, value] of [['parts', summary], [VD_ANNOTATIONS, annotations]]) {
        const hash = await vpClientHash(vpCanonical(value));
        next.metadata[source] = head.metadata[source]?.hash === hash ? head.metadata[source] : await stage(key, value);
      }
    }
    next.partsSource = {at: stamp, revision: m.revision, headerHash: inputHash};
    return publish(key, head, next);
  }
  return {inspect, writeDays, readRange, streamRange, readMetadata, readQuarantine, migrateLegacy, abandonMigration, syncParts, collect};
}
