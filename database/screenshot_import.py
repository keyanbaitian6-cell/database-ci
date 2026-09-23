"""Local screenshot OCR and validation helpers for database."""
from __future__ import annotations

import base64
import io
import re
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageGrab

FIELDS = ('rack', 'bb', 'rb', 'games', 'combined', 'previous_start', 'max_hold')
ALIASES = {
    'rack': ('台番号', '台番'),
    'bb': ('BB',),
    'rb': ('RB',),
    'games': ('総回転数', '回転数', 'G数'),
    'combined': ('合成確率', '合成'),
    'previous_start': ('前日最終スタート', '前日最終'),
    'max_hold': ('最大持玉', '最大持ち玉'),
}
_engine = None


def _ocr_engine():
    global _engine
    if _engine is None:
        from rapidocr import RapidOCR
        _engine = RapidOCR()
    return _engine


def _tokens(image):
    result = _ocr_engine()(image)
    if not result or not result.txts:
        return []
    tokens = []
    for box, text, confidence in zip(result.boxes, result.txts, result.scores, strict=True):
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        tokens.append(dict(text=str(text).strip(), confidence=float(confidence),
                           x0=min(xs), x1=max(xs), y0=min(ys), y1=max(ys),
                           cx=sum(xs) / len(xs), cy=sum(ys) / len(ys)))
    return tokens


def _normal(text):
    table = str.maketrans('０１２３４５６７８９', '0123456789')
    return re.sub(r'[\s・:_：]', '', text.translate(table)).upper()


def _integer(text):
    value = _normal(text).replace(',', '').replace('，', '')
    if not re.fullmatch(r'\d{1,7}', value):
        return None
    return int(value)


def _trailing_integer(text):
    """Read a number even when OCR joins it to the preceding Japanese label."""
    value = _integer(text)
    if value is not None:
        return value
    match = re.search(r'(\d{1,7})$', _normal(text).replace(',', '').replace('，', ''))
    return int(match.group(1)) if match else None


def graph_stats_from_tokens(tokens):
    """Read the current games/bonus/max-hold values in a graph tooltip."""
    labels = {str(token['text']).upper(): token for token in tokens
              if str(token['text']).upper() in ('BIG', 'REG', 'ART')}
    if 'BIG' not in labels or 'REG' not in labels:
        return None
    numbers = [dict(token, value=_trailing_integer(token['text'])) for token in tokens
               if _trailing_integer(token['text']) is not None]

    def value_on_line(label):
        anchor = labels[label]
        choices = [token for token in numbers
                   if token['cx'] > anchor['x1'] and abs(token['cy'] - anchor['cy']) < 12]
        return (min(choices, key=lambda token: abs(token['cy'] - anchor['cy']))['value']
                if choices else None)

    right_of_labels = labels['BIG']['x1']
    big_y = labels['BIG']['cy']
    label_bottom = max(token['cy'] for token in labels.values())
    games = [token for token in numbers
             if token['cx'] > right_of_labels and 5 < token['cy'] < big_y - 3]
    maximums = [token for token in numbers
                if label_bottom + 3 < token['cy'] < label_bottom + 30]
    result = {
        'games': max(games, key=lambda token: token['cy'])['value'] if games else None,
        'bb': value_on_line('BIG'),
        'rb': value_on_line('REG'),
        'max_hold': (min(maximums, key=lambda token: abs(token['cy'] - (label_bottom + 15)))['value']
                     if maximums else None),
    }
    return result if all(result[field] is not None for field in ('games', 'bb', 'rb')) else None


def parse_graph_stats(path):
    """Read the latest displayed counters from a full-page graph capture."""
    image, _offset, _baseline = graph_view(path)
    return graph_stats_from_tokens(_tokens(image))


