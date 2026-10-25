"""同じ日・群・候補数での比較と、開発期だけによる方式選択。"""
import argparse, collections, json, math
from pathlib import Path
import numpy as np
import pandas as pd
from audit import HERE,dump,sha

METRICS=['won','score','hit_rank','games','busyplus','low2000','net_medals']
def resample(values,block=5,rounds=4999,seed=20261025):
    s=values.sort_index();start=s.index.min();end=s.index.max()
    arr=s.reindex(pd.date_range(start,end)).to_numpy(float);n=len(arr)
    if n<block or not np.isfinite(arr).any():return (np.nan,np.nan,np.nan)
    rng=np.random.default_rng(seed);draw=rng.integers(0,n-block+1,size=(rounds,math.ceil(n/block)))
    ix=(draw[:,:,None]+np.arange(block)).reshape(rounds,-1)[:,:n]
    aa=arr[ix];means=np.divide(np.nansum(aa,axis=1),np.isfinite(aa).sum(axis=1),out=np.full(rounds,np.nan),where=np.isfinite(aa).sum(axis=1)>0)
    low,high=np.nanquantile(means,[.025,.975]);p=min(1.,2*min((means<=0).mean(),(means>=0).mean()))
    return float(low),float(high),float(p)

def stage(s,d):
    if s=='saiwaichou':
        if '2026-01-01'<=d<='2026-06-29':return 'development'
        if d>='2026-07-01':return 'confirmation'
    else:
        if d<='2026-09-28':return 'development'
        if d>='2026-09-30':return 'confirmation'
    return 'warmup'
def oldsort(x):return x.iloc[np.lexsort((x.rack.to_numpy(),-x.latest_used.to_numpy(),-x.evidence_days.to_numpy(),-x.games.to_numpy(),-x.old_round.to_numpy()))]
def ranksort(x,key):return x.iloc[np.lexsort((x.rack.to_numpy(),-x.games.to_numpy(),-x[key].fillna(-np.inf).to_numpy()))]

