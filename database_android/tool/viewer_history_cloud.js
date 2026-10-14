// 履歴モード。全期間のレコードを組み立てず、入力1本と変更日の完成版だけを扱う。
// 確定点は閲覧一覧1本。日別の原本と閲覧パーツは不変で、一覧を最後に書く。
function vhBytes(text) { return Utilities.newBlob(text).getBytes().length; }
function vhRead(ref) {
  const f = DriveApp.getFileById(ref.id);
  if (f.isTrashed() || f.getName() !== ref.name || f.getSize() !== ref.bytes || ref.bytes > VP_MAX_BYTES) {
    throw new Error('履歴の日別原本が見つかりません。元バックアップからの復旧が必要です。');
  }
  const text = f.getBlob().getDataAsString('UTF-8');
  if (vpHash(text) !== ref.hash) throw new Error('履歴の日別原本が破損しています。上書きせず停止しました。');
  const value = JSON.parse(text);
  if (value.day !== ref.day || value.site !== ref.site) throw new Error('履歴の日別原本の日付が不正です。');
  return value;
}
function vhImmutable(folder, name, text, write) {
  const hash = vpHash(text), bytes = vhBytes(text);
  if (bytes > VP_MAX_BYTES) throw new Error('1日分の統合原本が48MiBを超えます。既存の履歴は保持しました。');
  const matches = folder.getFilesByName(name); let file = null;
  while (matches.hasNext()) {
    const f = matches.next();
    if (!f.isTrashed() && f.getSize() === bytes && vpHash(f.getBlob().getDataAsString('UTF-8')) === hash) { file = f; break; }
  }
  const created = !file;
  if (!file) file = write(folder, null, name, text);
  return {id: file.getId(), name, hash, bytes, created};
}
function vhDayParts(folder, site, day, rows, write) {
  const parts = []; let batch = [], size = 2, written = 0, writtenBytes = 0;
  const flush = () => {
    if (!batch.length) return;
    const text = '[' + batch.join(',') + ']', hash = vpHash(text), name = vpPartName(site, hash);
    const ref = vhImmutable(folder, name, text, write);
    parts.push({day, hash, count: batch.length, bytes: ref.bytes, id: ref.id,
      file_version: vpVersion(DriveApp.getFileById(ref.id))});
    if (ref.created) { written++; writtenBytes += ref.bytes; }
    batch = []; size = 2;
  };
  for (const row of rows.map(vpCanonical).sort()) {
    const bytes = vhBytes(row);
    if (bytes + 2 > VP_PART_BYTES) throw new Error('1台の閲覧用データが1MiBを超えています。');
    if (size + bytes + (batch.length ? 1 : 0) > VP_PART_BYTES) flush();
    size += bytes + (batch.length ? 1 : 0); batch.push(row);
  }
  flush(); return {parts, written, writtenBytes};
}

