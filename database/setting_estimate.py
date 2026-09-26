"""BB/RB-only setting fit for models with manufacturer-published probabilities.

This is a conditional model comparison, not the actual setting probability.
It never reads or changes the manually confirmed setting or the daily score.
"""

import math
import re
import unicodedata


# (setting, published BB denominator, published RB denominator), low to high.
# Sources and the limits of this approximation are documented in SETTING_ESTIMATION.md.
SPECS = {
    'my_juggler_v': ('マイジャグラーⅤ', 'https://www.kitadenshi.co.jp/slot/myjuggler5/',
                     (('1', 273.1, 409.6), ('2', 270.8, 385.5), ('3', 266.4, 336.1),
                      ('4', 254.0, 290.0), ('5', 240.1, 268.6), ('6', 229.1, 229.1))),
    'neo_im_juggler': ('ネオアイムジャグラーEX', 'https://www.kitadenshi.co.jp/slot/neoimjugglerex/',
                       (('1', 273.1, 439.8), ('2', 269.7, 399.6), ('3', 269.7, 331.0),
                        ('4', 259.0, 315.1), ('5', 259.0, 255.0), ('6', 255.0, 255.0))),
    'houou_tensho': ('ハナハナホウオウ〜天翔〜', 'https://www.slot-pioneer.co.jp/product/hanahana_houoh_tensho/',
                     (('1', 297, 496), ('2', 284, 458), ('3', 273, 425),
                      ('4', 262, 397), ('5', 249, 366), ('6', 236, 337))),
    'new_king_v': ('ニューキングハナハナV', 'https://www.slot-pioneer.co.jp/product/new_king_hanahana_v/pop/pop_pdf.pdf',
                   (('1', 299, 496), ('2', 291, 471), ('3', 281, 442),
                    ('4', 268, 409), ('V', 253, 372))),
    'king_2023': ('キングハナハナ-30 (2023)', 'https://www.slot-pioneer.co.jp/product/king_hanahana2023/pop/pop_pdf.pdf',
                  (('1', 292, 489), ('2', 280, 452), ('3', 268, 420),
                   ('4', 257, 390), ('5', 244, 360), ('6', 232, 332))),
    'dragon_senko': ('ドラゴンハナハナ〜閃光〜', 'https://www.slot-pioneer.co.jp/product/dragon_hanahana_senko/pop/pop_pdf.pdf',
                     (('1', 256, 642), ('2', 246, 585), ('3', 235, 537),
                      ('4', 224, 489), ('5', 212, 442), ('6', 199, 399))),
}

MACHINE_SIGNATURES = {
    'SマイジャグラーVKD': 'my_juggler_v',
    'SネオアイムジャグラーEXKK': 'neo_im_juggler',
    'Sハナハナホウオウ天翔EX30': 'houou_tensho',
    'SBニューキングハナハナVPA30': 'new_king_v',
    'SキングハナハナSP30': 'king_2023',
    'Sドラゴンハナハナ閃光SP30': 'dragon_senko',
}


def model_for_machine(machine):
    name = unicodedata.normalize('NFKC', str(machine or '')).upper()
    name = re.sub(r'[\s\-−‐‑–—~〜～_・]+', '', name)
    return MACHINE_SIGNATURES.get(name)


def estimate_setting(row):
    """Return a reproducible, equal-prior fit summary, or None when unavailable."""
    key = model_for_machine(row.get('machine'))
    if key is None:
        return None
    games, bb, rb = (row.get(k) for k in ('games', 'bb', 'rb'))
    if any(type(value) is not int for value in (games, bb, rb)) or games <= 0 or min(bb, rb) < 0 or bb + rb > games:
        return None
    # サイトの点検中などの印（88888888・888）は推測しない（core.implausible_numbers と同じ基準）。
    if games > 20000 or bb > 500 or rb > 500 or (row.get('max_hold') or 0) > 100000:
        return None
    label, source, specs = SPECS[key]
    likelihoods = []
    for setting, bb_den, rb_den in specs:
        p_bb, p_rb = 1 / bb_den, 1 / rb_den
        likelihoods.append(bb * math.log(p_bb) + rb * math.log(p_rb)
                           + (games - bb - rb) * math.log1p(-p_bb - p_rb))
    peak = max(likelihoods)
    weights = [math.exp(value - peak) for value in likelihoods]
    total = sum(weights)
    weights = [value / total for value in weights]
    ranked = sorted(range(len(specs)), key=lambda i: (-weights[i], i))
    # An ordered, equal-tail interval avoids arbitrarily dropping one of
    # nearly equal settings when the observation contains little information.
    cumulative = 0.0
    lower = upper = None
    for index, weight in enumerate(weights):
        cumulative += weight
        if lower is None and cumulative >= 0.10:
            lower = index
        if cumulative >= 0.90:
            upper = index
            break
    return {
        'model': label,
        'source': source,
        'setting': specs[ranked[0]][0],
        'support': round(weights[ranked[0]] * 100, 1),
        'range80': [specs[i][0] for i in range(lower, upper + 1)],
        'setting_count': len(specs),
    }


def candidate_label(estimate):
    """Lead with uncertainty instead of presenting the best fit as a prediction."""
    if estimate is None:
        return '—'
    if len(estimate['range80']) == estimate['setting_count']:
        return 'BB/RBでは絞り込めず'
    return f"BB/RB候補 {'・'.join(estimate['range80'])}"
