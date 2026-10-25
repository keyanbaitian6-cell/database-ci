"""過去情報だけの特徴とD+1の結果を分離して構築。独立v12計算を本番関数と照合。"""
import collections, json, math, pickle, sys, unicodedata
from datetime import date
import numpy as np
import pandas as pd
from audit import HERE,ROOT,dump
sys.path.insert(0,str(ROOT/'database'))
import core

KNOWN_OTHER=['新ハナビ','バーサスリヴァイズ','ニューゲッターマウス','サンダーVライトニング','ニューパルサーSP4','ニューパルサーBT','LBAREXBRIGHTBA']
SUSPECT=['クランキー','クレア','ディスクアップ','ハイパーラッシュ','ガメラ','マタドール','ハーレムエース','ネオプラネット','不二子BT','シェイクボーナストリガー','スマスロサンダー','うみねこ','ハナビ','異世界かるてっと']
def category(name):
    n=unicodedata.normalize('NFKC',name)
    if 'ジャグラー' in n:return 'juggler'
    if 'ハナハナ' in n:return 'hanahana_or_BT'
    if any(unicodedata.normalize('NFKC',x) in n for x in KNOWN_OTHER):return 'known_A_RT_BT'
    if any(x in n for x in SUSPECT) or n.startswith('LB') or n.startswith('★LB'):return 'type_needs_confirmation'
    return 'remaining_type_unverified'
def valid(r):
    return not core.implausible_numbers(r) and all(r.get(k) is not None and r[k]>=0 for k in ['games','bb','rb'])
def won(r):
    if not valid(r) or r['games']==0:return np.nan
    for k in ['net_medals','jo_net']:
        x=r.get(k)
        if isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x):return float(x>0)
    g=r.get('graph_measurement') or {}
    try:
        e=float(g['baseline_y'])-float(g['end_y'])
        if math.isfinite(e):return float(e>1)
    except (KeyError,TypeError,ValueError):pass
    if core.no_hits(r) and not (r.get('at_art') or 0):return 0.
    return np.nan
def percent(x,v):return ((v<x).sum()+.5*(v==x).sum())/len(v)
def adjusted(x,refs,days,g,maximum):
    if not len(refs) or not np.isfinite(x):return np.nan
    w=(g/(g+1500)*len(refs)/(len(refs)+20)*len(set(days))/(len(set(days))+3))**(1/3)
    return maximum*(.5+w*(percent(x,refs)-.5))
