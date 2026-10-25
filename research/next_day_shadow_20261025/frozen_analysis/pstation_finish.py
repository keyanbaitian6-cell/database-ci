import json
import numpy as np
import pandas as pd
from audit import HERE,dump
f=pd.DataFrame(json.loads((HERE/'pstation_features_raw.json').read_text(encoding='utf-8')))
cols=['games','won','score','hit_rank','net_medals','jo_net'];labels=f[['store','machine','rack','ord']+cols].copy();labels['ord']-=1;labels=labels.rename(columns={k:'next_'+k for k in cols})
f=f.merge(labels,on=['store','machine','rack','ord'],how='left',validate='one_to_one')
f['label_day']=pd.to_datetime(f.day)+pd.Timedelta(days=1)
f['next_busyplus']=np.where(f.next_games.notna()&f.next_won.notna(),((f.next_games>=3000)&f.next_won.eq(1)).astype(float),np.nan)
f['next_low2000']=np.where(f.next_games.notna(),f.next_games.lt(2000).astype(float),np.nan)
f.to_pickle(HERE/'pstation_features.pkl')
dump('pstation_prepare_validation.json',dict(rows=len(f),groups=f.groupby(['store','day','machine']).ngroups,dates=[f.day.min(),f.day.max()],outcome_join='D+1 exact, same store rate machine rack',features='native dedicated MY or bonus profiles; no anaslo history',observed_at_missing=int(f.observed_at.isna().sum())))
print('P-STATION準備完了',len(f))
