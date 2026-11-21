"""アナスロの分析用JSON（幸町・P-STATIONのジャグラー・ハナハナ）を、日次学習の過去の学習・特徴にだけ足す（2026-11-12）。

利用者「ピーステーションと幸町のノーマルタイプについてはアナスロからの分析用jsonが学習に使えるかも検討してね」→
検討（共有記録 2026-11-12「アナスロの分析用JSON…の検討」）→「1」（両方に入れる）。

- 読むのは `html_converter/data/normal_analysis/saiwaichou/*.json` と `html_converter/data/pstation_analysis/*.json`
  （Gitの対象外。無ければ何も足さない）。原本DB・保存済みの記録・候補の一覧（従来方式）は変えない。
- 同じ台・日は、原本DBの有効な行を優先する。足すのは、原本DBに有効な行の無い台・日だけ。P-STATIONの原本DBにある
  アナスロの行（今は無効扱い）は、同じ台・日をJSONで足すときに置き換える（中身は同じ取得元）。
- 前日データ（予測の入力の日）には使わない：対象日の前日より前の日だけ。完全性の判定（ready）にも入れない。
- 同じ台・日・機種の重複は、中身が同じなら1件、違えば両方とも使わない（10/23の監査では矛盾は無かった）。
- P-STATIONのJSONはグラフが `source_graph` にあるので `graph` へ移す（今の outcome() が読む名前）。
- 符号の向きは今の取得元と98〜99%同じ（2026-11-12の監査）。予測が良くなる根拠ではない（改善未確認）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'html_converter' / 'data'
FOLDERS = {'saiwaichou': ROOT / 'normal_analysis' / 'saiwaichou',
           'pscube:c740601:20': ROOT / 'pstation_analysis'}
FLAG = 'normal-analysis'
ZERO_FIX = 'pstation-zero-20261121'     # start_at_zero の版（P-STATIONの方式の版に付ける）


def start_at_zero(graph):
    """P-STATIONの古い形式（2026-01〜08前半）のグラフは `zero_y` が 0 のまま書かれている。点は x=0・y=312 から始まる。

    差枚のグラフは0枚から始まるので、`zero_y` が 0 で最初の点が x=0 なら、最初の点の y をゼロ線にする（2026-11-21）。
    新しい形式（`zero_y` 312）は9,813行すべて (0,312) から始まり、この規則と同じ。直す前は、古い形式の行が
    1〜7月すべて「プラスでない」と読まれ、日次学習の正解・特徴が誤っていた（月ごとのプラス率0%、直すと40〜43%）。
    最初の点が y=0 の行（89行）・形が違う行はそのまま。"""
    try:
        first = graph['points'][0]
        if (graph.get('kind') == 'source_coordinates' and float(graph.get('zero_y', 0.)) == 0.
                and float(first[0]) == 0. and float(first[1]) != 0.):
            return {**graph, 'zero_y': float(first[1]), 'zero_from': 'first-point'}
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        pass
    return graph


def files(store, folders=None):
    folder = (folders or FOLDERS).get(store)
    return sorted(folder.glob('*.json')) if folder is not None and folder.is_dir() else []


def fingerprints(store, folders=None):
    """読んだJSONの名前と指紋（予測の記録に残す。足した行そのものは入力の塊として固定保存される）。"""
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files(store, folders)}


def load(store, first, last, folders=None):
    """first〜last（両端を含む）の行。日次学習の行の形にそろえる。"""
    found, conflicts = {}, set()
    for path in files(store, folders):
        document = json.loads(path.read_text(encoding='utf-8'))
        if document.get('format') != 'database-normal-analysis':
            continue
        for raw in document.get('records', []):
            day = raw.get('day')
            if not isinstance(day, str) or not first <= day <= last:
                continue
            row = {k: v for k, v in raw.items() if k not in ('source_probabilities',)}
            row['store'] = store
            row['archive'] = FLAG
            if store.startswith('pscube:'):
                row['rate'] = '20'
                if 'source_graph' in row:
                    row['graph'] = start_at_zero(row.pop('source_graph'))
            key = (day, int(row['rack']), str(row['machine']))
            if key in found and found[key] != row:
                conflicts.add(key)
            found.setdefault(key, row)
    return [row for key, row in sorted(found.items()) if key not in conflicts]


def merge(rows, store, target, folders=None):
    """原本DBの行（rows、1店舗分）に、JSONの行を足す。input_day（対象日の前日）とそれ以降は足さない。"""
    from daily_learning import shift, valid
    first, last = shift(target, -210), shift(target, -2)
    extra = load(store, first, last, folders)
    if not extra:
        return rows
    have = {(r['day'], int(r['rack'])) for r in rows if valid(r)}
    added = [r for r in extra if (r['day'], int(r['rack'])) not in have]
    replace = {(r['day'], int(r['rack'])) for r in added}
    kept = [r for r in rows if valid(r) or (r['day'], int(r['rack'])) not in replace]
    from daily_learning import identity
    return sorted(kept + added, key=lambda r: (r['day'], identity(r)))
