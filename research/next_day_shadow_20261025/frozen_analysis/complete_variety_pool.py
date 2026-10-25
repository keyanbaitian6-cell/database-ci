"""現行バラエティに含まれる少数ノーマル台を補完。了承済みのノーマル方式比較は再実行しない。"""
import pickle
import pandas as pd
from audit import HERE,dump
from prepare import prepare
data=pickle.load((HERE/'inputs.pkl').open('rb'))
rows=[r for r in data['rows'] if r['machine']=='LスターハナハナMX']
prepare(dict(rows=rows),prefix='variety_normal_',include_jh=True)
extra=pd.read_pickle(HERE/'variety_normal_features.pkl');extra=extra[extra.is_variety].copy();extra['id']+=2000000
f=pd.read_pickle(HERE/'features.pkl');f=f[~f.machine.eq('LスターハナハナMX')]
f=pd.concat([f,extra],ignore_index=True);assert not f.id.duplicated().any();f.to_pickle(HERE/'features.pkl')
dump('variety_pool_completion.json',dict(reason='現行バラエティの母集団一致のため、1〜2台のLスターハナハナMXだけ補完。ノーマルのモデル比較は繰り返さない。',added_rows=len(extra),first=extra.day.min(),last=extra.day.max(),total_rows=len(f)))
print('バラエティ母集団補完',len(extra),flush=True)
