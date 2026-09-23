"""Import the manually verified sidebar-browser sample into database.

This is a reproducible bridge for the initial sample, not a second collector.
It only accepts the store and 1000-yen 46-coin category fixed in this project.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from core import Store, report

ROOT = Path(__file__).parent
TABLES = ROOT / 'observed_tables.json'
GRAPHS = ROOT / 'observed_graphs.json'
STORE = ROOT / 'data' / 'database.sqlite3'
REPORTS = ROOT / 'reports'


def svg_path(xy: str, offset: float) -> str:
    values = [float(v) + offset for v in xy.split(',')]
    if len(values) < 4 or len(values) % 2:
        raise ValueError('グラフ座標が不完全です。')
    return ' '.join(('M' if i == 0 else 'L') + f'{values[i]:g},{values[i + 1]:g}'
                    for i in range(0, len(values), 2))


def build_rows(tables, graphs):
    if tables['machine'] != 'L戦国乙女5L8' or graphs['day'] not in tables['tables']:
        raise ValueError('この初期サンプルの機種または日付が一致しません。')
    target_day = graphs['day']
    target = {int(row[0]): row for row in tables['tables'][target_day]}
    graph_by_rack = {int(g['rack']): g for g in graphs['records']}
    if set(target) != set(graph_by_rack):
        raise ValueError('評価日の表とグラフの台番号が一致しません。')

    rows = []
    for day, records in tables['tables'].items():
        for rack, bb, rb, games, previous_start, max_hold in records:
            row = dict(
                store='nagamachiminami', kind_code=21, day=day,
                machine=tables['machine'], rack=int(rack), bb=int(bb), rb=int(rb),
                games=int(games), previous_start=int(previous_start), max_hold=int(max_hold),
                source_url=f"{tables['source']}&target_date={day}",
                captured_at=datetime.now().astimezone().isoformat(),
            )
            if day == target_day:
                graph = graph_by_rack[int(rack)]
                for key in ('bb', 'rb', 'games', 'max_hold'):
                    if row[key] != int(graph[key]):
                        raise ValueError(f'{rack}番台の{key}が表とグラフで一致しません。')
                row['graph'] = dict(
                    path=svg_path(graph['xy'], float(graphs['coordinate_offset'])),
                    baseline=float(graph['baseline']),
                    source_url=graphs['source_template'].format(rack=rack),
                )
            rows.append(row)
    return target_day, tables['machine'], rows


def main():
    tables = json.loads(TABLES.read_text(encoding='utf-8'))
    graphs = json.loads(GRAPHS.read_text(encoding='utf-8'))
    day, machine, rows = build_rows(tables, graphs)
    db = Store(STORE)
    try:
        db.save(rows)
        output, results = report(db, day, machine, REPORTS)
    finally:
        db.close()
    complete = sum(r['score']['total'] is not None for r in results)
    print(f'rows={len(rows)} target={len(results)} complete={complete}')
    print(output)


if __name__ == '__main__':
    main()
