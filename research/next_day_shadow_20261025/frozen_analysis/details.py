"""不確実性・欠測感度・タイプ別・保存履歴・具体例の補足集計。"""
import collections,json,math
import numpy as np
import pandas as pd
from audit import HERE,dump
from evaluate import resample

def sign_p(ds,rounds=4999):
    ds=ds.dropna().sort_index();ds.index=pd.to_datetime(ds.index)
    block=((ds.index-ds.index.min()).days//5)
    sums=ds.groupby(block).sum().to_numpy();obs=abs(sums.sum())
    if len(sums)<4:return np.nan
    rng=np.random.default_rng(20261025);null=np.abs(rng.choice([-1,1],size=(rounds,len(sums)))@sums)
    return (1+np.count_nonzero(null>=obs-1e-12))/(rounds+1)

def main():
    features=pd.concat([pd.read_pickle(HERE/'features.pkl'),pd.read_pickle(HERE/'pstation_features.pkl')],ignore_index=True).set_index('id',drop=False)
    summaries=[];effects=[];monthly=[];groups=[];sels=[]
    for prefix in ['', 'pstation_']:
        a=pd.read_csv(HERE/(prefix+'group_metrics.csv.gz'));p=pd.read_csv(HERE/(prefix+'selections.csv.gz'));e=pd.read_csv(HERE/(prefix+'effects.csv'));d=pd.read_csv(HERE/(prefix+'daily.csv.gz'))
        # p値は暦日5日ブロックの符号反転。区間とは異なる探索的検定である。
        for i,r in e.iterrows():
            x=d[(d.store==r.store)&(d.kind==r.kind)&(d.stage==r.stage)&(d.method==r.method)&(d.metric==r.metric)]
            ds=x.set_index(pd.to_datetime(x.day)).difference;e.loc[i,'p_block_sign']=sign_p(ds)
        e['p_block_sign_holm']=np.nan
        for keys,g in e.groupby(['store','kind','stage','metric']):
            v=g[g.p_block_sign.notna()].sort_values('p_block_sign');e.loc[v.index,'p_block_sign_holm']=np.minimum(1,np.maximum.accumulate(v.p_block_sign.to_numpy()*np.arange(len(v),0,-1)))
        e.to_csv(HERE/(prefix+'effects.csv'),index=False,encoding='utf-8-sig')
        # 無作為方式では、判定台が少ないと一度も判定台を選ばない確率がある。
        def random_any(r,c):
            if r.selected<=0 or r.pool_size<=0:return 0.
            n=int(r.pool_size);k=int(round(r.selected));m=int(round(r[c+'_n']*n/k))
            return 1. if n-m<k else 1-math.comb(n-m,k)/math.comb(n,k)
        a['score_any_probability']=[random_any(r,'score') if r.method=='random' else float(r.score_n>0) for _,r in a.iterrows()]
        a['won_any_probability']=[random_any(r,'won') if r.method=='random' else float(r.won_n>0) for _,r in a.iterrows()]
        ss=pd.read_csv(HERE/(prefix+'comparison.csv'))
        for i,r in ss.iterrows():
            x=a[(a.store==r.store)&(a.kind==r.kind)&(a.stage==r.stage)&(a.method==r.method)]
            ss.loc[i,'expected_groups_scorable']=x.score_any_probability.sum();ss.loc[i,'expected_groups_win_judged']=x.won_any_probability.sum();ss.loc[i,'selection_days']=x[x.selected.gt(0)].day.nunique();ss.loc[i,'selection_day_rate']=x[x.selected.gt(0)].day.nunique()/x.day.nunique();ss.loc[i,'net_medals_n']=x.net_medals_n.sum()
        ss.to_csv(HERE/(prefix+'comparison.csv'),index=False,encoding='utf-8-sig')
        summaries.append(ss);effects.append(e);groups.append(a);sels.append(p)
        monthly.append(pd.read_csv(HERE/(prefix+'monthly.csv')))
    summary=pd.concat(summaries,ignore_index=True);effect=pd.concat(effects,ignore_index=True);selection=pd.concat(sels,ignore_index=True)
    summary.to_csv(HERE/'all_comparison.csv',index=False,encoding='utf-8-sig');effect.to_csv(HERE/'all_effects.csv',index=False,encoding='utf-8-sig');pd.concat(monthly).to_csv(HERE/'all_monthly.csv',index=False,encoding='utf-8-sig')
    chosen=[]
    for prefix in ['', 'pstation_']:
        lock=json.loads((HERE/(prefix+'selection_lock.json')).read_text(encoding='utf-8'))
        for r in lock['locks']:
            s,kind,method=r['store'],r['kind'],r['method'];e=effect[(effect.store==s)&(effect.kind==kind)&effect.stage.eq('confirmation')&effect.method.eq(method)&effect.metric.eq('won')]
            if len(e):chosen.append({**r,**e.iloc[0].to_dict()})
    pd.DataFrame(chosen).to_csv(HERE/'selected_method_confirmation.csv',index=False,encoding='utf-8-sig')
    repeat=[]
    for (s,kind,method),g in selection.groupby(['store','kind','method']):
        prev=None;prior=set();den=num=0
        for day,x in g.groupby('day'):
            d=pd.Timestamp(day);now=set(zip(x.machine,x.rack))
            if prev is not None and (d-prev).days==1:den+=len(now);num+=len(now&prior)
            prev=d;prior=now
        repeat.append(dict(store=s,kind=kind,method=method,comparable_candidates=den,repeated=num,repeat_rate=num/den if den else np.nan,stale3_rate=g.stale.ge(3).mean(),selection_rows=len(g)))
    pd.DataFrame(repeat).to_csv(HERE/'repeat_and_stale.csv',index=False,encoding='utf-8-sig')
    selection=selection.merge(features.drop(columns=['store','day','machine','rack','category','stale']).reset_index(drop=True),on='id',how='left',validate='many_to_one')
    # タイプが異なる群の成績を分ける。P-STATIONの当たり順位はprofileによりMY順位。
    selection['stage']=[('confirmation' if (d>='2026-07-01' if s=='saiwaichou' else d>='2026-09-30') else 'other') for s,d in zip(selection.store,selection.day)]
    selection.groupby(['store','kind','category','stage','method']).agg(selected=('id','size'),judged=('next_won','count'),plus=('next_won','mean'),scored=('next_score','count'),score=('next_score','mean'),next_games=('next_games','mean')).reset_index().to_csv(HERE/'selected_type_comparison.csv',index=False,encoding='utf-8-sig')
    sensitivity=[]
    for (s,kind),x in selection[selection.stage.eq('confirmation')].groupby(['store','kind']):
        for mode in ['all_known','G2000_known']:
            z=x if mode=='all_known' else x[x.next_games.ge(2000)]
            daily=z.groupby(['day','group','method']).next_won.mean().unstack('method')
            if 'current' not in daily:continue
            for method in daily.columns:
                if method=='current':continue
                ds=(daily[method]-daily.current).groupby(level='day').mean().dropna();ds.index=pd.to_datetime(ds.index)
                if len(ds):
                    lo,hi,p=resample(ds,5);sensitivity.append(dict(store=s,kind=kind,method=method,mode=mode,days=len(ds),difference=ds.mean(),low=lo,high=hi))
    pd.DataFrame(sensitivity).to_csv(HERE/'low_activity_sensitivity.csv',index=False,encoding='utf-8-sig')
    # 結果を見てよい台を選ばず、各店の最後の予測日を固定して設計例を出す。
    examples=[]
    for r in chosen:
        x=selection[(selection.store==r['store'])&(selection.kind==r['kind'])&selection.method.isin(['current',r['method']])]
        if len(x):examples.append(x[x.day.eq(x.day.max())].sort_values(['method','group','rank']).head(24))
    if examples:
        pd.concat(examples)[['store','day','kind','group','method','rank','machine','rack','old','recent','simple1','pwin7','pwin14','pwin28','next_won','next_games']].to_csv(HERE/'design_examples.csv',index=False,encoding='utf-8-sig')
    # 3台等の「表示されるが候補なし」範囲。
    a=features.reset_index(drop=True);blind=a[~a.is_variety&a.installed.lt(4)].groupby(['store','day','machine']).size().reset_index(name='rows');blind.to_csv(HERE/'outside_candidate_scope.csv',index=False,encoding='utf-8-sig')
    # P-STATIONは原名で機種変更を監査。名前の似ている記録を勝手につながない。
    raw=json.loads((HERE/'pstation_input.json').read_text(encoding='utf-8'))['records'];z=pd.DataFrame(raw);changes=[]
    for (s,rate,rack),x in z.sort_values('day').groupby(['store','rate','rack']):
        prev=None
        for r in x[['day','machine','source_site']].to_dict('records'):
            if prev and prev['machine']!=r['machine']:changes.append(dict(store=s,rate=rate,rack=rack,previous_day=prev['day'],day=r['day'],before=prev['machine'],after=r['machine']))
            prev=r
    pd.DataFrame(changes).to_csv(HERE/'pstation_name_changes.csv',index=False,encoding='utf-8-sig')
    dump('details_validation.json',dict(selected_rows=len(selection),unknown_feature_ids=int((~selection.id.isin(features.index)).sum()),old_index_missing_selected_rows=int(selection.old.isna().sum()),random_group_coverage='hypergeometric exact probability, not probability=1 whenever expected judged>0',effect_p='non-overlap 5-calendar-day block sign randomization 4999; Holm per store kind stage metric; exploratory',outside_scope_groups=len(blind),pstation_machine_name_changes=len(changes)))
    print('補足集計完了',len(selection),flush=True)
if __name__=='__main__':main()
