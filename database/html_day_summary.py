"""保存したアナスロのHTML（幸町）から、日ごとの「何台中何台プラス」だけを作る（2026-10-18 利用者
「台のデータ入れると重くなってしまうので、共有カレンダーへのデータに…各日の勝率、何台中何台プラスで
終わったかをそれだけを乗せて欲しい」「今回のHTML分ってことね」）。

元：分析用JSON（html_converter/data/normal_analysis・other_analysis）。ノーマル用JSONの無い日
（2026-08-01以降。DBへ同じHTMLから取り込み済み）のジャグラー・ハナハナはDBの記録（読むだけ）を使う。
台の数値は出さない。分析用JSONは通常の記録へ取り込まない。勝ち負けは core.rack_won と同じ判定、
対象外・表示しない機種と数値の異常な台は除く。

PCの閲覧用ファイル（core.export_viewer）がこの結果を ``day_summaries`` として載せ、共有ページの
カレンダーは台データの無い日にだけ使う（EVENT_CALENDAR.md）。

    python html_day_summary.py      … database/data/html-day-summary.json を作り直す
"""
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import core

FORMAT = 'database-html-day-summary'
VERSION = 1
SUMMARY_NAME = 'html-day-summary.json'
STORE = 'saiwaichou'
ROOT = Path(__file__).resolve().parent.parent
NORMAL_DIR = ROOT / 'html_converter/data/normal_analysis/saiwaichou'
OTHER_DIR = ROOT / 'html_converter/data/other_analysis/saiwaichou'
NORMAL_WORDS = ('ジャグラー', 'ハナハナ')


def _is_normal(name):
    return any(word in core._machine_text(name) for word in NORMAL_WORDS)


def _counted(row):
    """対象外・表示しない機種、数値の異常な台は数えない（取り込み・閲覧用と同じ）。"""
    names = [row.get('machine'), row.get('source_machine')]
    return not any(core.is_excluded_machine(STORE, n) or core.is_hidden_machine(STORE, n) for n in names if n) \
        and not core.implausible_numbers(row)


def _row(raw):
    return {'store': STORE, 'day': raw['day'], 'machine': raw['machine'], 'source_machine': raw.get('source_machine'),
            'rack': int(raw['rack']), 'games': raw.get('games') or 0, 'bb': raw.get('bb'), 'rb': raw.get('rb'),
            'max_hold': raw.get('max_hold'), 'graph_measurement': raw.get('graph_measurement'), 'jo_net': raw.get('jo_net')}


def build(normal_dir=NORMAL_DIR, other_dir=OTHER_DIR, db_path=None):
    """{day: {(rack): row}} を作って日ごとに数える。その他機種の分析用JSONにある日だけ（HTMLを保存した日）。"""
    other, normal, sources = {}, {}, []
    for folder, into, prefix in ((other_dir, other, 'other-analysis-'), (normal_dir, normal, 'normal-analysis-')):
        for path in sorted(Path(folder).glob(f'{prefix}{STORE}-*.json')):
            doc = json.loads(path.read_text(encoding='utf-8'))
            if doc.get('store') != STORE:
                raise ValueError(f'{path.name} は幸町のファイルではありません。')
            sources.append(path.name)
            for raw in doc['records']:
                into.setdefault(raw['day'], {}).setdefault(int(raw['rack']), _row(raw))
    db_normal = {}
    missing = sorted(day for day in other if day not in normal)
    if missing and db_path and Path(db_path).is_file():
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
            for day, payload in db.execute(
                    f"SELECT day, payload FROM days WHERE store=? AND day IN ({','.join('?' * len(missing))})", (STORE, *missing)):
                raw = json.loads(payload)
                if _is_normal(raw.get('machine')):
                    db_normal.setdefault(day, {}).setdefault(int(raw['rack']), _row(raw))
    days = []
    for day in sorted(other):
        part = normal.get(day) if day in normal else db_normal.get(day)
        if part is None:
            continue  # ジャグラー・ハナハナの分が無い日は、その日の勝率にしない
        racks = {**part, **{k: v for k, v in other[day].items() if k not in part}}
        rows = [r for r in racks.values() if _counted(r)]
        results = [w for w in (core.rack_won(r) for r in rows) if w is not None]
        days.append({'store': STORE, 'day': day, 'racks': len(rows), 'judged': len(results), 'won': sum(results),
                     'normal_from': 'html' if day in normal else 'database'})
    return {'format': FORMAT, 'version': VERSION, 'built_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'note': '保存したアナスロのHTMLからの日ごとの集計（台の数値は含まない）。', 'sources': sources, 'days': days}


def valid_day(d):
    return (isinstance(d, dict) and d.get('store') in core.STORE_NAMES and isinstance(d.get('day'), str)
            and len(d['day']) == 10 and all(type(d.get(k)) is int for k in ('racks', 'judged', 'won'))
            and 0 <= d['won'] <= d['judged'] <= d['racks'])


def load_days(path):
    """閲覧用ファイルに載せる日ごとの集計（store・day・racks・judged・won）。無い・読めないときは []。"""
    try:
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict) or doc.get('format') != FORMAT or doc.get('version') != VERSION \
            or not isinstance(doc.get('days'), list):
        return []
    return [{k: d[k] for k in ('store', 'day', 'racks', 'judged', 'won')} for d in doc['days'] if valid_day(d)]


def main():
    data = Path(__file__).resolve().parent / 'data'
    result = build(db_path=data / 'database.sqlite3')
    if not result['days']:
        print('集計できる日がありません（分析用JSONが見つかりません）。')
        return 1
    from file_io import atomic_writer
    with atomic_writer(data / SUMMARY_NAME) as out:
        out.write(json.dumps(result, ensure_ascii=False, indent=1) + '\n')
    days = result['days']
    print(f"{len(days)}日（{days[0]['day']}〜{days[-1]['day']}）を {data / SUMMARY_NAME} に書きました。")
    return 0


if __name__ == '__main__':
    sys.exit(main())
