"""保存済みのサイトセブンの台に、グラフ画像から読んだ推定差枚を後から付ける（2026-11-07）。

取り込み済みの台（推定差枚の仕組みより前に保存した台）は、data/site777-staging/sources に残っている
グラフ一覧の画像（PNG）から site777_net で推定差枚を読み、同じ画像（SHA）の台だけに付ける。

- DB は読むだけ（mode=ro）。書き換えは、作ったバックアップを起動中のPC版が読み込むときに、
  既存の PscubeStore.import_backup（_merge：同じ表・同じ画像のときだけ推定差枚を移す）で行う。
- 出力は推定差枚を付けられた台だけ。数値・出典・MY は保存済みのまま（推定差枚以外を変えない）。
- 既に推定差枚がある台は通常は対象外。--upgrade では50枚刻みの旧方式を同じ画像から再計算する。
- 画像が見つからない台、保留（見切れ・短い線など）の台は入れない。
- サイトには接続しない。

使い方（database フォルダーで）：
  .venv/Scripts/python.exe site777_backfill.py                 # 件数を見るだけ
  .venv/Scripts/python.exe site777_backfill.py --out <ファイル>  # バックアップを書く
同期フォルダへ pscube-backup-site777net-YYYYMMDD.json の名前で置くと、起動中のPC版が数分以内に読み込む
（pscube_import.ANDROID_SYNC_NAME）。
"""
from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import site777_net

ROOT = Path(__file__).resolve().parent


def estimates_from_sources(sources_dir) -> dict:
    """{画像SHA: site777_net.analyze の結果}。資料置き場のグラフ一覧（kind='graphs'）の画像だけを読む。"""
    found = {}
    for path in sorted(Path(sources_dir).glob('*.json')):
        try:
            page = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(page, dict) or page.get('kind') != 'graphs' or not isinstance(page.get('graphs'), list):
            continue
        for item in page['graphs']:
            uri = item.get('png') if isinstance(item, dict) else None
            if not isinstance(uri, str) or not uri.startswith('data:image/png;base64,'):
                continue
            try:
                raw = base64.b64decode(uri.split(',', 1)[1], validate=True)
            except ValueError:
                continue
            found.setdefault(hashlib.sha256(raw).hexdigest(), site777_net.analyze(raw))
    return found


def build(db_path, sources_dir, *, upgrade=False):
    """(バックアップ, 件数の内訳)。推定差枚を付けられた台が無ければバックアップは None。"""
    analyzed = estimates_from_sources(sources_dir)
    uri = Path(db_path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        records = [json.loads(p) for (p,) in db.execute('SELECT payload FROM records')]
        machines = {k: json.loads(p) for k, p in db.execute('SELECT key, payload FROM machines')}
    from pscube_import import _machine_key
    summary = collections.Counter()
    out, keys = [], set()
    for r in records:
        if r.get('source_site') != 'site777':
            continue
        summary['サイトセブンの台'] += 1
        previous = r.get('net_estimate')
        is_upgrade = upgrade and site777_net.valid(previous) and previous['method'] == site777_net.LEGACY_METHOD
        if previous is not None and not is_upgrade:
            summary['既に推定あり'] += 1
            continue
        result = analyzed.get((r.get('source_graph') or {}).get('image_sha256'))
        if result is None:
            summary['画像なし'] += 1
            continue
        estimate = site777_net.net_estimate_from(result)
        if estimate is None:
            summary[f"保留：{result['reason']}"] += 1
            continue
        summary['推定を更新する' if is_upgrade else '推定を付ける'] += 1
        out.append({**r, 'net_estimate': estimate})
        keys.add(_machine_key(r))
    if not out:
        return None, summary
    backup = {'format': 'pscube-viewer', 'version': 1, 'kind': 'backup', 'source': 'site777',
              'import_mode': 'fill_missing', 'machines': [machines[k] for k in sorted(keys) if k in machines],
              'records': out, 'rack_captures': []}
    return backup, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--db', default=str(ROOT / 'data' / 'pscube.sqlite3'))
    parser.add_argument('--sources', default=str(ROOT / 'data' / 'site777-staging' / 'sources'))
    parser.add_argument('--out', help='バックアップを書くファイル（無ければ件数を見るだけ）')
    parser.add_argument('--upgrade', action='store_true', help='50枚刻みの旧方式も、同じ画像から再計算する')
    args = parser.parse_args(argv)
    backup, summary = build(args.db, args.sources, upgrade=args.upgrade)
    for name, count in sorted(summary.items()):
        print(f'{name}: {count}')
    if args.out and backup:
        path = Path(args.out)
        temp = path.with_name(path.name + '.part')
        temp.write_text(json.dumps(backup, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)
        print(f'書きました：{path}（{len(backup["records"])}台）')
    elif args.out:
        print('推定差枚を付けられる台がないので、書いていません。')


if __name__ == '__main__':
    sys.exit(main())