def run(features='features.pkl',prefix='',only_variety=False,aggregate_only=False):
    f=pd.read_pickle(HERE/features)
    if 'old_round' not in f:f['old_round']=f.old.round(9)
    last_by_store=f.groupby('store').day.max().to_dict()
    # 結果のある翌日が店舗単位で既に収録された予測日だけ。途中欠測は行を落とさない。
    f=f[[d<last_by_store[s] for s,d in zip(f.store,f.day)]].copy().reset_index(drop=True)
    outcomes=f[['next_'+c for c in METRICS]].to_numpy(float)
    identifiers=f[['id','rack','machine','stale','category']].to_numpy()
    metrics=[];choices=[];poollog=[]
    def group(x,kind,groupname,pool,methods,k):
        s=x.store.iloc[0];d=x.day.iloc[0];st=stage(s,d);cat=x.category.iloc[0] if kind=='ordinary' else 'mixed'
        common=dict(store=s,day=d,stage=st,kind=kind,group=groupname,category=cat,total=len(x),eligible=len(pool),k=k)
        poollog.append({**common,'zero_candidates':int(k==0)})
        for name,picks in methods.items():
            random=name=='random';selected=pool if random else picks
            weight=k/len(pool) if random and len(pool) else 1.
            q={**common,'method':name,'selected':float(len(selected)*weight),'pool_size':len(pool)}
            values=outcomes[selected.index.to_numpy()];nn=np.isfinite(values).sum(axis=0);ss=np.nansum(values,axis=0)
            for j,c in enumerate(METRICS):
                q[c+'_n']=float(nn[j]*weight);q[c+'_sum']=float(ss[j]*weight)
                q[c]=float(ss[j]/nn[j]) if nn[j] else np.nan
            q['unknown']=q['selected']-q['won_n'];q['score_unknown']=q['selected']-q['score_n']
            q['won_lower']=q['won_sum']/q['selected'] if q['selected'] else np.nan
            q['won_upper']=(q['won_sum']+q['unknown'])/q['selected'] if q['selected'] else np.nan
            metrics.append(q)
            if not random:
                for rank,(rid,rack,mach,stale,category) in enumerate(identifiers[selected.index.to_numpy()],1):choices.append(dict(store=s,day=d,kind=kind,group=groupname,method=name,id=rid,rank=rank,rack=rack,machine=mach,stale=stale,category=category))
    ordinary_groups=[] if only_variety or aggregate_only else f.groupby(['store','day','machine'],sort=True)
    for ix,((s,d,m),x) in enumerate(ordinary_groups):
        if ix%3000==0:print('比較グループ作成',ix,s,d,flush=True)
        if x.is_variety.iloc[0]:continue
        pool=x[x.old.notna()].copy();k=math.ceil(len(pool)/4) if len(pool)>=4 else 0
        current=oldsort(pool).head(k)
        methods=dict(current=current,random=pool)
        for w in [1,3,7,14,28]:methods['simple'+str(w)]=ranksort(pool,'simple'+str(w)).head(k)
        methods['recent']=ranksort(pool,'recent').head(k)
        methods['exclude88']=oldsort(pool[pool.score.isna()|pool.score.lt(88)]).head(k)
        methods['primary']=ranksort(pool[pool.score.isna()|pool.score.lt(88)],'recent').head(k)
        for w in [7,14,28]:methods['pwin'+str(w)]=ranksort(pool,'pwin'+str(w)).head(k)
        group(x,'ordinary',m,pool,methods,k)
    variety_groups=[] if aggregate_only else f[f.is_variety].groupby(['store','day'])
    for (s,d),x in variety_groups:
        pool=x[x.valid&x.state.isin(['plus','dented'])].copy()
        preferred='dented' if s=='nagamachiminami' else 'plus'
        pool['state_order']=(pool.state!=preferred).astype(int)
        sortcols=['state_order','variety_percent','games','rack','machine'];asc=[True,False,False,True,True]
        current=pool.sort_values(sortcols,ascending=asc,kind='stable').head(5);k=len(current)
        methods=dict(current=current,random=pool,reverse=pool.sort_values(sortcols,ascending=[False,False,False,True,True],kind='stable').head(k),statefree=ranksort(pool,'variety_percent').head(k),score_today=ranksort(pool,'score').head(k))
        for w in [7,14,28]:methods['pwin'+str(w)]=ranksort(pool,'pwin'+str(w)).head(k)
        group(x,'variety','バラエティ',pool,methods,k)
        allpool=x[x.valid].copy();extended={'current':current,'random':allpool}
        for w in [7,14,28]:extended['pwin'+str(w)]=ranksort(allpool,'pwin'+str(w)).head(k)
        group(x,'variety_all','バラエティ全台拡張',allpool,extended,k)
    if aggregate_only:
        a=pd.read_csv(HERE/(prefix+'group_metrics.csv.gz'));p=pd.read_csv(HERE/(prefix+'selections.csv.gz'));pools=pd.read_csv(HERE/(prefix+'pools.csv.gz'))
    else:a=pd.DataFrame(metrics);p=pd.DataFrame(choices);pools=pd.DataFrame(poollog)
    a.to_csv(HERE/(prefix+'group_metrics.csv.gz'),index=False,encoding='utf-8-sig');p.to_csv(HERE/(prefix+'selections.csv.gz'),index=False,encoding='utf-8-sig');pools.to_csv(HERE/(prefix+'pools.csv.gz'),index=False,encoding='utf-8-sig')
    summary=[]
    for keys,g in a.groupby(['store','kind','stage','method']):
        store,kind,st,method=keys;q=dict(store=store,kind=kind,stage=st,method=method,days=g.day.nunique(),groups=len(g),groups_with_selection=int(g.selected.gt(0).sum()),groups_scorable=int(g.score_n.gt(0).sum()),selected=g.selected.sum(),judged=g.won_n.sum(),scored=g.score_n.sum(),unknown_rate=g.unknown.sum()/g.selected.sum() if g.selected.sum() else np.nan)
        for c in METRICS:q[c]=g[c+'_sum'].sum()/g[c+'_n'].sum() if g[c+'_n'].sum() else np.nan
        q['won_lower']=g.won_sum.sum()/g.selected.sum() if g.selected.sum() else np.nan;q['won_upper']=(g.won_sum.sum()+g.unknown.sum())/g.selected.sum() if g.selected.sum() else np.nan
        summary.append(q)
    summary=pd.DataFrame(summary);summary.to_csv(HERE/(prefix+'comparison.csv'),index=False,encoding='utf-8-sig')
    effects=[];daily=[];monthly=[]
    for (s,kind,st),g in a.groupby(['store','kind','stage']):
        base=g[g.method=='current'];base=base.set_index(['day','group'])
        for method,z in g.groupby('method'):
            if method=='current':continue
            paired=z.set_index(['day','group']).join(base,lsuffix='',rsuffix='_base',validate='one_to_one')
            for c in ['won','score','hit_rank','busyplus','low2000','won_lower','won_upper']:
                gap=paired[c]-paired[c+'_base'];ds=gap.groupby(level='day').mean();ds.index=pd.to_datetime(ds.index);ds=ds.dropna()
                if ds.empty:continue
                lo,hi,p5=resample(ds,5);lo1,hi1,_=resample(ds,1);lo10,hi10,_=resample(ds,10)
                effects.append(dict(store=s,kind=kind,stage=st,method=method,metric=c,days=len(ds),pairs=int(gap.notna().sum()),difference=ds.mean(),low=lo,high=hi,p=p5,day_low=lo1,day_high=hi1,block10_low=lo10,block10_high=hi10,blocks5=len(ds)/5))
                for d,v in ds.items():daily.append(dict(store=s,kind=kind,stage=st,method=method,metric=c,day=d.strftime('%Y-%m-%d'),difference=v))
                for mo,v in ds.groupby(ds.index.to_period('M')):monthly.append(dict(store=s,kind=kind,stage=st,method=method,metric=c,month=str(mo),days=len(v),difference=v.mean()))
    effects=pd.DataFrame(effects)
    # Holmは店舗・区分・段階・指標ごとの、試した方式全体に適用。
    effects['p_holm']=np.nan
    for keys,g in effects.groupby(['store','kind','stage','metric']):
        valid=g[g.p.notna()].sort_values('p');adj=np.maximum.accumulate(valid.p.to_numpy()*np.arange(len(valid),0,-1));effects.loc[valid.index,'p_holm']=np.minimum(1,adj)
    effects.to_csv(HERE/(prefix+'effects.csv'),index=False,encoding='utf-8-sig');pd.DataFrame(daily).to_csv(HERE/(prefix+'daily.csv.gz'),index=False,encoding='utf-8-sig');pd.DataFrame(monthly).to_csv(HERE/(prefix+'monthly.csv'),index=False,encoding='utf-8-sig')
    # 開発期だけでロック。確認期の成績は方式選択に使わない。
    locks=[]
    for (s,kind),g in summary[summary.stage=='development'].groupby(['store','kind']):
        cur=g[g.method=='current'].iloc[0];e=effects[(effects.store==s)&(effects.kind==kind)&(effects.stage=='development')&effects.metric.eq('won')&~effects.method.isin(['random','current'])].copy()
        coverage=g[['method','unknown_rate','scored','selected']].copy();coverage['score_rate']=coverage.scored/coverage.selected.replace(0,np.nan)
        e=e.merge(coverage,on='method');e=e[(e.unknown_rate<=cur.unknown_rate+.02)&(e.score_rate>=cur.scored/cur.selected-.02)].sort_values(['difference','method'],ascending=[False,True])
        chosen=e.iloc[0] if len(e) else None
        locks.append(dict(store=s,kind=kind,method=chosen['method'] if chosen is not None else 'current',development_days=int(chosen['days']) if chosen is not None else 0,development_difference=float(chosen['difference']) if chosen is not None else None,eligible_for_selection=bool(chosen is not None and chosen['days']>=20),reason='development only; insufficient days => provisional, not adopted'))
    dump(prefix+'selection_lock.json',dict(plan_sha=sha(HERE/'計画.md'),features_sha=sha(HERE/features),selection_uses='development only',locks=locks))
    dump(prefix+'evaluation_validation.json',dict(groups=len(pools),metric_rows=len(a),selection_rows=len(p),future_labels_used_for_selection=False,comparison_count=len(effects),prediction_day_max=f.groupby('store').day.max().to_dict(),zero_candidate_groups=int(pools.zero_candidates.sum())))
    print(summary[(summary.stage=='confirmation')&summary.method.isin(['current','random','primary','pwin14'])].to_json(orient='records',force_ascii=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--features',default='features.pkl');parser.add_argument('--prefix',default='');parser.add_argument('--only-variety',action='store_true');parser.add_argument('--aggregate-only',action='store_true');args=parser.parse_args();run(args.features,args.prefix,args.only_variety,args.aggregate_only)
