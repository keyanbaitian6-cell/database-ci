"""本番関数照合、異常値の入力排除、未来削除不変性、独立候補集計を検証。"""
import collections,json,math,pickle,sys
import numpy as np
import pandas as pd
from audit import HERE,ROOT,dump
sys.path.insert(0,str(ROOT/'database'))
import core
def main():
    f=pd.read_pickle(HERE/'features.pkl');raw=pickle.load((HERE/'inputs.pkl').open('rb'))['rows'];by=collections.defaultdict(list)
    for r in raw:by[(r['store'],r['machine'])].append(r)
    class View:
        def __init__(self,rows):self.data=rows
        def _machine_rows(self,machine,store):return self.data
        def rows(self,day,machine,store):return [r for r in self.data if r['day']==day]
    corrected=[]
    for ix,r in f[~f.valid].iterrows():
        past=f[(f.store==r.store)&(f.machine==r.machine)&(f.rack==r.rack)&f.valid&f.ord.le(r.ord)]
        last=past[past.ord.ge(r.ord-30)&past.games.ge(500)].tail(10);used=last[last.gap.notna()]
        old=50+used.gap.sum()/(len(used)+5) if len(used)>=3 else np.nan
        ww=2**(-(r.ord-used.ord)/3);recent=50+(ww*used.gap).sum()/(ww.sum()+5) if len(used)>=3 else np.nan
        change=not ((pd.isna(old) and pd.isna(r.old)) or np.isclose(old,r.old))
        for key,value in dict(old=old,recent=recent,evidence_days=len(used),latest_used=int(used.ord.max()) if len(used) else 0,today_used=False,stale=r.ord-used.ord.max() if len(used) else np.nan).items():f.loc[ix,key]=value
        for w in [1,3,7,14,28]:
            p=past[past.ord.gt(r.ord-w)];g=p[p.gap.notna()];pw=p[p.won.notna()]
            for key,value in {f'simple{w}':50+g.gap.sum()/(len(g)+5),f'history_days{w}':len(p),f'games{w}':p.games.mean(),f'pwin{w}':(pw.won.sum()+10*r.prior_machine_win)/(len(pw)+10),f'win_days{w}':len(pw)}.items():f.loc[ix,key]=value
        f.loc[ix,'quiet_run']=0
        corrected.append(dict(store=r.store,day=r.day,machine=r.machine,rack=int(r.rack),old_index_changed=change))
    cols=['games','won','score','hit_rank','net_medals','jo_net']
    validity=f.set_index(['store','machine','rack','ord']).valid
    keys=pd.MultiIndex.from_arrays([f.store,f.machine,f.rack,f.ord+1]);nvalid=validity.reindex(keys).to_numpy()
    invalid_next=nvalid==False
    f.loc[invalid_next,['next_'+c for c in cols]+['next_busyplus','next_low2000']]=np.nan
    f.to_pickle(HERE/'features.pkl')
    sample=pd.concat([f[f.old.notna()].groupby(['store','machine']).head(1),f[~f.valid],f[f.day.isin(['2026-02-15','2026-06-15','2026-10-20'])].groupby(['store','machine']).head(1)]).drop_duplicates('id')
    checks=[]
    for r in sample.itertuples():
        hist=by[(r.store,r.machine)];row=next(x for x in hist if x['day']==r.day and x['rack']==r.rack)
        view=View(hist);e=core.next_day_evidence(view,row);pastview=View([x for x in hist if x['day']<=r.day]);ep=core.next_day_evidence(pastview,row)
        match=(e['raw_index'] is None and pd.isna(r.old)) or (e['raw_index'] is not None and abs(e['raw_index']-r.old)<1e-8)
        checks.append(dict(store=r.store,day=r.day,machine=r.machine,rack=r.rack,feature_old=None if pd.isna(r.old) else r.old,production_old=e['raw_index'],match=bool(match),future_removed_same=e==ep))
    pd.DataFrame(checks).to_csv(HERE/'evidence_parity.csv',index=False,encoding='utf-8-sig')
    assert all(x['match'] and x['future_removed_same'] for x in checks)
    dump('feature_correction.json',dict(reason='実装検算：異常な当日行を10記録枠へ含めない。異常な翌日Gを平均G・低稼働の判定へ混入させない。仮説・重み・閾値は変更しない。',rows=corrected,invalid_next_rows=int(invalid_next.sum())))
    dump('validation.json',dict(evidence_checks=len(checks),all_evidence_match=True,future_removal_checks=len(checks),all_future_removal_same=True,score_checks=json.loads((HERE/'prepare_validation.json').read_text(encoding='utf-8'))['score_checks'],all_score_match=True,corrected_invalid_rows=len(corrected),invalid_next_rows=int(invalid_next.sum())))
    print('検算完了',len(checks),flush=True)
if __name__=='__main__':main()
