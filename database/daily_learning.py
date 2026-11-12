"""固定した事前予測だけを評価する日次学習。原本DB・既存研究には書き込まない。"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics
import zlib

from daily_learning_names import learning_key, learning_machine

JST = timezone(timedelta(hours=9))
# v2（2026-11-12、結果を見る前）：P’s CUBEの数値差枚 net_medals も符号に使う（仕様「取得差枚があればその符号」に合わせた）。
# 同じv2（2026-11-12 朝、v2で保存した予測が無いうちに追加）：P-STATIONで取り込み元の切り替えで名前だけ変わった16機種を、
# 学習では同じ機種として数える（daily_learning_names.py。利用者「vivy同じものとして数えて」）。
# v3（2026-11-12、v2・v3で保存した予測が無いうちに）：アナスロの分析用JSON（幸町・P-STATIONのジャグラー・ハナハナ）を
# 過去の学習・特徴に足す（daily_learning_archive.py。利用者が検討の「1」を選択）。従来候補・前日データには使わない。
# v4（2026-11-12 夜、最初の結果の記録（11/20）より前。利用者「すぐ本番」）：機種ごとの係数が無い組にも学習版の順位を付ける。
# 4台以上の機種の組は「店舗共通の係数」（導入からの日数の印つき）、バラエティは「バラエティ専用の係数」（台ごとに独立。
# プラスでない日が続いた数つき。利用者の見立て「ローテーションのように設定が入る」）。機種ごとの係数・特徴はv3と同じ。
VERSION = 'daily-plus-ridge-20261112-v4'
# 採用・切り戻しの決まりの版（2026-11-12、結果を見る前に店舗単位・週の符号反転へ変更。DAILY_LEARNING.md）。
RULE_VERSION = 'store-weekly-flip-20261112'
MATURITY = 8
PERIOD = 112
STORE_COUNT = 3        # 採用判定の比較群（店舗）の数。有意水準をこの数で分ける。
FEATURES = ('constant', 'last_plus', 'last_missing', 'plus7', 'coverage7',
            'plus28', 'coverage28', 'games', 'weekday_sin', 'weekday_cos')
# v4：係数の鍵（店舗・貸玉・この名前）。機種名とぶつからないよう # で始める。
STORE_MODEL, VARIETY_MODEL = '#店舗共通', '#バラエティ'
STORE_FEATURES = FEATURES + ('fresh7', 'fresh28')       # 今の機種が入ってから7日以内／8〜28日
VARIETY_FEATURES = FEATURES + ('dry_streak',)            # プラスでない日が続いた数（直近28日、判定できない日は飛ばす）/28
KIND_FEATURES = {'machine': FEATURES, 'store': STORE_FEATURES, 'variety': VARIETY_FEATURES}
VARIETY_STORES = ('nagamachiminami', 'saiwaichou')       # バラエティの組があるのはメルヘンの2店舗


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


class LateError(ValueError):
    """保存できる時間帯（前日23:30〜当日08:00）の外。処理の失敗ではなく締切超過として扱う。"""


def prediction_target(now):
    """今の時刻に固定保存できる事前予測の対象日。保存できない時間帯は None。

    対象日の前日23:30から、対象日の08:00より前まで（2026-11-11 利用者「23時半～8時でいいよ」。
    朝7:30〜8:00にPCがついていない日があるので、閉店後の取り込みが終わった時点で保存できるようにした）。
    08:00〜23:30は、その日の分は締切後、次の日の分はまだ早いので、どちらも保存しない。
    """
    now = jst(now)
    today = now.date().isoformat()
    if (now.hour, now.minute) >= (23, 30):
        return shift(today, 1)
    return today if now.hour < 8 else None


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
    # P-STATIONの原本DBのアナスロ行は使わない。分析用JSONの行（daily_learning_archive、符号の向きを監査済み）だけ使う。
    return (row.get('source_site') != 'anaslo' or not str(row['store']).startswith('pscube:')
            or row.get('archive') == 'normal-analysis')


def measured_net(row):
    """取得した差枚（推定ではない）。ジャグラーオンラインの jo_net、無ければP’s CUBEの net_medals。MY・推定差枚は使わない。"""
    for key in ('jo_net', 'net_medals'):
        net = row.get(key)
        if isinstance(net, (int, float)) and not isinstance(net, bool) and math.isfinite(net):
            return key, net
    return None, None


def outcome_source(row):
    """outcome の符号を何から決めたか（'jo_net'・'net_medals'・'graph'・None）。結果の記録に残す。"""
    if not row or not valid(row):
        return None
    key, _ = measured_net(row)
    if key:
        return key
    return 'graph' if outcome(row) is not None else None


def outcome(row):
    """記録上の符号。取得差枚・グラフの由来を保持し、欠測を0にしない。"""
    if not row or not valid(row):
        return None
    _, net = measured_net(row)
    if net is not None:
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
        # 学習では名前の変わり目をそろえた形（learning_key）で数える。保存の名前・候補の一覧は変えない。
        for r in self.rows:
            key = learning_key(identity(r))
            seen = self.by_day.get((r['day'], key))
            if seen is not None:
                if identity(seen) == identity(r):
                    raise ValueError('同じ日・台・機種の重複入力があります')
                # 古い名前と新しい名前で同じ日の台が2つあるときは、新しい名前のほうを使う。
                if r['machine'] != key[2]:
                    continue
                self.by_id[key].remove(seen)
                self.racks[(key[0], key[1], key[3])].remove(seen)
            self.by_id[key].append(r)
            self.by_day[(r['day'], key)] = r
            self.racks[(key[0], key[1], key[3])].append(r)
        # 特徴を作るための索引（2026-11-12 軽量化A）。以前は1台・1日ごとにその台の全履歴をなめ直していた。
        # 結果は以前の書き方（_features_by_scan、試験で照合）と同じ。
        self._ids = {key: ([r['day'] for r in items], items) for key, items in self.by_id.items()}
        self._racks = {}
        for rack, items in self.racks.items():
            names = [learning_machine(rack[0], r['machine']) for r in items]
            # previous[i]：i より前で、i と学習の名前が違う一番近い位置（無ければ -1）。
            previous = []
            for i, name in enumerate(names):
                previous.append(-1 if i == 0 else i - 1 if names[i - 1] != name else previous[i - 1])
            self._racks[rack] = ([r['day'] for r in items], names, previous)
        self._outcomes = {}

    def _outcome(self, row):
        found = self._outcomes.get(id(row))
        if found is None and id(row) not in self._outcomes:
            found = self._outcomes[id(row)] = outcome(row)
        return found

    def get(self, day, ident):
        """その日のその台の行。ident は保存の名前のままでよい（学習の名前にそろえて探す）。"""
        return self.by_day.get((day, learning_key(tuple(ident))))

    def _past(self, row):
        """（機種が替わった日、または None、その台のこの機種の日の一覧、直近28日の行（当日を含む））。"""
        day, key = row['day'], learning_key(identity(row))
        # 機種の入れ替え：その日までで、この台に別の機種（学習の名前）があった一番新しい日。
        days, names, previous = self._racks.get((key[0], key[1], key[3]), ((), (), ()))
        i = bisect_right(days, day) - 1
        if i >= 0 and names[i] == key[2]:
            i = previous[i]
        start = days[i] if i >= 0 else '0001-01-01'
        ids, items = self._ids.get(key, ((), ()))
        past = items[max(bisect_right(ids, start), bisect_left(ids, shift(day, -27))):bisect_right(ids, day)]
        return (start if i >= 0 else None), ids, past

    def features(self, row):
        _, _, past = self._past(row)
        return self._vector(row, row['day'], past, self._outcome)

    def model_features(self, row, kind='machine'):
        """係数の種類（KIND_FEATURES）に合わせた特徴。'machine' は features と同じ。"""
        return self.features(row) + self.extras(row, kind)

    def extras(self, row, kind):
        """'store'・'variety' の係数で、今の10個の特徴の後ろに足す分。"""
        if kind == 'machine':
            return []
        start, ids, past = self._past(row)
        if kind == 'variety':
            streak = 0
            for r in reversed(past):
                y = self._outcome(r)
                if y is None:
                    continue
                if y:
                    break
                streak += 1
            return [streak / 28]
        if kind == 'store':
            if start is None:
                return [0., 0.]       # データの初めより前からある台は、入った日が分からない
            installed = ids[bisect_right(ids, start)]
            n = (date.fromisoformat(row['day']) - date.fromisoformat(installed)).days + 1
            return [float(n <= 7), float(8 <= n <= 28)]
        raise ValueError(f'係数の種類が不正です：{kind}')

    def _features_by_scan(self, row):
        """以前の書き方（全履歴をなめる）。索引の結果が同じかを試験で照合するためだけに残す。"""
        day, key = row['day'], learning_key(identity(row))
        changes = [r['day'] for r in self.racks[(key[0], key[1], key[3])]
                   if r['day'] <= day and learning_machine(key[0], r['machine']) != key[2]]
        start = max(changes, default='0001-01-01')
        past = [r for r in self.by_id[key] if start < r['day'] <= day and r['day'] >= shift(day, -27)]
        return self._vector(row, day, past, outcome)

    @staticmethod
    def _vector(row, day, past, label):
        y = outcome(row)
        x = [1., (y - .5) if y is not None else 0., float(y is None)]
        for n in (7, 28):
            first = shift(day, 1 - n)
            ys = [label(r) for r in past if r['day'] >= first]
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


def _fit(examples):
    """固定罰則100のリッジ回帰。1日を等重みにする（多数台の日の比重だけが増えるのを防ぐ）。"""
    days = len({e[2] for e in examples})
    n = len(examples[0][0])
    matrix = [[100. * (i == k) if i else 0. for k in range(n)] for i in range(n)]
    vector = [0.] * n
    counts = defaultdict(int)
    for _, _, d in examples:
        counts[d] += 1
    for x, y, d in examples:
        w = len(examples) / (days * counts[d])
        for i in range(n):
            vector[i] += w * x[i] * (y - .5)
            for k in range(n):
                matrix[i][k] += w * x[i] * x[k]
    return solve(matrix, vector), days


def variety_rows(rows):
    """その日その店でバラエティ（1〜2台・1〜3台）の機種の行の id。原本DBの行だけで決める（分析用JSONの行は数えない）。"""
    from core import variety_machines
    daily = defaultdict(list)
    for r in rows:
        if r['store'] in VARIETY_STORES and not r.get('archive'):
            daily[(r['store'], r['day'])].append(r)
    found = set()
    for items in daily.values():
        names = variety_machines(items)
        found.update(id(r) for r in items if r['machine'] in names)
    return found


def train(history, target):
    """候補内外の全有効台を学習。対象日の8日前までの翌日正解だけ使う。

    v4：機種ごとの係数（v3と同じ）に加え、店舗ごとの共通の係数（STORE_MODEL）と、メルヘン2店舗の
    バラエティ専用の係数（VARIETY_MODEL）を同じ行から作る。どれも100件・20日以上のときだけ。"""
    grouped = defaultdict(list)
    kinds = {}
    last, first = shift(target, -MATURITY), shift(target, -180)
    variety = variety_rows(history.rows)
    for row in history.rows:
        next_day = shift(row['day'], 1)
        if not first <= next_day <= last or not valid(row):
            continue
        if history.get(row['day'], identity(row)) is not row:
            continue      # 同じ日に古い名前と新しい名前の両方がある台は、新しい名前の行だけを数える（二重に数えない）
        y = outcome(history.get(next_day, identity(row)))
        if y is None:
            continue
        key, x = learning_key(identity(row)), history.features(row)
        grouped[key[:3]].append((x, y, next_day))
        kinds[key[:3]] = 'machine'
        common = (key[0], key[1], STORE_MODEL)
        grouped[common].append((x + history.extras(row, 'store'), y, next_day))
        kinds[common] = 'store'
        if id(row) in variety:
            own = (key[0], key[1], VARIETY_MODEL)
            grouped[own].append((x + history.extras(row, 'variety'), y, next_day))
            kinds[own] = 'variety'
    models = {}
    for key, examples in grouped.items():
        if len(examples) < 100 or len({e[2] for e in examples}) < 20:
            continue
        weights, days = _fit(examples)
        models[key] = dict(weights=weights, n=len(examples), days=days, first=first, last=last,
                           features=KIND_FEATURES[kinds[key]], kind=kinds[key], version=VERSION)
    return models


def _ordered(scores):
    return [r for _, r in sorted(scores, key=lambda v: (-round(v[0], 12), identity(v[1])))]


def rank_pool(pool, history, models):
    """機種ごとの係数で並べる。1台でも係数の無い機種があれば None。"""
    scores = []
    for row in pool:
        model = models.get(learning_key(identity(row))[:3])
        if model is None:
            return None
        x = history.features(row)
        score = sum(a * b for a, b in zip(x, model['weights']))
        scores.append((score, row))
    return _ordered(scores)


def rank_by(pool, history, model, kind):
    """1つの係数（店舗共通・バラエティ専用）で並べる（v4）。係数が無ければ None。同点の並びは rank_pool と同じ。"""
    if model is None:
        return None
    return _ordered([(sum(a * b for a, b in zip(history.model_features(r, kind), model['weights'])), r) for r in pool])


def _share(group, method, missing_as):
    """候補のうちプラスの割合。判定不能の台を missing_as（0＝非プラス、1＝プラス）として数える感度分析用。"""
    k = group.get('k_' + method)
    if not k:
        return None
    plus = group.get('plus_' + method)
    if plus is None:
        plus = (group[method] or 0) * group['n_' + method]
    return (plus + (k - group['n_' + method]) * missing_as) / k


def store_day(day, groups):
    """1店舗・1日の比較。学習済みの組を等しく重み付けして平均する（候補の多い組だけが効かないように）。"""
    groups = [g for g in groups if g.get('trained')]
    paired = [g for g in groups if g['current'] is not None and g['learned'] is not None]
    def mean_of(values):
        values = [v for v in values if v is not None]
        return statistics.mean(values) if values else None
    sens = {}
    for name, missing_as in (('nonplus', 0), ('plus', 1)):
        values = []
        for g in groups:
            a, b = _share(g, 'learned', missing_as), _share(g, 'current', missing_as)
            values.append(None if a is None or b is None else a - b)
        sens[name] = mean_of(values)
    return dict(day=day, groups=len(groups), paired=len(paired),
                diff=mean_of(g['learned'] - g['current'] for g in paired),
                diff_nonplus=sens['nonplus'], diff_plus=sens['plus'],
                missing=mean_of(g['missing_learned'] - g['missing_current'] for g in groups),
                n_current=sum(g['n_current'] for g in groups), n_learned=sum(g['n_learned'] for g in groups))


def flip_p(values):
    """週ごとの差の符号を入れ替える検定（片側、全組合せの正確な値）。帰無仮説：各週の差の分布が0について対称。

    S=Σ±v の 2^n 通りのうち、観測値以上になる割合。半分ずつの和を並べて数えるので n=30 でも速い。"""
    values = [float(v) for v in values]
    if not values:
        return 1.
    observed = sum(values)
    half = len(values) // 2

    def sums(part):
        out = [0.]
        for v in part:
            out = [s + v for s in out] + [s - v for s in out]
        return out
    left, right = sums(values[:half]), sorted(sums(values[half:]))
    count = sum(len(right) - bisect_left(right, observed - x - 1e-12) for x in left)
    return count / 2 ** len(values)


def comparison(days, alpha, first=None):
    """固定期間に1回、店舗ごとに判定する。days は store_day の結果。

    効果量は判定できた日の等重み平均（学習版−従来のプラス率）。検定は暦週ごとの差の合計に対する
    符号反転（日・台を独立試行にしない）。欠測を非プラス・プラスとみなした感度分析の両方が正であることも求める。"""
    paired = [d for d in days if d.get('diff') is not None]
    if not paired:
        return dict(adopt=False, reason='判定可能な日がありません', n=0, rule=RULE_VERSION)
    first = first or min(d['day'] for d in days)
    weeks = defaultdict(float)
    for d in paired:
        weeks[(date.fromisoformat(d['day']) - date.fromisoformat(first)).days // 7] += d['diff']
    blocks = [weeks[k] for k in sorted(weeks)]
    actual = sum(blocks) / len(paired)
    p = flip_p(blocks)

    def mean_key(key):
        values = [d[key] for d in days if d.get(key) is not None]
        return statistics.mean(values) if values else None
    missing, nonplus, plus = mean_key('missing'), mean_key('diff_nonplus'), mean_key('diff_plus')
    counts = [sum(d[k] for d in days) for k in ('n_current', 'n_learned')]
    enough = len(paired) >= 80 and len(blocks) >= 14 and min(counts) >= 80
    robust = nonplus is not None and plus is not None and nonplus > 0 and plus > 0
    adopt = (enough and actual >= .02 and missing is not None and missing <= .02 and robust and p <= alpha)
    return dict(adopt=adopt, reason='改善を確認' if adopt else '改善未確認', n=len(paired),
                weeks=len(blocks), difference=actual, median=statistics.median(d['diff'] for d in paired),
                missing_difference=missing, nonplus_difference=nonplus, plus_difference=plus,
                p=p, alpha=alpha, counts=counts, rule=RULE_VERSION)


def rollback_needed(days):
    """採用後の28暦日のまとまりで、従来へ戻すか。店舗単位（採用と同じ単位）。安全側の運用基準で、悪化の証明ではない。"""
    paired = [d for d in days if d.get('diff') is not None]
    missing = [d['missing'] for d in days if d.get('missing') is not None]
    if len(paired) < 14:
        return False
    return (statistics.mean(d['diff'] for d in paired) <= -.05
            or (bool(missing) and statistics.mean(missing) > .05))


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

    def has(self, table, key):
        if table not in ('predictions', 'outcomes', 'decisions', 'inputs', 'state'):
            raise ValueError('保存先が不正です')
        return self.db.execute(f'SELECT 1 FROM {table} WHERE key=?', (key,)).fetchone() is not None

    def get(self, table, key):
        if table not in ('predictions', 'outcomes', 'decisions', 'inputs', 'state'):
            raise ValueError('保存先が不正です')
        cols = 'body' if table == 'state' else 'body,sha'
        found = self.db.execute(f'SELECT {cols} FROM {table} WHERE key=?', (key,)).fetchone()
        if found is None:
            return None
        text = found[0]
        if isinstance(text, bytes):
            # 2026-11-12 軽量化C：本文は圧縮して保存する。指紋は今までどおり圧縮前の文字（encoded）に対するもの。
            text = zlib.decompress(text).decode('utf-8')
        body = json.loads(text)
        if (table != 'state' and hashlib.sha256(text.encode('utf-8')).hexdigest() != found[1]
                and digest(body) != found[1]):
            raise ValueError('固定記録の指紋が一致しません')
        return body

    def append(self, table, key, body):
        self.append_text(table, key, encoded(body))

    def append_text(self, table, key, text):
        """encoded() で作った本文の文字を、指紋を付けて圧縮して追記する（同じ行を何度も文字にしない。軽量化B・C）。"""
        if table not in ('predictions', 'outcomes', 'decisions', 'inputs'):
            raise ValueError('保存先が不正です')
        raw = text.encode('utf-8')
        self.db.execute(f'INSERT INTO {table} VALUES (?,?,?)',
                        (key, zlib.compress(raw, 6), hashlib.sha256(raw).hexdigest()))

    def state(self, key, body):
        self.db.execute('INSERT INTO state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body', (key, encoded(body)))

    def freeze(self, target, prediction, inputs, now, store=None):
        """事前予測を1回だけ固定する。inputs は {名前: 行の一覧}（一覧だけなら 'rows'）。

        入力は「店舗×日」の塊ごとに指紋を付けて保存し、同じ塊は2回保存しない（2026-11-12。以前は
        210日分を毎晩まるごと保存し、1晩で約132MB増えていた）。予測には塊の指紋の一覧を持たせる。"""
        now = jst(now)
        if target != prediction_target(now):
            raise LateError('保存できる時間（対象日の前日23:30〜当日08:00）の外なので、事前予測を保存しません')
        if not isinstance(inputs, dict):
            inputs = {'rows': inputs}
        key = target + ('|' + store if store else '')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.has('predictions', key):
                return False
            manifest = {}
            for name in sorted(inputs):
                chunks = defaultdict(list)
                for r in inputs[name]:
                    chunks[(str(r.get('store', '')), str(r.get('day', '')))].append(r)
                manifest[name] = []
                for part in sorted(chunks):
                    # 1行を文字にするのは1回だけ（軽量化B）。encoded(sorted(行, key=encoded)) と同じ文字・同じ指紋になる。
                    text = '[' + ','.join(sorted(encoded(r) for r in chunks[part])) + ']'
                    stamp = hashlib.sha256(text.encode('utf-8')).hexdigest()
                    if not self.has('inputs', stamp):
                        self.append_text('inputs', stamp, text)
                    manifest[name].append(stamp)
            prediction = {**prediction, 'target': target, 'saved_at': now.isoformat(), 'inputs': manifest,
                          'input_sha256': digest(manifest), 'version': VERSION}
            self.append('predictions', key, prediction)
        return True

    def input_rows(self, prediction, name='rows'):
        """固定した予測の入力を作り直す。2026-11-12より前の予測（1つの塊）にも対応する。"""
        if 'inputs' not in prediction:
            return self.get('inputs', prediction['input_sha256']) if name == 'rows' else []
        rows = []
        for stamp in prediction['inputs'].get(name, []):
            rows.extend(self.get('inputs', stamp))
        return rows
