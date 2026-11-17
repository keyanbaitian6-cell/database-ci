// v1のsnapshotsを保持したまま、日別の履歴へ移行する。取得・検査が完了してから確定する。
function vpCache() {
  // Reopening a long history must not retain every JSON string alongside the
  // decoded records. Read one day per transaction; never hold a transaction
  // open while awaiting crypto or rendering work.
  async function* stream(key) {
    if (!globalThis.indexedDB) return;
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('database-viewer-parts-v1', 2);
      request.onupgradeneeded = () => {
        for (const name of ['snapshots', 'history-heads', 'history-days']) {
          if (!request.result.objectStoreNames.contains(name)) request.result.createObjectStore(name);
        }
      };
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error('cache blocked'));
      request.onsuccess = () => resolve(request.result);
    });
    const read = (store, id) => new Promise((resolve, reject) => {
      const tx = db.transaction(store, 'readonly'), request = tx.objectStore(store).get(id);
      tx.oncomplete = () => resolve(request.result);
      tx.onabort = tx.onerror = () => reject(tx.error);
    });
    try {
      const head = await read('history-heads', key);
      if (!head) return;
      yield {header: head.header, days: head.days};
      for (const day of head.days) {
        // Verify the head did not change during a concurrent tab's commit.
        // The final check also detects a writer that replaced an earlier day.
        const value = await read('history-days', key + '|' + day);
        if (!value) throw new Error('保存した履歴の一部がありません。オンラインで最新を読み込んでください。');
        if (!value.parts || typeof value.parts !== 'object' || Array.isArray(value.parts)) throw new Error('保存した履歴が破損しています。');
        yield {day, parts: value.parts};
      }
      const latest = await read('history-heads', key);
      if (vpCanonical(latest) !== vpCanonical(head)) throw new Error('履歴が更新されました。もう一度読み込んでください。');
    } finally { db.close(); }
  }
  async function run(key, value, writing) {
    if (!globalThis.indexedDB) {
      if (writing) throw new Error('端末の保存領域を利用できません。');
      return null;
    }
    return new Promise((resolve, reject) => {
      const request = indexedDB.open('database-viewer-parts-v1', 2);
      request.onupgradeneeded = () => {
        for (const name of ['snapshots', 'history-heads', 'history-days']) {
          if (!request.result.objectStoreNames.contains(name)) request.result.createObjectStore(name);
        }
      };
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error('cache blocked'));
      request.onsuccess = () => {
        const db = request.result, tx = db.transaction(['snapshots', 'history-heads', 'history-days'], writing ? 'readwrite' : 'readonly');
        const heads = tx.objectStore('history-heads'), days = tx.objectStore('history-days');
        const head = heads.get(key);
        const result = {parts: {}, header: null, days: [], missingDays: [], partDays: {}};
        let stale = false;
        head.onsuccess = () => {
          if (writing) {
            const current = head.result || {days: []};
            // 古い通信が後から完了しても、新しく確定した日のデータを巻き戻さない。比べるのはGoogleの日別一覧どうしの時刻
            // （parts_at）だけ。閲覧用ファイル全体を読んだときの時刻（PCの書き出し）は一覧と別の時計なので比べない
            // （2026-10-18：全体を読んだ後、一覧の時刻が古いまま進まず、P-STATIONの保存を毎回断っていた）。
            if (value.header?.parts_at && Date.parse(current.header?.parts_at) > Date.parse(value.header.parts_at)) { stale = true; return; }
            for (const [day, parts] of Object.entries(value.updates)) days.put({parts}, key + '|' + day);
            heads.put({header: value.header, days: [...new Set([...current.days, ...Object.keys(value.updates)])].sort(), revision: (current.revision || 0) + 1}, key);
          } else if (head.result) {
            result.header = head.result.header; result.days = head.result.days;
            for (const day of head.result.days) {
              const part = days.get(key + '|' + day);
              part.onsuccess = () => {
                if (!part.result) { result.missingDays.push(day); return; }
                Object.assign(result.parts, part.result.parts || {});
                for (const hash of Object.keys(part.result.parts || {})) result.partDays[hash] = day;
              };
            }
          } else {
            const legacy = tx.objectStore('snapshots').get(key);
            legacy.onsuccess = () => Object.assign(result.parts, legacy.result?.parts || {});
          }
        };
        tx.oncomplete = () => { db.close(); resolve(writing ? {stale} : result); };
        tx.onabort = tx.onerror = () => { db.close(); reject(tx.error); };
      };
    });
  }
  return {get: key => run(key), commit: (key, value) => run(key, value, true), stream, pending: vpPendingStore()};
}
// 読みかけの部品（2026-11-17 利用者「続きから読めるように」。初めて開く端末はP-STATIONだけで約35MBを8部品ずつ読み、
// 途中で1回でも通信に失敗すると、それまでに読んだ分を捨てて最初から読み直していた）。
// ・表示用の履歴（database-viewer-parts-v1）とは別の保存先に置く。既存の保存先の版を上げると、同じ配信元の古い版の
//   ページ（閲覧ページ・共有カレンダー）が開けなくなるため。全部そろうまで表示用の履歴には入れない。
// ・部品は中身のハッシュで呼ぶので、使う前に一覧のハッシュ・バイト数と照合する（古い中身・壊れた中身は使わない）。
// ・全部そろって履歴に保存したら消す。一覧から外れた部品も、次に読むときに消す。
// ・この保存先が使えなくても読み込みは止めない（今までどおり最初から読む）。
function vpPendingStore() {
  const NAME = 'database-viewer-parts-pending-v1', STORE = 'parts';
  async function run(mode, work) {
    if (!globalThis.indexedDB || !globalThis.IDBKeyRange) return null;
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open(NAME, 1);
      request.onupgradeneeded = () => { if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE); };
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error('cache blocked'));
      request.onsuccess = () => resolve(request.result);
    });
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, mode), result = work(tx.objectStore(STORE));
        tx.oncomplete = () => resolve(result);
        tx.onabort = tx.onerror = () => reject(tx.error);
      });
    } finally { db.close(); }
  }
  const range = key => IDBKeyRange.bound(key + '|', key + '|￿');
  return {
    // 一覧（keep）にある読みかけを返し、一覧に無いものは消す。
    async take(key, keep) {
      return run('readwrite', store => {
        const found = new Map(), request = store.openCursor(range(key));
        request.onsuccess = () => {
          const cursor = request.result;
          if (!cursor) return;
          const hash = String(cursor.key).slice(key.length + 1);
          if (keep.has(hash) && typeof cursor.value === 'string') found.set(hash, cursor.value); else cursor.delete();
          cursor.continue();
        };
        return found;
      });
    },
    async put(key, entries) { return run('readwrite', store => { for (const [hash, text] of entries) store.put(text, key + '|' + hash); }); },
    async clear(key) { return run('readwrite', store => { store.delete(range(key)); }); },
  };
}
function vpEndpointKey(url, site) { const endpoint = new URL(url); endpoint.search = ''; endpoint.hash = ''; return endpoint.href + '|' + site; }
function vpCachedDays(cached) {
  const days = new Map();
  for (const [hash, text] of Object.entries(cached?.parts || {})) {
    const indexedDay = cached?.partDays?.[hash];
    if (typeof indexedDay === 'string') {
      if (!days.has(indexedDay)) days.set(indexedDay, {});
      days.get(indexedDay)[hash] = text; continue;
    }
    let rows;
    try { rows = JSON.parse(text); } catch { continue; }
    const day = rows?.[0]?.day;
    if (!Array.isArray(rows) || typeof day !== 'string' || rows.some(r => r?.day !== day)) continue;
    if (!days.has(day)) days.set(day, {}); days.get(day)[hash] = text;
  }
  return days;
}
async function vpStoreHistory(cache, key, cached, updates, header) {
  if (cache.commit) {
    // v1キャッシュの全日を最初のトランザクションに含め、移行漏れを防ぐ。
    const migration = cached?.header ? {} : Object.fromEntries(vpCachedDays(cached));
    const result = await cache.commit(key, {updates: {...migration, ...updates}, header});
    if (result?.stale) throw new Error('ほかの更新で新しい履歴が保存されています。もう一度読み込んでください。');
  } else {
    const days = vpCachedDays(cached);
    for (const [day, parts] of Object.entries(updates)) days.set(day, parts);
    await cache.set(key, {header, parts: Object.assign({}, ...days.values())});
  }
}
// 既存の自分用ページに保存済みの全期間データを、接続先ごとの履歴へ引き継ぐ。
async function rememberViewerHistory(url, site, doc, cache = vpCache(), replaceDays = false) {
  if (!doc || !Array.isArray(doc.records)) return;
  const key = vpEndpointKey(url, site), cached = await cache.get(key), days = vpCachedDays(cached), updates = {};
  for (const row of doc.records) {
    if (typeof row?.day !== 'string') continue;
    if (!updates[row.day]) updates[row.day] = [];
    updates[row.day].push(row);
  }
  for (const [day, rows] of Object.entries(updates)) {
    if (!replaceDays && days.has(day)) { delete updates[day]; continue; } // 移行時にGoogleで確定済みの日は変更しない。
    const text = JSON.stringify(rows), hash = await vpClientHash(text); updates[day] = {[hash]: text};
  }
  if (!Object.keys(updates).length && cached?.header) return;
  const {records, ...header} = doc;
  await vpStoreHistory(cache, key, cached, updates, replaceDays ? header : cached?.header || header);
}
// 端末の旧本文に出てくる日 [bodyDays] が、すべて接続先の日別キャッシュにあるか。あるなら rememberViewerHistory は何もしない
// （全件の解析も保存も要らない）ので、旧本文を丸ごと解析しないで済ませる。日別キャッシュは1日ずつ読む。
// 確かめられない（旧形式・読めない）ときは false（呼び出し側は今までどおり rememberViewerHistory を使う）。
async function viewerHistoryCovers(url, site, bodyDays, cache = vpCache()) {
  if (!cache.stream) return false;
  let header = null;
  const have = new Set();
  try {
    for await (const value of cache.stream(vpEndpointKey(url, site))) {
      if (value.header) { header = value.header; continue; }
      if (Object.keys(value.parts || {}).length) have.add(value.day);
    }
  } catch { return false; }
  if (!header) return false;
  for (const day of bodyDays) if (!have.has(day)) return false;
  return true;
}
async function vpClientHash(text) {
  const data = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(data)].map(b => b.toString(16).padStart(2, '0')).join('');
}
async function readViewerHistory(url, site, cache = vpCache()) {
  if (cache.stream) {
    let header = null, days = [], records = [];
    for await (const value of cache.stream(vpEndpointKey(url, site))) {
      if (value.header) { header = value.header; days = value.days; continue; }
      for (const [hash, text] of Object.entries(value.parts || {})) {
        if (await vpClientHash(text) !== hash) throw new Error('保存した履歴が破損しています。オンラインで最新を読み込んでください。');
        const rows = JSON.parse(text);
        if (!Array.isArray(rows) || rows.some(r => r?.day !== value.day)) throw new Error('保存した履歴の日付が一致しません。');
        for (const row of rows) records.push(row);
      }
    }
    if (!header) return null;
    return {...header, history: true, history_days: days, records};
  }
  const cached = await cache.get(vpEndpointKey(url, site));
  if (!cached?.header) return null;
  if (cached.missingDays?.length) throw new Error('保存した履歴の一部がありません。オンラインで最新を読み込んでください。');
  const records = [];
  for (const [hash, text] of Object.entries(cached.parts)) {
    if (await vpClientHash(text) !== hash) throw new Error('保存した履歴が破損しています。オンラインで最新を読み込んでください。');
    records.push(...JSON.parse(text));
  }
  return {...cached.header, history: true, history_days: cached.days || [...vpCachedDays(cached).keys()], records};
}
async function fetchViewerParts(url, site, manifest, getJson, cache = vpCache()) {
  const m = vpValidManifest(manifest, site), endpoint = new URL(url);
  endpoint.search = ''; endpoint.hash = '';
  const key = endpoint.href + '|' + site;
  let cached = null;
  try { cached = await cache.get(key); }
  catch { throw new Error('履歴を端末から読み出せませんでした。保存データは変更していません。'); }
  const parts = new Map(), missing = [];
  // 中身の一致を確かめ終えた部品（ハッシュ）と、その行。同じ部品を何度も計算・解析しない（更新1回のメモリの山を下げる、2026-11-18）。
  const verified = new Set(), parsedRows = new Map();
  for (const p of m.parts) {
    const text = cached?.parts?.[p.hash];
    // 端末内の欠損・破損も、当該パーツだけ再取得する。
    if (typeof text === 'string' && new TextEncoder().encode(text).length === p.bytes && await vpClientHash(text) === p.hash) {
      parsedRows.set(p.hash, vpRows(text, p)); verified.add(p.hash); parts.set(p.hash, text);
    } else missing.push(p);
  }
  // 前回の読み込みが途中で失敗していたら、読み終えていた部品を使う（一致を確かめたものだけ）。
  const pending = cache.pending;
  if (pending && missing.length) {
    let saved = null;
    try { saved = await pending.take(key, new Set(m.parts.map(p => p.hash))); } catch { /* 使えなければ最初から読む */ }
    for (let i = missing.length - 1; saved && i >= 0; i--) {
      const p = missing[i], text = saved.get(p.hash);
      if (typeof text !== 'string' || new TextEncoder().encode(text).length !== p.bytes || await vpClientHash(text) !== p.hash) continue;
      let rows;
      try { rows = vpRows(text, p); } catch { continue; }
      parsedRows.set(p.hash, rows); verified.add(p.hash); parts.set(p.hash, text); missing.splice(i, 1);
    }
  }
  for (let i = 0; i < missing.length; i += VP_BATCH) {
    const batch = missing.slice(i, i + VP_BATCH), request = new URL(endpoint);
    if (site === 'pscube') request.searchParams.set('file', 'pscube');
    request.searchParams.set('revision', m.revision);
    request.searchParams.set('parts', batch.map(p => p.hash).join(','));
    const result = await getJson(request.href);
    if (result?.format !== VP_FORMAT || result.revision !== m.revision || !Array.isArray(result.parts) ||
        result.parts.length !== batch.length) throw new Error('閲覧用が更新されました。もう一度読み込んでください。');
    for (let j = 0; j < batch.length; j++) {
      const p = batch[j], item = result.parts[j];
      if (item?.hash !== p.hash || typeof item.text !== 'string' || new TextEncoder().encode(item.text).length !== p.bytes ||
          await vpClientHash(item.text) !== p.hash) throw new Error('閲覧用の日別データが一致しません。');
      parsedRows.set(p.hash, vpRows(item.text, p)); verified.add(p.hash); parts.set(p.hash, item.text);
    }
    // 次の部品で失敗しても、ここまでの分は次の読み込みで使う（残りが無ければ保存しない）。
    if (pending && i + VP_BATCH < missing.length) {
      try { await pending.put(key, batch.map(p => [p.hash, parts.get(p.hash)])); } catch { /* 保存できなくても読み込みは続ける */ }
    }
  }
  const covered = m.version === 2 ? m.days : [...new Set(m.parts.map(p => p.day))];
  if (cached?.missingDays?.some(day => !covered.includes(day))) {
    throw new Error('Googleにない過去の履歴が端末で欠損しています。元バックアップから復元してください。保存データは変更していません。');
  }
  // 現行一覧にある壊れたパーツは取得済みの正しい内容へ置換してから検査する。
  const restored = {...(cached?.parts || {})};
  for (const [hash, text] of parts) restored[hash] = text;
  for (const [hash, text] of Object.entries(restored)) {
    if (verified.has(hash) || await vpClientHash(text) === hash) { verified.add(hash); continue; }
    if (covered.includes(cached?.partDays?.[hash])) { delete restored[hash]; continue; }
    let day;
    try { day = JSON.parse(text)?.[0]?.day; } catch { /* 日付不明は自動で破棄しない */ }
    if (day && covered.includes(day)) { delete restored[hash]; continue; }
    throw new Error('保存した過去の履歴が破損しています。元バックアップから復元してください。保存データは変更していません。');
  }
  const history = vpCachedDays({parts: restored, partDays: cached?.partDays}), updates = {};
  // v1の対象範囲内で消えた日も完成版として空にする。期間外の古い日は残す。
  if (m.version === 1 && covered.length) {
    const sorted = covered.slice().sort();
    for (const day of history.keys()) if (day >= sorted[0] && day <= sorted.at(-1) && !covered.includes(day)) covered.push(day);
  }
  for (const day of covered) updates[day] = {};
  for (const p of m.parts) updates[p.day][p.hash] = parts.get(p.hash);
  for (const [day, value] of Object.entries(updates)) history.set(day, value);
  // 更新に入らない日の部品は、すべて restored の検査（上）を通っている（壊れたものは消すか、例外で止まる）。
  // ここで同じハッシュをもう一度計算しない。
  for (const [day, value] of history) {
    if (Object.hasOwn(updates, day)) continue;
    for (const [hash] of Object.entries(value)) if (!verified.has(hash)) {
      throw new Error('保存した過去の履歴が破損しています。元バックアップから復元してください。保存データは変更していません。');
    }
  }
  // 日別に保存した過去分も既存画面へ渡す。画面・採点規則は変えない。
  // グラフの線の参照（台の画面を開いたときに fetchViewerCurves で読む）は、端末に保存する見出しにも残す。
  const curveRefs = vpPublicCurves(m);
  const doc = {...m.header, ...curveRefs, history: true, history_days: [...history.keys()].sort(), records: [...history].sort(([a], [b]) => a.localeCompare(b))
    .flatMap(([day, texts]) => Object.entries(texts).flatMap(([hash, text]) => {
      const rows = parsedRows.get(hash) ?? JSON.parse(text);
      if (!Array.isArray(rows) || rows.some(r => r?.day !== day)) throw new Error('保存した履歴の日付が一致しません。');
      return rows;
    }))};
  const previousDays = vpCachedDays(cached);
  const changed = Object.fromEntries(Object.entries(updates).filter(([day, value]) =>
    cached?.missingDays?.includes(day) || Object.keys(previousDays.get(day) || {}).sort().join(',') !== Object.keys(value).sort().join(',')));
  const store = () => vpStoreHistory(cache, key, cached, changed, {...m.header, ...curveRefs, parts_at: m.header.exported_at});
  try { await store(); }
  catch (e) {
    // 読みかけの分で容量が足りなかったときのため、読みかけを消してもう1回だけ保存する。
    let retried = false;
    if (pending) try { await pending.clear(key); await store(); retried = true; } catch { /* 下の知らせを出す */ }
    if (!retried) throw new Error('履歴を端末に保存できませんでした。前の保存データは保持しています。空き容量とブラウザの保存設定を確認してください。');
  }
  // 全部そろって保存したので、読みかけは要らない。
  if (pending) try { await pending.clear(key); } catch { /* 次に読むとき、一覧に無い分は消える */ }
  return doc;
}
// 1日分のグラフの線を読む（[通し番号, 線] の一覧）。refs は一覧の curve_parts のうちその日の分。
async function fetchViewerCurves(url, site, refs, getJson) {
  const endpoint = new URL(url); endpoint.search = ''; endpoint.hash = '';
  const rows = [];
  for (const ref of refs) {
    const request = new URL(endpoint);
    if (site === 'pscube') request.searchParams.set('file', 'pscube');
    request.searchParams.set('curves', ref.hash);
    const result = await getJson(request.href);
    if (result && typeof result.error === 'string') throw new Error(result.error);
    if (result?.format !== VP_CURVES_FORMAT || result.hash !== ref.hash || typeof result.text !== 'string' ||
        new TextEncoder().encode(result.text).length !== ref.bytes || await vpClientHash(result.text) !== ref.hash) {
      throw new Error('グラフの線のデータが一致しません。');
    }
    rows.push(...vpCurveRows(result.text, ref));
  }
  return rows;
}
async function fetchViewerDocument(url, site, getJson, cache) {
  const check = new URL(url); check.searchParams.set('check', '1');
  if (site === 'meruhen') check.searchParams.set('access', '1');
  // 更新途中の版変更は、一覧を取り直して1回だけ再試行する。
  for (let attempt = 0; ; attempt++) {
    const doc = await getJson(check.href);
    if (doc?.format !== 'drive-check') return doc; // 古いスクリプトが全文を返す。
    if (!doc.parts || !globalThis.crypto?.subtle) return getJson(url);
    try { return await fetchViewerParts(url, site, doc.parts, getJson, cache); }
    catch (error) { if (attempt) throw error; }
  }
}
