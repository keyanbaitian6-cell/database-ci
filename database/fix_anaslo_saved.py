"""保存済みの幸町のアナスロ補完を、今の変換の規則に合わせて直す（2026-10-17）。

1. 機種名：変換画面で選んだ対応が誤っていた分（例：ソードアート・オンライン初代を「Ⅱ」の名前で
   保存）を、対応表 ``html_converter/data/machine_names_saiwaichou.json`` の今の内容と、メルヘンが
   その台に付けた★などの表記（``MeruhenCatalog.rack_spelling``）で付け直す。古い名前の行には削除の印を
   残す（古いバックアップやアナスロのJSONを読み直しても戻らない）。同じ日・台に新しい名前の行が既に
   あれば、そちらを残して古い名前の行だけ消す。
2. グラフ：グラフの測定値が無い補完に、アナスロのグラフ（source_graph）から作った測定値を足す
   （``graph_measurement_from_source``。最大持玉が無いので推定差枚は出ない。採点の終点・維持と
   バラエティの終わり方に使われる）。

対象はアナスロ補完（source_site=anaslo）の行だけ。メルヘン・ジャグラーオンラインで取った行は変えない。

    python fix_anaslo_saved.py            # 直す内容を表示するだけ
    python fix_anaslo_saved.py --apply    # 直す。先に DB 全体を data/database.pre-anaslo-fix-<日時>.sqlite3 へ複製

PC版databaseと変換アプリを閉じてから --apply で実行する。
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

from anaslo_converter import MERUHEN_STORE, MeruhenCatalog, graph_measurement_from_source
from core import Store, is_excluded_machine, normalize_machine_name

ROOT = Path(__file__).resolve().parent
ALIASES = ROOT.parent / 'html_converter' / 'data' / 'machine_names_saiwaichou.json'


def _saved_rows(store, location):
    rows = []
    for day, machine, rack, raw in store.db.execute(
            'SELECT day, machine, rack, payload FROM days WHERE store=?', (location,)).fetchall():
        try:
            rows.append((day, machine, int(rack), json.loads(raw)))
        except ValueError:
            continue
    return rows


def plan_name_fixes(store, aliases, location=MERUHEN_STORE):
    """[(old_key, new_machine, payload)] and a Counter of skipped reasons."""
    rows = _saved_rows(store, location)
    catalog = MeruhenCatalog(location, [(d, m, r, p.get('source_site')) for d, m, r, p in rows])
    fixes, skipped = [], Counter()
    for day, machine, rack, payload in rows:
        if payload.get('source_site') != 'anaslo':
            continue
        source = payload.get('source_machine')
        target = aliases.get(source) if isinstance(source, str) else None
        if not isinstance(target, str) or not target.strip():
            skipped['no_mapping'] += 1
            continue
        target = catalog.rack_spelling(rack, normalize_machine_name(target))
        if is_excluded_machine(location, target):
            skipped['excluded_target'] += 1
            continue
        if target != machine:
            fixes.append(((location, day, machine, rack), target, payload))
    return fixes, skipped


def apply_name_fixes(store, fixes):
    """One transaction. Returns Counter(renamed=…, kept_existing=…)."""
    done = Counter()
    with store.db:
        store._begin_write()
        for key, target, payload in fixes:
            raw = store.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND machine=? AND rack=?',
                                   key).fetchone()
            if raw is None:
                continue
            store._record_deletion(store._deletion_source((*key, raw[0])))
            store.db.execute('DELETE FROM days WHERE store=? AND day=? AND machine=? AND rack=?', key)
            new_key = (key[0], key[1], target, key[3])
            if store.db.execute('SELECT 1 FROM days WHERE store=? AND day=? AND machine=? AND rack=?',
                                new_key).fetchone():
                done['kept_existing'] += 1
                continue
            store.db.execute('INSERT INTO days VALUES(?,?,?,?,?)',
                             (*new_key, json.dumps(dict(payload, machine=target), ensure_ascii=False)))
            done['renamed'] += 1
    store._machine_cache = {}
    return done


def plan_graph_fills(store, location=MERUHEN_STORE):
    """[(key, measurement)] for supplements that have the anaslo graph but no measurement."""
    fills = []
    for day, machine, rack, payload in _saved_rows(store, location):
        if payload.get('source_site') != 'anaslo' or payload.get('graph_measurement') or payload.get('graph'):
            continue
        measurement = graph_measurement_from_source(payload.get('source_graph'))
        if measurement:
            fills.append(((location, day, machine, rack), measurement))
    return fills


def apply_graph_fills(store, fills):
    done = 0
    with store.db:
        store._begin_write()
        for key, measurement in fills:
            raw = store.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND machine=? AND rack=?',
                                   key).fetchone()
            if raw is None:
                continue
            payload = json.loads(raw[0])
            if payload.get('source_site') != 'anaslo' or payload.get('graph_measurement') or payload.get('graph'):
                continue
            store.db.execute('UPDATE days SET payload=? WHERE store=? AND day=? AND machine=? AND rack=?',
                             (json.dumps(dict(payload, graph_measurement=measurement), ensure_ascii=False), *key))
            done += 1
    store._machine_cache = {}
    return done


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--db', type=Path, default=ROOT / 'data' / 'database.sqlite3')
    parser.add_argument('--aliases', type=Path, default=ALIASES)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    aliases = json.loads(args.aliases.read_text(encoding='utf-8'))
    store = Store(args.db)
    try:
        fixes, skipped = plan_name_fixes(store, aliases)
        summary = Counter((old[2], new) for old, new, _ in fixes)
        print(f'機種名を直す行：{len(fixes)}件')
        for (old, new), count in sorted(summary.items(), key=lambda item: -item[1]):
            racks = sorted({o[3] for o, n, _ in fixes if (o[2], n) == (old, new)})
            print(f'  {count:4d}件 {old} → {new}（台 {racks[0]}〜{racks[-1]}・{len(racks)}台）')
        if skipped:
            print('機種名を直さない行：', dict(skipped))
        if not args.apply:
            fills = plan_graph_fills(store)
            print(f'グラフを足す行：{len(fills)}件')
            print('（表示だけ。直すには --apply）' if fixes or fills else '直す行はありません。')
            return 0
        copy = args.db.with_name(f'{args.db.stem}.pre-anaslo-fix-{datetime.now():%Y%m%d-%H%M%S}{args.db.suffix}')
        target = sqlite3.connect(copy)
        try:
            store.db.backup(target)
        finally:
            target.close()
        print(f'DBを複製しました：{copy}')
        print('機種名：', dict(apply_name_fixes(store, fixes)))
        # Names first: the graph step then reads the rows under their new keys.
        print('グラフを足した行：', apply_graph_fills(store, plan_graph_fills(store)))
    finally:
        store.close()
    if args.db.resolve() == (ROOT / 'data' / 'database.sqlite3').resolve():
        # PC版が保存のあとに行う出力（レポート・バックアップ・閲覧用ファイル）と同じもの。
        from output_worker import refresh_outputs
        result = refresh_outputs(args.db, ROOT / 'data', ROOT / 'reports', history=True, backup=True)
        print('出力を更新しました。', *result['notices'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
