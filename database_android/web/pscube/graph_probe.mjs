import {validateData, validDay} from './data.mjs';

const fail = message => { throw new Error(message); };
const safe = value => Number.isSafeInteger(value) && Math.abs(value) <= 10000000;
const dayOf = value => {
  if (!Number.isSafeInteger(value) || !/^\d{8}$/.test(String(value))) fail('グラフの日付が不正です。');
  const s = String(value), day = `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}`;
  if (!validDay(day)) fail('グラフの日付が不正です。');
  return day;
};

/** P’s CUBEの連続グラフの元数値。各日の始点と終点の差がその日の差枚。 */
export function netMedalsOfProbe(raw) {
  if (!raw || !Number.isSafeInteger(raw.rack) || raw.rack < 1 ||
      !/^\d{8}$/.test(raw.day ?? '') || !raw.graph ||
      !Array.isArray(raw.graph.datas?.g) || !Array.isArray(raw.graph.datas?.p) ||
      raw.graph.datas.g.length < 1 || raw.graph.datas.g.length > 7 ||
      raw.graph.datas.p.length > 50000) fail('P’s CUBEのグラフJSONではありません。');
  const selectedDay = dayOf(Number(raw.day));
  const factor = raw.graph.anjYUnit ?? 1;
  if (!Number.isFinite(factor) || factor <= 0 || factor > 100000) fail('グラフの単位が不正です。');
  const found = new Map(), fields = new Set();
  for (const line of raw.graph.datas.g) {
    const day = dayOf(line.YMD_biz), x = line.xField, y = line.yField;
    if (day > selectedDay || found.has(day) || typeof x !== 'string' || typeof y !== 'string' ||
        !/^out-\d+$/.test(x) || !/^value-\d+$/.test(y) || fields.has(y)) fail('グラフの日付・系列が不正です。');
    fields.add(y);
    const points = raw.graph.datas.p.filter(p => p && Object.hasOwn(p, x) && Object.hasOwn(p, y));
    if (points.length < 2 || points.some((p, i) => !safe(p[x]) || !safe(p[y]) ||
        (i && p[x] < points[i - 1][x]))) fail('グラフの元数値が不正です。');
    const net = (points.at(-1)[y] - points[0][y]) * factor;
    if (!Number.isSafeInteger(net) || Math.abs(net) > 1000000) fail('差枚の数値が不正です。');
    found.set(day, net);
  }
  if (!found.has(selectedDay)) fail('選択日のグラフがありません。');
  return found;
}

/** 既存記録の台番号と日付にだけ付ける。異なる店舗・貸玉の同番号は推測せず止める。 */
export function applyGraphProbe(existing, raw) {
  const data = validateData(existing), values = netMedalsOfProbe(raw);
  let matched = 0;
  const records = data.records.map(record => {
    if (record.rack !== raw.rack || !values.has(record.day)) return record;
    const matches = data.records.filter(r => r.rack === raw.rack && r.day === record.day);
    if (matches.length !== 1) fail('同じ台番号・日付が複数店舗にあります。店舗を特定できません。');
    matched++;
    return {...record, net_medals: values.get(record.day)};
  });
  if (!matched || !records.some(r => r.rack === raw.rack && r.day === dayOf(Number(raw.day)))) {
    fail('先にこの台・営業日のP’s CUBE記録を読み込んでください。');
  }
  return validateData({...data, records});
}
