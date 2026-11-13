"""サイトセブンの出玉推移一覧のグラフ画像から、推定差枚を読む（2026-11-07）。

方法は ../outputs/site777-net-astra-20261107/報告.md（Codex・Astra の分析）のとおり。
260×226 の画像で、+5,000 の線が y=15、ゼロ線が y=111、-5,000 の線が y=207。
推定差枚 = (111 - 終点の y) × 10000 / 192。終点は黄色い線の一番右の列の、黄色の画素の y の中央値。

- 推定差枚として保存する（net_medals には入れない）。終点から換算した値を1枚単位に丸める。
- 目盛りの文字（+5,000・-5,000）が確かめた形と同じ画像だけを読む。違う大きさ・目盛りは推測で通さない。
- 上下の端に触れた（見切れ）台は、終点が目盛りの中に戻っていれば終点から読み、上の端のまま終わったらMYを差枚にする
  （2026-11-13。それまでは推定なしで、大勝ちの台ばかり店の合計から抜けていた）。下の端のまま終わった台は-5,000枚、
  右端に届いた台は右端の値、色の閾値で終点が5画素（約260枚）まで動く台は基準の値、目盛りの文字に線が重なった台は
  重なっていない画素で文字を確かめて読む（同日、利用者「四つとも治して」）。それ以外の、線が途切れた、終点が分かれた、色の閾値で終点が動く、
  線が短い（10画素未満）ときは推定を付けない（保留）。理由は status で返す。
- 読み取りの幅が0をまたぐ台は sure=False（画面では「※」。勝ち負けを言い切らない）。
- BB/RB は使わない。MY は上の端のまま終わった台だけに使う。

記録に付ける形はアナスロの推定差枚と同じ {'value', 'sure', 'method'}（method だけ違う）。
"""
from __future__ import annotations

import hashlib
import math
from io import BytesIO

LEGACY_METHOD = 'site777-axis-pixels-v1'
METHOD = 'site777-axis-pixels-v2'
SIZE = (260, 226)
# 確かめた 105 枚の画像の「5,000」「-5,000」の文字部分の白い画素の形（汎用の文字読み取りではない）。
TOP_LABEL = '3e266372af51f73d2b43c2b5bc413c6ca12c0419b819533ef0774b72e6448e3f'
BOTTOM_LABEL = 'a6114ee976d48f84c5a5fe685e0591771f161a0d6ce1f9a47d10818f92f84956'
# 上の2つのハッシュと同じ文字の形（12×37 画素のビット）。黄色い線が文字に重なった画像は、重なっていない画素で照らす
# （2026-11-13 利用者「四つとも治して」。大勝ちの台の線が「5,000」に重なり、目盛りの確認で落ちていた）。
TOP_MASK = '000000000000000000003c0c30c001000000000c049248000824924000412492000200000000e230c3000020000000000000000000000000'
BOTTOM_MASK = '000000000000000000003c0c30c001000000000c049248000824924070412492000200000000e230c3000020000000000000000000000000'
LABEL_BOXES = ((slice(9, 21), slice(16, 53), TOP_MASK, TOP_LABEL), (slice(201, 213), slice(16, 53), BOTTOM_MASK, BOTTOM_LABEL))
# 終点が色の閾値で動いてよい幅（画素）。2.5画素（約130枚）で落としていた台を、5画素（約260枚）まで読む（2026-11-13）。
UNSTABLE_PIXELS = 5
GRID_Y = (15, 35, 54, 73, 92, 111, 131, 150, 169, 188, 207)
TOP, ZERO, BOTTOM = 15.0, 111.0, 207.0
SCALE = 10000.0 / (BOTTOM - TOP)
SHORT_PIXELS = 10


def valid(value) -> bool:
    """記録に付いたサイトセブンの推定差枚の形（PC・Android・閲覧ページ・共有カレンダーで同じ検査）。"""
    return (isinstance(value, dict) and set(value) == {'value', 'sure', 'method'} and type(value['value']) is int
            and abs(value['value']) <= 1000000 and type(value['sure']) is bool
            and (value['method'] == METHOD or (value['method'] == LEGACY_METHOD and value['value'] % 50 == 0)))


def _yellow(a, threshold=130, blue_max=100):
    mask = (a[:, :, 0] >= threshold) & (a[:, :, 1] >= threshold) & (a[:, :, 2] < blue_max)
    mask &= (a[:, :, 0] - a[:, :, 2] >= 40) & (a[:, :, 1] - a[:, :, 2] >= 40)
    mask[:8] = False
    mask[212:] = False
    mask[:, :8] = False
    mask[:, 245:] = False
    return mask


