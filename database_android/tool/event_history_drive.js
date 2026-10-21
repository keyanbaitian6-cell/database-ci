// 共有ページの記号だけを保存する。PCの基準・数値記録・週の構成には書き込まない。
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
      !Array.isArray(doc.weeks) || doc.weeks.length || !Array.isArray(doc.links) || doc.links.length)
    throw new Error('共有の履歴ファイルを読めません。元のファイルは変更していません。');
  return {file,doc};
}

function readEventHistory() {
  try {
    const doc=EVENT_HISTORY_API.mergeHistoryCells(historyPcDocument(),historySharedDocument().doc.cells,{strict:false});
    return respond(JSON.stringify({...doc,shared_editing:true}));
  } catch(e) { return respond(JSON.stringify({error:String(e.message||e)})); }
}

function postEventHistory(cells) {
  if(!Array.isArray(cells) || !cells.length || cells.length>100)
    return respond(JSON.stringify({error:'履歴の記号は1〜100件ずつ保存してください。'}));
  const lock=LockService.getScriptLock();
  let locked=false;
  try {
    lock.waitLock(20000); locked=true;
    const pc=historyPcDocument(), model=EVENT_HISTORY_API.parsePrivateHistory(pc);
    const incoming=cells.map(c=>({...EVENT_HISTORY_API.historyCell(c,model),device:'shared'}));
    if(incoming.some(c=>Date.parse(c.updated_at)>Date.now()+5*60*1000))
      throw new Error('端末の日時が先に進んでいます。日時を確認してから再送してください。');
    const current=historySharedDocument();
    const shared=EVENT_HISTORY_API.mergeHistoryCells({...pc,cells:current.doc.cells},incoming);
    const history=EVENT_HISTORY_API.mergeHistoryCells(pc,shared.cells,{strict:false});
    const doc={format:'database-event-history',version:1,cells:shared.cells,weeks:[],links:[],updated_at:new Date().toISOString()};
    const text=JSON.stringify(doc);
    if(current.file) {
      if(JSON.stringify(shared.cells)!==JSON.stringify(current.doc.cells)) current.file.setContent(text);
    } else folderBeside(HISTORY_PC_NAME).createFile(HISTORY_SHARED_NAME,text,'application/json');
    const keptNewer=incoming.filter(c=>history.cells.some(old=>old && EVENT_HISTORY_API.historyEditKey(old)===EVENT_HISTORY_API.historyEditKey(c) && old.updated_at!==c.updated_at && old.value!==c.value)).length;
    return respond(JSON.stringify({ok:true,history:{...history,shared_editing:true},keptNewer}));
  } catch(e) { return respond(JSON.stringify({error:String(e.message||e)})); }
  finally { if(locked) lock.releaseLock(); }
}
