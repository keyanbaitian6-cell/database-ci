"""完全盲検（Double-Blind）パチスロ翌日ランキングモデル。

第一原理（ドメイン構造・条件付きランキング推定・階層ベイズ収縮・
忘却付きベイズモデル平均）のみに基づいて設計された単一モデル実装。
Python 3.14 標準ライブラリのみを使用。
"""

from __future__ import annotations

from collections import deque
from datetime import date
import math
from typing import Any

VERSION = 'blind-hbma-condrank-v1'

# ---------------------------------------------------------------------------
# 定数・ハイパーパラメータ（第一原理に基づく設定）
# ---------------------------------------------------------------------------

# 特徴量次元数（21次元）
_NUM_FEATURES = 21

# 弱情報事前分布の対角ペナルティ倍率（主効果 1.0、2次/空間/派生/EB 1.5）
_PRIOR_DIAG = (
    1.0,  # 0: prev_win（前日プラス二値）
    1.0,  # 1: prev_perf_rel（前日出玉・グループ内相対順位）
    1.0,  # 2: prev_perf_mag（前日出玉・絶対大きさ tanh）
    1.5,  # 3: prev_perf_sq（前日出玉・極端さ 2次項）
    1.0,  # 4: prev_games_rel（前日稼働・グループ内相対順位）
    1.0,  # 5: prev_games_log（前日稼働・機種平均比対数水準）
    1.0,  # 6: prev_hit_ev（前日合算当たり・ベイズ収縮ポアソン証拠）
    1.0,  # 7: prev_rb_ev（前日 REG 当たり・ベイズ収縮ポアソン証拠）
    1.0,  # 8: high_game_perf（前日高稼働 × 出玉 交互作用）
    1.5,  # 9: prev_peak_drop（前日ピークからの飲まれ・失速度）
    1.0,  # 10: hist_short_perf（直近 2〜7日 EMA 出玉）
    1.0,  # 11: hist_long_win（直近 2〜28日 台別ベイズ収縮勝率差）
    1.0,  # 12: streak_signed（連続プラス／マイナス記録）
    1.0,  # 13: past7_games_rel（直近 7日平均稼働・グループ内相対順位）
    1.0,  # 14: past14_hit_ev（直近 14日累積合算当たり証拠）
    1.0,  # 15: past14_rb_ev（直近 14日累積 REG 証拠）
    1.5,  # 16: is_corner（角台・内角フラグ）
    1.5,  # 17: date_digit_match（対象日末尾と台番号末尾の一致）
    1.5,  # 18: neighbor_prev_perf（隣接台の前日出玉）
    1.5,  # 19: digit_eb_lift（成熟済み末尾番号の超過勝率）
    1.5,  # 20: machine_eb_lift（成熟済み機種別超過勝率：バラエティで発動）
)

# 忘却半減期（暦日）
_HORIZONS = (14.0, 60.0, 240.0)
_HORIZON_DECAYS = tuple(math.pow(0.5, 1.0 / h) for h in _HORIZONS)

# エキスパート定義: (name, is_hier, horizon_idx, lam_store, lam_mach, prior_weight)
_EXPERTS: tuple[tuple[str, bool, int, float, float, float], ...] = (
    # 店舗共有（Pooled）9エキスパート: 3ホライゾン × 3正則化水準
    ('pool_h14_l12', False, 0, 12.0, 0.0, 0.8),
    ('pool_h14_l45', False, 0, 45.0, 0.0, 0.8),
    ('pool_h14_l180', False, 0, 180.0, 0.0, 0.8),
    ('pool_h60_l12', False, 1, 12.0, 0.0, 1.2),
    ('pool_h60_l45', False, 1, 45.0, 0.0, 1.5),
    ('pool_h60_l180', False, 1, 180.0, 0.0, 1.5),
    ('pool_h240_l12', False, 2, 12.0, 0.0, 1.2),
    ('pool_h240_l45', False, 2, 45.0, 0.0, 1.5),
    ('pool_h240_l180', False, 2, 180.0, 0.0, 1.5),
    # 階層ベイズ機種適応（Hierarchical）3エキスパート
    ('hier_h60_l12', True, 1, 12.0, 30.0, 0.7),
    ('hier_h60_l45', True, 1, 45.0, 90.0, 0.8),
    ('hier_h240_l45', True, 2, 45.0, 90.0, 0.8),
)
_NUM_EXPERTS = len(_EXPERTS)

# Prequential BMA（Dynamic Model Averaging）パラメータ
_BMA_HALF_LIFE = 21.0
_BMA_DECAY = math.pow(0.5, 1.0 / _BMA_HALF_LIFE)
_BMA_TEMP = 4.0

# 経験ベイズ統計（末尾・機種）の忘却半減期と事前強度
_EB_DECAY = math.pow(0.5, 1.0 / 90.0)
_DIGIT_EB_PRIOR = 60.0
_MACHINE_EB_PRIOR = 25.0

# 成熟遅延（本番厳守: 翌暦日結果 <= target - 8、すなわち学習日 <= target - 9）
_MATURITY_LAG_LABEL = 8
_MATURITY_LAG_FEAT = 9

# 最小学習開始条件（初期ノイズ出力回避）
_MIN_TRAIN_DAYS = 3
_MIN_TRAIN_OBS = 40

# バラエティ内部グループ名
_VARIETY_GROUP = '__VARIETY__'


# ---------------------------------------------------------------------------
# 数値検証・正解ラベル `outcome(row)`
# ---------------------------------------------------------------------------


def _as_finite_float(val: Any) -> float | None:
    """bool を除外し、有限な実数として解釈できる値のみ float で返す。"""
    if isinstance(val, bool) or val is None:
        return None
    if isinstance(val, (int, float)):
        f = float(val)
        return f if math.isfinite(f) else None
    return None


def _is_valid_count(val: Any, upper: float) -> bool:
    """None または 0..upper の有限数値（bool 不可）なら True。"""
    if val is None:
        return True
    f = _as_finite_float(val)
    if f is None:
        return False
    return 0.0 <= f <= upper


def _is_valid_row(row: dict[str, Any]) -> bool:
    """仕様に基づく有効行判定。"""
    if not isinstance(row, dict):
        return False
    games = _as_finite_float(row.get('games'))
    if games is None or not (0.0 < games <= 20000.0):
        return False
    if not _is_valid_count(row.get('bb'), 500.0):
        return False
    if not _is_valid_count(row.get('rb'), 500.0):
        return False
    if not _is_valid_count(row.get('my'), 100000.0):
        return False
    if not _is_valid_count(row.get('max_hold'), 100000.0):
        return False
    store = str(row.get('store') or '')
    if store.startswith('pscube:'):
        if row.get('source_site') == 'anaslo' and row.get('archive') != 'normal-analysis':
            return False
    return True


def _extract_graph_end_peak(row: dict[str, Any]) -> tuple[bool, float | None, float | None]:
    """グラフ構造から (グラフデータ有無, end, peak) を抽出する。

    グラフ構造自体は存在するが数値が非有限（NaN/inf等）の場合は
    has_graph=True, end=None を返し、ステップ4への誤フォールバックを防ぐ。
    """
    gm = row.get('graph_measurement')
    if isinstance(gm, dict) and ('baseline_y' in gm or 'end_y' in gm):
        by_raw = gm.get('baseline_y')
        ey_raw = gm.get('end_y')
        by = _as_finite_float(by_raw)
        ey = _as_finite_float(ey_raw)
        if by is not None and ey is not None:
            end = by - ey
            if not math.isfinite(end):
                return True, None, None
            py = _as_finite_float(gm.get('peak_y'))
            peak = (by - py) if (py is not None and math.isfinite(by - py)) else None
            if peak is not None and peak < end:
                peak = end
            return True, end, peak
        if by_raw is not None or ey_raw is not None:
            # 壊れた非有限値がある場合、graph 側が正常に取れなければ判定不能扱い
            gr_fallback = _extract_from_graph_points(row.get('graph'))
            if gr_fallback[0]:
                return gr_fallback
            return True, None, None

    return _extract_from_graph_points(row.get('graph'))


def _extract_from_graph_points(gr: Any) -> tuple[bool, float | None, float | None]:
    """graph={'zero_y': ..., 'points': [[x, y], ...]} から (有無, end, peak) を抽出。"""
    if not isinstance(gr, dict):
        return False, None, None
    pts = gr.get('points')
    zy_raw = gr.get('zero_y')
    if not isinstance(pts, (list, tuple)) or len(pts) == 0:
        return False, None, None
    zy = _as_finite_float(zy_raw)
    last = pts[-1]
    if not isinstance(last, (list, tuple)) or len(last) < 2:
        return True, None, None
    last_y = _as_finite_float(last[1])
    if zy is None or last_y is None:
        return True, None, None
    end = zy - last_y
    if not math.isfinite(end):
        return True, None, None
    peak = end
    for pt in pts:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            py = _as_finite_float(pt[1])
            if py is not None:
                val = zy - py
                if val > peak:
                    peak = val
    return True, end, peak


