// 合成3万台日で重複整理の処理時間・最大RSS・結果の指紋・入力保持を確認する。
// node --expose-gc tool/measure_share_calendar.mjs [比較対象モジュールのfile URL]
import {createHash} from 'node:crypto';
import {performance} from 'node:perf_hooks';
const {indexRecords}=await import(process.argv[2] || new URL('../../share_viewer/data.mjs', import.meta.url).href);
const records=Array.from({length:30000},(_,i)=>({store:i%2?'saiwaichou':'nagamachiminami',day:new Date(Date.UTC(2026,8,1+Math.floor(i/500))).toISOString().slice(0,10),machine:'機種'+i%20,rack:i%500,games:6000,bb:20,rb:15,net:(i%100-40)*50,graph:{baseline_y:100,end_y:80,curve:Array.from({length:32},(_,j)=>[j,100+j%12])}}));
for(let i=0;i<30000;i+=1500){records.push({...records[i]});records.push({...records[i+1],net:-9999});}
const before=createHash('sha256').update(JSON.stringify(records)).digest('hex');
const times=[];let out;
for(let i=0;i<5;i++){global.gc?.();const start=performance.now();out=indexRecords(records);times.push(performance.now()-start);}
const hash=createHash('sha256').update(JSON.stringify([...out])).update(JSON.stringify(out.issues)).digest('hex');
const unchanged=before===createHash('sha256').update(JSON.stringify(records)).digest('hex');
console.log(JSON.stringify({median_ms:times.sort((a,b)=>a-b)[2],peak_rss_kib:process.resourceUsage().maxRSS,hash,unchanged,rows:records.length,issues:out.issues.length}));
