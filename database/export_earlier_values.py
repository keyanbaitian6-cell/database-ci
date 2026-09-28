"""Export the earlier values of records from the PC write log (read-only).

The PC app appends every write to the ``observations`` table (a row payload
with its own ``captured_at``). A record captured before a prediction cutoff and
re-captured after it keeps only the later values in ``days``; this log still
has the earlier ones. The next-day candidate validation uses them only as a
supplementary check (see NEXT_DAY_CANDIDATES_VALIDATION_20260929.md).

Run from database/ (writes outside the repository; the output is real data):
    python export_earlier_values.py <output.json> [--db data/database.sqlite3]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

FIELDS = ('store', 'day', 'machine', 'rack', 'kind_code', 'games', 'bb', 'rb',
          'max_hold', 'previous_start', 'captured_at')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--db', type=Path, default=Path('data/database.sqlite3'))
    args = parser.parse_args()
    db = sqlite3.connect(f'file:{args.db.as_posix()}?mode=ro', uri=True)
    rows = []
    for (payload,) in db.execute('SELECT payload FROM observations ORDER BY id'):
        row = json.loads(payload)
        if not row.get('captured_at'):
            continue
        rows.append({k: row[k] for k in FIELDS if k in row})
    args.output.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    print(f'{len(rows)} earlier values -> {args.output}')


if __name__ == '__main__':
    main()
