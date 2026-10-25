// 共有ページの記号だけを保存する。4大オススメも構成はPCのみ、台ごとの顔文字は共有で編集する。
const HISTORY_SHARED_NAME = 'database-event-history-shared.json';
const HISTORY_PC_NAME = 'database-event-history.json';

function historyPcDocument() {
  const file=latestFile(HISTORY_PC_NAME);
  if(!file) throw new Error('PCでイベント履歴を共有へ反映してください。');
  const doc=JSON.parse(file.getBlob().getDataAsString('UTF-8'));
  EVENT_HISTORY_API.parsePrivateHistory(doc);
  return doc;
}

function historySharedDocument() {
  const file=latestFile(HISTORY_SHARED_NAME);
  if(!file) return {file:null,doc:{format:'database-event-history',version:1,cells:[],weeks:[],links:[]}};
  const doc=JSON.parse(file.getBlob().getDataAsString('UTF-8'));
  if(!doc || doc.format!=='database-event-history' || doc.version!==1 || !Array.isArray(doc.cells) || doc.cells.length>30000 ||
      !Array.isArray(doc.weeks) || doc.weeks.length || !Array.isArray(doc.links) || doc.links.length ||
      (doc.recommendations != null && (!Array.isArray(doc.recommendations) || doc.recommendations.length>3000)) ||
      (doc.recommendation_results != null && (!Array.isArray(doc.recommendation_results) || doc.recommendation_results.length>30000)))
    throw new Error('共有の履歴ファイルを読めません。元のファイルは変更していません。');
  return {file,doc};
}

function readEventHistory() {
  try {
    const pc=historyPcDocument(), shared=historySharedDocument().doc;
    const doc=EVENT_HISTORY_API.mergeHistoryCells(pc,shared.cells,{strict:false});
    const recommendation_results=EVENT_HISTORY_API.mergeRecommendationResults(pc.recommendation_results??[],shared.recommendation_results??[],{strict:false});
    return respond(JSON.stringify({...doc,recommendation_results,shared_editing:true,recommendations_editing:false,recommendation_results_editing:true}));
  } catch(e) { return respond(JSON.stringify({error:String(e.message||e)})); }
}

function postEventHistory(cells=[],recommendations=[],results=[]) {
  if(!Array.isArray(recommendations) || recommendations.length)
    return respond(JSON.stringify({error:'イベントの機種構成はPCで変更してください。'}));
  if(!Array.isArray(cells) || !Array.isArray(results) || cells.length+results.length<1 || cells.length+results.length>100)
    return respond(JSON.stringify({error:'結果記号は1〜100件ずつ保存してください。'}));
  const lock=LockService.getScriptLock();
  let locked=false;
  try {
    lock.waitLock(20000); locked=true;
    const pc=historyPcDocument(), model=EVENT_HISTORY_API.parsePrivateHistory(pc);
    const incoming=cells.map(c=>({...EVENT_HISTORY_API.historyCell(c,model),device:'shared'}));
    const plans=EVENT_HISTORY_API.recommendationPlans(pc.recommendations??[]);
    const selected=results.map(raw=>{
      const r=EVENT_HISTORY_API.recommendationResult(raw);
      if(!plans.some(p=>p.week===r.week && p.machines.includes(r.machine)))throw new Error('対象の週・機種が4大オススメの選定にありません。');
      return {...r,device:'shared'};
    });
    if([...incoming,...selected].some(c=>Date.parse(c.updated_at)>Date.now()+5*60*1000))
      throw new Error('端末の日時が先に進んでいます。日時を確認してから再送してください。');
    const current=historySharedDocument();
    const shared=EVENT_HISTORY_API.mergeHistoryCells({...pc,cells:current.doc.cells},incoming);
    const history=EVENT_HISTORY_API.mergeHistoryCells(pc,shared.cells,{strict:false});
    const savedResults=EVENT_HISTORY_API.mergeRecommendationResults(current.doc.recommendation_results??[],selected);
    history.recommendation_results=EVENT_HISTORY_API.mergeRecommendationResults(pc.recommendation_results??[],savedResults,{strict:false});
    const doc={...current.doc,format:'database-event-history',version:1,cells:shared.cells,weeks:[],links:[],recommendation_results:savedResults,updated_at:new Date().toISOString()};
    const text=JSON.stringify(doc);
    if(current.file) {
      if(JSON.stringify(shared.cells)!==JSON.stringify(current.doc.cells) || JSON.stringify(savedResults)!==JSON.stringify(current.doc.recommendation_results??[])) current.file.setContent(text);
    } else folderBeside(HISTORY_PC_NAME).createFile(HISTORY_SHARED_NAME,text,'application/json');
    const keptNewer=incoming.filter(c=>history.cells.some(old=>old && EVENT_HISTORY_API.historyEditKey(old)===EVENT_HISTORY_API.historyEditKey(c) && old.updated_at!==c.updated_at && old.value!==c.value)).length;
    return respond(JSON.stringify({ok:true,history:{...history,shared_editing:true,recommendations_editing:false,recommendation_results_editing:true},keptNewer}));
  } catch(e) { return respond(JSON.stringify({error:String(e.message||e)})); }
  finally { if(locked) lock.releaseLock(); }
}