def prepare(data=None,prefix='',include_jh=False):
    data=data if data is not None else pickle.load((HERE/'inputs.pkl').open('rb'));rows=data['rows']
    # J/Hは既存検証を再計算しない。その他の同定済みA/RT/BTと要同定群を別枠で保持。
    rows=[r for r in rows if include_jh or category(r['machine']) not in ['juggler','hanahana_or_BT']]
    rows.sort(key=lambda r:(r['store'],r['machine'],r['day'],r['rack']))
    checks=[];records=[];groups=collections.defaultdict(list)
    for rid,r in enumerate(rows):r['_id']=rid;groups[(r['store'],r['machine'])].append(r)
    for gi,((s,m),hist) in enumerate(groups.items()):
        ords=np.array([date.fromisoformat(r['day']).toordinal() for r in hist]);games=np.array([r.get('games') or 0 for r in hist],float)
        val=np.array([valid(r) for r in hist]);rates=np.array([(r['bb']+r['rb'])/r['games'] if valid(r) and r['games'] else np.nan for r in hist])
        holds=np.array([r['max_hold'] if r.get('max_hold') is not None else np.nan for r in hist],float);wins=np.array([won(r) for r in hist])
        byday=collections.defaultdict(list)
        for i,r in enumerate(hist):byday[r['day']].append(i)
        rackhist=collections.defaultdict(list)
        for day,ii in sorted(byday.items()):
            o=date.fromisoformat(day).toordinal();g=games[ii];rate=rates[ii];v=val[ii]
            gaps=np.full(len(ii),np.nan);ranks=np.full(len(ii),np.nan)
            for j,i in enumerate(ii):
                peers=v&(g>=500)&(g>=g[j]/2)&(g<=g[j]*2)
                if val[i] and g[j]>=500 and peers.sum()>=3:gaps[j]=(100*percent(rate[j],rate[peers])-50)*g[j]/(g[j]+1500)
                peers2=v&(g>=2000)&(g>=g[j]/2)&(g<=g[j]*2)
                if val[i] and g[j]>=2000 and peers2.sum()>=3:ranks[j]=100*percent(rate[j],rate[peers2])
            last30=np.where((ords>=o-30)&(ords<o))[0]
            prior90=(ords>=o-90)&(ords<o)&np.isfinite(wins)
            p0=float(wins[prior90].mean()) if prior90.any() else .5
            for j,i in enumerate(ii):
                r=hist[i];rankscore=np.nan
                if val[i] and games[i]>500:
                    target=max(500,games[i]);refs=last30[(games[last30]>=max(500,target/2))&(games[last30]<=target*2)&val[last30]]
                    hit=adjusted(rates[i],rates[refs],ords[refs],games[i],60)
                    hr=refs[np.isfinite(holds[refs])&(holds[refs]>=0)]
                    hold=adjusted(holds[i],holds[hr],ords[hr],games[i],20)
                    if np.isfinite(hold):hold=max(hold,20*min(1,holds[i]/19000))
                    pos=ret=np.nan
                    try:
                        if core.graph_not_needed(r):pos=ret=0.
                        elif r.get('graph_measurement'):
                            met=core.measurement_metrics(r['graph_measurement']);pos=met['positive_score'];ret=met['retention_score']
                        elif r.get('graph'):
                            met=core.graph_metrics(r['graph']['path'],r['graph']['baseline']);pos=met['positive_score'];ret=met['retention_score']
                    except (ValueError,TypeError,KeyError):pass
                    values=[hit,hold,pos,ret];maxes=[60,20,10,10]
                    rankscore=core.round_score(sum(float(x) if x is not None and np.isfinite(x) else mx/2 for x,mx in zip(values,maxes)))
                # 本番v12との点検対象は機種の初日・中盤・最終日、最大約700件。
                if j==0 and (day==min(byday) or day==max(byday) or gi%11==0 and day.endswith('-15')):
                    ref=[hist[z] for z in last30];actual=core.score(r,ref)['total']
                    checks.append(dict(store=s,machine=m,day=day,independent=None if not np.isfinite(rankscore) else rankscore,production=actual,match=(actual is None and not np.isfinite(rankscore)) or (actual is not None and abs(rankscore-actual)<1e-8)))
                rh=rackhist[r['rack']]
                # 当日の記録も入力に含む。500G未満の日は旧方式の10記録枠を消費しない。
                current=dict(ord=o,games=games[i],gap=gaps[j],won=wins[i],day=day)
                allhist=rh+([current] if val[i] else [])
                latest=[x for x in allhist if x['ord']>=o-30 and x['games']>=500][-10:]
                usable=[x for x in latest if np.isfinite(x['gap'])]
                old=50+sum(x['gap'] for x in usable)/(len(usable)+5) if len(usable)>=3 else np.nan
                ww=[2**(-(o-x['ord'])/3) for x in usable]
                recent=50+sum(w*x['gap'] for w,x in zip(ww,usable))/(sum(ww)+5) if len(usable)>=3 else np.nan
                # 同機種の過去30日・近いGと比較した当日の当たり順位（現行バラエティ）。
                refs=last30[(games[last30]>=max(500,max(500,games[i])/2))&(games[last30]<=max(500,games[i])*2)&val[last30]]
                vp=100*percent(rates[i],rates[refs]) if games[i]>0 and np.isfinite(rates[i]) and len(refs)>=3 else np.nan
                state=core.variety_state(r) if val[i] else 'invalid'
                q=dict(id=r['_id'],store=s,day=day,ord=o,machine=m,rack=r['rack'],source=r['source'],category=category(m),valid=bool(val[i]),games=games[i],bb=r.get('bb'),rb=r.get('rb'),at_art=r.get('at_art'),won=wins[i],score=rankscore,hit_rank=ranks[j],gap=gaps[j],old=old,recent=recent,evidence_days=len(usable),latest_used=usable[-1]['ord'] if usable else 0,today_used=bool(usable and usable[-1]['ord']==o),stale=o-usable[-1]['ord'] if usable else np.nan,variety_percent=core.round_score(vp) if np.isfinite(vp) else 50.,variety_refs=len(refs),state=state,captured_at=r.get('captured_at'),observed_at=r.get('observed_at'),prior_machine_win=p0,net_medals=r.get('net_medals'),jo_net=r.get('jo_net'))
                for w in [1,3,7,14,28]:
                    past=[x for x in allhist if x['ord']>o-w]
                    usablew=[x['gap'] for x in past if np.isfinite(x['gap'])]
                    q['simple'+str(w)]=50+sum(usablew)/(len(usablew)+5)
                    q['history_days'+str(w)]=len(past)
                    q['games'+str(w)]=sum(x['games'] for x in past)/len(past) if past else np.nan
                    pw=[x['won'] for x in past if np.isfinite(x['won'])]
                    q['pwin'+str(w)]=(sum(pw)+10*p0)/(len(pw)+10)
                    q['win_days'+str(w)]=len(pw)
                q['quiet_run']=0
                for x in reversed(allhist):
                    if x['ord']!=o-q['quiet_run'] or x['games']>=500:break
                    q['quiet_run']+=1
                records.append(q)
                if val[i]:rh.append(current)
        if gi%35==0:print('準備',gi+1,'/',len(groups),s,m,flush=True)
    f=pd.DataFrame(records)
    # 保存された機種名を維持し、翌暦日・同じ店・機種・台番だけに結合する。
    result_cols=['games','won','score','hit_rank','net_medals','jo_net']
    labels=f[['store','machine','rack','ord']+result_cols].copy();labels['ord']-=1;labels=labels.rename(columns={x:'next_'+x for x in result_cols})
    labels.loc[~f.valid.to_numpy(),['next_'+x for x in result_cols]]=np.nan
    n=len(f);f=f.merge(labels,on=['store','machine','rack','ord'],how='left',validate='one_to_one');assert len(f)==n
    f['label_day']=pd.to_datetime(f.day)+pd.Timedelta(days=1)
    f['next_busyplus']=np.where(f.next_games.notna()&f.next_won.notna(),((f.next_games>=3000)&(f.next_won==1)).astype(float),np.nan)
    f['next_low2000']=np.where(f.next_games.notna(),(f.next_games<2000).astype(float),np.nan)
    # 台数は除外前の全機種の原記録で決定。A/RT等を除いて母集団を作り替えない。
    full=pd.DataFrame([{k:r[k] for k in ['store','day','machine','rack']} for r in data['rows']])
    count=full.groupby(['store','day','machine']).rack.nunique().rename('installed').reset_index();f=f.merge(count,on=['store','day','machine'],how='left',validate='many_to_one')
    f['variety_limit']=np.where(f.store.eq('saiwaichou'),2,3);f['is_variety']=f.installed<=f.variety_limit
    f.to_pickle(HERE/(prefix+'features.pkl'))
    f.groupby(['store','category']).agg(first=('day','min'),last=('day','max'),days=('day','nunique'),rows=('id','size'),machines=('machine','nunique')).reset_index().to_csv(HERE/(prefix+'type_scope.csv'),index=False,encoding='utf-8-sig')
    pd.DataFrame(checks).to_csv(HERE/(prefix+'score_parity.csv'),index=False,encoding='utf-8-sig');assert all(x['match'] for x in checks)
    dump(prefix+'prepare_validation.json',dict(rows=len(f),unique_ids=int(f.id.nunique()),next_day_join='exact calendar D+1, same store machine rack',score_checks=len(checks),all_score_checks_match=True,first=f.day.min(),last=f.day.max(),candidate_features_use_latest_day='D, no D+1',type_unverified=True))
    print('準備完了',len(f),'採点照合',len(checks),flush=True)
if __name__=='__main__':prepare()
