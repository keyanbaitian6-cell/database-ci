// 前回までの方式（履歴方式か）と、貼り替えたスクリプトの設定の値が違えば、何も書かずに止める（2026-11-05）。
// 11/4、リポジトリのまま（履歴方式 false）の全文を貼り、履歴方式だった閲覧用ファイルを古い方式で書き直した。
// 方式を覚えていない（この版を初めて貼った）ときは、閲覧用の一覧が履歴方式（v2）なのに false なら止め、
// それ以外は今の方式を覚える。止める理由の文を返す（続けてよければ null）。
function vhModeProblem(folder, site, props, history, setting, change) {
  const key = site + 'CloudMode', mode = history ? 'history' : 'legacy';
  let last = props.getProperty(key);
  if (!last && !history) {
    try {
      const files = folder.getFilesByName(vpManifestName(site));
      if (files.hasNext() && JSON.parse(files.next().getBlob().getDataAsString('UTF-8')).version === 2) last = 'history';
    } catch (e) { /* 一覧が読めなければ判断しない */ }
  }
  if (!last) { props.setProperty(key, mode); return null; }
  if (last === mode) return null;
  return '前回までは' + (last === 'history' ? '履歴方式（' + setting + ' = true）' : '従来の方式（' + setting + ' = false）') +
    'で動いていましたが、貼ったスクリプトは ' + setting + ' = ' + history + ' です。閲覧用ファイルを書き換えずに止めました。' +
    '前回と同じ値にして貼り直してください（方式を本当に変えるときだけ、' + change + ' を実行してから同期します）。';
}

