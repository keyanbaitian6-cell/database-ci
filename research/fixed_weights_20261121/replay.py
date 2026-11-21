"""結果表へのアクセスを拒否し、当時の入力だけで11/13〜21を日付順に再生する。"""
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'database'))
from daily_learning import History, Journal, STORE_MODEL, VARIETY_MODEL, encoded, identity, prediction_target, rank_blend, rank_by, rank_pool, shift, valid
from daily_learning_fixed import STORES, matched_pairs

FIRST, LAST = '2026-11-13', '2026-11-21'  # v4の初日から依頼日の締切まで。成績で期間を選ばない。


def predictions_only(action, table, column, db_name, context):
    if action == sqlite3.SQLITE_READ and table not in ('predictions', 'inputs'):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def replay(path):
    anchors, evidence = {}, []
    with closing(Journal(path, readonly=True)) as journal:
        journal.db.set_authorizer(predictions_only)
        journal.db.execute('BEGIN')
        for (key,) in journal.db.execute('SELECT key FROM predictions WHERE key>=? AND key<? ORDER BY key',
                                         (FIRST, shift(LAST, 1))):
            p = journal.get('predictions', key)
            target, store = key.split('|', 1)
            day = shift(target, -1)
            if (p['target'] != target or p['input_day'] != day or prediction_target(datetime.fromisoformat(p['saved_at'])) != target
                    or p['version'] != 'daily-plus-ridge-20261112-v4' or store not in STORES):
                raise ValueError(f'{key} の対象日・版・保存時刻を確認できません')
            rows = journal.input_rows(p)
            archive = journal.input_rows(p, 'archive_rows')
            if any(r['day'] > day or r['store'] != store for r in rows + archive):
                raise ValueError(f'{key} の入力範囲が不正です')
            replaced = {(r['day'], r['rack']) for r in archive}
            kept = [r for r in rows if valid(r) or (r['day'], r['rack']) not in replaced]
            history = History(kept + archive)
            daily = {identity(r): r for r in rows if r['day'] == day}
            models = {tuple(json.loads(k)): v for k, v in p['models'].items()}
            if any(v['last'] > shift(target, -8) for v in models.values()):
                raise ValueError(f'{key} の係数に成熟前の日付があります')
            first, method, fixed = anchors.setdefault(store, (target, p['methods'][store], models))
            if first != FIRST or method != p['methods'][store]:
                raise ValueError(f'{key} は開始日・方式が一致しません')
            groups = []
            for saved in p['groups']:
                _, rate, name = json.loads(saved['key'])
                pool = [daily[tuple(i['id'])] for i in saved['pool']]
                groups.append(dict(rate=rate, pool=pool))
                kind = saved['model']
                features = [history.model_features(r, kind or 'machine') for r in pool]
                if features != [i['features'] for i in saved['pool']]:
                    raise ValueError(f'{key} {name} の当時の特徴と不一致')
                if kind == 'blend':     # 2026-11-22以降の幸町（混合）。この再生の期間（〜11-21）には出ない。
                    ordered = rank_blend(pool, history, models, store, rate)
                elif kind == 'machine':
                    ordered = rank_pool(pool, history, models)
                elif kind is not None:
                    model = VARIETY_MODEL if kind == 'variety' else STORE_MODEL
                    ordered = rank_by(pool, history, models[store, rate, model], kind)
                else:
                    ordered = None
                selected = saved['current'] if ordered is None else [list(identity(r)) for r in ordered[:len(saved['current'])]]
                if selected != saved['learned']:
                    raise ValueError(f'{key} {name} の当時の候補と不一致')
            pairs = matched_pairs(store, groups, p['groups'], history, models, fixed)
            evidence.append(dict(key=key, anchor=first, saved_at_original=p['saved_at'], input_sha256=p['input_sha256'],
                                 method=method, pairs=pairs))
    return evidence


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('新規の検証用JSONの出力先を1つ指定してください')
    rows = replay(ROOT / 'database/data/daily-learning/journal.sqlite3')
    data = encoded(dict(type='retrospective-blind-replay', first=FIRST, last=LAST, predictions=rows)).encode('utf-8')
    with Path(sys.argv[1]).open('xb') as f:
        f.write(data)
    print('店舗日', len(rows), '組', sum(len(r['pairs']) for r in rows), 'SHA-256', hashlib.sha256(data).hexdigest())