def find_headers(tokens):
    candidates = []
    for token in tokens:
        value = _normal(token['text'])
        for field, aliases in ALIASES.items():
            exact = any(_normal(alias) == value for alias in aliases)
            # RapidOCR sometimes replaces the first kanji of 総回転数 with a
            # symbol while reading the small site header (for example #回転数).
            games_suffix = field == 'games' and value.endswith('回転数')
            if exact or games_suffix:
                candidates.append((field, token))
    best = None
    for _, anchor in candidates:
        height = max(10, anchor['y1'] - anchor['y0'])
        same_line = [(field, token) for field, token in candidates
                     if abs(token['cy'] - anchor['cy']) <= height * 1.5]
        selected = {}
        for field, token in same_line:
            if field not in selected or token['confidence'] > selected[field]['confidence']:
                selected[field] = token
        if best is None or len(selected) > len(best):
            best = selected
    required = {'rack', 'bb', 'rb', 'games', 'combined', 'previous_start', 'max_hold'}
    if not best or not required.issubset(best):
        missing = '、'.join(ALIASES[x][0] for x in FIELDS if not best or x not in best)
        raise ValueError('一覧の見出しを読み取れません。見出しを含めて撮影してください。未検出：' + missing)
    return best


def parse_table_image(path):
    """Read the known seven-column machine table and return editable candidates."""
    image = Image.open(path).convert('RGB')
    headers = find_headers(_tokens(image))
    ordered = sorted(((field, headers[field]['cx']) for field in FIELDS), key=lambda x: x[1])
    if [field for field, _ in ordered] != list(FIELDS):
        raise ValueError('一覧の列順が想定と違います。保存しません。')
    centers = [x for _, x in ordered]
    bounds = [max(0, centers[0] - (centers[1] - centers[0]) / 2)]
    bounds += [(a + b) / 2 for a, b in zip(centers, centers[1:])]
    bounds += [min(image.width, centers[-1] + (centers[-1] - centers[-2]) / 2)]
    data_top = int(max(t['y1'] for t in headers.values()) + 2)

    columns = {}
    for index, field in enumerate(FIELDS):
        crop_left, crop_right = int(bounds[index]), int(bounds[index + 1])
        crop = image.crop((crop_left, data_top, crop_right, image.height))
        values = []
        for token in _tokens(crop):
            number = _integer(token['text'])
            if number is None:
                continue
            values.append(dict(value=number, confidence=token['confidence'],
                               cy=token['cy'] + data_top,
                               height=max(8, token['y1'] - token['y0'])))
        columns[field] = values

    rows = []
    for rack_token in columns['rack']:
        rack = rack_token['value']
        if not 1 <= rack <= 9999:
            continue
        row = {'rack': rack, 'confidence': rack_token['confidence']}
        matched = 0
        for field in ('bb', 'rb', 'games', 'previous_start', 'max_hold'):
            choices = sorted(columns[field], key=lambda token: abs(token['cy'] - rack_token['cy']))
            tolerance = max(18, rack_token['height'] * 1.3)
            token = choices[0] if choices and abs(choices[0]['cy'] - rack_token['cy']) <= tolerance else None
            row[field] = token['value'] if token else None
            if token:
                row['confidence'] = min(row['confidence'], token['confidence'])
                matched += 1
        if matched >= 2:
            rows.append(row)
    unique = {}
    for row in rows:
        current = unique.get(row['rack'])
        if current is None or row['confidence'] > current['confidence']:
            unique[row['rack']] = row
    return [unique[rack] for rack in sorted(unique)]


def save_input_image(image_or_path, folder, prefix):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / f'{prefix}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.png'
    if isinstance(image_or_path, Image.Image):
        image_or_path.convert('RGB').save(output)
    else:
        with Image.open(image_or_path) as source:
            source.convert('RGB').save(output)
    return output


# 保存する画像を小さくするための設定。グラフは線と目盛りだけなので、画素を半分・
# 色数を32色にしても見た目はほとんど変わらず、容量は約1/6になる（実データで計測）。
PREVIEW_PIXEL_SCALE = 2
PREVIEW_COLORS = 32