function vhInput(file, kind) {
  return {file, kind, id: kind + ':' + file.getId(), name: file.getName(), size: file.getSize(), version: vpVersion(file)};
}
function vhSourceStatus(old,fresh,input) {
  // PCが店ごとに分けて書き出したとき（2026-11-23）：見出しのファイル（split_stores）は台を持たないので「PCの書き出し」を
  // 作らない（作ると、同じ書き出しの店の分を台0件で上書きする）。
  if (Array.isArray(fresh.split_stores)) return mergeSyncStatus(old.sync_status,fresh.sync_status);
  // Driveの更新時刻は、その入力自身の書き出しにだけ結び付ける。
  // 古いPC出力の読み込みで、別ファイルにある新しいPC出力の時刻を偽って更新しない。
  const own=fresh.cloud_merged ? null : makeSyncWrite(fresh.source,fresh.exported_at,fresh.records || [],
    input?.file ? input.file.getLastUpdated().toISOString() : undefined);
  // 店のファイル（stores）は、同じ時刻の書き出し（PCは1回の書き出しの3つのファイルに同じ時刻を入れる）の
  // 「PCの書き出し」に、その店の分を足し合わせる。時刻が違えば今までどおり新しい方を残す。
  const prior=fresh.source==='pc-viewer' && Array.isArray(fresh.stores) && own ? (validateSyncStatus(old.sync_status)?.writes || []).find(w => w.source==='pc') : null;
  const mine=own?.writes[0];
  if (prior && mine && Date.parse(prior.at)===Date.parse(mine.at)) {
    const drive=[prior.drive_at,mine.drive_at].filter(Boolean).sort().pop();
    const joined=validateSyncStatus({version:1,writes:[{source:'pc',at:mine.at,...(drive ? {drive_at:drive} : {}),
      stores:[...prior.stores.filter(s => !fresh.stores.includes(s.store)),...mine.stores]}]});
    const rest=validateSyncStatus(old.sync_status);
    return mergeSyncStatus({...rest,writes:rest.writes.filter(w => w.source!=='pc')},fresh.sync_status,joined);
  }
  return mergeSyncStatus(old.sync_status,fresh.sync_status,own);
}
// A missing day may have aged out of the PC's 60-day view. Only an explicit,
// timestamped operation can remove a record from the permanent cloud history.
function vhDeletions(doc) {
  const marks = doc.record_deletions === undefined ? [] : doc.record_deletions;
  if (!Array.isArray(marks) || marks.some(m => !m || !MERUHEN_STORES.includes(m.store) ||
      !meruhenValidDay(m.day) || typeof m.machine !== 'string' || !m.machine.trim() ||
      !Number.isSafeInteger(m.rack) || m.rack < 1 || meruhenTime(m.deleted_at) === null ||
      !/(?:Z|[+-]\d{2}:\d{2})$/.test(m.deleted_at))) throw new Error('削除記録が不正です。');
  return marks;
}
function vhNotDeleted(row, deletions) {
  const mark = deletions.get(meruhenKey(row));
  return !mark || Math.max(meruhenTime(row.record_updated_at) || 0, meruhenTime(row.captured_at) || 0) > meruhenTime(mark.deleted_at);
}
function vhSortPc(rows) {
  return rows.map((r, i) => [r, i]).sort(([a, i], [b, j]) =>
    a.store < b.store ? -1 : a.store > b.store ? 1 : a.rack - b.rack || i - j).map(([r]) => r);
}
function vhMergeMeruhen(old, fresh, kind) {
  const marks = new Map(vhDeletions(old).map(m => [meruhenKey(m), m]));
  for (const m of vhDeletions(fresh)) {
    const key = meruhenKey(m), prior = marks.get(key);
    if (!prior || meruhenTime(m.deleted_at) > meruhenTime(prior.deleted_at)) marks.set(key, m);
  }
  const android = new Map(old.android.map(r => [meruhenKey(r), r]));
  if (kind !== 'pc') for (const r of fresh.records) {
    const key = meruhenKey(r), prior = android.get(key);
    android.set(key, prior ? meruhenPick(prior, r) : r);
  }
  // PCの閲覧用入力に記録が1件も無い日（削除印・イベントだけの日。60日より前の削除印の日など）は、
  // その日の記録を出していないだけ。置き換えると、残っているPCの記録が消える（2026-10-17、8/1〜8/17だけの
  // 入力で9/14〜9/20などの30日が消えた）。残した記録にも削除印を当てるので、本当に消した台は消える。
  // 店ごとのファイル（stores あり。2026-11-23 利用者「店ごとに分ける」）は、その店のPCの台だけを入れ替え、
  // ほかの店の台は残す。並びは分ける前の1ファイル（PC の ORDER BY day,store,rack）と同じ店→台番の順にそろえ、
  // 同じ中身なら日別原本を書き直さない（読む順で並びが変わると、毎回全日を書き直してしまう）。
  const stores = Array.isArray(fresh.stores) ? new Set(fresh.stores) : null;
  const pc = kind === 'pc' && fresh.records.length
    ? (stores ? vhSortPc([...old.pc.filter(r => !stores.has(r.store)), ...fresh.records]) : fresh.records)
    : old.pc;
  return {...old, record_deletions: [...marks.values()],
    pc: pc.filter(r => vhNotDeleted(r, marks)),
    android: [...android.values()].filter(r => vhNotDeleted(r, marks))};
}
function vhGroup(doc, site) {
  const grouped = new Map();
  for (const r of doc.records) {
    if (!grouped.has(r.day)) grouped.set(r.day, []); grouped.get(r.day).push(r);
  }
  // イベントだけのバックアップも日付単位で処理する。
  for (const e of doc.date_events || []) if (!grouped.has(e.day)) grouped.set(e.day, []);
  if (site === 'meruhen') for (const m of vhDeletions(doc)) if (!grouped.has(m.day)) grouped.set(m.day, []);
  const captures = new Set(doc.rack_captures || []);
  return new Map([...grouped].map(([day, records]) => [day, {...doc, site, day, records,
    ...(doc.date_events ? {date_events: doc.date_events.filter(e => e.day === day)} : {}),
    ...(site === 'meruhen' ? {record_deletions: vhDeletions(doc).filter(m => m.day === day)} : {}),
    ...(doc.rack_captures ? {rack_captures: records.map(recordKey).filter(k => captures.has(k))} : {})}]));
}
function vhMeruhen(folder, base, props, startedAt) {
  return vhSync(folder, base, props, {
    site: 'meruhen', write: meruhenWrite,
    header: () => ({format: 'database-backup', version: 1, source: 'pc-viewer', exported_at: new Date().toISOString()}),
    inputs: () => {
      const legacy = meruhenUniqueFile(folder, MERUHEN_CLOUD_STORE);
      // PCの店ごとの閲覧用（2026-11-23）。見出しの base より後に読む。無ければ（分ける前のPC）今までどおり base だけ。
      const stores = MERUHEN_STORES.map(s => meruhenUniqueFile(folder, 'database-viewer-' + s + '.json')).filter(Boolean);
      return [vhInput(base, 'pc'), ...stores.map(f => vhInput(f, 'pc')), ...(legacy ? [vhInput(legacy, 'legacy')] : []),
        ...meruhenListInputs([folder, DriveApp.getRootFolder()]).map(i => vhInput(i.file, 'android'))];
    },
    read: input => {
      if (input.kind === 'android') return meruhenReadBackup(input.file, input.size, true);
      if (input.kind === 'legacy') return meruhenReadStore(input.file);
      if (input.size > MERUHEN_CLOUD_MAX_BYTES) throw new Error('PC閲覧用入力が48MiBを超えています。期間を分けてください。');
      let text;
      try { text = input.file.getBlob().getDataAsString('UTF-8'); } catch (e) { throw new MeruhenCloudTransient(e.message); }
      const doc = JSON.parse(text.replace(/^\uFEFF/, ''));
      if (doc.format !== 'database-backup' || doc.version !== 1 || doc.source !== 'pc-viewer' ||
          !Array.isArray(doc.records) || !doc.records.every(meruhenValidRecord)) throw new Error('PC閲覧用の形式が不正です。');
      // 店ごとのファイルは、書いてある店の台・削除の印だけ。見出しのファイル（split_stores）は台を持たない。
      const inStores = list => !Array.isArray(doc.stores) || list.every(x => doc.stores.includes(x.store));
      if (doc.stores !== undefined && (!Array.isArray(doc.stores) || !doc.stores.length ||
          !doc.stores.every(s => MERUHEN_STORES.includes(s)) || !inStores(doc.records) || !inStores(vhDeletions(doc)))) {
        throw new Error('PCの店ごとの閲覧用の形式が不正です。');
      }
      if (doc.split_stores !== undefined && (!Array.isArray(doc.split_stores) || doc.records.length)) {
        throw new Error('PCの閲覧用の見出しの形式が不正です。');
      }
      vhDeletions(doc); return doc;
    },
    group: doc => vhGroup(doc, 'meruhen'),
    fromViewer: (day, header, records) => ({site: 'meruhen', day, pc: records, android: []}),
    merge: (old, fresh, input) => {
      if (!Array.isArray(old.pc) || !Array.isArray(old.android) || ![...old.pc, ...old.android].every(meruhenValidRecord)) {
        throw new Error('メルヘンの日別原本が不正です。');
      }
      return vhMergeMeruhen(old, fresh, input.kind);
    },
    viewer: value => meruhenApply({records: value.pc}, value.android).records,
    mergeHeader: (old, fresh, input) => {
      const events = new Map((old.date_events || []).map(e => [e.store + '|' + e.day, e]));
      for (const e of fresh.date_events || []) {
        const key = e.store + '|' + e.day, prior = events.get(key);
        if (!prior || !prior.updated_at || Date.parse(e.updated_at) >= Date.parse(prior.updated_at)) events.set(key, e);
      }
      // PCの閲覧用の日ごとの「何台中何台プラス」（day_summaries、2026-10-18 html_day_summary.py）は、
      // PCの最新の出力のものに置き換える。Androidのバックアップには無いので前のまま。
      const summaries = Array.isArray(fresh.day_summaries) ? {day_summaries: fresh.day_summaries} : {};
      // 当時の翌日候補（answer_candidates、2026-11-04 閲覧ページの答え合わせ用、core.py saved_answer_candidates）も
      // PCの最新の出力のものに置き換える。Androidのバックアップには無いので前のまま。
      const answers = fresh.answer_candidates && typeof fresh.answer_candidates === 'object' && !Array.isArray(fresh.answer_candidates)
        ? {answer_candidates: fresh.answer_candidates} : {};
      return {...old, ...summaries, ...answers, date_events: [...events.values()],sync_status:vhSourceStatus(old,fresh,input)};
    },
    failures: () => ({reasons: meruhenParse(props.getProperty(MERUHEN_CLOUD_ERRORS)) || {},
      versions: meruhenParse(props.getProperty(MERUHEN_CLOUD_FAILED)) || {}}),
    transient: e => e instanceof MeruhenCloudTransient,
    save: (status, f) => { meruhenSave(props, status, f.reasons, f.versions);
      for (const line of meruhenStatusLines(status, Object.values(f.reasons), Object.keys(f.versions).length)) console.log(line); },
  }, startedAt);
}
function vhPscube(folder, base, props, startedAt) {
  if (!base) base = pscubeCloudWrite(folder, null, PSCUBE_CLOUD_VIEWER,
    JSON.stringify({...emptyData(), kind: 'viewer', source: 'cloud', exported_at: new Date().toISOString()}));
  return vhSync(folder, base, props, {
    site: 'pscube', write: pscubeCloudWrite,
    header: () => { const {records, ...header} = emptyData(); return {...header, kind: 'viewer', source: 'cloud', exported_at: new Date().toISOString()}; },
    inputs: () => {
      const legacy = pscubeCloudUniqueFile(folder, PSCUBE_CLOUD_BACKUP);
      const inputs = [vhInput(base, 'pc'), ...(legacy ? [vhInput(legacy, 'legacy')] : []),
        ...pscubeCloudListInputs([folder, DriveApp.getRootFolder()]).map(i => vhInput(i.file, i.browser ? 'browser' : 'backup'))];
      const baseline = vpHash(vpCanonical(inputs.filter(i=>i.kind!=='browser').map(i=>[i.id,i.version])));
      for (const input of inputs) if (input.kind==='browser') input.baseline=baseline;
      return inputs;
    },
    read: input => {
      if (input.kind !== 'pc') return pscubeCloudRead(input.file, input.size,input.kind==='browser' ? 'browser' : null);
      if (input.size > PSCUBE_CLOUD_MAX_BYTES) throw new Error('PC閲覧用入力が48MiBを超えています。期間を分けてください。');
      let text;
      try { text = input.file.getBlob().getDataAsString('UTF-8'); } catch (e) { throw new PscubeCloudTransient(e.message); }
      const raw=JSON.parse(text);
      return {...validateData(raw),source:raw.source,exported_at:raw.exported_at};
    },
    group: doc => vhGroup(doc, 'pscube'),
    fromViewer: (day, header, records) => ({site: 'pscube', day, data: {...emptyData(), machines: header.machines || [], records}}),
    merge: (old, fresh, input) => {
      if (input.kind === 'pc') {
        // PC閲覧用の16点グラフを、日別原本の完全グラフへ逆流させない。一覧のグラフ（overview、多くは17点）も同じ
        // （2026-10-25：16点と17点を行き来して、同じ日の原本を同期のたびに書き直していた）。
        const previous = new Map(old.data.records.map(r => [recordKey(r), r]));
        fresh = {...fresh, records: fresh.records.map(r => {
          const prior = previous.get(recordKey(r));
          const same = prior && ['bb', 'rb', 'at_art', 'games', 'my'].every(k => prior[k] === r[k]);
          // 新旧ともグラフなしならkindも両方undefinedになる。点列のある原本だけを保護する。
          const previousPoints = prior?.graph?.points;
          const incomingPoints = r.graph?.points;
          return same && Array.isArray(previousPoints) &&
            (prior.graph.kind === 'daily' || prior.graph.kind === r.graph?.kind) &&
            previousPoints.length > (Array.isArray(incomingPoints) ? incomingPoints.length : 0)
            ? {...r, graph: prior.graph} : r;
        })};
      }
      const report=input.kind==='browser' ? (input.report || (input.report={})) : null;
      const merged = input.kind==='browser' ? mergeNetSupplement(old.data,fresh,report) : pscubeCloudMerge(old.data,fresh);
      // 更新経路は一覧の見出しに保持し、同じ情報だけで全日別原本を再生成しない。
      const {sync_status,...data}=merged;
      return {site: 'pscube', day: fresh.day, data};
    },
    viewer: value => pscubeCloudViewer(value.data, '').records,
    mergeHeader: (old, fresh, input) => {
      if (input?.kind==='browser') return {...old,sync_status:vhSourceStatus(old,fresh,input)};
      const machines = new Map((old.machines || []).map(m => [machineKey(m), m]));
      for (const m of fresh.machines) {
        const prior = machines.get(machineKey(m)); machines.set(machineKey(m), {...m, machine_type: m.machine_type ?? prior?.machine_type ?? null});
      }
      return {...old, machines: [...machines.values()], date_events: mergeDateEvents(old.date_events, fresh.date_events),sync_status:vhSourceStatus(old,fresh,input)};
    },
    failures: () => ({reasons: pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_ERRORS)) || {},
      versions: pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_FAILED)) || {}}),
    transient: e => e instanceof PscubeCloudTransient,
    save: (status, f) => { pscubeCloudSave(props, status, f.reasons, f.versions);
      for (const line of pscubeCloudStatusLines(status, Object.values(f.reasons), Object.keys(f.versions).length)) console.log(line); },
  }, startedAt);
}
