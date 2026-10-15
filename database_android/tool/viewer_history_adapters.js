function vhInput(file, kind) {
  return {file, kind, id: kind + ':' + file.getId(), name: file.getName(), size: file.getSize(), version: vpVersion(file)};
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
  return {...old, record_deletions: [...marks.values()],
    pc: (kind === 'pc' ? fresh.records : old.pc).filter(r => vhNotDeleted(r, marks)),
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
      return [vhInput(base, 'pc'), ...(legacy ? [vhInput(legacy, 'legacy')] : []),
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
    mergeHeader: (old, fresh) => {
      const events = new Map((old.date_events || []).map(e => [e.store + '|' + e.day, e]));
      for (const e of fresh.date_events || []) {
        const key = e.store + '|' + e.day, prior = events.get(key);
        if (!prior || !prior.updated_at || Date.parse(e.updated_at) >= Date.parse(prior.updated_at)) events.set(key, e);
      }
      return {...old, date_events: [...events.values()]};
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
      return [vhInput(base, 'pc'), ...(legacy ? [vhInput(legacy, 'legacy')] : []),
        ...pscubeCloudListInputs([folder, DriveApp.getRootFolder()]).map(i => vhInput(i.file, 'backup'))];
    },
    read: input => {
      if (input.kind !== 'pc') return pscubeCloudRead(input.file, input.size);
      if (input.size > PSCUBE_CLOUD_MAX_BYTES) throw new Error('PC閲覧用入力が48MiBを超えています。期間を分けてください。');
      let text;
      try { text = input.file.getBlob().getDataAsString('UTF-8'); } catch (e) { throw new PscubeCloudTransient(e.message); }
      return validateData(JSON.parse(text));
    },
    group: doc => vhGroup(doc, 'pscube'),
    fromViewer: (day, header, records) => ({site: 'pscube', day, data: {...emptyData(), machines: header.machines || [], records}}),
    merge: (old, fresh, input) => {
      if (input.kind === 'pc') {
        // PC閲覧用の16点グラフを、日別原本の完全グラフへ逆流させない。
        const previous = new Map(old.data.records.map(r => [recordKey(r), r]));
        fresh = {...fresh, records: fresh.records.map(r => {
          const prior = previous.get(recordKey(r));
          const same = prior && ['bb', 'rb', 'at_art', 'games', 'my'].every(k => prior[k] === r[k]);
          return same && prior.graph?.kind === 'daily' && prior.graph.points.length > (r.graph?.points.length || 0)
            ? {...r, graph: prior.graph} : r;
        })};
      }
      return {site: 'pscube', day: fresh.day, data: pscubeCloudMerge(old.data, fresh)};
    },
    viewer: value => pscubeCloudViewer(value.data, '').records,
    mergeHeader: (old, fresh) => {
      const machines = new Map((old.machines || []).map(m => [machineKey(m), m]));
      for (const m of fresh.machines) {
        const prior = machines.get(machineKey(m)); machines.set(machineKey(m), {...m, machine_type: m.machine_type ?? prior?.machine_type ?? null});
      }
      return {...old, machines: [...machines.values()], date_events: mergeDateEvents(old.date_events, fresh.date_events)};
    },
    failures: () => ({reasons: pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_ERRORS)) || {},
      versions: pscubeCloudParse(props.getProperty(PSCUBE_CLOUD_FAILED)) || {}}),
    transient: e => e instanceof PscubeCloudTransient,
    save: (status, f) => { pscubeCloudSave(props, status, f.reasons, f.versions);
      for (const line of pscubeCloudStatusLines(status, Object.values(f.reasons), Object.keys(f.versions).length)) console.log(line); },
  }, startedAt);
}
