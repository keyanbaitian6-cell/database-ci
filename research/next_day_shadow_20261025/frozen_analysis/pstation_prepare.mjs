// P-STATIONは実際の専用候補関数を使用。MYをBB/RBへ置き換えない。
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../../database-main');
const {nextDayEvidence,scoreRecord,profileOf,graphMetrics,implausible,dayShift,nextDayCandidates}=await import(pathToFileURL(path.join(root,'database_android/web/pscube/scoring.mjs')));
const {machineKey,noHits}=await import(pathToFileURL(path.join(root,'database_android/web/pscube/data.mjs')));
const data=JSON.parse(fs.readFileSync(path.join(here,'pstation_input.json'),'utf8'));
const native=data.records.filter(r=>r.source_site!=='anaslo');
const map=new Map();for(const r of native){const k=machineKey(r);if(!map.has(k))map.set(k,[]);map.get(k).push(r);}
const ordinal=d=>Math.floor(Date.parse(d+'T00:00:00Z')/86400000)+719163;
const win=r=>{if(!r.games||implausible(r))return null;if(Number.isFinite(r.net_medals))return Number(r.net_medals>0);const g=graphMetrics(r.graph);if(g)return Number(g.end>1);return noHits(r)?0:null;};
const output=[],checks=[];
let id=1000000;
for(const [key,hist] of map){
  hist.sort((a,b)=>a.day.localeCompare(b.day)||a.rack-b.rack);
  const metadata=data.machines.find(m=>machineKey(m)===key)??hist[0];
  const local={records:hist,machines:[metadata]},profile=profileOf(metadata),rh=new Map(),gaps=new Map();
  const byDay=new Map();for(const r of hist){if(!byDay.has(r.day))byDay.set(r.day,[]);byDay.get(r.day).push(r);}
  for(const [day,rows] of byDay){
    const o=ordinal(day);const prior=hist.filter(r=>r.day<day&&r.day>=dayShift(day,-90)).map(win).filter(x=>x!=null);const p0=prior.length?prior.reduce((a,b)=>a+b,0)/prior.length:.5;
    const ds=[];
    for(const r of rows){
      const e=nextDayEvidence(r,local),score=scoreRecord(r,local).total,own=e.contributions.find(x=>x.day===day),won=win(r);
      const item={ord:o,games:r.games,gap:own?.gap??null,won};const histRack=rh.get(r.rack)??[];const all=[...histRack,item];
      const used=e.contributions.filter(x=>x.gap!=null),weights=used.map(x=>2**(-(o-ordinal(x.day))/3));
      const recent=used.length>=3?50+used.reduce((s,x,i)=>s+x.gap*weights[i],0)/(weights.reduce((a,b)=>a+b,0)+5):null;
      const metric=profile==='normal'?r.bb+r.rb:r.my;const peers=rows.filter(x=>x.games>=2000&&x.games>=r.games/2&&x.games<=r.games*2&&!implausible(x));
      const vals=peers.map(x=>profile==='normal'?(x.bb+x.rb)/x.games:x.my);const xx=profile==='normal'?(r.bb+r.rb)/r.games:r.my;
      const hit_rank=r.games>=2000&&peers.length>=3?100*(vals.filter(v=>v<xx).length+.5*vals.filter(v=>v===xx).length)/vals.length:null;
      const q={id:id++,store:`pscube:${r.store}:${r.rate}`,day,ord:o,machine:r.machine,rack:r.rack,source:'pscube_native',category:profile==='normal'?'pstation_normal_profile':'pstation_other_profile',profile,valid:!implausible(r)&&r.games>=0,games:r.games,bb:r.bb,rb:r.rb,at_art:r.at_art,my:r.my,won,score,hit_rank,gap:own?.gap??null,old:e.rawIndex,recent,evidence_days:e.usedDays,latest_used:e.latestUsed?ordinal(e.latestUsed):0,today_used:e.todayUsed,stale:e.latestUsed?o-ordinal(e.latestUsed):null,variety_percent:50,variety_refs:0,state:'not_used',captured_at:null,observed_at:r.observed_at,prior_machine_win:p0,net_medals:r.net_medals,jo_net:null,installed:rows.length,variety_limit:0,is_variety:false};
      for(const w of [1,3,7,14,28]){const a=all.filter(x=>x.ord>o-w),g=a.filter(x=>x.gap!=null),pw=a.filter(x=>x.won!=null);q['simple'+w]=50+g.reduce((s,x)=>s+x.gap,0)/(g.length+5);q['history_days'+w]=a.length;q['games'+w]=a.reduce((s,x)=>s+x.games,0)/a.length;q['pwin'+w]=(pw.reduce((s,x)=>s+x.won,0)+10*p0)/(pw.length+10);q['win_days'+w]=pw.length;}
      q.quiet_run=0;for(const x of [...all].reverse()){if(x.ord!==o-q.quiet_run||x.games>=500)break;q.quiet_run++;}
      output.push(q);ds.push(q);histRack.push(item);rh.set(r.rack,histRack);
    }
    const candidates=nextDayCandidates(local,metadata,day).candidates.map(x=>x.record.rack);
    const own=ds.filter(x=>x.old!=null).sort((a,b)=>Number(b.old.toFixed(9))-Number(a.old.toFixed(9))||b.games-a.games||b.evidence_days-a.evidence_days||b.latest_used-a.latest_used||a.rack-b.rack);
    const selected=own.length>=4?own.slice(0,Math.ceil(own.length/4)).map(x=>x.rack):[];
    checks.push({key,day,profile,candidates,selected,match:JSON.stringify(candidates)===JSON.stringify(selected)});
  }
}
fs.writeFileSync(path.join(here,'pstation_features_raw.json'),JSON.stringify(output));
fs.writeFileSync(path.join(here,'pstation_candidate_parity.json'),JSON.stringify({groups:checks.length,all_match:checks.every(x=>x.match),mismatches:checks.filter(x=>!x.match)},null,2));
if(checks.some(x=>!x.match))throw Error('候補照合不一致');
console.log(JSON.stringify({rows:output.length,groups:checks.length,all_match:true}));
