const SCRIPT_RELEASE = '09e2c8670954';
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
