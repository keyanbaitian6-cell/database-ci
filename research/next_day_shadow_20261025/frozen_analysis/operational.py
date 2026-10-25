"""当時保存した候補の実績と、時刻付き後日再現を区別して集計。"""
import collections,json,pickle
import numpy as np
import pandas as pd
from audit import HERE,dump
from prepare import category
def main():
    data=pickle.load((HERE/'inputs.pkl').open('rb'));f=pd.read_pickle(HERE/'features.pkl')
    labels=f.set_index(['store','day','machine','rack']);slots=f.set_index(['store','day','rack']);latest={};rejected=collections.Counter()
    for x in data['snapshots']:
        if x['machine']!='バラエティ' and category(x['machine']) in ['juggler','hanahana_or_BT']:continue
        try:
            at=pd.Timestamp(x['taken_at']);cutoff=pd.Timestamp(x['day'],tz='Asia/Tokyo')+pd.Timedelta(days=1,hours=2)
            if at.tzinfo is None:at=at.tz_localize('Asia/Tokyo')
        except (ValueError,TypeError,KeyError):rejected['bad_time']+=1;continue
        if at>=cutoff:rejected['after_cutoff']+=1;continue
        if x['day']>='2026-10-24':rejected['no_next_closed_day']+=1;continue
        key=(x['store'],x['day'],x['machine'])
        if key not in latest or at>pd.Timestamp(latest[key]['taken_at']):latest[key]=x
    out=[];rows=[]
    for x in latest.values():
        won=[];score=[];games=[]
        for c in x['candidates']:
            m=c.get('machine') or x['machine']
            if m=='バラエティ':
                try:
                    slot=slots.loc[(x['store'],x['day'],int(c['rack']))]
                    if isinstance(slot,pd.Series):m=slot['machine']
                except KeyError:pass
            key=(x['store'],x['day'],m,int(c['rack']))
            try:r=labels.loc[key]
            except KeyError:r=None
            w=r.next_won if r is not None else np.nan;sc=r.next_score if r is not None else np.nan;g=r.next_games if r is not None else np.nan
            won.append(w);score.append(sc);games.append(g);rows.append(dict(store=x['store'],day=x['day'],group=x['machine'],machine=m,rack=c['rack'],taken_at=x['taken_at'],method=x.get('method','unspecified'),won=w,score=sc,games=g))
        out.append(dict(store=x['store'],day=x['day'],group=x['machine'],taken_at=x['taken_at'],method=x.get('method','unspecified'),selected=len(won),judged=int(np.isfinite(won).sum()),wins=float(np.nansum(won)),scored=int(np.isfinite(score).sum()),score_sum=float(np.nansum(score))))
    a=pd.DataFrame(out);pd.DataFrame(rows).to_csv(HERE/'saved_prediction_rows.csv',index=False,encoding='utf-8-sig');a.to_csv(HERE/'saved_prediction_groups.csv',index=False,encoding='utf-8-sig')
    summaries=[]
    for (s,method),x in a.groupby(['store','method']):
        summaries.append(dict(store=s,method=method,days=x.day.nunique(),groups=len(x),selected=x.selected.sum(),judged=x.judged.sum(),win=x.wins.sum()/x.judged.sum() if x.judged.sum() else None,unknown_rate=1-x.judged.sum()/x.selected.sum() if x.selected.sum() else None))
    pd.DataFrame(summaries).to_csv(HERE/'saved_prediction_summary.csv',index=False,encoding='utf-8-sig')
    op=pd.DataFrame(json.loads((HERE/'pstation_asof_groups.json').read_text(encoding='utf-8')));op.to_csv(HERE/'pstation_asof_groups.csv.gz',index=False,encoding='utf-8-sig')
    summaries=[]
    for (s,method),x in op.groupby(['store','method']):
        summaries.append(dict(store=s,method=method,days=x.day.nunique(),selection_days=x[x.selected.gt(0)].day.nunique(),groups=len(x),selected=x.selected.sum(),judged=x.judged.sum(),win=x.wins.sum()/x.judged.sum() if x.judged.sum() else None,net_n=x.net_n.sum(),net=x.net_sum.sum()/x.net_n.sum() if x.net_n.sum() else None))
    pd.DataFrame(summaries).to_csv(HERE/'pstation_asof_summary.csv',index=False,encoding='utf-8-sig')
    dump('operational_validation.json',dict(saved_groups_before_cutoff=len(latest),rejected=dict(rejected),pstation='No native saved candidate snapshots table exists. observed_at reconstruction is not live prediction history.',saved_inputs='Full historical input versions absent. Saved picks can be scored but pool consistency and input corrections cannot be proved.'))
    print('保存予測の集計完了',len(latest),flush=True)
if __name__=='__main__':main()
