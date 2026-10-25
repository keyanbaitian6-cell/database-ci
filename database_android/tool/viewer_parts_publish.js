// 全件のバックアップは従来どおり保持。閲覧用の出力だけを分割する。
function vpCheckpoint(folder, site, base) {
  const file = vpUnique(folder, vpManifestName(site));
  return (file ? vpVersion(file) : '') + (base ? ':' + vpVersion(base) : '');
}
function vpPublish(folder, base, site, doc, write, expectedBase) {
  const name = vpManifestName(site), oldFile = vpUnique(folder, name);
  const old = oldFile ? vpReadManifest(oldFile, site) : null;
  const byDay = new Map();
  for (const r of doc.records) {
    if (!byDay.has(r.day)) byDay.set(r.day, []);
    byDay.get(r.day).push(vpCanonical(r));
  }
  const planned = [];
  for (const day of [...byDay.keys()].sort()) {
    let rows = [], size = 2;
    const flush = () => { if (!rows.length) return; const text = '[' + rows.join(',') + ']';
      planned.push({day, count: rows.length, bytes: size, hash: vpHash(text), text}); rows = []; size = 2; };
    for (const row of byDay.get(day).sort()) {
      const bytes = Utilities.newBlob(row).getBytes().length;
      if (bytes + 2 > VP_PART_BYTES) throw new Error('1台の閲覧用データが1MiBを超えています。');
      if (size + bytes + (rows.length ? 1 : 0) > VP_PART_BYTES) flush();
      size += bytes + (rows.length ? 1 : 0); rows.push(row);
    }
    flush();
  }
  const {records, exported_at, cloud_merged, ...stableHeader} = doc;
  const signature = vpHash(vpCanonical({header: stableHeader, parts: planned.map(({day, hash}) => ({day, hash}))}));
  const header = {...stableHeader, exported_at: old?.signature === signature ? old.header.exported_at : exported_at};
  if (cloud_merged !== undefined) header.cloud_merged = cloud_merged;
  const version = expectedBase || vpVersion(base);
  if (vpVersion(base) !== version) throw new Error('PCの閲覧用が更新されました。次の同期でやり直します。');
  const revision = vpHash(vpCanonical({signature, base: version}));
  const m = {format: VP_FORMAT, version: 1, site, base: version, signature, revision,
    header, count: records.length, parts: planned.map(({text, ...p}) => p)};
  vpValidManifest(m, site); // 全出力の容量を先に検査。途中で失敗しても旧一覧は残る。
  // IDと版の追記分も見込んで、一覧の読み出し上限より余裕を持って止める。
  if (Utilities.newBlob(JSON.stringify(m)).getBytes().length + m.parts.length * 256 > 1024 * 1024) {
    throw new Error('閲覧用の更新一覧が1MiBを超えます。旧一覧を保って停止しました。');
  }
  const oldParts = new Map((old?.parts || []).map(p => [p.hash, p]));
  let written = 0, writtenBytes = 0;
  for (const p of m.parts) {
    const prior = oldParts.get(p.hash);
    let file = null;
    if (prior) { try { file = DriveApp.getFileById(prior.id); } catch (_) { /* 消えた生成ファイルを作り直す */ } }
    else file = vpUnique(folder, vpPartName(site, p.hash));
    // 紛失・手編集された生成ファイルは上書き修復。元バックアップには触れない。
    let valid = false;
    if (file && !file.isTrashed()) {
      valid = file.getName() === vpPartName(site, p.hash) && file.getSize() === p.bytes &&
        (!prior || prior.file_version === vpVersion(file));
      if (valid && !prior) valid = vpHash(file.getBlob().getDataAsString('UTF-8')) === p.hash;
    }
    if (!valid) {
      // 壊れた旧IDは旧一覧で読まれている可能性があるため、別の不変ファイルを作る。
      file = write(folder, null, vpPartName(site, p.hash), planned.find(x => x.hash === p.hash).text);
      written++; writtenBytes += p.bytes;
    }
    p.id = file.getId(); p.file_version = vpVersion(file);
  }
  if (vpVersion(base) !== version) throw new Error('PCの閲覧用が更新されました。次の同期でやり直します。');
  const text = JSON.stringify(m);
  const unchanged = old && vpCanonical(old) === vpCanonical(m);
  if (!unchanged) write(folder, oldFile, name, text); // 一覧を最後に確定する。
  return {parts: written, bytes: writtenBytes, total: planned.reduce((n, p) => n + p.bytes, 0), revision};
}

// 現在の一覧にない生成パーツだけを7日後にごみ箱へ。バックアップや旧形式JSONは対象外。
// 一覧確定後の保守であり、失敗しても確定済みの閲覧データは有効。
function vpPrune(folder, site) {
  const manifest = vpReadManifest(vpUnique(folder, vpManifestName(site)), site);
  const active = new Set([...manifest.parts, ...(manifest.curve_parts || [])].map(p => p.id));
  const pattern = new RegExp('^database-viewer-(part|curves)-' + site + '-[a-f0-9]{64}\\.json$');
  const files = folder.getFiles(), cutoff = Date.now() - 7 * 86400000;
  let removed = 0;
  while (files.hasNext() && removed < 200) {
    const f = files.next();
    if (!f.isTrashed() && pattern.test(f.getName()) && !active.has(f.getId()) && f.getLastUpdated().getTime() < cutoff) {
      f.setTrashed(true); removed++;
    }
  }
  return removed;
}
function vpMaintain(folder, site, props) {
  const key = site + 'ViewerPartsCleaned';
  if (Date.now() - Number(props.getProperty(key) || 0) < 6 * 3600000) return;
  try { vpPrune(folder, site); props.setProperty(key, String(Date.now())); }
  catch (error) { console.log('古い閲覧用キャッシュの整理は次回再試行します：' + String(error.message || error)); }
}
