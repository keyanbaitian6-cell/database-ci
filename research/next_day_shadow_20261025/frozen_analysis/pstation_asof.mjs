// 予測締切以前のobserved_atがあるP-STATION記録だけを使う再現。保存予測の実績ではない。
import fs from 'node:fs';import path from 'node:path';import{fileURLToPath,pathToFileURL}from'node:url';
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(here,'../../database-main');
const{nextDayCandidates,nextDayEvidence,scoreRecord,graphMetrics,dayShift}=await import(pathToFileURL(path.join(root,'database_android/web/pscube/scoring.mjs')));
const{machineKey,noHits}=await import(pathToFileURL(path.join(root,'database_android/web/pscube/data.mjs')));
const data=JSON.parse(fs.readFileSync(path.join(here,'pstation_input.json'),'utf8'));data.records=data.records.filter(r=>r.source_site!=='anaslo');
const dateTime=x=>!x?NaN:Date.parse(/(?:Z|[+-]\d\d:\d\d)$/.test(x)?x:x+'+09:00');
const key=r=>JSON.stringify([r.store,r.rate,r.day,r.machine,r.rack]);const byKey=new Map(data.records.map(r=>[key(r),r]));
const win=r=>{if(!r||!r.games)return null;if(Number.isFinite(r.net_medals))return +(r.net_medals>0);const g=graphMetrics(r.graph);return g?+(g.end>1):noHits(r)?0:null;};
const days=[...new Set(data.records.map(r=>r.day))].sort(),groups=[],selections=[];
for(const day of days.slice(0,-1)){
 const cutoff=Date.parse(dayShift(day,1)+'T02:00:00+09:00');
 const records=data.records.filter(r=>r.day<=day&&dateTime(r.observed_at)<cutoff),available={...data,records};
 for(const machine of data.machines){
  const todays=records.filter(r=>machineKey(r)===machineKey(machine)&&r.day===day),fulltoday=data.records.filter(r=>machineKey(r)===machineKey(machine)&&r.day===day);
  if(fulltoday.length<4)continue;
  const app=nextDayCandidates(available,machine,day),pool=todays.map(r=>nextDayEvidence(r,available)).filter(e=>e.rawIndex!=null),k=app.candidates.length;
  const recent=e=>{const u=e.contributions.filter(x=>x.gap!=null);const w=u.map(x=>2**(-(Date.parse(day)-Date.parse(x.day))/86400000/3));return 50+u.reduce((v,x,i)=>v+x.gap*w[i],0)/(w.reduce((a,b)=>a+b,0)+5);};
  const pw=e=>{const hist=records.filter(r=>machineKey(r)===machineKey(e.record)&&r.day>=dayShift(day,-13));const p0=hist.map(win).filter(x=>x!=null),prior=p0.length?p0.reduce((a,b)=>a+b,0)/p0.length:.5;const same=hist.filter(r=>r.rack===e.record.rack).map(win).filter(x=>x!=null);return(same.reduce((a,b)=>a+b,0)+10*prior)/(same.length+10);};
  const sorted=(key,exclude=false)=>pool.filter(e=>!exclude||scoreRecord(e.record,available).total==null||scoreRecord(e.record,available).total<88).sort((a,b)=>key(b)-key(a)||b.record.games-a.record.games||a.record.rack-b.record.rack).slice(0,k);
  for(const[method,picks]of Object.entries({current:app.candidates,random:pool,recent:sorted(recent),primary:sorted(recent,true),pwin14:sorted(pw)})){
   const weight=method==='random'&&pool.length?k/pool.length:1;let judged=0,wins=0,scored=0,score=0,netN=0,net=0;
   for(const e of picks){const r=e.record,n=byKey.get(key({...r,day:dayShift(day,1)})),w=win(n),sc=n?scoreRecord(n,data).total:null;if(w!=null){judged+=weight;wins+=w*weight;}if(sc!=null){scored+=weight;score+=sc*weight;}if(n?.net_medals!=null){netN+=weight;net+=n.net_medals*weight;}if(method!=='random')selections.push({store:`pscube:${r.store}:${r.rate}`,day,machine:r.machine,rack:r.rack,method,observed_at:r.observed_at,cutoff:new Date(cutoff).toISOString()});}
   groups.push({store:`pscube:${machine.store}:${machine.rate}`,day,machine:machine.machine,method,available_rows:todays.length,total_rows:fulltoday.length,eligible:pool.length,selected:picks.length*weight,judged,wins,scored,score_sum:score,net_n:netN,net_sum:net});
  }
 }
}
fs.writeFileSync(path.join(here,'pstation_asof_groups.json'),JSON.stringify(groups));fs.writeFileSync(path.join(here,'pstation_asof_selections.json'),JSON.stringify(selections));
console.log(JSON.stringify({groups:groups.length,selections:selections.length,days:days.length,cutoff:'D+1 02:00 JST',caveat:'latest record timestamps only; earlier overwritten values not restored; not a saved live prediction history'}));