def outcome(row: dict[str, Any]) -> int | None:
    """仕様厳守の正解ラベル（記録上のプラス＝1、非プラス＝0、判定不能／無効＝None）。"""
    if not _is_valid_row(row):
        return None

    # 2. 確定差枚（jo_net -> net_medals の順）
    jo_net = _as_finite_float(row.get('jo_net'))
    if jo_net is not None:
        return 1 if jo_net > 0.0 else 0
    net_medals = _as_finite_float(row.get('net_medals'))
    if net_medals is not None:
        return 1 if net_medals > 0.0 else 0

    # 3. グラフ終点判定（abs(end) <= 1 は判定不能 None）
    has_graph, end, _ = _extract_graph_end_peak(row)
    if has_graph:
        if end is None or not math.isfinite(end) or abs(end) <= 1.0:
            return None
        return 1 if end > 1.0 else 0

    # 4. 差枚もグラフも無い場合の大当たり0回グラフ省略仕様
    bb = _as_finite_float(row.get('bb'))
    rb = _as_finite_float(row.get('rb'))
    if bb is None or rb is None or bb != 0.0 or rb != 0.0:
        return None

    store = str(row.get('store') or '')
    at_raw = row.get('at_art')
    at_val = _as_finite_float(at_raw)
    if store.startswith('pscube:'):
        # pscube は明示的 0 のみ（None や非数値は除外）
        if at_val is not None and at_val == 0.0:
            return 0
        return None
    # メルヘン系: at_art が無ければ OK、あれば 0 のみ
    if at_raw is None:
        return 0
    if at_val is not None and at_val == 0.0:
        return 0
    return None


# ---------------------------------------------------------------------------
# 内部データ構造・数値計算ユーティリティ
# ---------------------------------------------------------------------------


def _day_to_ord(day_str: str) -> int:
    return date.fromisoformat(day_str).toordinal()


def _tiebreak_key(row: dict[str, Any]) -> tuple[str, str, str, int]:
    rack_raw = row.get('rack', 0)
    try:
        rack_int = int(rack_raw) if not isinstance(rack_raw, bool) else 0
    except (TypeError, ValueError):
        rack_int = 0
    return (
        str(row.get('store') or ''),
        str(row.get('rate') or ''),
        str(row.get('machine') or ''),
        rack_int,
    )


class _CleanRow:
    """1行のクリーニング済み軽量表現。"""

    __slots__ = (
        'store',
        'rate',
        'machine',
        'rack',
        'games',
        'bb',
        'rb',
        'at_art',
        'max_hold',
        'net',
        'graph_end',
        'graph_peak',
        'outcome_val',
        'info_rank',
    )

    def __init__(self, row: dict[str, Any]) -> None:
        self.store = str(row.get('store') or '')
        self.rate = str(row.get('rate') or '')
        self.machine = str(row.get('machine') or '')
        rack_raw = row.get('rack', 0)
        try:
            self.rack = int(rack_raw) if not isinstance(rack_raw, bool) else 0
        except (TypeError, ValueError):
            self.rack = 0
        games = _as_finite_float(row.get('games'))
        self.games = games if (games is not None and games > 0.0) else 0.0
        bb = _as_finite_float(row.get('bb'))
        self.bb = bb if (bb is not None and 0.0 <= bb <= 500.0) else None
        rb = _as_finite_float(row.get('rb'))
        self.rb = rb if (rb is not None and 0.0 <= rb <= 500.0) else None
        at_art = _as_finite_float(row.get('at_art'))
        self.at_art = at_art if (at_art is not None and 0.0 <= at_art <= 5000.0) else None
        mh = _as_finite_float(row.get('max_hold'))
        self.max_hold = mh if (mh is not None and 0.0 <= mh <= 100000.0) else None

        jo = _as_finite_float(row.get('jo_net'))
        nm = _as_finite_float(row.get('net_medals'))
        self.net = jo if jo is not None else nm

        has_g, end, peak = _extract_graph_end_peak(row)
        self.graph_end = end if has_g else None
        self.graph_peak = peak if has_g else None

        self.outcome_val = outcome(row)
        # 重複行解決用の情報優先度（確定差枚 > グラフ > その他, 稼働大）
        src_prio = 2 if self.net is not None else (1 if self.graph_end is not None else 0)
        self.info_rank = (src_prio, 1 if self.outcome_val is not None else 0, self.games)


class _MachineBaseStats:
    """機種ごとの因果的ベースライン統計（特徴量の無次元化・ベイズ収縮用）。"""

    __slots__ = (
        'net_abs_sum',
        'net_w',
        'graph_abs_sum',
        'graph_w',
        'games_sum',
        'games_w',
        'hit_sum',
        'hit_games',
        'hit_at_sum',
        'hit_at_games',
        'rb_sum',
        'rb_games',
        'win_sum',
        'win_w',
        'rack_last_seen',
    )

    def __init__(self) -> None:
        self.net_abs_sum = 0.0
        self.net_w = 0.0
        self.graph_abs_sum = 0.0
        self.graph_w = 0.0
        self.games_sum = 0.0
        self.games_w = 0.0
        self.hit_sum = 0.0
        self.hit_games = 0.0
        self.hit_at_sum = 0.0
        self.hit_at_games = 0.0
        self.rb_sum = 0.0
        self.rb_games = 0.0
        self.win_sum = 0.0
        self.win_w = 0.0
        self.rack_last_seen: dict[int, int] = {}

    def decay(self, factor: float) -> None:
        self.net_abs_sum *= factor
        self.net_w *= factor
        self.graph_abs_sum *= factor
        self.graph_w *= factor
        self.games_sum *= factor
        self.games_w *= factor
        self.hit_sum *= factor
        self.hit_games *= factor
        self.hit_at_sum *= factor
        self.hit_at_games *= factor
        self.rb_sum *= factor
        self.rb_games *= factor
        self.win_sum *= factor
        self.win_w *= factor


class _QuadraticAccumulator:
    """指数減衰付きの対称行列 H (D×D) とベクトル b (D) の十分統計量。"""

    __slots__ = ('decay_rate', 'last_ord', 'h_mat', 'b_vec', 'eff_groups')

    def __init__(self, decay_rate: float) -> None:
        self.decay_rate = decay_rate
        self.last_ord: int | None = None
        self.h_mat = [[0.0] * _NUM_FEATURES for _ in range(_NUM_FEATURES)]
        self.b_vec = [0.0] * _NUM_FEATURES
        self.eff_groups = 0.0

    def apply_decay_to(self, day_ord: int) -> None:
        if self.last_ord is None:
            self.last_ord = day_ord
            return
        delta = day_ord - self.last_ord
        if delta > 0:
            f = math.pow(self.decay_rate, delta)
            hm = self.h_mat
            bv = self.b_vec
            for i in range(_NUM_FEATURES):
                row_i = hm[i]
                bv[i] *= f
                for j in range(_NUM_FEATURES):
                    row_i[j] *= f
            self.eff_groups *= f
            self.last_ord = day_ord

    def add_stats(
        self,
        day_ord: int,
        h_add: list[list[float]],
        b_add: list[float],
        eff_g: float,
    ) -> None:
        self.apply_decay_to(day_ord)
        hm = self.h_mat
        bv = self.b_vec
        for i in range(_NUM_FEATURES):
            row_i = hm[i]
            add_i = h_add[i]
            bv[i] += b_add[i]
            for j in range(_NUM_FEATURES):
                row_i[j] += add_i[j]
        self.eff_groups += eff_g


