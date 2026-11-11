"""保存済みの原本を読み、別DBへ日次予測を追記し、表示用JSONを同期する。"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, date, timedelta
import json
import os
from pathlib import Path
import shutil
import sqlite3
import statistics
import subprocess

import core
from daily_learning import (JST, VERSION, MATURITY, PERIOD, History, Journal, comparison,
                            digest, encoded, identity, jst, outcome, period_days, rank_pool, shift, train)
from file_io import atomic_writer

FILE_NAME = 'daily-learning.json'
STORES = ('nagamachiminami', 'saiwaichou', 'pscube:c740601:20')


def compact(value):
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if k not in
                ('preview_image', 'image_base64', 'screenshot', 'raw_html')}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def read_database(path, table):
    """Store初期化やinput_versionsの記録を行わない読み取り専用接続。"""
    if table not in ('days', 'records', 'machines'):
        raise ValueError('入力表が不正です')
    if not Path(path).is_file():
        raise FileNotFoundError(f'{Path(path).name} がありません')
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        return [compact(json.loads(row[0])) for row in db.execute(f'SELECT payload FROM {table}')]
    finally:
        db.close()


class MemoryStore:
    _machine_rows = core.Store._machine_rows

    def __init__(self, rows):
        self.all = rows

    def rows(self, day=None, machine=None, store=None):
        return [r for r in self.all if (not day or r['day'] == day) and
                (not machine or r['machine'] == machine) and (not store or r['store'] == store)]


def load_inputs(data_dir, target):
    first, last = shift(target, -210), shift(target, -1)
    meruhen = [r for r in read_database(data_dir / 'database.sqlite3', 'days')
               if first <= r['day'] <= last and r['store'] in STORES and
               not core.is_hidden_machine(r['store'], r['machine'])]
    raw = [r for r in read_database(data_dir / 'pscube.sqlite3', 'records')
           if first <= r['day'] <= last and str(r['store']) == 'c740601' and str(r['rate']) == '20']
    machines = [m for m in read_database(data_dir / 'pscube.sqlite3', 'machines')
                if str(m['store']) == 'c740601' and str(m['rate']) == '20']
    normalized = [{**r, 'store': f"pscube:{r['store']}:{r['rate']}"} for r in raw]
    rows = sorted(meruhen + normalized, key=lambda r: (r['day'], identity(r)))
    return rows, {'records': raw, 'machines': machines}


def baseline_groups(rows, pscube, day, node=None):
    groups, store = [], MemoryStore([r for r in rows if not r['store'].startswith('pscube:')])
    for location in STORES[:2]:
        daily = store.rows(day=day, store=location)
        variety = core.variety_machines(daily)
        for machine in sorted({r['machine'] for r in daily} - variety):
            pool = [r for r in daily if r['machine'] == machine and core.next_day_evidence(store, r)['index'] is not None]
            result = core.provisional_next_day_candidates(store, day, machine, location)
            if result['count']:
                groups.append(dict(store=location, rate='', name=machine, pool=pool,
                                   current=[identity(c['row']) for c in result['candidates']]))
        if variety:
            pool = [r for r in daily if r['machine'] in variety and not core.implausible_numbers(r)
                    and core.variety_state(r) in core.variety_order(location)]
            result = core.variety_next_day_candidates(store, day, location)
            if result['count']:
                groups.append(dict(store=location, rate='', name='バラエティ', pool=pool,
                                   current=[identity(c['row']) for c in result['candidates']]))
    if pscube['records']:
        binary = node or shutil.which('node')
        if not binary:
            raise RuntimeError('P-STATIONの従来候補を計算するNode.jsがありません')
        proc = subprocess.run([binary, str(Path(__file__).with_name('daily_learning_pscube.mjs'))],
                              input=encoded({'data': pscube, 'day': day}), text=True, encoding='utf-8',
                              capture_output=True, timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if proc.returncode:
            raise RuntimeError('P-STATIONの従来候補計算に失敗しました')
        for group in json.loads(proc.stdout):
            pool = [r for r in rows if r['day'] == day and r['store'] == group['store']
                    and r['machine'] == group['name'] and r['rack'] in group['pool']]
            by_rack = {r['rack']: r for r in pool}
            groups.append({**group, 'pool': pool, 'current': [identity(by_rack[r]) for r in group['current']]})
    return groups


def group_key(group):
    return encoded([group['store'], group.get('rate', ''), group['name']])


def ready(rows, target, stores=STORES):
    """部分取り込みを初回固定しない。判定は保存行数だけで、成績を見ない。"""
    day, reasons = shift(target, -1), []
    for store in stores:
        counts = defaultdict(int)
        current = []
        for r in rows:
            if r['store'] == store and shift(day, -7) <= r['day'] <= day:
                counts[r['day']] += 1
                if r['day'] == day:
                    current.append(r)
        previous = [n for d, n in counts.items() if d < day]
        if not current or (previous and len(current) < .9 * statistics.median(previous)):
            reasons.append(f'{store}の前日データが不足しています')
        if store.startswith('pscube:'):
            from pscube_import import site777_final
            if any(r.get('source_site') == 'site777' and not site777_final(r) for r in current):
                reasons.append('P-STATIONの確定前データが残っています')
    return reasons


def build_prediction(rows, pscube, target, journal, node=None):
    history, groups = History(rows), baseline_groups(rows, pscube, shift(target, -1), node)
    models = train(history, target)
    projected = []
    for group in groups:
        key = group_key(group)
        state = journal.get('state', 'method:' + key) or {'active': 'current', 'since': target}
        ordered = rank_pool(group['pool'], history, models)
        current = [list(k) for k in group['current']]
        learned = [list(identity(r)) for r in ordered[:len(current)]] if ordered is not None else current
        active = state['active'] if ordered is not None else 'current'
        projected.append(dict(key=key, store=group['store'], name=group['name'], current=current,
                              learned=learned, selected=learned if active == 'learned' else current,
                              active=active, trained=ordered is not None,
                              status=('改善を確認して採用中' if active == 'learned' else
                                      '学習済み・将来成績を比較中' if ordered is not None else '学習データ不足・従来方式'),
                              pool=[{'id': list(identity(r)), 'features': history.features(r)} for r in group['pool']]))
    sources = [Path(__file__), Path(__file__).with_name('daily_learning.py'), Path(core.__file__),
               Path(__file__).with_name('normal_next_day_model.py'),
               Path(__file__).with_name('daily_learning_pscube.mjs'),
               Path(__file__).parents[1] / 'database_android/web/pscube/scoring.mjs']
    return dict(input_day=shift(target, -1), groups=projected,
                models={encoded(k): v for k, v in models.items()},
                source_sha256={p.name: __import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in sources})


def record_outcomes(journal, rows, today):
    history = History(rows)
    keys = [k for (k,) in journal.db.execute('SELECT key FROM predictions ORDER BY key')]
    for key in keys:
        prediction, results = journal.get('predictions', key), []
        target = prediction['target']
        if target > shift(today, -MATURITY) or journal.get('outcomes', key) is not None:
            continue
        for group in prediction['groups']:
            stats = dict(key=group['key'], day=target, trained=group['trained'])
            # 母集団全体の正解も残す。候補だけを学習・評価資料にしない。
            labels = {encoded(p['id']): outcome(history.by_day.get((target, tuple(p['id'])))) for p in group['pool']}
            for method in ('current', 'learned'):
                observed = [labels[encoded(k)] for k in group[method] if labels[encoded(k)] is not None]
                stats[method] = statistics.mean(observed) if observed else None
                stats['n_' + method] = len(observed)
                stats['missing_' + method] = 1 - len(observed) / len(group[method])
            stats['labels'] = labels
            results.append(stats)
        with journal.db:
            journal.append('outcomes', key, dict(target=target, recorded_at=today, groups=results))


def decisions(journal, today):
    """期間終了後に1度だけ検定。処理の再実行で判定回数を増やさない。"""
    start = journal.get('state', 'start')
    if not start:
        return
    offset, epoch = 0, 0
    while True:
        epoch += 1
        length = period_days(epoch)
        first, last = shift(start, offset), shift(start, offset + length - 1)
        if last > shift(today, -MATURITY):
            break
        offset += length
        key = f'adoption:{epoch}'
        if journal.get('decisions', key) is not None:
            continue
        groups = defaultdict(list)
        for (target,) in journal.db.execute('SELECT key FROM outcomes WHERE key>=? AND key<=?', (first, last + '~')):
            for g in journal.get('outcomes', target)['groups']:
                if g['trained']:
                    groups[g['key']].append(g)
        alpha = .05 / (epoch * (epoch + 1) * max(len(groups), 1))
        results = {}
        with journal.db:
            for group, days in groups.items():
                state = journal.get('state', 'method:' + group) or {'active': 'current', 'since': start}
                result = comparison(days, alpha)
                # 切り戻した期間の成績を再採用に使わない。
                if state['active'] == 'current' and first >= state['since'] and result['adopt']:
                    state = {'active': 'learned', 'since': today}
                    journal.state('method:' + group, state)
                results[group] = result
            journal.append('decisions', key, dict(first=first, last=last, at=today, results=results))
    for key, body in journal.db.execute("SELECT key,body FROM state WHERE key LIKE 'method:%'").fetchall():
        state, group = json.loads(body), key[len('method:'):]
        if state['active'] != 'learned':
            continue
        blocks = (date.fromisoformat(shift(today, -MATURITY)) - date.fromisoformat(state['since'])).days // 28
        for block in range(1, blocks + 1):
            decision_key = f'rollback:{group}:{state["since"]}:{block}'
            if journal.get('decisions', decision_key) is not None:
                continue
            first, last = shift(state['since'], 28 * (block - 1)), shift(state['since'], 28 * block - 1)
            values = []
            for (target,) in journal.db.execute('SELECT key FROM outcomes WHERE key>=? AND key<=?', (first, last + '~')):
                values.extend(g for g in journal.get('outcomes', target)['groups'] if g['key'] == group)
            paired = [g for g in values if g['current'] is not None and g['learned'] is not None]
            rollback = len(paired) >= 14 and (statistics.mean(g['learned'] - g['current'] for g in paired) <= -.05
                       or statistics.mean(g['missing_learned'] - g['missing_current'] for g in values) > .05)
            with journal.db:
                journal.append('decisions', decision_key, dict(at=today, first=first, last=last, rollback=rollback))
                if rollback:
                    journal.state(key, {'active': 'current', 'since': today})
            if rollback:
                break


def export(journal, data_dir, status, now, sync_dir=None):
    targets = [k for (k,) in journal.db.execute('SELECT key FROM predictions ORDER BY key DESC LIMIT 93')]
    by_day = {}
    for target in targets:
        p = journal.get('predictions', target)
        day = by_day.setdefault(p['target'], {k: p[k] for k in ('target', 'input_day', 'saved_at', 'version')} | {'groups': []})
        day['groups'].extend([{k: g[k] for k in ('store', 'name', 'active', 'status', 'selected', 'current', 'learned')} |
                              {'saved_at': p['saved_at']} for g in p['groups']])
    days = [by_day[d] for d in sorted(by_day, reverse=True)[:31]]
    document = dict(format='daily-learning', version=1, updated_at=jst(now).isoformat(),
                    status=status, days=days, next_cutoff='08:00 JST', improvement='将来成績で確認するまで改善未確認')
    with atomic_writer(data_dir / FILE_NAME) as f:
        f.write(encoded(document))
    if sync_dir is not None:
        if not Path(sync_dir).is_dir():
            raise OSError('日次学習の同期先が見つかりません')
        with atomic_writer(Path(sync_dir) / FILE_NAME) as f:
            f.write(encoded(document))
    return document


def _run(data_dir, *, clock=lambda: datetime.now(JST), node=None, sync=True):
    data_dir = Path(data_dir)
    now, journal = jst(clock()), Journal(data_dir / 'daily-learning' / 'journal.sqlite3')
    today = now.date().isoformat()
    try:
        rows, pscube = load_inputs(data_dir, today)
        record_outcomes(journal, rows, today)
        decisions(journal, today)
        statuses = []
        for store in STORES:
            status = '本日の事前予測は保存済みです'
            if journal.get('predictions', today + '|' + store) is not None:
                statuses.append(store + '：' + status)
                continue
            why = ready(rows, today, (store,))
            if now.hour >= 8:
                status = '本日は締切超過・事前予測なし。従来方式を表示してください'
            elif why:
                status = '取り込み待ち：' + '／'.join(why)
            else:
                store_rows = [r for r in rows if r['store'] == store]
                prediction = build_prediction(store_rows, pscube if store.startswith('pscube:') else
                                              {'records': [], 'machines': []}, today, journal, node)
                if not prediction['groups']:
                    statuses.append(store + '：候補を選べるデータが不足しています')
                    continue
                journal.freeze(today, prediction, store_rows, clock(), store=store)
                with journal.db:
                    if journal.get('state', 'start') is None:
                        journal.state('start', today)
                status = '本日の事前予測を固定保存しました'
            statuses.append(store + '：' + status)
        status = '／'.join(statuses)
        folder = core.resolve_sync_dir(data_dir) if sync else None
        if sync and folder is None:
            status += '／同期先未設定または利用不可'
        return export(journal, data_dir, status, clock(), folder)
    except Exception as error:
        try:
            export(journal, data_dir, f'処理失敗：{type(error).__name__}。従来方式を使用してください', clock())
        except Exception:
            pass
        raise
    finally:
        journal.close()


def run(data_dir, **kwargs):
    from backup_status import output_lock
    # 既存のOSファイルロックはプロセス終了時にも解除される。
    with output_lock(Path(data_dir) / 'daily-learning', 'meruhen'):
        return _run(data_dir, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).with_name('data'))
    parser.add_argument('--no-sync', action='store_true')
    parser.add_argument('--node')
    args = parser.parse_args()
    try:
        result = run(args.data_dir, sync=not args.no_sync, node=args.node)
        print(result['status'])
    except Exception as error:
        print(f'日次学習に失敗しました：{type(error).__name__}: {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
