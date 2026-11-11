"""固定した事前予測だけを評価する日次学習。原本DB・既存研究には書き込まない。"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import sqlite3
import statistics

JST = timezone(timedelta(hours=9))
VERSION = 'daily-plus-ridge-20261111-v1'
MATURITY = 8
PERIOD = 112
FEATURES = ('constant', 'last_plus', 'last_missing', 'plus7', 'coverage7',
            'plus28', 'coverage28', 'games', 'weekday_sin', 'weekday_cos')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


def shift(day, n):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def period_days(epoch):
    # 反復の有意水準が小さくなるのに対し、週の数も事前規則で増やす。
    return PERIOD + 14 * math.ceil(math.log2(epoch))


def jst(now):
    if now.tzinfo is None:
        raise ValueError('時刻にはタイムゾーンが必要です')
    return now.astimezone(JST)


def identity(row):
    return (str(row['store']), str(row.get('rate', '')), str(row['machine']), int(row['rack']))


def valid(row):
    g = row.get('games')
    if isinstance(g, bool) or not isinstance(g, (int, float)) or not 0 < g <= 20000:
        return False
    for key, maximum in (('bb', 500), ('rb', 500), ('my', 100000), ('max_hold', 100000)):
        v = row.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= maximum):
            return False
    return row.get('source_site') != 'anaslo' or not str(row['store']).startswith('pscube:')


def outcome(row):
    """記録上の符号。取得差枚・グラフの由来を保持し、欠測を0にしない。"""
    if not row or not valid(row):
        return None
    net = row.get('jo_net')
    if isinstance(net, (int, float)) and not isinstance(net, bool) and math.isfinite(net):
        return int(net > 0)
    m, g = row.get('graph_measurement'), row.get('graph')
    try:
        if m:
            end = float(m['baseline_y']) - float(m['end_y'])
        elif g and 'points' in g:
            end = float(g['zero_y']) - float(g['points'][-1][1])
        elif g and 'path' in g:
            from core import graph_metrics
            metrics = graph_metrics(g['path'], g['baseline'])
            end = metrics['baseline'] - metrics['points'][-1][1]
        else:
            return None
        if not math.isfinite(end) or abs(end) <= 1:
            return None
        return int(end > 1)
    except (KeyError, ValueError, TypeError, IndexError):
        return None


class History:
    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r: (r['day'], identity(r)))
        self.by_id = defaultdict(list)
        self.by_day = {}
        self.racks = defaultdict(list)
        for r in self.rows:
            key = identity(r)
            if (r['day'], key) in self.by_day:
                raise ValueError('同じ日・台・機種の重複入力があります')
            self.by_id[key].append(r)
            self.by_day[(r['day'], key)] = r
            self.racks[(key[0], key[1], key[3])].append(r)

    def features(self, row):
        day, key = row['day'], identity(row)
        changes = [r['day'] for r in self.racks[(key[0], key[1], key[3])]
                   if r['day'] <= day and r['machine'] != row['machine']]
        start = max(changes, default='0001-01-01')
        past = [r for r in self.by_id[key] if start < r['day'] <= day and r['day'] >= shift(day, -27)]
        y = outcome(row)
        x = [1., (y - .5) if y is not None else 0., float(y is None)]
        for n in (7, 28):
            ys = [outcome(r) for r in past if r['day'] >= shift(day, 1 - n)]
            observed = [v for v in ys if v is not None]
            x.extend([(sum(observed) - .5 * len(observed)) / (len(observed) + 10), len(observed) / n])
        weekday = date.fromisoformat(shift(day, 1)).weekday()
        x.extend([min(max(row.get('games') or 0, 0), 20000) / 20000,
                  math.sin(2 * math.pi * weekday / 7), math.cos(2 * math.pi * weekday / 7)])
        return x


def solve(matrix, vector):
    """小さい正定値連立方程式。外部数値ライブラリ不要。"""
    a = [list(row) + [v] for row, v in zip(matrix, vector)]
    n = len(a)
    for i in range(n):
        pivot = max(range(i, n), key=lambda k: abs(a[k][i]))
        a[i], a[pivot] = a[pivot], a[i]
        if abs(a[i][i]) < 1e-12:
            raise ValueError('学習行列を解けません')
        scale = a[i][i]
        a[i] = [v / scale for v in a[i]]
        for k in range(n):
            if k != i:
                scale = a[k][i]
                a[k] = [v - scale * w for v, w in zip(a[k], a[i])]
    result = [r[-1] for r in a]
    if not all(math.isfinite(v) for v in result):
        raise ValueError('係数が有限値ではありません')
    return result


def train(history, target):
    """候補内外の全有効台を学習。対象日の8日前までの翌日正解だけ使う。"""
    grouped = defaultdict(list)
    last, first = shift(target, -MATURITY), shift(target, -180)
    for row in history.rows:
        next_day = shift(row['day'], 1)
        if not first <= next_day <= last or not valid(row):
            continue
        y = outcome(history.by_day.get((next_day, identity(row))))
        if y is not None:
            grouped[identity(row)[:3]].append((history.features(row), y, next_day))
    models = {}
    for key, examples in grouped.items():
        days = len({e[2] for e in examples})
        if len(examples) < 100 or days < 20:
            continue
        n = len(FEATURES)
        matrix = [[100. * (i == k) if i else 0. for k in range(n)] for i in range(n)]
        vector = [0.] * n
        # 1日を等重みにする。多数台の日の比重だけが増えるのを防ぐ。
        counts = defaultdict(int)
        for _, _, d in examples:
            counts[d] += 1
        for x, y, d in examples:
            w = len(examples) / (days * counts[d])
            for i in range(n):
                vector[i] += w * x[i] * (y - .5)
                for k in range(n):
                    matrix[i][k] += w * x[i] * x[k]
        models[key] = dict(weights=solve(matrix, vector), n=len(examples), days=days,
                           first=first, last=last, features=FEATURES, version=VERSION)
    return models


def rank_pool(pool, history, models):
    scores = []
    for row in pool:
        model = models.get(identity(row)[:3])
        if model is None:
            return None
        x = history.features(row)
        score = sum(a * b for a, b in zip(x, model['weights']))
        scores.append((score, row))
    return [r for _, r in sorted(scores, key=lambda v: (-round(v[0], 12), identity(v[1])))]


def comparison(days, alpha):
    """固定期間に1回。週の符号の二項検定と日等重みの効果量を両方使う。"""
    paired = [d for d in days if d['current'] is not None and d['learned'] is not None]
    if not paired:
        return dict(adopt=False, reason='判定可能な日がありません', n=0)
    deltas = [d['learned'] - d['current'] for d in paired]
    weeks = defaultdict(list)
    first = min(d['day'] for d in days)
    for d, diff in zip(paired, deltas):
        weeks[(date.fromisoformat(d['day']) - date.fromisoformat(first)).days // 7].append(diff)
    # 日等重みの効果量と、週単位の符号の一貫性を分ける。台を独立試行にしない。
    blocks = [sum(v) / len(paired) for v in weeks.values()]
    actual = sum(blocks)
    signs = [v > 0 for v in blocks if abs(v) > 1e-12]
    positives, n = sum(signs), len(signs)
    p = sum(math.comb(n, k) for k in range(positives, n + 1)) / 2 ** n if n else 1.
    missing = statistics.mean(d['missing_learned'] - d['missing_current'] for d in days)
    counts = [sum(d[k] for d in days) for k in ('n_current', 'n_learned')]
    enough = len(paired) >= 80 and len(blocks) >= 14 and min(counts) >= 80
    adopt = enough and actual >= .02 and missing <= .02 and p <= alpha
    return dict(adopt=adopt, reason='改善を確認' if adopt else '改善未確認', n=len(paired),
                weeks=len(blocks), difference=actual, median=statistics.median(deltas),
                missing_difference=missing, p=p, alpha=alpha, counts=counts)


class Journal:
    """追記専用の証拠と、復旧可能な最新表示を分離する。"""
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        for table in ('predictions', 'outcomes', 'decisions', 'inputs'):
            self.db.execute(f'CREATE TABLE IF NOT EXISTS {table}(key TEXT PRIMARY KEY, body TEXT NOT NULL, sha TEXT NOT NULL)')
            for action in ('UPDATE', 'DELETE'):
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, '追記専用記録です'); END")
        self.db.execute('CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, body TEXT NOT NULL)')
        self.db.commit()

    def close(self):
        self.db.close()

    def get(self, table, key):
        if table not in ('predictions', 'outcomes', 'decisions', 'inputs', 'state'):
            raise ValueError('保存先が不正です')
        cols = 'body' if table == 'state' else 'body,sha'
        found = self.db.execute(f'SELECT {cols} FROM {table} WHERE key=?', (key,)).fetchone()
        if found is None:
            return None
        body = json.loads(found[0])
        if table != 'state' and digest(body) != found[1]:
            raise ValueError('固定記録の指紋が一致しません')
        return body

    def append(self, table, key, body):
        if table not in ('predictions', 'outcomes', 'decisions', 'inputs'):
            raise ValueError('保存先が不正です')
        self.db.execute(f'INSERT INTO {table} VALUES (?,?,?)', (key, encoded(body), digest(body)))

    def state(self, key, body):
        self.db.execute('INSERT INTO state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body', (key, encoded(body)))

    def freeze(self, target, prediction, rows, now, store=None):
        now = jst(now)
        if target != now.date().isoformat() or now.hour >= 8:
            raise ValueError('締切を過ぎたため事前予測を保存しません')
        key = target + ('|' + store if store else '')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.get('predictions', key) is not None:
                return False
            stamp = digest(rows)
            if self.get('inputs', stamp) is None:
                self.append('inputs', stamp, rows)
            prediction = {**prediction, 'target': target, 'saved_at': now.isoformat(),
                          'input_sha256': stamp, 'version': VERSION}
            self.append('predictions', key, prediction)
        return True
