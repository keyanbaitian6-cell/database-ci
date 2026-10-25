// メルヘンの閲覧用：グラフの線を記録から外し、線があるうちに推定差枚を計算して添える（2026-10-25）。
// iPhoneの閲覧ページが起動のたびに全日分の線をメモリに載せて落ちていたため。線の正本は日別原本に残す。
// 差枚は閲覧ページ（Dart の meruhenNetEstimateDetail）と同じ入力で計算する。Dart は最大持玉・回転数を
// 整数に直してから使い、共有カレンダー（net.mjs）は元の値を使うため、両方が同じ値になる記録
// （最大持玉・回転数が整数、座標がすべて有限の数）だけ線を外す。それ以外は今までどおり線を残す。
function vpCurveSplittable(r) {
  const g = r && r.graph_measurement, finite = v => typeof v === 'number' && Number.isFinite(v);
  if (!g || typeof g !== 'object' || Array.isArray(g) || !Array.isArray(g.curve) || g.curve.length < 2) return false;
  if (!['baseline_y', 'peak_y', 'end_y'].every(k => finite(g[k]))) return false;
  if (['trough_y', 'baseline_x', 'peak_x', 'trough_x', 'end_x'].some(k => g[k] != null && !finite(g[k]))) return false;
  if (g.curve.some(p => !Array.isArray(p) || p.length < 2 || !p.every(finite))) return false;
  if (r.max_hold != null && !Number.isSafeInteger(r.max_hold)) return false;
  if (r.games != null && !Number.isSafeInteger(r.games)) return false;
  return !('net_estimate' in g) && !('curve_index' in g) && !('curve_remote' in g);
}
// 1日分の閲覧用の記録から線を外す。rows は日別パーツへ、curves は [通し番号, 線] の一覧。
// 通し番号は記録の並べ方（vpCanonical の文字順）で決まり、同じ内容なら毎回同じになる。
function vpSplitCurves(rows, fits) {
  const ordered = rows.map(r => [vpCanonical(r), r]).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([, r]) => r);
  const light = [], curves = [];
  for (const r of ordered) {
    if (!vpCurveSplittable(r) || !fits(r.graph_measurement.curve)) { light.push(r); continue; }
    const {curve, ...graph} = r.graph_measurement;
    const net = VP_NET.meruhenNetDetail(r.graph_measurement, r.max_hold ?? null, r.games ?? null);
    const index = curves.length;
    curves.push([index, curve]);
    light.push({...r, graph_measurement: {...graph, curve_remote: true, curve_index: index,
      net_estimate: {value: net.value, needs_check: net.needsCheck, max_hold: r.max_hold ?? null, games: r.games ?? 0}}});
  }
  return {rows: light, curves};
}
// 線を外した記録へ線を戻す（日別原本の無い古い日を閲覧用パーツから組み立て直すとき）。
function vpRestoreCurves(rows, curves) {
  const byIndex = new Map(curves);
  return rows.map(r => {
    const g = r && r.graph_measurement;
    if (!g || g.curve_remote !== true) return r;
    if (!byIndex.has(g.curve_index)) throw new Error('グラフの線が見つかりません。元バックアップからの復旧が必要です。');
    const {curve_remote, curve_index, net_estimate, ...graph} = g;
    return {...r, graph_measurement: {...graph, curve: byIndex.get(g.curve_index)}};
  });
}
