// 現行専用エンジンをそのまま呼ぶ。日次学習側で別の旧方式を再実装しない。
import {nextDayEvidence, nextDayCandidates, profileOf} from '../database_android/web/pscube/scoring.mjs';
import {machineKey} from '../database_android/web/pscube/data.mjs';
let input='';
for await (const part of process.stdin) input+=part;
const {data,day}=JSON.parse(input), groups=[];
for(const machine of data.machines){
  const rows=data.records.filter(r=>r.day===day && machineKey(r)===machineKey(machine));
  if(!rows.length) continue;
  const pool=rows.filter(r=>nextDayEvidence(r,data).rawIndex!=null);
  const current=nextDayCandidates(data,machine,day).candidates.map(e=>e.record.rack);
  if(current.length) groups.push({store:`pscube:${machine.store}:${machine.rate}`,rate:machine.rate,
    name:machine.machine,profile:profileOf(machine),pool:pool.map(r=>r.rack),current});
}
process.stdout.write(JSON.stringify(groups));
