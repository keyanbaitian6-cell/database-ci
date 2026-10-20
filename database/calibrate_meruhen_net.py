"""正確なjo_netとの照合。SQLiteは読み取り専用、出力は集計値だけ。

例: python database/calibrate_meruhen_net.py --baseline-ref e2731af --report report.json
除外条件は補正前の誤差で固定する。実記録や正確値は保存・削除しない。
"""
import argparse
import ast
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import statistics
import subprocess

from core import meruhen_net_estimate_detail

ROOT = Path(__file__).resolve().parents[1]


def baseline_function(ref):
    """指定コミットの推定式と定数だけを読み、製品側の変更から除外条件を独立させる。"""
    source = subprocess.check_output(['git', 'show', f'{ref}:database/core.py'], cwd=ROOT).decode('utf-8')
    names = {'MERUHEN_AXIS_STEPS', '_MERUHEN_ZERO_Y', '_MERUHEN_TOP_Y',
             'MERUHEN_PLAUSIBLE_USE_PER_GAME', 'MERUHEN_MAX_USE_PER_GAME'}
    nodes = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in {'_rise', 'meruhen_net_estimate_detail'}:
            nodes.append(node)
        elif isinstance(node, ast.Assign):
            targets = {n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name)}
            if targets & names:
                nodes.append(node)
    # 終点が0pxでも選んだ倍率を取得する。値・除外判定そのものは変えない。
    class ScaleReturn(ast.NodeTransformer):
        def visit_Return(self, node):
            if isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2:
                final = isinstance(node.value.elts[0], ast.Name) and node.value.elts[0].id == 'rounded'
                node.value.elts.append(ast.Name(id='chosen', ctx=ast.Load()) if final else ast.Constant(value=None))
            return node
    tree = ast.fix_missing_locations(ScaleReturn().visit(ast.Module(body=nodes, type_ignores=[])))
    scope = {}
    exec(compile(tree, '<baseline>', 'exec'), scope)
    return scope['meruhen_net_estimate_detail']


def round_away(value):
    return math.floor(value + .5) if value >= 0 else -math.floor(-value + .5)


def corrected(row, offset):
    if row['scale'] is None:
        return row['old']
    return round_away((row['end'] + offset) * row['scale'] / 180)


def metrics(rows, prediction):
    if not rows:
        return {'n': 0}
    residuals = [prediction(r) - r['actual'] for r in rows]
    errors = sorted(abs(e) for e in residuals)
    return dict(n=len(rows), mae=round(statistics.mean(errors), 4),
                median=statistics.median(errors), bias=round(statistics.mean(residuals), 4),
                p95=errors[int((len(errors)-1)*.95)], maximum=max(errors),
                at_least_100=sum(e >= 100 for e in errors))


def analyze(database, baseline_ref, cutoff, threshold):
    baseline = baseline_function(baseline_ref)
    records = []
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        counts = db.execute("""SELECT store,count(*),sum(json_type(payload,'$.jo_net')='integer')
            FROM days GROUP BY store""").fetchall()
        pairs = db.execute("""SELECT store,day,json_extract(payload,'$.jo_net'),
            json_extract(payload,'$.games'),json_extract(payload,'$.max_hold'),
            json_remove(json_extract(payload,'$.graph_measurement'),'$.preview_image')
            FROM days WHERE store IN ('saiwaichou','nagamachiminami')
            AND json_type(payload,'$.jo_net')='integer'
            AND json_type(payload,'$.graph_measurement')='object'
            AND json_type(payload,'$.max_hold')='integer' ORDER BY day,rack""").fetchall()
    for store, day, actual, games, max_hold, graph in pairs:
        measurement = json.loads(graph)
        old, _, scale = baseline(measurement, max_hold, games)
        if old is None:
            continue
        new, _ = meruhen_net_estimate_detail(measurement, max_hold, games)
        records.append(dict(store=store, day=day, actual=actual, old=old, new=new,
                            scale=scale, end=measurement['baseline_y']-measurement['end_y'],
                            measurement=measurement, games=games, max_hold=max_hold))
    clean = [r for r in records if abs(r['old']-r['actual']) < threshold]
    train = [r for r in clean if r['day'] <= cutoff]
    validation = [r for r in clean if r['day'] > cutoff]
    if not train or not validation:
        raise ValueError('補正用・確認用の両期間に照合可能な記録が必要です')
    def loss(offset):
        return sum(abs(corrected(r, offset)-r['actual']) for r in train)
    offset = min((i/100 for i in range(-100, 101)), key=loss)
    def comparison(rows):
        return dict(before=metrics(rows, lambda r:r['old']),
                    fitted=metrics(rows, lambda r:corrected(r, offset)),
                    product=metrics(rows, lambda r:r['new']))
    four_point = []
    for row in clean:
        m = {k:v for k,v in row['measurement'].items() if k != 'curve'}
        old, _, scale = baseline(m, row['max_hold'], row['games'])
        new, _ = meruhen_net_estimate_detail(m, row['max_hold'], row['games'])
        if old is not None and new is not None:
            four_point.append(dict(row, old=old, new=new, scale=scale))
    return dict(baseline_ref=baseline_ref, threshold=threshold, cutoff=cutoff,
                stores={s:dict(records=n, jo_records=jo or 0) for s,n,jo in counts},
                paired=len(pairs), estimable=len(records), excluded=len(records)-len(clean),
                unestimable=len(pairs)-len(records), fitted_pixel_offset=offset,
                train=comparison(train), validation=comparison(validation),
                all_filtered=comparison(clean), all_unfiltered=comparison(records),
                four_point=comparison(four_point),
                by_day={day:comparison([r for r in clean if r['day']==day])
                        for day in sorted({r['day'] for r in clean})},
                worse=sum(abs(r['new']-r['actual']) > abs(r['old']-r['actual']) for r in clean),
                improved=sum(abs(r['new']-r['actual']) < abs(r['old']-r['actual']) for r in clean))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT/'database/data/database.sqlite3')
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--cutoff', default='2026-10-09')
    parser.add_argument('--threshold', type=int, default=100)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.threshold <= 0:
        parser.error('--threshold は正の整数で指定してください')
    report = analyze(args.database, args.baseline_ref, args.cutoff, args.threshold)
    text = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.report:
        if args.report.resolve() == args.database.resolve():
            parser.error('報告の保存先にはデータベースと別のファイルを指定してください')
        args.report.write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
