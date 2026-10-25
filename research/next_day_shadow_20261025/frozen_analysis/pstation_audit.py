"""P-STATION専用DBの現物棚卸しと分析用コピー。PscubeStoreは初期化しない。"""
import collections,json,pickle,sqlite3
from audit import HERE,ROOT,sha,dump
import pandas as pd
def main():
    p=ROOT/'database/data/pscube.sqlite3'
    protected=[p]+list((ROOT/'database_android/web/pscube').glob('*.mjs'))+[ROOT/'database/PSCUBE_SCORING.md',ROOT/'database/pscube_import.py']
    dump('pstation_hashes_before.json',{str(p):sha(p) for p in protected if p.exists()})
    with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        rows=[json.loads(x[0]) for x in db.execute('SELECT payload FROM records')]
        machines=[json.loads(x[0]) for x in db.execute('SELECT payload FROM machines')]
        states={k:json.loads(v) if k=='date_events' else v for k,v in db.execute('SELECT * FROM state')}
    rr=[]
    for r in rows:
        q={k:v for k,v in r.items() if k not in ['source_graph','source_probabilities']};rr.append(q)
    dump('pstation_input.json',dict(records=rr,machines=machines))
    f=pd.DataFrame(rows)
    quality=[]
    for keys,x in f.groupby(['store','rate','source_site'],dropna=False):
        q=dict(store=keys[0],rate=keys[1],source=str(keys[2]),rows=len(x),days=x.day.nunique(),first=x.day.min(),last=x.day.max(),machines=x.machine.nunique())
        for k in ['games','bb','rb','at_art','my','net_medals','graph','observed_at']:
            q[k+'_null']=int(x[k].isna().sum());q[k+'_888']=int(x[k].eq(888).sum()) if k!='graph' else 0
        q['zero_games']=int(x.games.eq(0).sum());q['low2000']=int(x.games.between(1,1999).sum())
        quality.append(q)
    pd.DataFrame(quality).to_csv(HERE/'pstation_quality.csv',index=False,encoding='utf-8-sig')
    f.groupby(['store','rate','machine','source_site'],dropna=False).agg(first=('day','min'),last=('day','max'),rows=('rack','size'),days=('day','nunique')).reset_index().to_csv(HERE/'pstation_inventory.csv',index=False,encoding='utf-8-sig')
    native=f[f.source_site.ne('anaslo')];gaps=sorted(set(pd.date_range(native.day.min(),native.day.max()).strftime('%Y-%m-%d'))-set(native.day))
    dup=f.duplicated(['store','rate','day','rack'],keep=False)
    f[dup].drop(columns=['graph','source_graph','source_probabilities'],errors='ignore').to_csv(HERE/'pstation_duplicate_slots.csv',index=False,encoding='utf-8-sig')
    dump('pstation_audit.json',dict(quality=quality,native_gaps=gaps,duplicate_slot_rows=int(dup.sum()),current_profile_metadata='machines table at audit time; history of type edits unavailable',events=states.get('date_events'),native_sample=next((r for r in rr if r.get('source_site')!='anaslo'),None),supplement_policy='anaslo source excluded from native scoring/candidates'))
    print(json.dumps(dict(quality=quality,gaps=gaps,duplicates=int(dup.sum())),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