function vhSync(folder, base, props, adapter, startedAt) {
  const {site, write} = adapter, indexName = vpManifestName(site);
  const indexFile = vpUnique(folder, indexName);
  const old = indexFile ? vpReadManifest(indexFile, site) : null;
  const baseVersion = base ? vpVersion(base) : '';
  // v1の閲覧パーツも消さずに引き継ぐ。原本が無い日は最初の更新時だけパーツから戻す。
  const m = old ? JSON.parse(JSON.stringify(old)) : {header: adapter.header(), parts: [], count: 0};
  m.format = VP_FORMAT; m.version = 2; m.site = site; m.base = baseVersion;
  m.history_inputs ||= {}; m.history_progress ||= {}; m.cloud_days ||= [];
  const days = new Map(m.cloud_days.map(d => [d.day, d]));
  const parts = new Map();
  for (const p of m.parts) { if (!parts.has(p.day)) parts.set(p.day, []); parts.get(p.day).push(p); }
  const loadDay = day => {
    if (days.has(day)) return vhRead(days.get(day));
    const rows = (parts.get(day) || []).flatMap(p => vpRows(vpReadPart(site, p), p));
    return adapter.fromViewer(day, m.header, rows);
  };
  // 移行元・PC再出力も版が変わった場合だけ読む。入力原本は変更・削除しない。
  const inputs = adapter.inputs();
  const failures = adapter.failures();
  const live = new Set(inputs.map(i => i.id));
  for (const table of [m.history_inputs, m.history_progress, failures.reasons, failures.versions]) {
    for (const id of Object.keys(table)) if (!live.has(id)) delete table[id];
  }
  const newFailures = []; let processed = 0, changedDays = 0, written = 0, bytes = 0, readBytes = 0;
  const pending = inputs.filter(i => m.history_inputs[i.id] !== i.version && failures.versions[i.id] !== i.version);
  for (const input of pending.slice(0, 10)) {
    if (readBytes && (Date.now() - startedAt > 150000 || readBytes + input.size > 64 * 1024 * 1024)) break;
    let incoming;
    try { incoming = adapter.read(input); }
    catch (error) {
      if (adapter.transient(error)) continue;
      const f = {name: input.name, reason: String(error.message || error).slice(0, 120), version: input.version,
        checked_at: new Date().toISOString(), size: input.size};
      failures.reasons[input.id] = f; failures.versions[input.id] = input.version; newFailures.push(f);
      continue;
    }
    readBytes += input.size;
    if (vpVersion(input.file) !== input.version) continue;
    const grouped = adapter.group(incoming), allDays = [...grouped.keys()].sort();
    const resume = m.history_progress[input.id];
    const start = resume?.version === input.version ? resume.next : 0;
    let next = start;
    // 大きい初回入力は日付単位で途中確定し、次の30分実行で続きから処理する。
    for (; next < allDays.length; next++) {
      if (changedDays >= 24 || (next > start && Date.now() - startedAt > 150000)) break;
      const day = allDays[next], prior = loadDay(day);
      const value = adapter.merge(prior, grouped.get(day), input);
      if (value.day !== day || value.site !== site) throw new Error('統合後の日付が不正です。');
      const rawText = vpCanonical(value), rawHash = vpHash(rawText);
      if (days.get(day)?.hash === rawHash) continue;
      const rows = adapter.viewer(value);
      if (rows.length > 100000) throw new Error('1日分の閲覧記録が10万件を超えています。');
      const published = vhDayParts(folder, site, day, rows, write);
      const rawName = 'database-history-day-' + site + '-' + day + '-' + rawHash + '.json';
      const {created, ...rawRef} = vhImmutable(folder, rawName, rawText, write);
      days.set(day, {...rawRef, day, site, count: rows.length}); parts.set(day, published.parts);
      written += published.written; bytes += published.writtenBytes; changedDays++;
    }
    if (next < allDays.length) m.history_progress[input.id] = {version: input.version, next};
    else {
      m.history_inputs[input.id] = input.version; delete m.history_progress[input.id];
      delete failures.versions[input.id]; delete failures.reasons[input.id]; processed++;
    }
    m.header = adapter.mergeHeader(m.header, incoming);
    if (next < allDays.length) break;
  }
  if (props.getProperty(site + 'HistoryRebuild')) {
    let next = m.history_rebuild_next || 0;
    const ordered = [...days.keys()].sort();
    for (; next < ordered.length; next++) {
      if (changedDays >= 24 || Date.now() - startedAt > 150000) break;
      const day = ordered[next], value = vhRead(days.get(day));
      const published = vhDayParts(folder, site, day, adapter.viewer(value), write);
      parts.set(day, published.parts); written += published.written; bytes += published.writtenBytes; changedDays++;
    }
    m.history_rebuild_next = next < ordered.length ? next : null;
  }
  if (base && vpVersion(base) !== baseVersion) throw new Error('PCの閲覧用が処理中に変更されました。次回やり直します。');
  m.parts = [...parts].sort(([a], [b]) => a.localeCompare(b)).flatMap(([, p]) => p);
  m.cloud_days = [...days.values()].sort((a, b) => a.day.localeCompare(b.day));
  m.days = [...new Set([...parts.keys(), ...days.keys()])].sort();
  m.count = m.parts.reduce((n, p) => n + p.count, 0);
  const {exported_at, ...stableHeader} = m.header;
  m.signature = vpHash(vpCanonical({parts: m.parts.map(({day, hash}) => ({day, hash})), days: m.days, header: stableHeader}));
  if (old?.signature !== m.signature) m.header.exported_at = new Date(Math.max(Date.now(), Date.parse(old?.header?.exported_at || '') + 1 || 0)).toISOString();
  m.revision = vpHash(vpCanonical({base: m.base, parts: m.parts, days: m.days, header: m.header}));
  vpValidManifest(m, site);
  const text = JSON.stringify(m);
  // 一覧だけに独立した上限。レコード総容量の48MiB制限は適用しない。
  if (vhBytes(text) > 1024 * 1024) throw new Error('履歴の更新一覧が1MiBを超えます。元データを保持して停止しました。');
  if (!old || vpCanonical(old) !== vpCanonical(m)) write(folder, indexFile, indexName, text);
  if (props.getProperty(site + 'HistoryRebuild') && m.history_rebuild_next === null) props.deleteProperty(site + 'HistoryRebuild');
  // 故障した原本の自動削除はしない。未参照の生成物だけ7日後に整理する。
  vpMaintain(folder, site, props);
  vhMaintain(folder, site, props);
  const remaining = inputs.filter(i => m.history_inputs[i.id] !== i.version && failures.versions[i.id] !== i.version).length + (m.history_rebuild_next != null ? 1 : 0);
  const status = {at: new Date().toISOString(), result: Object.keys(failures.versions).length ? 'partial' : 'ok', history: true,
    message: '履歴を日別に保存・' + changedDays + '日更新', processed, remaining,
    viewer_records: m.count, android_records: m.count, backup_records: m.count, records: m.count,
    viewer_bytes: m.parts.reduce((n, p) => n + p.bytes, 0),
    backup_bytes: m.cloud_days.reduce((n, d) => n + d.bytes, 0),
    incremental: {parts: written, bytes}, elapsed_ms: Date.now() - startedAt};
  adapter.save(status, failures);
  return {changed: changedDays > 0, pending: remaining, newFailures, status};
}

// 元バックアップ・現行の全日原本・移行用控えは対象外。未参照の生成原本だけ7日後に整理。
function vhMaintain(folder, site, props) {
  const key = site + 'HistoryCleaned';
  if (Date.now() - Number(props.getProperty(key) || 0) < 6 * 3600000) return;
  try {
    const index = vpUnique(folder, vpManifestName(site)), revision = vpVersion(index);
    const m = vpReadManifest(index, site), active = new Set((m.cloud_days || []).map(d => d.id));
    const pattern = new RegExp('^database-history-day-' + site + '-\\d{4}-\\d{2}-\\d{2}-[a-f0-9]{64}\\.json$');
    const files = folder.getFiles(), cutoff = Date.now() - 7 * 86400000; let removed = 0;
    while (files.hasNext() && removed < 200) {
      const file = files.next();
      if (!file.isTrashed() && pattern.test(file.getName()) && !active.has(file.getId()) && file.getLastUpdated().getTime() < cutoff) {
        if (vpVersion(index) !== revision) throw new Error('履歴一覧が更新されました。');
        file.setTrashed(true); removed++;
      }
    }
    props.setProperty(key, String(Date.now()));
  } catch (error) { console.log('古い日別原本の整理は次回再試行します：' + String(error.message || error)); }
}
