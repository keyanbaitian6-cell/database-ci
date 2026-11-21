"""営業前に同時保存する係数固定対照。成績を読むのは固定期間の満了後だけ。"""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path

from daily_learning import (
    JST, MATURITY, STORE_MODEL, VARIETY_MODEL, Journal, candidate_rates, comparison,
    identity, rank_blend, rank_by, rank_pool, shift, store_day,
)
from daily_learning_names import learning_key

FIRST = '2026-11-22'
PERIOD_DAYS = 112
LAST = shift(FIRST, PERIOD_DAYS - 1)
EVALUATE_ON = shift(LAST, MATURITY)
STUDY = 'fixed-weights-20261122'
STORES = ('nagamachiminami', 'saiwaichou', 'pscube:c740601:20')
# この期間はP-STATIONの「23日」研究と重なる。結果表の該当店舗を開ける日を守る。
PS_EVALUATE_ON = '2027-04-30'


def prediction(target, store, method, groups, projected, history, models, journal):
    """最初に保存された同店の予測が原点。固定係数はその予測本文からだけ読む。"""
    first = journal.db.execute(
        'SELECT key FROM predictions WHERE key>=? AND key<? AND substr(key,12)=? ORDER BY key LIMIT 1',
        (FIRST, target, store)).fetchone()
    anchor = first[0][:10] if first else target
    fixed = models
    if first:
        initial = journal.get('predictions', first[0])
        if initial['methods'][store] != method:
            return dict(anchor=anchor, reason='開始時と方式の版が異なる')
        fixed = {tuple(json.loads(key)): model for key, model in initial['models'].items()}
    return dict(anchor=anchor, pairs=matched_pairs(store, groups, projected, history, models, fixed))


def matched_pairs(store, groups, projected, history, models, fixed):
    pairs = {}
    for group, saved in zip(groups, projected, strict=True):
        pool, count = group['pool'], len(saved['current'])
        if not count:
            continue
        kind = saved['model']
        if kind == 'machine' and any(learning_key(identity(r))[:3] not in fixed for r in pool):
            kind = 'store'
        updated = saved['learned']
        if kind == 'blend':
            # 2026-11-21 幸町・P-STATIONの混合：固定版は開始日の係数と、その係数の学習量から決まる混合比のまま
            # （開始日に専用係数の無かった機種は、後から専用係数ができても共通だけ）。更新版はその日の本番の候補。
            key = (store, group.get('rate', ''), STORE_MODEL)
            ordered = rank_blend(pool, history, fixed, store, group.get('rate', '')) if key in models else None
        elif kind == 'machine':
            ordered = rank_pool(pool, history, fixed)
        elif kind in ('store', 'variety'):
            name = STORE_MODEL if kind == 'store' else VARIETY_MODEL
            key = (store, group.get('rate', ''), name)
            ordered = rank_by(pool, history, fixed.get(key), kind) if key in models else None
            if ordered is not None and kind != saved['model']:
                daily = rank_by(pool, history, models[key], kind)
                updated = [list(identity(r)) for r in daily[:count]]
        else:
            ordered = None
        if ordered is None:
            pairs[saved['key']] = {'reason': '両版に共通する係数がない'}
            continue
        pairs[saved['key']] = dict(kind=kind, fixed=[list(identity(r)) for r in ordered[:count]], updated=updated)
    return pairs


def paired_day(journal, key, pairs):
    outcome = journal.get('outcomes', key)
    if outcome is None:
        raise ValueError(f'{key} の成熟結果を待っています')
    groups = []
    evidence = {g['key']: g['labels'] for g in outcome['groups']}
    for group_key, pair in pairs.items():
        if 'reason' in pair:
            continue
        labels = evidence[group_key]
        stats = candidate_rates('current', pair['fixed'], labels)
        stats.update(candidate_rates('learned', pair['updated'], labels))
        groups.append(dict(trained=True, **stats))
    return store_day(key[:10], groups), len(pairs) - len(groups)


def evaluate(path):
    """期間全体の事前予測と成熟結果が対応してから、研究用の店舗別比較だけを返す。"""
    today = datetime.now(JST).date().isoformat()
    if today < EVALUATE_ON:
        raise ValueError(f'評価日は {EVALUATE_ON} 以降です')
    with closing(Journal(path, readonly=True)) as journal:
        journal.db.execute('BEGIN')  # 全店舗で同じ時点の記録を読む。
        report = {}
        for store in STORES:
            if store == 'pscube:c740601:20' and today < PS_EVALUATE_ON:
                report[store] = {'available_from': PS_EVALUATE_ON}
                continue
            days, skipped, unavailable = [], 0, 0
            keys = journal.db.execute(
                'SELECT key FROM predictions WHERE key>=? AND key<? AND substr(key,12)=? ORDER BY key',
                (FIRST, shift(LAST, 1), store))
            for (key,) in keys:
                study = journal.get('predictions', key).get(STUDY)
                if not study or 'reason' in study:
                    unavailable += 1
                    continue
                day, excluded = paired_day(journal, key, study['pairs'])
                days.append(day)
                skipped += excluded
            score = comparison(days, .05 / len(STORES), FIRST)
            supported = score.pop('adopt')
            report[store] = dict(update_benefit_supported=supported, comparison=score,
                                 missing_predictions=PERIOD_DAYS - len(days) - unavailable, unavailable_days=unavailable,
                                 unavailable_groups=skipped)
        return report


if __name__ == '__main__':
    path = Path(__file__).resolve().parent / 'data/daily-learning/journal.sqlite3'
    try:
        print(json.dumps(evaluate(path), ensure_ascii=False, indent=2))
    except ValueError as error:
        raise SystemExit(str(error))
