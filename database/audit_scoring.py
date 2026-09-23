"""Read-only local scoring audit; also writes a Python/Dart parity fixture.

Run from database/: .runtime/Scripts/python.exe audit_scoring.py
Never changes source records. Output is private local data under reports/.
"""
import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path
from statistics import mean, median

from core import VERSION, graph_metrics, score


def main():
    root = Path(__file__).resolve().parent
    with sqlite3.connect((root / 'data/database.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        original = [json.loads(r[0]) for r in db.execute('SELECT payload FROM days ORDER BY store,day,machine,rack')]
    # Convert only the audit copy's legacy SVG to the shared four-point format.
    rows = []
    keys = ('store', 'day', 'machine', 'rack', 'games', 'bb', 'rb', 'max_hold', 'captured_at')
    converted = 0
    for raw in original:
        row = {k: raw[k] for k in keys if k in raw}
        m = raw.get('graph_measurement')
        if m:
            row['graph_measurement'] = {k: m[k] for k in ('baseline_y', 'peak_y', 'trough_y', 'end_y') if k in m}
        elif raw.get('graph'):
            g = graph_metrics(raw['graph']['path'], raw['graph']['baseline'])
            ys = [p[1] for p in g['points']]
            row['graph_measurement'] = dict(baseline_y=g['baseline'], peak_y=min(ys), trough_y=max(ys), end_y=ys[-1])
            converted += 1
        rows.append(row)
    results = [score(r, rows) for r in rows]
    for r, raw, result in zip(rows, original, results):
        assert result == score(raw, original), f'Legacy conversion changed a score: {r["rack"]}'
        if result['total'] is not None:
            assert 0 <= result['total'] <= 100
            assert result['missing_low'] <= result['total'] <= result['missing_high']
            assert result['games'] == 0
        assert result == score(r, [x for x in rows if x['day'] < r['day']])
    output = root / 'reports/scoring-v8-audit'
    output.mkdir(parents=True, exist_ok=True)
    fields = ('games', 'max_hold', 'hits', 'positive', 'retention', 'total',
              'reference_count', 'reference_days', 'hold_reference_count', 'coverage',
              'missing_low', 'missing_high', 'provisional')
    fixture = dict(version=VERSION, rows=rows,
                   expected=[{k: s[k] for k in fields} for s in results])
    (output / 'parity.json').write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
    with (output / 'scores.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['店舗', '日付', '機種', '台番号', 'G', '実績点', '暫定', '比較件数', '比較日数', '評価可能配点', '欠測下限', '欠測上限', '採点版'])
        for r, s in zip(rows, results):
            writer.writerow([r['store'], r['day'], r['machine'], r['rack'], r['games'], s['total'], s['provisional'],
                             s['reference_count'], s['reference_days'], s['coverage'], s['missing_low'], s['missing_high'], VERSION])
    totals = [s['total'] for s in results if s['total'] is not None]
    example = [dict(row=r, score=s) for r, s in zip(rows, results)
               if r['store'] == 'saiwaichou' and r['day'] == '2026-09-16' and r['rack'] == 623]
    summary = dict(version=VERSION, rows=len(rows), scored=len(totals),
                   unscored=len(rows)-len(totals), provisional=sum(s['provisional'] for s in results if s['total'] is not None),
                   mean=round(mean(totals), 1), median=median(totals), minimum=min(totals), maximum=max(totals),
                   coverage=dict(Counter(s['coverage'] for s in results if s['total'] is not None)),
                   legacy_svg_converted_only_in_audit=converted, example=example)
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
