// お店のひとこと（2026-11-04）：共有カレンダーの文が、閲覧ページ（Dart）と同じ試験データの期待値どおりか。
// Dart 側は test/day_comment_test.dart が同じファイルを読む。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {dayComment, storeDayComment} from '../../share_viewer/data.mjs';

const fixture = JSON.parse(fs.readFileSync(new URL('../test/fixtures/day_comment_cases.json', import.meta.url), 'utf8'));

for (const c of fixture.cases) {
  test(`ひとこと：${c.name}`, () => assert.equal(dayComment(c.input), c.expected));
}

test('ひとこと：店の前の30日の勝ち負けを数える（31日前・ほかの店は数えない）', () => {
  const rack = (store, day, rack, net) => ({store, day, machine: 'A', rack, games: 3000, bb: 10, rb: 5, net, estimated: true});
  const byDay = new Map();
  const put = r => byDay.set(`${r.store}|${r.day}`, [...(byDay.get(`${r.store}|${r.day}`) ?? []), r]);
  const day = n => new Date(Date.UTC(2026, 10, 3) - n * 86400000).toISOString().slice(0, 10);
  for (let back = 1; back <= 31; back++) for (let i = 0; i < 20; i++) put(rack('s', day(back), i + 1, back <= 30 ? -100 : 100));
  for (let i = 0; i < 20; i++) { put(rack('s', day(0), i + 1, i < 10 ? 100 : -100)); put(rack('t', day(5), i + 1, 100)); }
  const text = storeDayComment(byDay, 's', day(0));
  assert.match(text, /この30日で記録のある30日の中では、プラスの台の割合が高い方でした。/);
});
