"""数値・候補数・保護対象を独立に再計算し、提出可否を記録。"""
import json,math,pickle
import numpy as np
import pandas as pd
from audit import HERE,sha,dump

def main():
    checks=[];hashdiff=[]
    for name in ['input_hashes_before.json','pstation_hashes_before.json']:
        before=json.loads((HERE/name).read_text(encoding='utf-8'));after={p:sha(__import__('pathlib').Path(p)) for p in before};dump(name.replace('before','after'),after)
        for p,v in before.items():
            if after[p]!=v:hashdiff.append(dict(path=p,before=v,after=after[p]))
    dump('protection_check.json',dict(files_checked=sum(len(json.loads((HERE/x).read_text(encoding='utf-8'))) for x in ['input_hashes_before.json','pstation_hashes_before.json']),changed=hashdiff,all_unchanged=not hashdiff))
    for prefix in ['', 'pstation_']:
        a=pd.read_csv(HERE/(prefix+'group_metrics.csv.gz'));p=pd.read_csv(HERE/(prefix+'selections.csv.gz'));s=pd.read_csv(HERE/(prefix+'comparison.csv'))
        assert not a.duplicated(['store','day','kind','group','method']).any()
        assert (a.selected<=a.k+1e-7).all();assert (a.won_n<=a.selected+1e-7).all();assert (a.score_n<=a.selected+1e-7).all()
        assert (a.won_sum<=a.won_n+1e-7).all()
        counts=p.groupby(['store','day','kind','group','method']).size().rename('actual')
        z=a[a.method.ne('random')].set_index(['store','day','kind','group','method']).join(counts);assert np.allclose(z.actual.fillna(0),z.selected)
        for r in s.itertuples():
            sub=a[(a.store==r.store)&(a.kind==r.kind)&(a.stage==r.stage)&(a.method==r.method)]
            assert abs(sub.selected.sum()-r.selected)<1e-6;assert abs(sub.won_n.sum()-r.judged)<1e-6
            if sub.won_n.sum():assert abs(sub.won_sum.sum()/sub.won_n.sum()-r.won)<1e-10
        checks.append(dict(prefix=prefix,groups=len(a),selected_rows=len(p),counts_match=True,aggregate_win_match=True))
    ev=pd.read_csv(HERE/'evidence_parity.csv');score=pd.read_csv(HERE/'score_parity.csv');pstation=json.loads((HERE/'pstation_candidate_parity.json').read_text(encoding='utf-8'))
    assert ev.match.all() and ev.future_removed_same.all() and score.match.all() and pstation['all_match']
    # 保存候補のラベルはバラエティを同日一意の台番で解決する。復元不能は欠測のまま。
    saved=pd.read_csv(HERE/'saved_prediction_rows.csv');assert saved.won.dropna().isin([0,1]).all()
    # P-STATION締切再現の判定不能は名前変更を含み、同台番というだけで別名を結合しない。
    inp=json.loads((HERE/'pstation_input.json').read_text(encoding='utf-8'))['records'];keys={(r['store'],r['rate'],r['day'],r['machine'],r['rack']) for r in inp if r.get('source_site')!='anaslo'}
    psel=json.loads((HERE/'pstation_asof_selections.json').read_text(encoding='utf-8'));exact=alternative=0
    for r in psel:
        store=r['store'].split(':')[1];rate=r['store'].split(':')[2];day=(pd.Timestamp(r['day'])+pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        if (store,rate,day,r['machine'],r['rack']) in keys:exact+=1
        elif any(k[0]==store and k[1]==rate and k[2]==day and k[4]==r['rack'] for k in keys):alternative+=1
    # 新方式の特徴の未来削除検算（future_check.py）と、ID照合の訂正（details_id_check.py）の保存結果を確かめる。再計算はしない。
    future=json.loads((HERE/'new_features_future_check.json').read_text(encoding='utf-8'));assert future['all_match'] and all(c['all_match'] for c in future['checks'])
    details=json.loads((HERE/'details_validation.json').read_text(encoding='utf-8'));assert details['unknown_feature_ids']==0 and set(details['old_index_missing_by_kind'])<={'variety','variety_all'}
    # 計画の範囲（同定済みA/RT/BTを除く）でも、ロックは変えず結論だけを照合する（plan_scope_check.py）。
    scope=json.loads((HERE/'plan_scope_check.json').read_text(encoding='utf-8'));assert not scope['lock_changed']
    scope_rows=[dict(scope=x['scope'],store=x['store'],locked=x['locked_method'],rule_choice=x['rule_choice_in_scope'],confirmation_difference=x['locked_confirmation_difference'],confirmation_low=x['locked_confirmation_low'],confirmation_high=x['locked_confirmation_high']) for x in scope['selection']]
    result=dict(checks=checks,evidence_cases=len(ev),score_cases=len(score),pstation_native_candidate_groups=pstation['groups'],all_parity=True,protected_unchanged=not hashdiff,pstation_asof_selected_nonrandom_rows=len(psel),pstation_asof_exact_next_identity=exact,pstation_asof_next_slot_different_machine=alternative,
                new_features_future_check=dict(cutoff=future['cutoff'],rows=future['rows'],features=future['features'],all_match=True),
                details_id_check=dict(unknown_feature_ids=details['unknown_feature_ids'],old_index_missing_selected_rows=details['old_index_missing_selected_rows'],by_kind=details['old_index_missing_by_kind']),
                plan_scope_check=scope_rows,
                assessment='制約を明示して共有可。改善確立なし。本番反映なし。')
    dump('report_qa.json',result);assert not hashdiff
    print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