def encode_preview_image(image, max_width=420):
    """Downscale a graph image for storage next to its saved record.

    Used for both the screenshot flow (crop of the captured picture) and the
    browser flow (a rendered curve), so history can always show an actual
    small graph for anything saved from now on.

    返す幅・高さは「座標の大きさ」（4点や曲線と同じ座標系）で、画像の画素数では
    ない。画素は ``PREVIEW_PIXEL_SCALE`` 分の1にして保存し、表示側はこの幅・高さに
    引き伸ばして描くので、点の位置はずれない。
    """
    image = image.convert('RGB')
    if image.width > max_width:
        ratio = max_width / image.width
        size = (max_width, max(1, round(image.height * ratio)))
        image = image.resize(size, Image.Resampling.LANCZOS)
    width, height = image.width, image.height
    stored = image.resize((max(1, width // PREVIEW_PIXEL_SCALE), max(1, height // PREVIEW_PIXEL_SCALE)),
                          Image.Resampling.LANCZOS)
    stored = stored.convert('P', palette=Image.Palette.ADAPTIVE, colors=PREVIEW_COLORS)
    buffer = io.BytesIO()
    stored.save(buffer, format='PNG', optimize=True)
    return base64.b64encode(buffer.getvalue()).decode('ascii'), width, height


def clipboard_image():
    value = ImageGrab.grabclipboard()
    if isinstance(value, Image.Image):
        return value
    if isinstance(value, list) and value:
        return Image.open(value[0]).copy()
    raise ValueError('クリップボードに画像がありません。スクリーンショットをコピーしてください。')


def graph_view(path):
    """Crop around the longest red zero line when it can be found."""
    import numpy as np
    image = Image.open(path).convert('RGB')
    pixels = np.asarray(image)
    red = (pixels[:, :, 0] > 160) & (pixels[:, :, 1] < 100) & (pixels[:, :, 2] < 100)
    counts = red.sum(axis=1)
    # The zero line is one thin, isolated horizontal red line. Its visible
    # length changes with the grey filled graph, so distinguish it from thick
    # red buttons and bars by comparing the rows immediately above and below.
    neighbours = np.maximum(np.roll(counts, 1), np.roll(counts, -1))
    isolated = counts - neighbours
    enough_red = counts > max(40, image.width * .02)
    rows = [int(y) for y in np.where(enough_red & (isolated > counts * .5))[0]]
    if not rows:
        return image, (0, 0), None
    baseline = max(rows, key=lambda y: counts[y])
    xs = np.where(red[baseline])[0]
    red_left, red_right = int(xs.min()), int(xs.max())

    # Find the dark vertical borders of the graph panel on the zero-line row.
    # This restores the left side even when a negative fill hides that part of
    # the red line.
    dark_xs = np.where(pixels[baseline].max(axis=1) < 180)[0]
    runs = []
    if len(dark_xs):
        gaps = np.where(np.diff(dark_xs) > 1)[0]
        starts = np.r_[0, gaps + 1]
        ends = np.r_[gaps, len(dark_xs) - 1]
        runs = [(int(dark_xs[start]), int(dark_xs[end]))
                for start, end in zip(starts, ends)
                if dark_xs[end] - dark_xs[start] + 1 >= 4]
    left_runs = [run for run in runs if run[1] < red_left]
    right_runs = [run for run in runs if run[0] > red_right]
    if left_runs and right_runs:
        left = max(left_runs, key=lambda run: run[1])[0]
        right = min(right_runs, key=lambda run: run[0])[1]
    else:
        visible_width = max(1, red_right - red_left)
        left = max(0, int(red_left - visible_width * .25))
        right = min(image.width - 1, int(red_right + visible_width * .25))
    width = max(1, right - left)
    box = (max(0, left), max(0, int(baseline - width * .32)),
           min(image.width, right + 1), min(image.height, int(baseline + width * .32)))
    return image.crop(box), (box[0], box[1]), baseline - box[1]


def graph_auto_points(image, baseline):
    """Estimate baseline, highest point, lowest point, and endpoint."""
    import numpy as np

    if baseline is None:
        return None
    pixels = np.asarray(image.convert('RGB'))
    height, width = pixels.shape[:2]
    baseline = int(round(baseline))
    if not 0 <= baseline < height:
        return None

    luminance = pixels.mean(axis=2)
    neutral = pixels.max(axis=2) - pixels.min(axis=2) < 25
    fill = (luminance > 18) & neutral
    # Join the grey area across the one-pixel red baseline.
    fill[max(0, baseline - 1):min(height, baseline + 2), :] = True

    x_start, x_stop = max(20, int(width * .03)), min(width - 20, int(width * .97))
    y_start = max(30, int(baseline - width * .28))
    y_stop = min(height - 20, int(baseline + width * .27))
    required_bottom = min(y_stop - 1, int(baseline + max(35, width * .11)))
    candidates = []
    for x in range(x_start, x_stop):
        ys = np.where(fill[y_start:y_stop, x])[0] + y_start
        if not len(ys):
            continue
        gaps = np.where(np.diff(ys) > 1)[0]
        starts = np.r_[0, gaps + 1]
        ends = np.r_[gaps, len(ys) - 1]
        runs = [(int(ys[start]), int(ys[end])) for start, end in zip(starts, ends)
                if ys[end] >= required_bottom and ys[end] - ys[start] >= 1]
        if not runs:
            continue
        # Prefer the long filled graph column over a short time tick lower in
        # the same column.
        start, end = max(runs, key=lambda run: (run[1] - run[0], run[1]))
        candidates.append((x, start, end))
    if len(candidates) < 10:
        return None

    # The real graph forms one long, continuous run from the left edge to its
    # current endpoint. Time ticks below the graph are isolated columns. When
    # a graph reaches the lower border its fill-bottom changes, so continuity
    # is more reliable than requiring one common bottom position.
    groups = []
    for candidate in candidates:
        if not groups or candidate[0] - groups[-1][-1][0] > 3:
            groups.append([candidate])
        else:
            groups[-1].append(candidate)
    active = max(groups, key=len)
    if len(active) < 10:
        return None
    curve = []
    for x, start, end in active:
        # The outline is the brightest part near the top of the filled area.
        # Looking for brightness also avoids treating a dark circular marker
        # around a peak as part of the curve.
        search_end = min(end, start + 30)
        values = luminance[start:search_end + 1, x]
        line_y = start + int(np.argmax(values))
        if values.max(initial=0) < 55:
            line_y = start
        if abs(line_y - baseline) <= 2:
            line_y = baseline
        curve.append((x, line_y))
    if len(curve) < 10:
        return None

    # The site's lower-right statistics box can cover the grey fill just
    # after the real endpoint.  Its bright border then looks like a second,
    # much lower curve (rack 303 is a real example).  Discard only a short
    # trailing fragment separated from the long graph by an implausibly large
    # one-column jump.  Keeping this tail would turn a clearly positive finish
    # into a negative one and would also invent a false trough.
    jump_limit = max(20, int(width * .04))
    minimum_prefix = max(20, int(len(curve) * .70))
    maximum_tail = max(12, int(width * .10))
    for index in range(1, len(curve)):
        previous_x, previous_y = curve[index - 1]
        current_x, current_y = curve[index]
        if (index >= minimum_prefix and len(curve) - index <= maximum_tail
                and current_x - previous_x <= 3
                and abs(current_y - previous_y) > jump_limit):
            curve = curve[:index]
            break

    # Near the lower edge the grey fill can fade out before the white outline
    # ends. Continue along that outline for a few pixels at a time, stopping
    # before an unrelated time tick or the distant plot border can be joined.
    outline = neutral & (luminance > 70)
    border_start = min(height - 1, int(baseline + width * .18))
    border_counts = outline[border_start:y_stop].sum(axis=1)
    if len(border_counts):
        border_y = border_start + int(np.argmax(border_counts))
        if border_counts.max(initial=0) > width * .5:
            outline[border_y, :] = False
    last_x, last_y = max(curve, key=lambda point: point[0])
    misses = 0
    for x in range(last_x + 1, x_stop):
        low, high = max(y_start, last_y - 7), min(y_stop - 1, last_y + 7)
        choices = np.where(outline[low:high + 1, x])[0] + low
        if not len(choices):
            misses += 1
            if misses > 2:
                break
            continue
        y = max((int(value) for value in choices),
                key=lambda value: float(luminance[value, x]) - abs(value - last_y) * 4)
        last_x, last_y = x, y
        curve.append((x, y))
        misses = 0

    peak_x, peak_y = min(curve, key=lambda point: point[1])
    trough_x, trough_y = max(curve, key=lambda point: point[1])
    end_x = max(x for x, _ in curve)
    tail = [(x, y) for x, y in curve if end_x - 2 <= x <= end_x]
    end_y = int(round(sum(y for _, y in tail) / len(tail)))
    return [(int(width * .85), baseline), (peak_x, peak_y),
            (trough_x, trough_y), (end_x, end_y)]
