"""共通の試験データ database_android/test/fixtures/store_pattern_cases.json を作る（PCの計算が正解）。
閲覧ページ（Dart）とPC（Python）の「店の入れ方のふり返り」が同じ数字かを確かめる。作り直し：
    database/.venv/Scripts/python.exe tests/make_store_pattern_cases.py
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core  # noqa: E402
import store_pattern  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / 'database_android/test/fixtures/store_pattern_cases.json'
MACHINES = ['ﾏｲｼﾞｬｸﾞﾗｰV', 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', 'L 防振り FN', 'SﾂｲﾝｴﾝｼﾞｪﾙPARTY ZF', 'ﾊﾅﾊﾅﾎｳｵｳ-30', 'L戦国ｺﾚｸｼｮﾝ6KS']


def rows_for(store, day, n, start, salt):
    out, state = [], salt
    for i in range(n):
        state = state * 48271 % 2147483647
        rack = start + i + (3 if i > n // 2 else 0)            # 途中で台番が飛ぶ
        machine = MACHINES[0] if i < 8 else MACHINES[(state >> 3) % len(MACHINES)]
        games = 400 if i % 17 == 5 else 1500 + state % 4000
        plus = i < 8 or (rack % 10 == 7) or state % 3 == 0     # 1機種の全台系・末尾7・ランダム
        net = (500 + state % 2000) if plus else -(300 + state % 1500)
        row = dict(store=store, day=day, machine=machine, rack=rack, games=games, bb=5, rb=4)
        unknown = i % 13 == 6
        if store.startswith('pscube:'):
            row.update(source='pscube', my=1000, rate='20', machine_type='normal')
            if not unknown:
                row['net_medals'] = net
        elif not unknown:
            row['jo_net'] = net
        out.append(row)
    return out


def won(row):
    return store_pattern.pscube_won(row) if row['store'].startswith('pscube:') else core.rack_won(row)


def main():
    cases = []
    for store, day, n, start, salt in [('nagamachiminami', '2026-11-16', 120, 1101, 7),
                                       ('saiwaichou', '2026-11-15', 90, 700, 11),
                                       ('pscube:c740601:20', '2026-11-14', 100, 1001, 23),
                                       ('nagamachiminami', '2026-11-13', 12, 101, 5)]:
        rows = rows_for(store, day, n, start, salt)
        r = store_pattern.store_pattern_day(store, day, rows, won)
        cases.append(dict(store=store, day=day, rows=rows, expected=dict(
            plus=r['plus'], total=r['total'], played=r['played'], excluded=r['excluded'], usable=r['usable'],
            machines=[[g['label'], g['plus'], g['total'], g['compared'], g['p'], g['chance']] for g in r['machines']],
            suffixes=[[g['label'], g['plus'], g['total'], g['compared'], g['p'], g['chance']] for g in r['suffixes']],
            run=None if r['run'] is None else [r['run']['racks'], r['run']['p'], r['run']['chance']],
            highlights=r['highlights'])))
    # 分かる台が7割に届かない日（アナスロ補完の日のような）は判定しない。
    rows = rows_for('pscube:c740601:20', '2026-09-20', 40, 1001, 31)
    for i, row in enumerate(rows):
        if i % 2:
            row.pop('net_medals', None)
    r = store_pattern.store_pattern_day('pscube:c740601:20', '2026-09-20', rows, won)
    cases.append(dict(store='pscube:c740601:20', day='2026-09-20', rows=rows, expected=dict(
        plus=r['plus'], total=r['total'], played=r['played'], excluded=r['excluded'], usable=r['usable'],
        machines=[[g['label'], g['plus'], g['total'], g['compared'], g['p'], g['chance']] for g in r['machines']],
        suffixes=[[g['label'], g['plus'], g['total'], g['compared'], g['p'], g['chance']] for g in r['suffixes']],
        run=None if r['run'] is None else [r['run']['racks'], r['run']['p'], r['run']['chance']],
        highlights=r['highlights'])))
    OUT.write_text(json.dumps(dict(note='PC database/store_pattern.py で作った正解。閲覧ページの store_pattern.dart も同じ値になること。',
                                   cases=cases), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    for c in cases:
        e = c['expected']
        print(c['store'], c['day'], e['total'], e['played'], e['usable'], e['run'] and e['run'][1], e['highlights'])


if __name__ == '__main__':
    main()
