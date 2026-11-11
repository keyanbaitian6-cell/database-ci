// 公開用の項目だけを取り出す。入力・係数・原本DBを公開しない。
function projectDailyLearning(raw) {
  if(raw?.format!=='daily-learning'||raw.version!==1||!Array.isArray(raw.days)||raw.days.length>31||
     typeof raw.status!=='string'||typeof raw.updated_at!=='string') throw Error('日次学習の形式が不正です');
  const stores=['nagamachiminami','saiwaichou','pscube:c740601:20'];
  const days=raw.days.map(d=>{
    if(!/^\d{4}-\d{2}-\d{2}$/.test(d.target)||!Array.isArray(d.groups)||d.groups.length>300) throw Error('対象日が不正です');
    const groups=d.groups.map(g=>{
      const stamp=g.saved_at??d.saved_at, time=Date.parse(stamp);
      const local=new Date(time+9*3600000), minutes=local.getUTCHours()*60+local.getUTCMinutes();
      // 保存できるのは対象日の前日23:30〜当日08:00（日本時間。2026-11-11）。
      const savedDay=local.toISOString().slice(0,10), before=new Date(Date.parse(d.target+'T00:00:00Z')-86400000).toISOString().slice(0,10);
      const inWindow=(savedDay===d.target&&minutes<480)||(savedDay===before&&minutes>=1410);
      if(!stores.includes(g.store)||typeof g.name!=='string'||typeof g.status!=='string'||
        !['current','learned'].includes(g.active)||!Number.isFinite(time)||
        !/(Z|[+-]\d\d:\d\d)$/.test(stamp)||!inWindow)
        throw Error('締切前の候補ではありません');
      const out={store:g.store,name:g.name,active:g.active,status:g.status,saved_at:stamp};
      for(const key of ['selected','current','learned']) {
        if(!Array.isArray(g[key])||g[key].length>500) throw Error('候補数が不正です');
        out[key]=g[key].map(id=>{
          if(!Array.isArray(id)||id.length!==4||id[0]!==g.store||typeof id[1]!=='string'||typeof id[2]!=='string'||!Number.isInteger(id[3])) throw Error('台の形式が不正です');
          return id.slice();
        });
      }
      return out;
    });
    return {target:d.target,input_day:d.input_day,saved_at:d.saved_at,version:d.version,groups};
  });
  return {format:'daily-learning',version:1,updated_at:raw.updated_at,status:raw.status,days};
}

function readDailyLearning() {
  try {
    const folder=folderBeside('database-viewer.json');
    const files=folder.getFilesByName('daily-learning.json');
    let latest=null;
    while(files.hasNext()) {
      const f=files.next();
      if(!f.isTrashed()&&(!latest||f.getLastUpdated()>latest.getLastUpdated())) latest=f;
    }
    if(!latest) return respond(JSON.stringify({error:'日次学習の出力はまだありません'}));
    if(latest.getSize()>4*1024*1024) throw Error('日次学習ファイルが大きすぎます');
    return respond(JSON.stringify(projectDailyLearning(JSON.parse(latest.getBlob().getDataAsString('UTF-8')))));
  } catch (_) { return respond(JSON.stringify({error:'日次学習の保存先または形式を確認してください'})); }
}
