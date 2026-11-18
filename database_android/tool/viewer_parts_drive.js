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
// 2026-11-19：PCの書き出しが新しくなってから、同期（30分ごと）が日別の部品を作り直すまでの間、前の一覧を使わずにいたため、
// 閲覧ページの更新とグラフの線の読み込みが止まり、台のグラフが概略図になった（利用者のiPhone、11/19 7:18）。部品と線は中身の
// ハッシュで決まるので、前の一覧のものも正しい。書き出しからこの時間内なら、前の一覧で一覧・部品・線を返す（閲覧ページは前の
// 内容のまま、作り直したあとの更新で新しくなる）。これを過ぎても作り直されないとき（同期が止まっている等）は、黙って古い内容を
// 出し続けないよう、今までどおり一覧を返さない。旧クライアントの全件GETは、今までどおり最新のファイル（doGet）を返す。
const VP_STALE_MS = 3 * 3600000;
function vpGet(latest, site, params) {
  // 旧形式だけの環境では追加の権限・設定は不要。
  const candidates = DriveApp.getFilesByName(vpManifestName(site));
  let manifest = null, previous = null;
  while (candidates.hasNext()) {
    const file = candidates.next(); if (file.isTrashed()) continue;
    if (file.getSize() > 1024 * 1024) continue;
    const raw = JSON.parse(file.getBlob().getDataAsString('UTF-8'));
    if (raw.base !== vpVersion(latest)) {
      const behind = latest.getLastUpdated().getTime() - file.getLastUpdated().getTime();
      if (!previous && behind >= 0 && behind <= VP_STALE_MS) previous = vpValidManifest(raw, site);
      continue;
    }
    const m = vpValidManifest(raw, site);
    if (manifest) throw new Error('閲覧用の更新一覧が複数あります。');
    manifest = m;
  }
  if (!manifest && previous && (params.check || params.parts || params.curves)) manifest = previous;
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