def _trace(mask):
    import numpy as np
    points = []
    for x in range(8, 245):
        ys = np.flatnonzero(mask[:, x])
        if len(ys):
            points.append((int(x), float(np.median(ys))))
    return points


def _label_ok(a, white):
    """目盛りの文字（+5,000・-5,000）が確かめた形か。ふつうは白い画素の形が完全に一致する。黄色い線が文字に重なった
    画像は、線（と縁の1画素）を除いた画素で一致し、文字の6割以上が見えていればよい。"""
    import numpy as np
    yellow = _yellow(a, 100, 120)
    for rows, cols, bits, digest in LABEL_BOXES:
        seen = white[rows, cols]
        if hashlib.sha256(seen.tobytes()).hexdigest() == digest:
            continue
        expected = np.unpackbits(np.frombuffer(bytes.fromhex(bits), dtype=np.uint8))[:12 * 37].reshape(12, 37).astype(bool)
        line = yellow[rows.start - 1:rows.stop + 1, cols.start - 1:cols.stop + 1]
        if not line.any():
            return False
        # 縁の1画素まで広げる（線の縁の色が混ざった画素は比べない）。
        cover = np.zeros_like(seen)
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                cover |= line[dy:dy + 12, dx:dx + 37]
        visible = ~cover
        if (seen[visible] != expected[visible]).sum() > 2 or (expected & visible).sum() < .6 * expected.sum():
            return False
    return True


def _round_medals(value):
    return int(math.copysign(math.floor(abs(value) + .5), value))