def _solve_spd_ridge(
    h_mat: list[list[float]],
    b_vec: list[float],
    lam: float,
    prior_mean: list[float] | None = None,
) -> list[float]:
    """(H + lam * P) w = b + lam * P * prior_mean を Cholesky 分解で厳密に解く。"""
    n = _NUM_FEATURES
    # 下三角 Cholesky 因子 L を構築
    l_mat = [[0.0] * n for _ in range(n)]
    rhs = [0.0] * n
    if prior_mean is None:
        for i in range(n):
            rhs[i] = b_vec[i]
    else:
        for i in range(n):
            rhs[i] = b_vec[i] + lam * _PRIOR_DIAG[i] * prior_mean[i]

    jitter = 0.0
    for _attempt in range(3):
        ok = True
        for i in range(n):
            li = l_mat[i]
            hi = h_mat[i]
            for j in range(i):
                lj = l_mat[j]
                s = hi[j]
                for k in range(j):
                    s -= li[k] * lj[k]
                li[j] = s / lj[j]
            s = hi[i] + lam * _PRIOR_DIAG[i] + jitter
            for k in range(i):
                s -= li[k] * li[k]
            if s <= 1e-12 or not math.isfinite(s):
                ok = False
                break
            li[i] = math.sqrt(s)
        if ok:
            # 前進代入 L y = rhs
            y = [0.0] * n
            for i in range(n):
                li = l_mat[i]
                s = rhs[i]
                for k in range(i):
                    s -= li[k] * y[k]
                y[i] = s / li[i]
            # 後退代入 L^T w = y
            w = [0.0] * n
            for i in range(n - 1, -1, -1):
                s = y[i]
                for k in range(i + 1, n):
                    s -= l_mat[k][i] * w[k]
                val = s / l_mat[i][i]
                w[i] = val if math.isfinite(val) else 0.0
            return w
        jitter = 1e-6 if jitter == 0.0 else jitter * 100.0
    return list(prior_mean) if prior_mean is not None else [0.0] * n


def _relative_ranks(values: list[float | None]) -> list[float]:
    """欠測を除外した観測値のみを [-1, 1] の平均タイ順位へ写像する（欠測は 0.0）。"""
    indexed: list[tuple[float, int]] = []
    for idx, v in enumerate(values):
        if v is not None and math.isfinite(v):
            indexed.append((v, idx))
    m = len(indexed)
    out = [0.0] * len(values)
    if m <= 1:
        return out
    indexed.sort(key=lambda t: t[0])
    denom = float(m - 1)
    i = 0
    while i < m:
        j = i + 1
        val_i = indexed[i][0]
        while j < m and indexed[j][0] == val_i:
            j += 1
        avg_rank = 0.5 * (i + j - 1)
        norm_val = (2.0 * avg_rank / denom) - 1.0
        for k in range(i, j):
            out[indexed[k][1]] = norm_val
        i = j
    return out


def _log1pexp(x: float) -> float:
    """数値安定な log(1 + exp(x))。"""
    if x > 30.0:
        return x
    if x < -30.0:
        return math.exp(x)
    return math.log1p(math.exp(x))


def _dot(a: list[float], b: list[float]) -> float:
    s = 0.0
    for i in range(_NUM_FEATURES):
        s += a[i] * b[i]
    return s


# ---------------------------------------------------------------------------
# メインモデルクラス: BlindModel
# ---------------------------------------------------------------------------


