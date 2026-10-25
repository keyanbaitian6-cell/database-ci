"""未来を物理的に削除した入力で新方式の特徴を再計算する。全履歴再計算はしない。"""
import pickle
import numpy as np
import pandas as pd
from audit import HERE,dump
from prepare import prepare
f=pd.read_pickle(HERE/'features.pkl');raw=pickle.load((HERE/'inputs.pkl').open('rb'))
selected=[]
for s,x in f[f.category.eq('remaining_type_unverified')].groupby('store'):
    selected.append((s,x.groupby('machine').size().idxmax()))
cut='2026-10-15';records=[r for r in raw['rows'] if (r['store'],r['machine']) in selected and r['day']<=cut]
prepare(dict(rows=records),prefix='future_cut_')
p=pd.read_pickle(HERE/'future_cut_features.pkl')
keys=['store','day','machine','rack'];cols=['old','recent','prior_machine_win','today_used','evidence_days','latest_used','stale','variety_percent','variety_refs','quiet_run']+[f'{stem}{w}' for stem in ['simple','pwin','history_days','games','win_days'] for w in [1,3,7,14,28]]
both=p[keys+cols].merge(f[keys+cols],on=keys,validate='one_to_one',suffixes=['_cut','_full'])
checks=[]
for c in cols:
    a=both[c+'_cut'].astype(float);b=both[c+'_full'].astype(float);same=np.isclose(a,b,atol=1e-10,equal_nan=True)
    checks.append(dict(feature=c,rows=len(a),all_match=bool(same.all()),max_absolute_difference=float(np.nanmax(abs(a-b))) if (a-b).notna().any() else 0))
assert all(x['all_match'] for x in checks)
dump('new_features_future_check.json',dict(cutoff=cut,machines=selected,rows=len(both),features=len(cols),all_match=True,checks=checks))
print('新方式の未来削除検算',len(both),'行',len(cols),'項目すべて一致',flush=True)
