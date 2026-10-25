// 推定差枚の一致を確かめる合成データ（test/fixtures/meruhen_net_parity.json）を作る（2026-10-25）。
// グラフの線を外して Google で計算した値（tool/viewer_curves_split.js）が、閲覧ページ（Dart）・
// 共有カレンダー（share_viewer/net.mjs）が線から計算する値と1枚も違わないことを、3つの試験で確かめる。
// 規則（net.mjs・meruhen_net.dart）を変えたら作り直す：node tool/make_meruhen_net_parity.mjs
import {writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {meruhenNetDetail} from '../../share_viewer/net.mjs';

const ZERO = 200.5, TOP = 20.5, HALF = ZERO - TOP;
const STEPS = [1000, 2000, 4000, 6000, 8000, 10000, 12000, 14000, 16000, 18000, 20000, 22000, 24000, 26000, 28000, 30000];

export function parityRecords(count = 600) {
  let seed = 20261025;
  const random = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  const pick = list => list[Math.floor(random() * list.length)];
  const records = [];
  for (let i = 0; i < count; i++) {
    const points = 2 + Math.floor(random() * 70), curve = [];
    let y = ZERO, x = 0;
    for (let p = 0; p < points; p++) {
      // 小数1桁・2桁の座標、ゼロ線ちょうど・上端・下端も混ぜる。
      y = Math.min(380.5, Math.max(TOP, y + (random() - 0.5) * pick([4, 20, 60, 140, 240])));
      if (random() < 0.05) y = ZERO;
      const scale = pick([10, 100]);
      curve.push([Math.round(x * 10) / 10, Math.round(y * scale) / scale]);
      x += 1 + random() * 12;
    }
    const values = curve.map(p => ZERO - p[1]), last = curve.at(-1);
    let low = 0, rise = 0, drops = 0;
    values.forEach((v, k) => {
      if (v < low) low = v; if (v - low > rise) rise = v - low;
      if (k && v < values[k - 1]) drops += values[k - 1] - v;
    });
    // 振れ幅に合う目盛り（net.mjs の fits）から選び、持玉・回転数を境目の前後に散らす。
    const amp = Math.max(...values.map(Math.abs), 0.01);
    const fitting = STEPS.filter((range, k) => amp * range / HALF > (k ? STEPS[k - 1] : 0) - range / HALF / 2);
    const step = pick(fitting.length ? fitting : STEPS);
    const maxHold = random() < 0.06 ? null : random() < 0.04 ? 0
      : Math.max(0, Math.round(rise * step / HALF * (0.9 + random() * 0.6)));
    const games = random() < 0.08 ? 0 : Math.max(1, Math.round(drops * step / HALF / (0.6 + random() * 3)));
    const peak = curve.reduce((a, b) => (b[1] < a[1] ? b : a)), trough = curve.reduce((a, b) => (b[1] > a[1] ? b : a));
    const graph = {
      baseline_y: random() < 0.04 ? 200 : ZERO, peak_y: peak[1], end_y: last[1], baseline_x: 0,
      peak_x: peak[0], end_x: last[0], method: 'synthetic', preview_width: 600, preview_height: 400, curve,
    };
    if (random() < 0.9) { graph.trough_y = trough[1]; graph.trough_x = trough[0]; }
    records.push({store: i % 7 === 0 ? 'nagamachiminami' : 'saiwaichou', day: '2026-10-' + String(1 + (i % 9)).padStart(2, '0'),
      machine: '合成機種' + (i % 13), rack: 100 + i, games, bb: Math.floor(random() * 60), rb: Math.floor(random() * 60),
      ...(maxHold === null ? {} : {max_hold: maxHold}), graph_measurement: graph});
  }
  return records;
}

export function parityExpected(records) {
  return records.map(r => {
    const net = meruhenNetDetail(r.graph_measurement, r.max_hold ?? null, r.games ?? 0);
    return {value: net.value, needs_check: net.needsCheck};
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const records = parityRecords();
  writeFileSync(new URL('../test/fixtures/meruhen_net_parity.json', import.meta.url),
    JSON.stringify({records, expected: parityExpected(records)}) + '\n');
}