def analyze(raw: bytes) -> dict:
    """画像（PNGのバイト列）を読み、{'status', 'reason', ...} を返す。推定が付くのは status='candidate' だけ。"""
    import numpy as np
    from PIL import Image

    result = {'method': METHOD, 'status': 'unavailable', 'reason': None, 'estimate': None}

    def reject(reason, **extra):
        return {**result, **extra, 'reason': reason}

    try:
        image = Image.open(BytesIO(raw))
        image.load()
    except (OSError, ValueError):
        return reject('image_unreadable')
    if image.size != SIZE:
        return reject('unsupported_size')
    a = np.asarray(image.convert('RGB')).astype('int16')
    white = (a.min(2) >= 185) & (a.max(2) - a.min(2) <= 15)
    if not _label_ok(a, white):
        return reject('axis_labels_unknown')
    if list(np.flatnonzero(white[:, 60:244].sum(1) >= 160)) != [111]:
        return reject('zero_line_unknown')
    gray = (a.min(2) >= 60) & (a.max(2) <= 68) & (a.max(2) - a.min(2) <= 3)
    grid = set(map(int, np.flatnonzero(gray[:, 60:244].sum(1) >= 100)))
    # 線が途中の目盛りを隠すことはある。上下の端は必須、決まった位置の線が8本以上。
    if not {15, 207} <= grid or len(grid) < 8 or not grid <= set(GRID_Y) - {111}:
        return reject('grid_unknown')
    mask = _yellow(a)
    points = _trace(mask)
    if not points:
        return reject('curve_missing')
    if len(points) < 3 or points[0][0] > 14:
        return reject('curve_start_unknown')
    rows = np.nonzero(mask)[0]
    # 上下の端（±5,000枚の目盛り）に触れた（見切れ）台（2026-11-13 利用者「両方直す」「myそのままでいい」）：
    # 終点が端から離れて目盛りの中に戻っていれば、ふつうどおり終点から読む（縮尺は目盛りの文字・線で確かめ済み）。
    # 上の端のまま終わった台は 'clipped_top' を返し、net_estimate_from が MY（最高出玉）をそのまま差枚にする
    # （MYはグラフの最高点より中央で約500枚大きく、終点は最高点より中央で約290枚下がるので、約800枚多めになりうる）。
    # 下の端のまま終わった台は 'clipped_bottom' を返し、-5,000枚を差枚にする（それ以上の負けは分からない。
    # 下側にはMYのような値が無い。2026-11-13 利用者「四つとも治して」）。
    touched = rows.min() <= TOP + 2 or rows.max() >= BOTTOM - 2
    near_edge = lambda y: y <= TOP + 4 or y >= BOTTOM - 4
    # 白いゼロ線が黄色い線の上に描かれ、y=111〜112 を隠すことがある。ゼロ付近の2列以内の欠けだけ許す。
    # 見切れた台は、端の外を通った区間が描かれないことがあるので、両側が端に接した欠けも許す。
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        gap = x1 - x0
        if (gap > 1 and not (gap <= 3 and abs(y0 - ZERO) <= 4 and abs(y1 - ZERO) <= 4)
                and not (touched and near_edge(y0) and near_edge(y1))):
            return reject('curve_gap')
    # 右端に届いた台は、右端の値を差枚にする（その先は描かれないが、1日の終わりに近い。2026-11-13）。
    right_edge = points[-1][0] >= 243
    if touched and near_edge(points[-1][1]):
        kind = 'clipped_top' if points[-1][1] <= TOP + 4 else 'clipped_bottom'
        return {**result, 'status': kind, 'reason': 'boundary_contact', 'endpoint': list(points[-1])}
    for x, _ in points[-2:]:
        ys = np.flatnonzero(mask[:, x])
        for first, last in zip(ys, ys[1:]):
            if last - first > 2 and not (first == 110 and last <= 114):
                return reject('multiple_endpoint_traces')
    variants, envelope = [], []
    for threshold, blue_max in ((100, 120), (130, 100), (180, 100), (210, 100)):
        m = _yellow(a, threshold, blue_max)
        ps = _trace(m)
        # 細い色の閾値では終点の列が数画素ずれることがある（線の先が細い）。3列までは同じ終点とみる（2026-11-13）。
        if not ps or abs(ps[-1][0] - points[-1][0]) > 3:
            return reject('endpoint_unstable')
        variants.append((ZERO - ps[-1][1]) * SCALE)
        xe = ps[-1][0]
        ys = np.nonzero(m[:, max(8, xe - 1):xe + 1])[0]
        envelope += [float(ys.min()), float(ys.max())]
    if max(variants) - min(variants) > UNSTABLE_PIXELS * SCALE:
        return reject('endpoint_unstable')
    net = (ZERO - points[-1][1]) * SCALE
    # 画像の読み取りの幅（実際の差枚に対する信頼区間ではない）。終点の上下1画素、ゼロ線±0.5画素、目盛り幅±1画素、
    # 色の閾値で動いた終点。この幅が0をまたぐ台は「※」（勝ち負けを言い切らない）。
    ends = (min(envelope) - 1, max(envelope) + 1)
    options = [(z - y) * s for z in (ZERO - .5, ZERO + .5) for y in ends for s in (10000 / 193, 10000 / 191)]
    low = math.floor(min(min(options), min(variants), net - 2 * SCALE) / 50) * 50
    high = math.ceil(max(max(options), max(variants), net + 2 * SCALE) / 50) * 50
    short = points[-1][0] - points[0][0] < SHORT_PIXELS
    return {**result, 'status': 'review_short' if short else 'candidate',
            'reason': 'short_curve' if short else 'axis_and_endpoint_confirmed',
            'estimate': _round_medals(net), 'estimate_unrounded': net, 'interval': [low, high],
            'sign_uncertain': low <= 0 <= high, 'endpoint': [points[-1][0], points[-1][1]],
            'right_edge': right_edge, 'spread': round(max(variants) - min(variants))}


def net_estimate_from(result: dict, my=None):
    """analyze の結果から、記録に付ける推定差枚。付けられなければ None（保留・判定不能）。
    上の端のまま終わった台（clipped_top）は、MY（表の最高出玉）が5,000枚以上ならMYをそのまま差枚にする
    （2026-11-13 利用者「myそのままでいい」）。形は同じなので、PC・Android・閲覧ページ・同期の確認はそのまま通る。
    見分けるときは「value が MY と同じで5,000以上」。"""
    if result['status'] == 'clipped_top':
        if type(my) is int and my >= 5000:
            return {'value': my, 'sure': True, 'method': METHOD}
        return None
    if result['status'] == 'clipped_bottom':
        # 下の端のまま終わった台は -5,000枚（それ以上の負けは分からない。2026-11-13）。見分けるときは value が -5000。
        return {'value': -5000, 'sure': True, 'method': METHOD}
    if result['status'] != 'candidate':
        return None
    return {'value': result['estimate'], 'sure': not result['sign_uncertain'], 'method': METHOD}


def net_estimate(raw: bytes, my=None):
    """記録に付ける推定差枚。付けられなければ None（保留・判定不能）。my は表の最高出玉（見切れの台だけ使う）。"""
    return net_estimate_from(analyze(raw), my)
