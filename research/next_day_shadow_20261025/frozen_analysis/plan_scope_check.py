"""計画どおり同定済みA/RT/BTを除いた通常機種で、開発期の選択と確認期の差を照合する。
保存済みgroup_metricsを読むだけ。方式ロックは変更せず、照合結果だけを保存する。"""
import json
import numpy as np
import pandas as pd
from audit import HERE,dump
from evaluate import resample

a=pd.read_csv(HERE/'group_metrics.csv.gz')
a=a[a.kind.eq('ordinary')]
locks={(r['store'],r['kind']):r['method'] for r in json.loads((HERE/'selection_lock.json').read_text(encoding='utf-8'))['locks']}
scopes={'all_reference_included':a,'plan_scope_without_known_A_RT_BT':a[a.category.ne('known_A_RT_BT')],'remaining_type_unverified_only':a[a.category.eq('remaining_type_unverified')]}
rows=[];selection=[]
for scope,x in scopes.items():
    for (s,st),g in x.groupby(['store','stage']):
        if st=='warmup':continue
        base=g[g.method.eq('current')].set_index(['day','group'])
        cur_unknown=base.unknown.sum()/base.selected.sum();cur_score=base.score_n.sum()/base.selected.sum()
        for method,z in g.groupby('method'):
            if method=='current':continue
            p=z.set_index(['day','group']).join(base,rsuffix='_base',validate='one_to_one')
            ds=(p.won-p.won_base).groupby(level='day').mean().dropna();ds.index=pd.to_datetime(ds.index)
            if ds.empty:continue
            lo,hi,_=resample(ds,5)
            sel=z.selected.sum()
            rows.append(dict(scope=scope,store=s,stage=st,method=method,locked=method==locks.get((s,'ordinary')),days=len(ds),selected=sel,difference=ds.mean(),low=lo,high=hi,
                             unknown_rate=z.unknown.sum()/sel if sel else np.nan,score_rate=z.score_n.sum()/sel if sel else np.nan,current_unknown_rate=cur_unknown,current_score_rate=cur_score))
r=pd.DataFrame(rows)
r.to_csv(HERE/'plan_scope_check.csv',index=False,encoding='utf-8-sig')
# 選択規則（判定不能率・採点率の悪化2pp以内、差最大、同値は方式名順）を範囲ごとに当てた場合の参考。
for (scope,s),g in r[r.stage.eq('development')&~r.method.isin(['random'])].groupby(['scope','store']):
    e=g[(g.unknown_rate<=g.current_unknown_rate+.02)&(g.score_rate>=g.current_score_rate-.02)].sort_values(['difference','method'],ascending=[False,True])
    best=e.iloc[0]
    conf=r[(r.scope==scope)&(r.store==s)&(r.stage=='confirmation')&(r.method==locks[(s,'ordinary')])].iloc[0]
    selection.append(dict(scope=scope,store=s,locked_method=locks[(s,'ordinary')],rule_choice_in_scope=best.method,same_as_lock=best.method==locks[(s,'ordinary')],
                          development_days=int(best.days),locked_confirmation_days=int(conf.days),locked_confirmation_selected=float(conf.selected),
                          locked_confirmation_difference=float(conf.difference),locked_confirmation_low=float(conf.low),locked_confirmation_high=float(conf.high)))
dump('plan_scope_check.json',dict(source='group_metrics.csv.gz (saved, not recomputed)',lock_changed=False,note='known_A_RT_BTは計画で主比較から外すとした参考群。ロックは全参考群を含む集約で作成済みのため変更しない。',selection=selection))
print(json.dumps(selection,ensure_ascii=False,indent=1),flush=True)