class BlindModel:
    """完全盲検パチスロ翌日候補ランキングモデル（店舗独立インスタンス）。"""

    def __init__(self, store: str) -> None:
        self.store = str(store)
        # 日別クリーニング済みレコード: day_ord -> list[_CleanRow]（決定論的ソート済み）
        self._days: dict[int, list[_CleanRow]] = {}
        self._sorted_day_ords: list[int] = []
        self._days_dirty: bool = False
        self._init_runtime_state()

    def _init_runtime_state(self) -> None:
        """カーソル・履歴統計・十分統計量・BMA 状態を初期化する。"""
        # 特徴量用履歴統計を取り込み済みの最新日（特徴量日 d を処理する直前は d-1）
        self._hist_cursor: int | None = None
        # 成熟済み学習ペア (s, s+1) を取り込み済みの最新特徴量日 s（常に <= target - 9）
        self._train_cursor: int | None = None
        # 成熟済み EB 統計（末尾・機種）の取り込み済み最新ラベル日（常に <= target - 8）
        self._eb_cursor: int | None = None

        # 店舗全体のベースライン統計（新台フォールバック用）
        self._store_base = _MachineBaseStats()
        self._store_base_last_ord: int | None = None
        # 機種別ベースライン統計: (rate, machine) -> _MachineBaseStats
        self._mach_base: dict[tuple[str, str], _MachineBaseStats] = {}
        self._mach_base_last_ord: dict[tuple[str, str], int] = {}
        # 店舗全体の直近台番号観測（バラエティ角台用）: rate -> dict[rack, last_ord]
        self._store_racks_seen: dict[str, dict[int, int]] = {}

        # 台別履歴バッファ: (rate, machine, rack) -> deque[(ord, games, outcome, perf_z, bb_rb, at_art, rb)]
        self._rack_hist: dict[tuple[str, str, int], deque[tuple[Any, ...]]] = {}

        # 成熟済み EB 統計（ラベル日 <= target - 8 のみで更新）
        self._digit_eb_sum = [0.0] * 10
        self._digit_eb_cnt = [0.0] * 10
        self._mach_eb_sum: dict[str, float] = {}
        self._mach_eb_cnt: dict[str, float] = {}
        self._eb_last_decay_ord: int | None = None

        # 日別学習用特徴量キャッシュ（未成熟期間のみ保持、学習消費後に解放）
        # day_ord -> list[(group_key, list[(rate, machine, rack, feat_vec)])]
        self._pending_day_groups: dict[
            int,
            list[tuple[str, list[tuple[str, str, int, list[float]]]]],
        ] = {}

        # 店舗全体のホライゾン別十分統計量
        self._store_acc = [_QuadraticAccumulator(d) for d in _HORIZON_DECAYS]
        # 機種別ホライゾン別十分統計量: group_key -> dict[horizon_idx, _QuadraticAccumulator]
        self._mach_acc: dict[str, dict[int, _QuadraticAccumulator]] = {}
        self._mach_last_train_ord: dict[str, int] = {}

        # One-step-ahead Prequential 評価および最新予測用の学習済み重み
        # 常に直前の成熟学習ペア（feat_day <= s - 1, label_day <= s）のみから解かれた重み
        self._last_store_weights: list[list[float]] | None = None
        self._last_hier_weights: dict[int, dict[str, list[float]]] | None = None

        # BMA 累積対数尤度比スコア
        self._bma_scores = [0.0] * _NUM_EXPERTS
        self._bma_last_ord: int | None = None

        # 学習進捗カウンタ（最小稼働条件判定用）
        self._trained_days = 0
        self._trained_obs = 0

        # 直近 target 用の予測パラメータキャッシュ
        self._cached_target_ord: int | None = None
        self._cached_bma_probs: list[float] | None = None
        self._cached_store_weights: list[list[float]] | None = None
        self._cached_hier_weights: dict[int, dict[str, list[float]]] | None = None
        self._cached_nbr_map: dict[tuple[str, int], float] | None = None

    def ingest_day(self, day: str, rows: list[dict[str, Any]]) -> None:
        """営業日 day のレコード群を受け取る。"""
        day_ord = _day_to_ord(day)
        dedup: dict[tuple[str, str, str, int], _CleanRow] = {}
        for r in rows:
            if not _is_valid_row(r):
                continue
            cr = _CleanRow(r)
            key = (cr.store, cr.rate, cr.machine, cr.rack)
            prev = dedup.get(key)
            if prev is None or cr.info_rank > prev.info_rank:
                dedup[key] = cr

        cleaned = [dedup[k] for k in sorted(dedup.keys())]
        already_processed = (
            (self._hist_cursor is not None and day_ord <= self._hist_cursor)
            or (self._train_cursor is not None and day_ord <= self._train_cursor + 1)
            or (self._eb_cursor is not None and day_ord <= self._eb_cursor)
            or (self._cached_target_ord is not None and day_ord < self._cached_target_ord)
        )
        self._days[day_ord] = cleaned
        self._days_dirty = True
        if already_processed:
            # 過去日が後から再投入・改変された場合は全状態を安全に再構築する
            self._init_runtime_state()

    def _get_sorted_days(self) -> list[int]:
        if self._days_dirty:
            self._sorted_day_ords = sorted(self._days.keys())
            self._days_dirty = False
        return self._sorted_day_ords

    # -----------------------------------------------------------------------
    # ベース統計・履歴統計の更新（因果的）
    # -----------------------------------------------------------------------

    def _get_scales(
        self, rate: str, machine: str, group_rows: list[_CleanRow]
    ) -> tuple[float, float, float, float, float, float, float]:
        """特徴量無次元化用の各種基準値（net_scale, graph_scale, mean_games,
        bb_rb_rate, bb_rb_at_rate, rb_rate, mach_win_rate）を返す。"""
        sb = self._store_base
        mb = self._mach_base.get((rate, machine))

        # 店舗デフォルト
        st_net = (sb.net_abs_sum / sb.net_w) if sb.net_w >= 5.0 else 1000.0
        st_net = max(250.0, min(5000.0, st_net))
        st_gr = (sb.graph_abs_sum / sb.graph_w) if sb.graph_w >= 5.0 else 30.0
        st_gr = max(5.0, min(500.0, st_gr))
        st_games = (sb.games_sum / sb.games_w) if sb.games_w >= 5.0 else 2500.0
        st_games = max(300.0, min(10000.0, st_games))
        st_win = (sb.win_sum + 2.0) / (sb.win_w + 4.0)

        # 当日グループ内の統計（新台・初登場時の補間にも使う、d日時点の情報）
        g_games = 0.0
        g_cnt = 0
        g_hit = 0.0
        g_hit_g = 0.0
        g_hit_at = 0.0
        g_hit_at_g = 0.0
        g_rb = 0.0
        g_rb_g = 0.0
        for r in group_rows:
            if r.games > 0.0:
                g_games += r.games
                g_cnt += 1
                if r.bb is not None and r.rb is not None:
                    g_hit += r.bb + r.rb
                    g_hit_g += r.games
                    if r.at_art is not None:
                        g_hit_at += r.bb + r.rb + r.at_art
                        g_hit_at_g += r.games
                if r.rb is not None:
                    g_rb += r.rb
                    g_rb_g += r.games

        if mb is not None:
            # 事前強度 8.0 台分で店舗スケールへ収縮
            net_scale = (mb.net_abs_sum + 8.0 * st_net) / (mb.net_w + 8.0)
            graph_scale = (mb.graph_abs_sum + 8.0 * st_gr) / (mb.graph_w + 8.0)
            games_prior = (g_games / g_cnt) if g_cnt > 0 else st_games
            mean_games = (mb.games_sum + 6.0 * games_prior) / (mb.games_w + 6.0)
            mach_win = (mb.win_sum + 8.0 * st_win) / (mb.win_w + 8.0)

            tot_hg = mb.hit_games + g_hit_g
            bb_rb_rate = (mb.hit_sum + g_hit + 5.0) / (tot_hg + 1200.0) if tot_hg > 0.0 else (1.0 / 240.0)

            tot_hag = mb.hit_at_games + g_hit_at_g
            bb_rb_at_rate = (
                (mb.hit_at_sum + g_hit_at + 5.0) / (tot_hag + 1200.0)
                if tot_hag > 0.0
                else bb_rb_rate
            )

            tot_rg = mb.rb_games + g_rb_g
            rb_rate = (mb.rb_sum + g_rb + 1.5) / (tot_rg + 1200.0) if tot_rg > 0.0 else (1.0 / 450.0)
        else:
            net_scale = st_net
            graph_scale = st_gr
            mean_games = (g_games / g_cnt) if g_cnt > 0 else st_games
            mach_win = st_win
            bb_rb_rate = (g_hit + 5.0) / (g_hit_g + 1200.0) if g_hit_g > 0.0 else (1.0 / 240.0)
            bb_rb_at_rate = (
                (g_hit_at + 5.0) / (g_hit_at_g + 1200.0) if g_hit_at_g > 0.0 else bb_rb_rate
            )
            rb_rate = (g_rb + 1.5) / (g_rb_g + 1200.0) if g_rb_g > 0.0 else (1.0 / 450.0)

        net_scale = max(250.0, min(6000.0, net_scale))
        graph_scale = max(5.0, min(500.0, graph_scale))
        mean_games = max(300.0, min(10000.0, mean_games))
        return net_scale, graph_scale, mean_games, bb_rb_rate, bb_rb_at_rate, rb_rate, mach_win

    def _compute_perf_z(self, r: _CleanRow, net_scale: float, graph_scale: float) -> float | None:
        if r.net is not None:
            return r.net / net_scale
        if r.graph_end is not None:
            return r.graph_end / graph_scale
        if r.outcome_val == 0 and r.games > 0.0:
            # 大当たり0回グラフ省略仕様：稼働量に応じたマイナス推定（極低稼働を大凹み扱いしない）
            return -min(2.5, r.games / 1500.0)
        return None

    def _update_history_with_day(self, day_ord: int) -> None:
        """日 day_ord の観測を過去履歴・機種ベース統計へ取り込む。"""
        rows = self._days.get(day_ord)
        if not rows:
            return

        # 店舗ベース統計の減衰（半減期 45日）
        base_decay = math.pow(0.5, 1.0 / 45.0)
        if self._store_base_last_ord is not None and day_ord > self._store_base_last_ord:
            self._store_base.decay(math.pow(base_decay, day_ord - self._store_base_last_ord))
        self._store_base_last_ord = day_ord

        # まず機種単位にまとめてスケールを確定してから履歴を追記
        by_rm: dict[tuple[str, str], list[_CleanRow]] = {}
        for r in rows:
            by_rm.setdefault((r.rate, r.machine), []).append(r)

        sb = self._store_base
        for (rate, machine), mrows in by_rm.items():
            net_scale, graph_scale, _, _, _, _, _ = self._get_scales(rate, machine, mrows)

            mb = self._mach_base.get((rate, machine))
            if mb is None:
                mb = _MachineBaseStats()
                self._mach_base[(rate, machine)] = mb
            prev_m_ord = self._mach_base_last_ord.get((rate, machine))
            if prev_m_ord is not None and day_ord > prev_m_ord:
                mb.decay(math.pow(base_decay, day_ord - prev_m_ord))
            self._mach_base_last_ord[(rate, machine)] = day_ord

            store_racks = self._store_racks_seen.setdefault(rate, {})

            for r in mrows:
                perf_z = self._compute_perf_z(r, net_scale, graph_scale)
                bb_rb = (r.bb + r.rb) if (r.bb is not None and r.rb is not None) else None
                hist_key = (r.rate, r.machine, r.rack)
                dq = self._rack_hist.get(hist_key)
                if dq is None:
                    dq = deque(maxlen=35)
                    self._rack_hist[hist_key] = dq
                dq.append((day_ord, r.games, r.outcome_val, perf_z, bb_rb, r.at_art, r.rb))

                # 機種・店舗ベース統計の更新
                if r.net is not None:
                    abs_n = abs(r.net)
                    mb.net_abs_sum += abs_n
                    mb.net_w += 1.0
                    sb.net_abs_sum += abs_n
                    sb.net_w += 1.0
                if r.graph_end is not None:
                    abs_g = abs(r.graph_end)
                    mb.graph_abs_sum += abs_g
                    mb.graph_w += 1.0
                    sb.graph_abs_sum += abs_g
                    sb.graph_w += 1.0
                if r.games > 0.0:
                    mb.games_sum += r.games
                    mb.games_w += 1.0
                    sb.games_sum += r.games
                    sb.games_w += 1.0
                    if bb_rb is not None:
                        mb.hit_sum += bb_rb
                        mb.hit_games += r.games
                        if r.at_art is not None:
                            mb.hit_at_sum += bb_rb + r.at_art
                            mb.hit_at_games += r.games
                    if r.rb is not None:
                        mb.rb_sum += r.rb
                        mb.rb_games += r.games
                if r.outcome_val is not None:
                    mb.win_sum += float(r.outcome_val)
                    mb.win_w += 1.0
                    sb.win_sum += float(r.outcome_val)
                    sb.win_w += 1.0
                mb.rack_last_seen[r.rack] = day_ord
                store_racks[r.rack] = day_ord

            # 古い台番号観測（30日超前）を掃除
            cutoff = day_ord - 30
            if len(mb.rack_last_seen) > 0:
                stale = [rk for rk, lo in mb.rack_last_seen.items() if lo < cutoff]
                for rk in stale:
                    del mb.rack_last_seen[rk]

    # -----------------------------------------------------------------------
    # 成熟済み EB 統計（ラベル日 <= target - 8 のみ）
    # -----------------------------------------------------------------------

    def _update_eb_with_label_day(self, label_day_ord: int) -> None:
        """ラベル日 label_day_ord の観測結果のみを用いて末尾・機種 EB 統計を更新する。"""
        rows = self._days.get(label_day_ord)
        if not rows:
            return

        if self._eb_last_decay_ord is not None and label_day_ord > self._eb_last_decay_ord:
            f = math.pow(_EB_DECAY, label_day_ord - self._eb_last_decay_ord)
            for d in range(10):
                self._digit_eb_sum[d] *= f
                self._digit_eb_cnt[d] *= f
            for m_key in list(self._mach_eb_sum.keys()):
                self._mach_eb_sum[m_key] *= f
                self._mach_eb_cnt[m_key] *= f
        self._eb_last_decay_ord = label_day_ord

        # 店舗日平均勝率（機種超過勝率用）
        obs_all = [r for r in rows if r.outcome_val is not None]
        if len(obs_all) < 2:
            return
        day_mean_win = sum(r.outcome_val for r in obs_all if r.outcome_val is not None) / len(obs_all)

        # (rate, machine) 単位のグループ平均勝率（末尾超過勝率用：機種交絡を完全除去）
        by_rm: dict[tuple[str, str], list[_CleanRow]] = {}
        for r in obs_all:
            by_rm.setdefault((r.rate, r.machine), []).append(r)

        for (_rate, machine), mrows in by_rm.items():
            # 機種超過勝率の更新
            m_sum = 0.0
            for r in mrows:
                assert r.outcome_val is not None
                m_sum += float(r.outcome_val) - day_mean_win
            self._mach_eb_sum[machine] = self._mach_eb_sum.get(machine, 0.0) + m_sum
            self._mach_eb_cnt[machine] = self._mach_eb_cnt.get(machine, 0.0) + float(len(mrows))

            # 末尾超過勝率（同機種内で2台以上観測された場合のみ）
            if len(mrows) >= 2:
                g_mean = sum(r.outcome_val for r in mrows if r.outcome_val is not None) / len(mrows)
                for r in mrows:
                    assert r.outcome_val is not None
                    digit = r.rack % 10
                    self._digit_eb_sum[digit] += float(r.outcome_val) - g_mean
                    self._digit_eb_cnt[digit] += 1.0

    def _advance_eb_to(self, max_label_ord: int) -> None:
        for d_ord in self._get_sorted_days():
            if d_ord > max_label_ord:
                break
            if self._eb_cursor is not None and d_ord <= self._eb_cursor:
                continue
            self._update_eb_with_label_day(d_ord)
            self._eb_cursor = d_ord

    # -----------------------------------------------------------------------
    # 特徴量抽出（21次元：学習時・推論時で100%同一関数）
    # -----------------------------------------------------------------------

    def _build_group_features(
        self,
        feat_day_ord: int,
        group_rows: list[_CleanRow],
        *,
        is_variety: bool,
        nbr_perf_map: dict[tuple[str, int], float],
    ) -> list[list[float]]:
        """日 feat_day_ord のグループ候補に対する 21次元特徴量行列を返す。

        前提:
        - self._hist_cursor <= feat_day_ord - 1（過去履歴統計に当日は未混入）
        - self._eb_cursor <= feat_day_ord - 7（成熟遅延8日厳守: next_day <= (feat_day+1)-8）
        """
        m = len(group_rows)
        if m == 0:
            return []

        target_ord = feat_day_ord + 1
        target_dom_digit = date.fromordinal(target_ord).day % 10

        # 同一機種またはバラエティの各台について基準スケールを計算
        scales_by_rm: dict[tuple[str, str], tuple[float, float, float, float, float, float, float]] = {}
        rows_by_rm: dict[tuple[str, str], list[_CleanRow]] = {}
        for r in group_rows:
            rows_by_rm.setdefault((r.rate, r.machine), []).append(r)
        for rm, rm_rows in rows_by_rm.items():
            scales_by_rm[rm] = self._get_scales(rm[0], rm[1], rm_rows)

        # グループ内で at_art を合算に含めるか（同一機種かつ全員非Noneなら含める）
        use_at_by_rm: dict[tuple[str, str], bool] = {}
        for rm, rm_rows in rows_by_rm.items():
            all_has_at = all(r.at_art is not None for r in rm_rows)
            any_pos_at = any((r.at_art is not None and r.at_art > 0.0) for r in rm_rows)
            use_at_by_rm[rm] = all_has_at and any_pos_at

        # 前日 perf_z, games, drop_z, past7_games の一覧を作成（グループ内相対ランク用）
        perf_z_list: list[float | None] = [None] * m
        games_list: list[float | None] = [None] * m
        past7_games_list: list[float | None] = [None] * m

        # drop_z のソース一貫性チェック（グラフ peak 優先、なければ max_hold+net）
        graph_peak_cnt = sum(1 for r in group_rows if r.graph_peak is not None and r.graph_end is not None)
        mh_net_cnt = sum(1 for r in group_rows if r.max_hold is not None and r.net is not None)
        use_graph_drop = graph_peak_cnt >= max(2, (m + 1) // 2)
        use_mh_drop = (not use_graph_drop) and (mh_net_cnt >= max(2, (m + 1) // 2))
        drop_z_raw: list[float | None] = [None] * m

        # 各台の履歴要約を一時保存
        hist_short_list = [0.0] * m
        hist_long_win_list = [0.0] * m
        streak_list = [0.0] * m
        past14_hit_ev_list = [0.0] * m
        past14_rb_ev_list = [0.0] * m

        for idx, r in enumerate(group_rows):
            rm = (r.rate, r.machine)
            net_scale, graph_scale, _, bb_rb_rate, bb_rb_at_rate, rb_rate, mach_win = scales_by_rm[rm]
            pz = self._compute_perf_z(r, net_scale, graph_scale)
            perf_z_list[idx] = pz
            games_list[idx] = r.games if r.games > 0.0 else None

            if use_graph_drop and r.graph_peak is not None and r.graph_end is not None:
                drop_z_raw[idx] = max(0.0, r.graph_peak - r.graph_end) / graph_scale
            elif use_mh_drop and r.max_hold is not None and r.net is not None:
                drop_z_raw[idx] = max(0.0, r.max_hold - max(0.0, r.net)) / net_scale

            # 過去履歴（厳密に hist_ord < feat_day_ord のみ参照）
            dq = self._rack_hist.get((r.rate, r.machine, r.rack))
            if dq:
                ema_num = 0.0
                ema_den = 0.0
                win_cnt = 0.0
                win_obs = 0.0
                g7_sum = 0.0
                g7_cnt = 0
                h14_sum = 0.0
                h14_g = 0.0
                rb14_sum = 0.0
                rb14_g = 0.0
                use_at = use_at_by_rm[rm]

                for rec in dq:
                    h_ord, h_games, h_out, h_pz, h_bbrb, h_at, h_rb = rec
                    delta = feat_day_ord - h_ord
                    if delta <= 0:
                        continue
                    if delta <= 7:
                        if h_pz is not None:
                            w_d = math.pow(0.5, float(delta - 1) / 2.0)
                            ema_num += w_d * h_pz
                            ema_den += w_d
                        if h_games > 0.0:
                            g7_sum += h_games
                            g7_cnt += 1
                    if delta <= 14 and h_games > 0.0:
                        if h_bbrb is not None:
                            if use_at and h_at is not None:
                                h14_sum += h_bbrb + h_at
                                h14_g += h_games
                            elif not use_at:
                                h14_sum += h_bbrb
                                h14_g += h_games
                        if h_rb is not None:
                            rb14_sum += h_rb
                            rb14_g += h_games
                    if delta <= 28 and h_out is not None:
                        win_cnt += float(h_out)
                        win_obs += 1.0

                if ema_den > 0.0:
                    hist_short_list[idx] = math.tanh((ema_num / ema_den) / 1.8)
                if win_obs > 0.0:
                    eb_rack_win = (win_cnt + 6.0 * mach_win) / (win_obs + 6.0)
                    hist_long_win_list[idx] = math.tanh((eb_rack_win - mach_win) / 0.12)
                if g7_cnt > 0:
                    past7_games_list[idx] = g7_sum / g7_cnt
                if h14_g > 0.0:
                    lam_h = bb_rb_at_rate if use_at else bb_rb_rate
                    exp_h = h14_g * lam_h
                    z_h14 = (h14_sum - exp_h) / math.sqrt(exp_h + 3000.0 * lam_h + 1.0)
                    past14_hit_ev_list[idx] = math.tanh(z_h14 / 2.5)
                if rb14_g > 0.0 and rb_rate > 1e-4:
                    exp_r = rb14_g * rb_rate
                    z_r14 = (rb14_sum - exp_r) / math.sqrt(exp_r + 3000.0 * rb_rate + 1.0)
                    past14_rb_ev_list[idx] = math.tanh(z_r14 / 2.5)

                # 連続勝敗（前日 outcome から開始して直近を遡る、間隔3日以内で打ち切り）
                if r.outcome_val is not None:
                    target_sign = r.outcome_val
                    streak = 1
                    prev_ord = feat_day_ord
                    for rec in reversed(dq):
                        h_ord = rec[0]
                        h_out = rec[2]
                        if h_ord >= prev_ord:
                            continue
                        if prev_ord - h_ord > 3:
                            break
                        if h_out is None:
                            break
                        if h_out == target_sign:
                            streak += 1
                            prev_ord = h_ord
                            if streak >= 7:
                                break
                        else:
                            break
                    signed_s = float(streak) if target_sign == 1 else -float(streak)
                    streak_list[idx] = math.tanh(signed_s / 3.0)
            else:
                if r.outcome_val is not None:
                    streak_list[idx] = math.tanh((1.0 if r.outcome_val == 1 else -1.0) / 3.0)

        # グループ内相対順位（欠測は 0.0）
        perf_rel = _relative_ranks(perf_z_list)
        games_rel = _relative_ranks(games_list)
        past7_games_rel = _relative_ranks(past7_games_list)

        # drop_z の中心化（観測済みの中央値/平均を引いて圧縮、欠測は 0.0）
        drop_obs = [v for v in drop_z_raw if v is not None]
        drop_mean = (sum(drop_obs) / len(drop_obs)) if drop_obs else 0.0

        # 角台判定用の台番号集合を準備
        corner_sets: dict[tuple[str, str], set[int]] = {}
        if is_variety:
            # バラエティでは店舗全体（同一 rate）の直近台番号集合＋当日台番号で島端を判定
            for r in group_rows:
                key = (r.rate, _VARIETY_GROUP)
                if key not in corner_sets:
                    s_racks = set(self._store_racks_seen.get(r.rate, {}).keys())
                    for rk_row in group_rows:
                        if rk_row.rate == r.rate:
                            s_racks.add(rk_row.rack)
                    corner_sets[key] = s_racks
        else:
            for rm, rm_rows in rows_by_rm.items():
                mb = self._mach_base.get(rm)
                r_set = set(mb.rack_last_seen.keys()) if mb is not None else set()
                for rk_row in rm_rows:
                    r_set.add(rk_row.rack)
                corner_sets[rm] = r_set

        # 全21特徴量ベクトルを構築
        feats: list[list[float]] = []
        for idx, r in enumerate(group_rows):
            rm = (r.rate, r.machine)
            _, _, mean_games, bb_rb_rate, bb_rb_at_rate, rb_rate, _ = scales_by_rm[rm]
            use_at = use_at_by_rm[rm]

            # 0: prev_win
            f0 = 0.5 if r.outcome_val == 1 else (-0.5 if r.outcome_val == 0 else 0.0)

            # 1: prev_perf_rel
            f1 = perf_rel[idx]

            # 2, 3: prev_perf_mag, prev_perf_sq
            pz = perf_z_list[idx]
            if pz is not None:
                f2 = math.tanh(pz / 2.0)
                f3 = (f2 * f2) * 1.8
            else:
                f2 = 0.0
                f3 = 0.0

            # 4, 5: prev_games_rel, prev_games_log
            f4 = games_rel[idx]
            if r.games > 0.0:
                f5 = math.tanh((math.log1p(r.games) - math.log1p(mean_games)) / 0.8)
            else:
                f5 = 0.0

            # 6: prev_hit_ev（ベイズ収縮ポアソン z）
            if r.games > 0.0 and r.bb is not None and r.rb is not None:
                if use_at and r.at_art is not None:
                    hits_now = r.bb + r.rb + r.at_art
                    lam_now = bb_rb_at_rate
                else:
                    hits_now = r.bb + r.rb
                    lam_now = bb_rb_rate
                exp_now = r.games * lam_now
                z_hit = (hits_now - exp_now) / math.sqrt(exp_now + 1500.0 * lam_now + 1.0)
                f6 = math.tanh(z_hit / 2.5)
            else:
                f6 = 0.0

            # 7: prev_rb_ev
            if r.games > 0.0 and r.rb is not None and rb_rate > 1e-4:
                exp_rb = r.games * rb_rate
                z_rb = (r.rb - exp_rb) / math.sqrt(exp_rb + 1500.0 * rb_rate + 1.0)
                f7 = math.tanh(z_rb / 2.5)
            else:
                f7 = 0.0

            # 8: high_game_perf（高稼働 × 出玉の非線形交互作用）
            u_g = 1.0 / (1.0 + math.exp(-2.0 * f4))
            f8 = (u_g * f2) * 1.5

            # 9: prev_peak_drop
            dz = drop_z_raw[idx]
            f9 = math.tanh((dz - drop_mean) / 1.5) if dz is not None else 0.0

            # 10..15: 複数日履歴
            f10 = hist_short_list[idx]
            f11 = hist_long_win_list[idx]
            f12 = streak_list[idx]
            f13 = past7_games_rel[idx]
            f14 = past14_hit_ev_list[idx]
            f15 = past14_rb_ev_list[idx]

            # 16: is_corner
            c_key = (r.rate, _VARIETY_GROUP) if is_variety else rm
            c_set = corner_sets.get(c_key, set())
            if len(c_set) >= 3:
                left_open = (r.rack - 1) not in c_set
                right_open = (r.rack + 1) not in c_set
                if left_open ^ right_open:
                    f16 = 1.0
                elif left_open and right_open:
                    f16 = 0.5
                else:
                    # 内角判定（片隣のさらに隣が開いている）
                    left2_open = ((r.rack - 2) not in c_set) and (len(c_set) >= 5)
                    right2_open = ((r.rack + 2) not in c_set) and (len(c_set) >= 5)
                    f16 = 0.3 if (left2_open or right2_open) else 0.0
            else:
                f16 = 0.0

            # 17: date_digit_match
            f17 = 1.0 if (r.rack % 10 == target_dom_digit) else 0.0

            # 18: neighbor_prev_perf
            n_vals = []
            left_p = nbr_perf_map.get((r.rate, r.rack - 1))
            if left_p is not None:
                n_vals.append(left_p)
            right_p = nbr_perf_map.get((r.rate, r.rack + 1))
            if right_p is not None:
                n_vals.append(right_p)
            f18 = math.tanh((sum(n_vals) / len(n_vals)) / 2.0) if n_vals else 0.0

            # 19: digit_eb_lift（成熟済みラベル統計のみ）
            dg = r.rack % 10
            d_lift = self._digit_eb_sum[dg] / (self._digit_eb_cnt[dg] + _DIGIT_EB_PRIOR)
            f19 = math.tanh(d_lift / 0.08)

            # 20: machine_eb_lift（成熟済みラベル統計のみ、バラエティで自動発動）
            m_lift = self._mach_eb_sum.get(r.machine, 0.0) / (
                self._mach_eb_cnt.get(r.machine, 0.0) + _MACHINE_EB_PRIOR
            )
            f20 = math.tanh(m_lift / 0.10)

            feats.append(
                [
                    f0, f1, f2, f3, f4, f5, f6, f7, f8, f9,
                    f10, f11, f12, f13, f14, f15, f16, f17, f18, f19, f20,
                ]
            )
        return feats

    def _build_neighbor_perf_map(
        self, day_rows: list[_CleanRow]
    ) -> dict[tuple[str, int], float]:
        """当日全行から隣接台検索用の (rate, rack) -> perf_z マップを作成。"""
        by_rm: dict[tuple[str, str], list[_CleanRow]] = {}
        for r in day_rows:
            by_rm.setdefault((r.rate, r.machine), []).append(r)

        nbr_map: dict[tuple[str, int], float] = {}
        for rm, mrows in by_rm.items():
            net_scale, graph_scale, _, _, _, _, _ = self._get_scales(rm[0], rm[1], mrows)
            for r in mrows:
                pz = self._compute_perf_z(r, net_scale, graph_scale)
                if pz is not None:
                    nbr_map[(r.rate, r.rack)] = pz
        return nbr_map

    def _prepare_day_groups_for_training(self, feat_day_ord: int) -> None:
        """日 feat_day_ord の学習用グループ特徴量を確定保存する。

        前提:
        - self._hist_cursor <= feat_day_ord - 1
        - self._eb_cursor <= feat_day_ord - 7
        """
        rows = self._days.get(feat_day_ord)
        if not rows:
            return

        # 成熟済み EB 統計を feat_day_ord - 7（= (feat_day_ord + 1) - 8）まで進める
        self._advance_eb_to(feat_day_ord - (_MATURITY_LAG_LABEL - 1))

        nbr_map = self._build_neighbor_perf_map(rows)

        # (rate, machine) に分け、直近30日観測台数 <= 3 をバラエティへまとめる
        by_rm: dict[tuple[str, str], list[_CleanRow]] = {}
        for r in rows:
            by_rm.setdefault((r.rate, r.machine), []).append(r)

        variety_by_rate: dict[str, list[_CleanRow]] = {}
        normal_groups: list[tuple[str, list[_CleanRow]]] = []

        for (rate, machine), mrows in sorted(by_rm.items()):
            mb = self._mach_base.get((rate, machine))
            r_set = set(mb.rack_last_seen.keys()) if mb is not None else set()
            for r in mrows:
                r_set.add(r.rack)
            if len(r_set) <= 3:
                variety_by_rate.setdefault(rate, []).extend(mrows)
            else:
                normal_groups.append((machine, mrows))

        cached_groups: list[tuple[str, list[tuple[str, str, int, list[float]]]]] = []
        for g_name, g_rows in normal_groups:
            if len(g_rows) < 2:
                continue
            fmat = self._build_group_features(
                feat_day_ord, g_rows, is_variety=False, nbr_perf_map=nbr_map
            )
            entries = [
                (r.rate, r.machine, r.rack, fmat[i]) for i, r in enumerate(g_rows)
            ]
            cached_groups.append((g_name, entries))

        for _rate, v_rows in sorted(variety_by_rate.items()):
            if len(v_rows) < 2:
                continue
            fmat = self._build_group_features(
                feat_day_ord, v_rows, is_variety=True, nbr_perf_map=nbr_map
            )
            entries = [
                (r.rate, r.machine, r.rack, fmat[i]) for i, r in enumerate(v_rows)
            ]
            cached_groups.append((_VARIETY_GROUP, entries))

        if cached_groups:
            self._pending_day_groups[feat_day_ord] = cached_groups

    # -----------------------------------------------------------------------
    # 学習（十分統計量更新）・Prequential BMA 更新・重み算出
    # -----------------------------------------------------------------------

    def _solve_current_experts(
        self, ref_day_ord: int
    ) -> tuple[list[list[float]], dict[int, dict[str, list[float]]]]:
        """現在の十分統計量から全12エキスパートの重みを解く。"""
        # まず全ホライゾンの店舗統計量を ref_day_ord へ減衰整合
        for acc in self._store_acc:
            acc.apply_decay_to(ref_day_ord)

        store_weights: list[list[float]] = []
        # 同じ (h_idx, lam_store) の店舗重みをキャッシュ共有
        solved_store: dict[tuple[int, float], list[float]] = {}
        hier_weights: dict[int, dict[str, list[float]]] = {}

        # 直近 21日以内に学習データがあったアクティブ機種のみ階層重みを計算
        active_cutoff = ref_day_ord - 21
        active_groups = [
            g for g, last_o in self._mach_last_train_ord.items() if last_o >= active_cutoff
        ]

        for exp_idx, (_name, is_hier, h_idx, lam_s, lam_m, _prior_w) in enumerate(_EXPERTS):
            s_key = (h_idx, lam_s)
            w_store = solved_store.get(s_key)
            if w_store is None:
                acc = self._store_acc[h_idx]
                w_store = _solve_spd_ridge(acc.h_mat, acc.b_vec, lam_s)
                solved_store[s_key] = w_store
            store_weights.append(w_store)

            if is_hier:
                g_map: dict[str, list[float]] = {}
                for g_key in active_groups:
                    m_accs = self._mach_acc.get(g_key)
                    if not m_accs:
                        continue
                    m_acc = m_accs.get(h_idx)
                    if m_acc is None or m_acc.eff_groups < 0.25:
                        continue
                    m_acc.apply_decay_to(ref_day_ord)
                    w_g = _solve_spd_ridge(m_acc.h_mat, m_acc.b_vec, lam_m, prior_mean=w_store)
                    g_map[g_key] = w_g
                hier_weights[exp_idx] = g_map

        return store_weights, hier_weights

    def _compute_bma_probs(self) -> list[float]:
        """現在の BMA 累積対数尤度比スコアからエキスパート重み分布を算出する。"""
        logits: list[float] = []
        for idx, exp in enumerate(_EXPERTS):
            prior_w = exp[5]
            raw = math.log(prior_w) + _BMA_TEMP * self._bma_scores[idx]
            logits.append(raw)
        max_l = max(logits)
        # 数値安定かつ極端な 0 崩壊を防ぐソフトマックス
        exps = [math.exp(max(-12.0, l - max_l)) for l in logits]
        tot = sum(exps)
        if tot <= 0.0 or not math.isfinite(tot):
            return [1.0 / _NUM_EXPERTS] * _NUM_EXPERTS
        return [e / tot for e in exps]

    def _eval_prequential_day(
        self,
        feat_day_ord: int,
        eval_groups: list[tuple[str, int, list[tuple[list[float], int]]]],
    ) -> None:
        """直前までの成熟学習ペアのみから解いた重みを使って、日 feat_day_ord の
        真の out-of-sample グループ内ペアワイズ対数尤度比を計算し BMA を更新する。"""
        if self._last_store_weights is None or self._last_hier_weights is None:
            return

        store_ws = self._last_store_weights
        hier_ws = self._last_hier_weights

        # BMA 累積スコアの時間減衰
        if self._bma_last_ord is not None and feat_day_ord > self._bma_last_ord:
            f = math.pow(_BMA_DECAY, feat_day_ord - self._bma_last_ord)
            for i in range(_NUM_EXPERTS):
                self._bma_scores[i] *= f
        self._bma_last_ord = feat_day_ord

        exp_num = [0.0] * _NUM_EXPERTS
        w_den = 0.0
        log2 = math.log(2.0)

        for g_key, n_total, obs_items in eval_groups:
            m = len(obs_items)
            pos_feats = [f for f, y in obs_items if y == 1]
            neg_feats = [f for f, y in obs_items if y == 0]
            m_pos = len(pos_feats)
            m_neg = len(neg_feats)
            if m_pos == 0 or m_neg == 0:
                continue

            obs_ratio = float(m) / float(max(m, n_total))
            omega_g = (4.0 * m_pos * m_neg) / (m * (m + 2.0)) * obs_ratio
            w_den += omega_g

            inv_pairs = 1.0 / float(m_pos * m_neg)
            for exp_idx in range(_NUM_EXPERTS):
                h_map = hier_ws.get(exp_idx)
                w_vec = h_map.get(g_key, store_ws[exp_idx]) if h_map is not None else store_ws[exp_idx]

                pos_s = [_dot(w_vec, fv) for fv in pos_feats]
                neg_s = [_dot(w_vec, fv) for fv in neg_feats]
                ll_sum = 0.0
                for sp in pos_s:
                    for sn in neg_s:
                        diff = sp - sn
                        if diff > 6.0:
                            diff = 6.0
                        elif diff < -6.0:
                            diff = -6.0
                        ll_sum += log2 - _log1pexp(-diff)
                exp_num[exp_idx] += omega_g * (ll_sum * inv_pairs)

        if w_den > 0.0:
            for exp_idx in range(_NUM_EXPERTS):
                self._bma_scores[exp_idx] += exp_num[exp_idx] / w_den

    def _train_on_pair_day(self, feat_day_ord: int) -> None:
        """成熟したペア (feat_day_ord, feat_day_ord + 1) で Prequential BMA 評価と
        十分統計量更新を実行する。"""
        groups_cached = self._pending_day_groups.pop(feat_day_ord, None)
        next_rows = self._days.get(feat_day_ord + 1)
        if not groups_cached or not next_rows:
            return

        # 翌暦日の正解ラベルマップ: (rate, machine, rack) -> outcome (0/1)
        label_map: dict[tuple[str, str, int], int] = {}
        for r in next_rows:
            if r.outcome_val is not None:
                label_map[(r.rate, r.machine, r.rack)] = r.outcome_val
        if not label_map:
            return

        # グループごとに観測済み (feat, y) を収集
        eval_groups: list[tuple[str, int, list[tuple[list[float], int]]]] = []
        for g_key, entries in groups_cached:
            n_total = len(entries)
            obs_items: list[tuple[list[float], int]] = []
            for rate, machine, rack, fv in entries:
                y = label_map.get((rate, machine, rack))
                if y is not None:
                    obs_items.append((fv, y))
            if len(obs_items) >= 2:
                eval_groups.append((g_key, n_total, obs_items))

        if not eval_groups:
            return

        # ステップ1: まず直前までのモデルで真の out-of-sample Prequential BMA 評価
        self._eval_prequential_day(feat_day_ord, eval_groups)

        # ステップ2: 日次十分統計量 (H_d, b_d) と機種別 (H_{d,g}, b_{d,g}) を計算・反映
        h_day = [[0.0] * _NUM_FEATURES for _ in range(_NUM_FEATURES)]
        b_day = [0.0] * _NUM_FEATURES
        day_eff_g = 0.0
        day_obs_cnt = 0

        for g_key, n_total, obs_items in eval_groups:
            m = len(obs_items)
            m_pos = sum(y for _fv, y in obs_items)
            m_neg = m - m_pos
            if m_pos == 0 or m_neg == 0:
                continue

            r_g = float(m_pos) / float(m)
            var_y = r_g * (1.0 - r_g)
            obs_ratio = float(m) / float(max(m, n_total))
            # 飽和型グループ重み（組等重みと統計効率の両立・自然対数尤度スケール維持）
            c_g = (8.0 / (m + 4.0)) * obs_ratio
            scale_h = c_g * var_y

            # グループ内平均特徴量 x_bar
            x_bar = [0.0] * _NUM_FEATURES
            inv_m = 1.0 / float(m)
            for fv, _y in obs_items:
                for i in range(_NUM_FEATURES):
                    x_bar[i] += fv[i]
            for i in range(_NUM_FEATURES):
                x_bar[i] *= inv_m

            h_g = [[0.0] * _NUM_FEATURES for _ in range(_NUM_FEATURES)]
            b_g = [0.0] * _NUM_FEATURES
            for fv, y in obs_items:
                dx = [fv[i] - x_bar[i] for i in range(_NUM_FEATURES)]
                dy_c = c_g * (float(y) - r_g)
                for i in range(_NUM_FEATURES):
                    dxi = dx[i]
                    b_g[i] += dy_c * dxi
                    if dxi != 0.0:
                        row_hg = h_g[i]
                        s_dxi = scale_h * dxi
                        for j in range(i, _NUM_FEATURES):
                            row_hg[j] += s_dxi * dx[j]

            # 対称行列の下三角を補完しつつ日次合算
            for i in range(_NUM_FEATURES):
                row_hg = h_g[i]
                row_hd = h_day[i]
                b_day[i] += b_g[i]
                for j in range(i, _NUM_FEATURES):
                    v = row_hg[j]
                    h_g[j][i] = v
                    row_hd[j] += v
                    if i != j:
                        h_day[j][i] += v

            eff_g_val = c_g * float(m) * var_y
            day_eff_g += eff_g_val
            day_obs_cnt += m

            # 機種別十分統計量（Hierarchical が使うホライゾン 1, 2 のみ保持で高速化）
            m_accs = self._mach_acc.get(g_key)
            if m_accs is None:
                m_accs = {
                    1: _QuadraticAccumulator(_HORIZON_DECAYS[1]),
                    2: _QuadraticAccumulator(_HORIZON_DECAYS[2]),
                }
                self._mach_acc[g_key] = m_accs
            m_accs[1].add_stats(feat_day_ord, h_g, b_g, eff_g_val)
            m_accs[2].add_stats(feat_day_ord, h_g, b_g, eff_g_val)
            self._mach_last_train_ord[g_key] = feat_day_ord

        if day_obs_cnt > 0:
            for acc in self._store_acc:
                acc.add_stats(feat_day_ord, h_day, b_day, day_eff_g)
            self._trained_days += 1
            self._trained_obs += day_obs_cnt

            # 最新重みを更新（次回の out-of-sample Prequential 評価および最新推論に利用）
            if self._trained_days >= _MIN_TRAIN_DAYS and self._trained_obs >= _MIN_TRAIN_OBS:
                sw, hw = self._solve_current_experts(feat_day_ord)
                self._last_store_weights = sw
                self._last_hier_weights = hw

    # -----------------------------------------------------------------------
    # 対象日 target への厳格な状態進行（未来リーク完全遮断）
    # -----------------------------------------------------------------------

    def _sync_to_target(self, target_ord: int) -> None:
        """target_ord の予測に必要な全状態を厳格な時間上限で同期する。

        厳守される上限:
        - 過去履歴統計 self._hist_cursor <= target_ord - 2
          （特徴量日 d = target_ord - 1 の計算直前のクリーン状態）
        - 成熟済み EB ラベル統計 self._eb_cursor <= target_ord - 8
        - 成熟済み学習ペア self._train_cursor <= target_ord - 9（ラベル日 <= target_ord - 8）
        """
        if self._cached_target_ord == target_ord:
            return

        feat_limit_hist = target_ord - 2
        train_feat_limit = target_ord - _MATURITY_LAG_FEAT
        eb_label_limit = target_ord - _MATURITY_LAG_LABEL

        # 過去日に遡る呼び出しが来た場合は安全のためゼロから再構築
        if (
            (self._hist_cursor is not None and self._hist_cursor > feat_limit_hist)
            or (self._train_cursor is not None and self._train_cursor > train_feat_limit)
            or (self._eb_cursor is not None and self._eb_cursor > eb_label_limit)
        ):
            self._init_runtime_state()

        sorted_days = self._get_sorted_days()

        # 1. 過去履歴カーソルを target_ord - 2 まで進める。
        #    その途中で各日 d を履歴追記する「直前」に、日 d の学習用特徴量キャッシュを確定させる。
        for d_ord in sorted_days:
            if d_ord > feat_limit_hist:
                break
            if self._hist_cursor is not None and d_ord <= self._hist_cursor:
                continue
            # 日 d_ord の学習用特徴量（<= d_ord の観測と <= d_ord - 7 の EB 統計のみ使用）
            self._prepare_day_groups_for_training(d_ord)
            # 日 d_ord の観測を履歴・ベース統計へ追記（d_ord + 1 以降の特徴量に使う）
            self._update_history_with_day(d_ord)
            self._hist_cursor = d_ord

        # 2. 成熟済み学習ペアを train_feat_limit (= target_ord - 9) まで進める
        for s_ord in sorted_days:
            if s_ord > train_feat_limit:
                break
            if self._train_cursor is not None and s_ord <= self._train_cursor:
                continue
            self._train_on_pair_day(s_ord)
            self._train_cursor = s_ord

        # 3. target_ord の特徴量用に EB 統計を target_ord - 8 まで進める
        self._advance_eb_to(eb_label_limit)

        # 4. target_ord 用のエキスパート重みと BMA 統合確率をキャッシュ
        self._cached_target_ord = target_ord
        self._cached_nbr_map = None
        if self._last_store_weights is not None and self._last_hier_weights is not None:
            self._cached_store_weights = self._last_store_weights
            self._cached_hier_weights = self._last_hier_weights
            self._cached_bma_probs = self._compute_bma_probs()
        else:
            self._cached_store_weights = None
            self._cached_hier_weights = None
            self._cached_bma_probs = None

    # -----------------------------------------------------------------------
    # 公開インターフェース: rank
    # -----------------------------------------------------------------------

    def rank(
        self,
        target: str,
        group_name: str,
        pool: list[dict[str, Any]],
        *,
        is_variety: bool = False,
    ) -> list[dict[str, Any]] | None:
        """対象日 target の候補母集団 pool（day == target - 1）を並べ替えて返す。"""
        if not pool:
            return None

        target_ord = _day_to_ord(target)
        feat_day_ord = target_ord - 1

        # 厳格な時間上限で状態を同期
        self._sync_to_target(target_ord)

        if (
            self._cached_store_weights is None
            or self._cached_hier_weights is None
            or self._cached_bma_probs is None
        ):
            return None

        # 入力順不変を 100% 保証するため、処理前に決定論的タイブレークキーでソート
        indexed_pool = sorted(
            [(_tiebreak_key(r), idx, r) for idx, r in enumerate(pool)],
            key=lambda t: (t[0], t[1]),
        )
        sorted_orig = [t[2] for t in indexed_pool]
        clean_pool = [_CleanRow(r) for r in sorted_orig]

        # 隣接台検索用マップ（target - 1 の店舗全行から日次1回だけ構築、未ingestなら pool 自身）
        day_rows = self._days.get(feat_day_ord)
        if day_rows:
            if self._cached_nbr_map is None:
                self._cached_nbr_map = self._build_neighbor_perf_map(day_rows)
            nbr_map = self._cached_nbr_map
        else:
            nbr_map = self._build_neighbor_perf_map(clean_pool)

        # 21次元特徴量を抽出（学習時と完全同一関数）
        feats = self._build_group_features(
            feat_day_ord,
            clean_pool,
            is_variety=is_variety,
            nbr_perf_map=nbr_map,
        )

        # 当該グループに対する BMA 統合重みベクトルを構成
        if is_variety:
            g_key = _VARIETY_GROUP
        else:
            machines_in_pool = {r.machine for r in clean_pool}
            g_key = next(iter(machines_in_pool)) if len(machines_in_pool) == 1 else str(group_name)
        w_final = [0.0] * _NUM_FEATURES
        store_ws = self._cached_store_weights
        hier_ws = self._cached_hier_weights
        bma_p = self._cached_bma_probs

        for exp_idx in range(_NUM_EXPERTS):
            p_m = bma_p[exp_idx]
            if p_m <= 0.0:
                continue
            h_map = hier_ws.get(exp_idx)
            w_m = h_map.get(g_key, store_ws[exp_idx]) if h_map is not None else store_ws[exp_idx]
            for j in range(_NUM_FEATURES):
                w_final[j] += p_m * w_m[j]

        # 重みが実質ゼロ（学習シグナル完全無）の場合は None
        if max(abs(v) for v in w_final) < 1e-12:
            return None

        # スコア計算・降順ソート（同点時は決定論的タイブレークキー昇順）
        scored: list[tuple[float, tuple[str, str, str, int], int, dict[str, Any]]] = []
        for idx, orig_row in enumerate(sorted_orig):
            sc = _dot(w_final, feats[idx])
            sc_rounded = round(sc, 12) if math.isfinite(sc) else 0.0
            scored.append((-sc_rounded, indexed_pool[idx][0], idx, orig_row))

        scored.sort(key=lambda t: (t[0], t[1], t[2]))
        return [t[3] for t in scored]
