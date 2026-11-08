/* 枠・ドラッグ・倍率はメルヘンと共通。読み取りとページ送りだけを差し替える。 */
(() => {
  const u=new URL(location.href);
  if(u.hostname!=='m.site777.jp' || !/^\/f\/D(?:0300|2300|3300|4300)\.do$/.test(u.pathname) ||
     u.searchParams.get('pmc')!=='04034001' || u.searchParams.get('urt')!=='2000' ||
     document.getElementById('database-site777')) return;
  const {card,grip,mount}=databaseCaptureCard({id:'database-site777',layout:window.__site777Layout||{},
    save:value=>window.pywebview.api.save_overlay_layout(JSON.stringify(value))});
  const makeButton=text=>{
    const b=document.createElement('button');b.textContent=text;
    b.style.cssText='padding:8px 10px;border:none;border-radius:6px;background:#304d6e;color:white;cursor:pointer;font-size:12px;width:100%';
    return b;
  };
  const capture=makeButton('この画面を取り込む'), auto=makeButton('自動取り込み：OFF（押すと開始）');
  capture.id='database-site777-capture';auto.id='database-site777-auto';
  // 上から／下から（2026-11-07 利用者「メルヘンは上から取り込みとか下から取り込みとかとても良い感じ」）：メルヘンと同じく、
  // 押すと自動取り込みをONにする。選んだ向きはOFFの間も枠で示し、手動の「この画面を取り込む」もこの向きで次の機種を選ぶ。
  const top=makeButton('上から取り込む'), bottom=makeButton('下から取り込む');
  top.id='database-site777-top';bottom.id='database-site777-bottom';
  const startRow=document.createElement('div');startRow.style.cssText='display:flex;gap:6px';startRow.append(top,bottom);
  const dayLabel=document.createElement('label'), day=document.createElement('select');
  dayLabel.textContent='日付指定取り込み（から）';day.id='database-site777-day';day.setAttribute('aria-label','取り込む日付（から）');
  day.style.cssText='width:100%;padding:5px;margin-top:4px';dayLabel.append(day);
  // 範囲の終わり（2026-11-07）。始まりと同じ日なら1日だけ。古い日から順に取り込む。
  const untilLabel=document.createElement('label'), until=document.createElement('select');
  untilLabel.textContent='（まで）';until.id='database-site777-until';until.setAttribute('aria-label','取り込む日付（まで）');
  until.style.cssText='width:100%;padding:5px;margin-top:4px';untilLabel.append(until);
  const progress=document.createElement('div');progress.id='database-site777-range';progress.style.cssText='font-size:11px;white-space:normal;overflow-wrap:anywhere';
  const interval=document.createElement('div');interval.textContent='間隔：5〜7秒ランダム';interval.style.fontSize='11px';
  const status=document.createElement('div');status.id='database-site777-status';status.style.cssText='font-size:11px;white-space:normal;overflow-wrap:anywhere';
  // 前回の取り込みの範囲・済んだ日・止まった理由（2026-11-08）。窓を開き直したとき、開始するまで出す。
  const previous=document.createElement('div');previous.id='database-site777-previous';
  previous.style.cssText='font-size:11px;white-space:normal;overflow-wrap:anywhere;background:#fff6dc;border-radius:4px;padding:4px;display:none';
  card.append(grip,capture,auto,startRow,dayLabel,untilLabel,progress,previous,interval,status);mount();
  let busy=false,alive=true,token=0,current=null;
  const api=()=>window.pywebview.api;
  const render=s=>{
    current=s;
    const dates=s.days||[];
    for(const select of [day,until]){
      if(Array.from(select.options).map(o=>o.value).join()!==dates.join()){
        select.replaceChildren(...dates.map(value=>{const o=document.createElement('option');o.value=value;o.textContent=value;return o;}));
      }
    }
    day.value=s.day||'';
    until.value=s.until||s.day||'';
    // ページの移動中（PCが読み込みの完了を待っている間）は、旧画面を取り込み直さない（2026-11-08）。
    day.disabled=until.disabled=busy||s.enabled;capture.disabled=busy||s.enabled||!!s.navigating;
    for(const button of [top,bottom]){
      button.disabled=busy||s.enabled;button.style.opacity=button.disabled?'.5':'1';
      const chosen=button===(s.direction==='bottom'?bottom:top);
      button.style.outline=chosen?'3px solid #087d59':'';button.setAttribute('aria-pressed',String(chosen));
    }
    const rest=s.queue||[];
    progress.textContent=(s.finished_days||[]).length||rest.length
      ?`済み：${(s.finished_days||[]).join('、')||'なし'}／この後：${rest.join('、')||'なし'}`:'';
    // 止まって自動の再開を待っている間（2026-11-08 利用者「3分後には自動復帰」）。押すと再開を取り消す。
    auto.textContent=s.enabled?'自動取り込み：ON（押すと停止）':s.resume_at?`自動取り込み：${s.resume_at}に再開予定（押すと取り消し）`
      :'自動取り込み：OFF（押すと開始）';
    auto.style.background=s.enabled||s.resume_at?'#b74237':'#304d6e';
    // 自動で再開しても、グラフの読み込み直しの回数は戻さない（2026-11-08 利用者「256やって」。今までは再開のたびに
    // 0に戻し、グラフが出ないページを再開1回につき4回読み込み、5回の再開で約24回・約40分になっていた）。
    // 再開の読み込み直し（PC）でも出なければ、すぐ止まり、3分後の次の再開を待つ（再開1回につき読み込み1回）。
    status.textContent=s.status;
    previous.textContent=s.previous||'';previous.style.display=s.previous?'block':'none';
  };
  // グラフが出ないとき（2026-11-07 利用者「グラフが出なかったら1分後に再読みするんじゃなかったの？」）：自動取り込み中だけ、
  // 1分待ってからそのページを読み込み直し、自動取り込みはONのまま続ける（読み込み後はいつもどおり続きから）。
  // 同じページで3回まで。回数はページを読み込み直しても残るよう sessionStorage に置き、残せないときは読み込み直さずに止める。
  // 回数は、利用者が自動取り込みを新しく開始したときだけ0に戻す（2026-11-08 Codexのレビュー：同じ窓で止めて開始し直しても
  // 前の3回が残り、次にグラフが出ないとすぐOFFになっていた）。自動の読み込み直しの間は残す。
  // 戻り値：読み込み直した（または古い処理で何もしない）は true、上限は 'limit'、回数を残せないときは 'storage'。
  const MAX_RETRIES=3, retryKey='database-site777-retries';
  const retryCounts=()=>{try{const v=JSON.parse(sessionStorage.getItem(retryKey)||'{}');return v&&typeof v==='object'&&!Array.isArray(v)?v:null;}catch(_){return null;}};
  const retryLater=async(mine,epoch)=>{
    const url=databaseSite777.read(true).url, counts=retryCounts();
    if(!counts)return 'storage';
    const count=(Number(counts[url])||0)+1;
    if(count>MAX_RETRIES)return 'limit';
    const until=Date.now()+(window.__site777RetryMs||60000);
    while(Date.now()<until){
      if(!alive||token!==mine)return true;
      status.textContent=`グラフが表示されないため、${Math.ceil((until-Date.now())/1000)}秒後にこのページを読み込み直して続けます（${count}/${MAX_RETRIES}回目）。`;
      await new Promise(resolve=>setTimeout(resolve,Math.min(1000,Math.max(0,until-Date.now()))));
    }
    const s=await api().state();
    if(!alive||token!==mine||!s.enabled||s.epoch!==epoch)return true;
    try{
      sessionStorage.setItem(retryKey,JSON.stringify({...counts,[url]:count}));
      if(Number(retryCounts()?.[url])!==count)return 'storage';
    }catch(_){return 'storage';}
    status.textContent='このページを読み込み直しています…';
    location.reload();
    return true;
  };
  // reason は停止の理由コード（PCのログに残す。2026-11-08）。
  const stop=async(message,reason,retries)=>{
    token++;
    const s=await api().pause(message||null,reason||null,Number.isInteger(retries)?retries:null);render(s);
  };
  const cycle=async automatic=>{
    if(busy||!alive)return;
    busy=true;
    const mine=token;
    let epoch=null;
    try{
      const s=await api().state();render(s);
      if(automatic&&!s.enabled)return;
      epoch=s.epoch;
      let result=await api().capture(JSON.stringify(databaseSite777.read(true)),epoch);
      if(result.prepare_graphs){
        status.textContent='表示されていないグラフを順に読み込んでいます…';
        await databaseSite777.prepare(()=>!alive||token!==mine);
        if(!alive||token!==mine)return;
        result=await api().capture(JSON.stringify(databaseSite777.read()),epoch);
      }
      if(!alive||token!==mine)return;
      if(result.state)render(result.state);
      if(result.error){status.textContent=result.error;return;}
      const latest=await api().state();
      if(latest.epoch!==epoch||(automatic&&!latest.enabled))return;
      if(result.action){
        const before=databaseSite777.read(true).url;
        databaseSite777.go(result.action);
        setTimeout(async()=>{
          if(!alive||token!==mine)return;
          try{
            const s=await api().state();
            if(s.epoch!==epoch){render(s);return;}
            if(databaseSite777.samePage(databaseSite777.read(true).url,before))await stop('リンクを押しても移動しないため停止しました。画面を確認してください。','not_moved');
          }catch(_){}
        },8000);
      }
    }catch(error){
      if(error?.stalled&&automatic&&alive&&token===mine){
        let retried='storage';
        try{retried=await retryLater(mine,epoch);}catch(_){}
        if(retried===true)return;
        // 表示の回数を実際に読み込み直した回数に合わせる（回数を残せず読み込み直していないのに「3回」と出していた）。
        if(alive&&token===mine)await (retried==='limit'
          ?stop(`${MAX_RETRIES}回読み込み直してもグラフが表示されないため停止しました。画面を確認してください。`,'graph_retry_limit',MAX_RETRIES)
          :stop('グラフが表示されないため停止しました（読み込み直しの回数を残せないため、読み込み直していません）。画面を確認してください。','graph_retry_storage',0));
        return;
      }
      if(alive&&token===mine)await stop(error.message||String(error),'card_error');
    }finally{
      busy=false;
      if(alive&&current)render(current);
    }
  };
  // 今の営業日以降の日（営業中になりうる日）を取り込むときは確かめる（2026-11-08）。サイトセブンは無い台だけ補うので、
  // 営業中に取り込むと、その時点の数値のまま残り、あとで取り込み直しても置き換わらない。PCも確認なしの開始・保存を止める。
  // 戻り値：今の営業日以降の日を含まない＝false、含んで確かめた＝true、やめた＝null。
  const unfinishedOk=(first,last)=>{
    const today=current?.today, [a,b]=[first,last||first].sort();
    if(!today||!a||b<today)return false;
    const label=(a>today?a:today).slice(5).replace('-','/');
    return confirm(`${label}の分は、営業中（または営業前）の数値のことがあります。\n取り込んだ時点の数値のまま残り、あとで取り込み直しても置き換わりません。\n閉店後のデータか確かめましたか？ 取り込むときは「OK」を押してください。`)?true:null;
  };
  const range=()=>[day.value||null,until.value&&until.value!==day.value?until.value:null];
  capture.onclick=async()=>{
    if(current&&!current.today_ok){
      const ok=unfinishedOk(current.day,current.until);
      if(ok===null)return;
      if(ok){try{token++;render(await api().configure(false,current.day,current.until||null,null,true));}
        catch(error){status.textContent=error.message||String(error);return;}}
    }
    cycle(false);
  };
  const start=async direction=>{
    try{
      if(current?.enabled||current?.resume_at){await stop(null,'user_stop');return;}
      const [first,last]=range(), ok=unfinishedOk(first,last);
      if(ok===null)return;
      try{sessionStorage.removeItem(retryKey);}catch(_){}
      token++;render(await api().configure(true,first,last,direction,ok));
    }catch(error){status.textContent=error.message||String(error);}
  };
  auto.onclick=()=>start(null);
  top.onclick=()=>{if(!current?.enabled)start('top');};
  bottom.onclick=()=>{if(!current?.enabled)start('bottom');};
  day.onchange=async()=>{
    // 始まりを変えたら、終わりも同じ日に戻す（1日だけ）。範囲にするときは、その後で終わりを選ぶ。
    try{token++;render(await api().configure(false,day.value||null));}
    catch(error){status.textContent=error.message||String(error);}
  };
  until.onchange=async()=>{
    try{token++;render(await api().configure(false,day.value||null,until.value&&until.value!==day.value?until.value:null));}
    catch(error){status.textContent=error.message||String(error);}
  };
  // 移動がキャンセルされたら元ページは残る。古い処理だけ無効化し、表示更新は続ける。
  window.addEventListener('beforeunload',()=>{token++;});
  window.addEventListener('pagehide',()=>{alive=false;token++;});
  const tick=async()=>{
    try{const s=await api().state();if(alive&&!busy){render(s);if(s.enabled&&s.ready)await cycle(true);}}
    catch(_){if(alive)status.textContent='PCとの接続を待っています。';}
    if(alive)setTimeout(tick,1000);
  };
  tick();
})();
