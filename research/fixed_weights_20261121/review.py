"""11/21に結果を見ずに確定した再生候補の記述集計。採用の判定には使わない。"""
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'database'))
from daily_learning import JST, Journal
from daily_learning_fixed import STORES, paired_day

SEALED_SHA256 = '78c84bad1f30734abe07fc36ba8901059f74f9f1785786d6c9e3490a4c77020f'


def review(artifact, db):
    if datetime.now(JST).date().isoformat() < '2027-03-11':
        raise ValueError('既存の日次学習の初回評価日（2027-03-11）まで成績を開きません')
    data = artifact.read_bytes()
    if hashlib.sha256(data).hexdigest() != SEALED_SHA256:
        raise ValueError('11/21に固定した再生候補の指紋が一致しません')
    rows = json.loads(data)['predictions']
    with closing(Journal(db, readonly=True)) as journal:
        journal.db.execute('BEGIN')
        result = {}
        for store in STORES:
            days = [paired_day(journal, r['key'], r['pairs'])[0] for r in rows if r['key'].endswith('|' + store)]
            diffs = [d['diff'] for d in days if d['diff'] is not None]
            result[store] = dict(saved_days=len(days), paired_days=len(diffs),
                                 mean_difference=statistics.mean(diffs) if diffs else None,
                                 median_difference=statistics.median(diffs) if diffs else None)
        return result


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('11/21に固定した検証用JSONのパスを指定してください')
    try:
        print(json.dumps(review(Path(sys.argv[1]), ROOT / 'database/data/daily-learning/journal.sqlite3'),
                         ensure_ascii=False, indent=2))
    except ValueError as error:
        raise SystemExit(str(error))
