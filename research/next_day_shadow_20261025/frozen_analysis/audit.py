"""読取専用監査・画像を除いた分析入力の保存。本番Storeは起動しない。"""
import collections, hashlib, json, pickle, sqlite3, sys
from pathlib import Path
import pandas as pd
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]/'database-main'
sys.path.insert(0,str(ROOT/'database'))
import core

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def dump(n,v): (HERE/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def trim(r):
    q={k:v for k,v in r.items() if k not in ['source_graph','source_image','image','preview','curve']}
    if isinstance(q.get('graph_measurement'),dict):
        q['graph_measurement']={k:v for k,v in q['graph_measurement'].items() if k not in ['preview','curve','preview_stored','curve_stored']}
    q['raw_machine']=q['machine'];q['machine']=core.normalize_machine_name(q['machine']);q['rack']=int(q['rack'])
    return q
def main():
    paths=sorted((ROOT/'html_converter/data/normal_analysis').rglob('*.json'))+sorted((ROOT/'html_converter/data/other_analysis').rglob('*.json'))
    dbp=ROOT/'database/data/database.sqlite3'
    protected=paths+[dbp]+list((ROOT/'database').glob('*.py'))+list((ROOT/'database_android/lib').glob('*.dart'))+list((ROOT/'database_android/tool').glob('*focus*.dart'))+list(ROOT.glob('*PLAN*.md'))
    dump('input_hashes_before.json',{str(p):sha(p) for p in protected})
    rows={};raw=[];files=[];dups=[];conflicts=[];field_quality=[]
    def add(r,source):
        q=trim(r);q['source']=source;raw.append(q)
        key=(q['store'],q['day'],q['rack'],q['machine'])
        if key in rows:
            old=rows[key]
            different=[k for k in ['games','bb','rb','at_art','max_hold','net_medals','graph_measurement'] if old.get(k)!=q.get(k)]
            (dups if old['source']==source else conflicts).append(dict(key=key,old=old['source'],new=source,different='|'.join(different)))
        rows[key]=q
    for p in paths:
        o=json.loads(p.read_text(encoding='utf-8'));source='normal_archive' if 'normal_analysis' in str(p) else 'other_archive'
        recs=o['records']; files.append(dict(path=str(p),format=o.get('format'),exported_at=o.get('exported_at'),rows=len(recs),first=min(r['day'] for r in recs),last=max(r['day'] for r in recs)))
        for r in recs:add(r,source)
    snapshots=[];dbrows=[]
    with sqlite3.connect(dbp.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        for s,d,m,r,payload in db.execute('SELECT store,day,machine,rack,payload FROM days ORDER BY store,day,machine,rack'):
            q=json.loads(payload);q.update(store=s,day=d,machine=m,rack=r);add(q,'database');dbrows.append(trim(q))
        for s,d,m,t,payload in db.execute('SELECT * FROM candidate_snapshots'):
            q=json.loads(payload);q.update(store=s,day=d,machine=m,taken_at=t);snapshots.append(q)
        obs_schema=db.execute('PRAGMA table_info(observations)').fetchall()
        obs_count=db.execute('SELECT count(*) FROM observations').fetchone()[0]
        states=[dict(key=k,length=len(v),event_value=v if 'event' in k else None) for k,v in db.execute('SELECT * FROM app_state')]
    # 同日の同台番でDBとアーカイブの名前が違う場合、現行DBの機種を優先する。
    dbslots=collections.defaultdict(set)
    for r in dbrows:dbslots[(r['store'],r['day'],r['rack'])].add(r['machine'])
    shadow=[]
    for k,r in list(rows.items()):
        names=dbslots.get(k[:3])
        if r['source']!='database' and names and r['machine'] not in names:shadow.append(r);del rows[k]
    slots=collections.Counter((r['store'],r['day'],r['rack']) for r in rows.values())
    ambiguous=[r for r in rows.values() if slots[(r['store'],r['day'],r['rack'])]>1]
    merged=[r for r in rows.values() if slots[(r['store'],r['day'],r['rack'])]==1]
    def compact(r):
        g=r.get('graph_measurement') or {}
        return {**{k:r.get(k) for k in ['store','day','rack','machine','raw_machine','source','games','bb','rb','at_art','max_hold','net_medals','jo_net','captured_at','observed_at','source_site','source_url','source_sha256']},'graph':bool(g),'graph_method':g.get('method'),'bad':core.implausible_numbers(r) or any((r.get(k) or 0)<0 for k in ['games','bb','rb','max_hold'])}
    f=pd.DataFrame([compact(r) for r in raw]);m=pd.DataFrame([compact(r) for r in merged])
    quality=[]
    for (s,src),x in f.groupby(['store','source']):
        q=dict(store=s,source=src,rows=len(x),days=x.day.nunique(),first=x.day.min(),last=x.day.max(),bad=int(x.bad.sum()),zero=int(x.games.eq(0).sum()),low500=int(x.games.between(1,500).sum()),low2000=int(x.games.between(1,1999).sum()),graph=int(x.graph.sum()))
        for k in ['games','bb','rb','at_art','max_hold','net_medals','jo_net','captured_at','observed_at','source_url','source_sha256']:
            q[k+'_null']=int(x[k].isna().sum());q[k+'_888']=int(x[k].eq(888).sum())
        quality.append(q)
    pd.DataFrame(quality).to_csv(HERE/'source_quality.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(files).to_csv(HERE/'source_files.csv',index=False,encoding='utf-8-sig')
    m.groupby(['store','source','machine']).agg(first=('day','min'),last=('day','max'),days=('day','nunique'),rows=('rack','size'),racks=('rack','nunique')).reset_index().to_csv(HERE/'inventory_by_machine.csv',index=False,encoding='utf-8-sig')
    counts=m.groupby(['store','day','machine']).rack.nunique().rename('racks').reset_index();counts.to_csv(HERE/'installation_daily.csv',index=False,encoding='utf-8-sig')
    changes=[]
    for (s,rack),x in m.sort_values('day').groupby(['store','rack']):
        prev=None
        for r in x.to_dict('records'):
            if prev and prev['machine']!=r['machine']:changes.append(dict(store=s,rack=rack,previous_day=prev['day'],day=r['day'],before=prev['machine'],after=r['machine']))
            prev=r
    pd.DataFrame(changes).to_csv(HERE/'rack_machine_changes.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(dups).to_csv(HERE/'duplicates.csv',index=False,encoding='utf-8-sig');pd.DataFrame(conflicts).to_csv(HERE/'overlap_conflicts.csv',index=False,encoding='utf-8-sig')
    f[f.bad|f.bb.eq(888)|f.rb.eq(888)|f.at_art.eq(888)].to_csv(HERE/'abnormal_rows.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame([compact(r) for r in ambiguous]).to_csv(HERE/'ambiguous_slots.csv',index=False,encoding='utf-8-sig')
    m.groupby(['store','source','graph_method'],dropna=False).size().rename('rows').reset_index().to_csv(HERE/'provenance.csv',index=False,encoding='utf-8-sig')
    gaps={s:sorted(set(pd.date_range(x.day.min(),x.day.max()).strftime('%Y-%m-%d'))-set(x.day)) for s,x in m.groupby('store')}
    summary=dict(quality=quality,merged=m.groupby('store').agg(first=('day','min'),last=('day','max'),days=('day','nunique'),rows=('rack','size'),machines=('machine','nunique')).to_dict('index'),duplicates=len(dups),conflicting_duplicates=sum(bool(x['different']) for x in dups),overlaps=len(conflicts),numeric_overlap_conflicts=sum(any(k in x['different'].split('|') for k in ['games','bb','rb']) for x in conflicts),shadowed_rows=len(shadow),ambiguous_rows=len(ambiguous),gaps=gaps,snapshots=len(snapshots),observation_rows=obs_count,observation_schema=obs_schema,states=states)
    dump('audit.json',summary)
    with (HERE/'inputs.pkl').open('wb') as f:pickle.dump(dict(rows=merged,database=dbrows,snapshots=snapshots),f)
    # DB現物だけの固定計画用入力。アーカイブを当時の入力へ混ぜない。
    dump('database_input.json',dict(format='database-backup',exported_at='2026-10-25 analysis-readonly-export',records=dbrows,candidate_snapshots=snapshots))
    print(json.dumps({k:summary[k] for k in ['merged','duplicates','conflicting_duplicates','numeric_overlap_conflicts','shadowed_rows','ambiguous_rows','gaps','snapshots','observation_rows']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
