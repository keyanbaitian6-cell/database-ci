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
  const interval=document.createElement('div');interval.textContent='間隔：3〜5秒ランダム';interval.style.fontSize='11px';
  const status=document.createElement('div');status.id='database-site777-status';status.style.cssText='font-size:11px;white-space:normal;overflow-wrap:anywhere';
  // 前回の取り込みの範囲・済んだ日・止まった理由（2026-11-08）。窓を開き直したとき、開始するまで出す。
  const previous=document.createElement('div');previous.id='database-site777-previous';
  // 文字はカードの白を引き継ぐと薄い黄色の上で読めない（2026-11-10 利用者「オーバーレイの一番下みづらすぎてなにかえてるか見えない」）。
  previous.style.cssText='font-size:11px;white-space:normal;overflow-wrap:anywhere;background:#fff6dc;color:#3a2a00;border-radius:4px;padding:4px;display:none';
  card.append(grip,capture,auto,startRow,dayLabel,untilLabel,progress,previous,interval,status);mount();
  let busy=false,alive=true,token=0,current=null;
  const api=()=>window.pywebview.api;
  // 機種一覧の各機種の横に、その日の取り込み状況を出す（2026-11-10 利用者「なぜメルヘンと同じ仕様になってないんだ。
  // 機種のよこに未取り込みとかもでてないし」）。文言と色はメルヘン（browser_import.py の markMachines）と同じ：
  // 未取込（灰）／途中 n/m（黄）／済 n/m（緑）／対象外。500G未満で取り込まなかった台も済みに数える（PCが数える）。
  // 日付・追加・保持の数が変わったときだけ PC に聞き直す。
  let markedKey=null;
  const markMachines=async s=>{
    if(u.pathname!=='/f/D0300.do'||!api().machine_status)return;
    const key=[s.day,s.added,s.kept,s.epoch].join('|');
    if(key===markedKey)return;
    markedKey=key;
    try{
      const machines=(databaseSite777.read(true).machines||[]).map(m=>({model_id:m.model_id,name:m.name,count:m.count}));
      const data=await api().machine_status(JSON.stringify({machines}));
      const byModel=new Map(machines.map((m,i)=>[m.model_id,data.status?.[i]]));
      const md=data.day?`${+data.day.slice(5,7)}/${+data.day.slice(8,10)} `:'';
      for(const a of document.querySelectorAll('a.imageSet')){
        let model=null;
        try{const href=new URL(a.href);if(href.pathname==='/f/D2300.do')model=href.searchParams.get('mdc');}catch(_){}
        if(!model||!byModel.has(model))continue;
        a.querySelector('.database-site777-badge')?.remove();
        const st=byModel.get(model), badge=document.createElement('span');
        badge.className='database-site777-badge';
        let text,bg,fg;
        if(st?.excluded){text='対象外';bg='transparent';fg='#8a94a6';}
        else if(!st||!st.done){text=md+'未取込';bg='#e2e2e5';fg='#707070';}
        else if(st.total&&st.done>=st.total){text=`${md}済 ${st.done}/${st.total}`;bg='#0d8b74';fg='#fff';}
        else{text=`${md}${st.done}/${st.total??'?'}`;bg='#f5a623';fg='#1d1d1f';}
        badge.textContent=text;
        badge.style.cssText=`display:inline-block;margin-left:8px;padding:1px 9px;border-radius:980px;font:600 12px system-ui;background:${bg};color:${fg}`;
        const strong=a.querySelector('strong');
        if(strong)strong.insertAdjacentElement('afterend',badge);else a.append(badge);
      }
    }catch(_){markedKey=null;}
  };
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
  // 少し待ってからそのページを読み込み直し、自動取り込みはONのまま続ける（読み込み後はいつもどおり続きから）。
  // 同じページで3回まで。回数はページを読み込み直しても残るよう sessionStorage に置き、残せないときは読み込み直さずに止める。
  // 回数は、利用者が自動取り込みを新しく開始したときだけ0に戻す（2026-11-08 Codexのレビュー：同じ窓で止めて開始し直しても
  // 前の3回が残り、次にグラフが出ないとすぐOFFになっていた）。自動の読み込み直しの間は残す。
  // 戻り値：読み込み直した（または古い処理で何もしない）は true、回復は 'recovered'、上限は 'limit'、回数を残せないときは 'storage'。
  // 待つ時間は、2026-11-19 利用者「仮だと思ったら再読み込みして」で1分から約4秒に短くした（サイトセブンの取り込み間隔
  // 3〜5秒と同じくらい。読み込み直しの回数は3回のまま。1台だけの機種は1台ごとに約10分かかっていた）。
  const MAX_RETRIES=3, RETRY_MS=4000, retryKey='database-site777-retries';
  const HIDDEN_TEXT='窓が最小化されているため、グラフが読み込まれません。窓を元に戻すと続きます（ほかの窓の後ろに置くのは問題ありません）。';
  const retryCounts=()=>{try{const v=JSON.parse(sessionStorage.getItem(retryKey)||'{}');return v&&typeof v==='object'&&!Array.isArray(v)?v:null;}catch(_){return null;}};
  const retryLater=async(mine,epoch,wanted,stalledRack)=>{
    const meta=databaseSite777.read(true), url=meta.url, counts=retryCounts();
    const targets=meta.graph_racks?.filter(r=>wanted===null||wanted.includes(r));
    const recovered=()=>{
      if(!targets||!databaseSite777.readyRacks)return false;
      const current=databaseSite777.read(true);
      if(!databaseSite777.samePage(current.url,url)||current.graph_racks?.join()!==meta.graph_racks.join())return false;
      const ready=databaseSite777.readyRacks(targets);
      // 止まった台より先はまだスクロールしていない。全台の表示をここで待たず、通常の準備へ戻す。
      if(Number.isInteger(stalledRack)&&meta.graph_racks.includes(stalledRack))
        return !targets.includes(stalledRack)||ready.includes(stalledRack);
      return targets.every(r=>ready.includes(r));
    };
    const stillCurrent=async()=>{
      const s=await api().state();
      return alive&&token===mine&&s.enabled&&s.epoch===epoch;
    };
    // 待つ間に実画像が出たら、通常の取り込みへ戻す。回数は消費・初期化しない。
    if(recovered())return await stillCurrent()?'recovered':true;
    if(!counts)return 'storage';
    const count=(Number(counts[url])||0)+1;
    if(count>MAX_RETRIES)return 'limit';
    let until=Date.now()+(window.__site777RetryMs||RETRY_MS);
    while(Date.now()<until){
      if(!alive||token!==mine)return true;
      if(recovered())return await stillCurrent()?'recovered':true;
      // 見えない間は読み込み直さない（読み込み直しても出ない）。見えたら待ちを数え直す（2026-11-21）。
      if(databaseSite777.pageHidden?.()){
        status.textContent=HIDDEN_TEXT;
        await new Promise(resolve=>setTimeout(resolve,250));
        until=Date.now()+(window.__site777RetryMs||RETRY_MS);
        continue;
      }
      status.textContent=`グラフが表示されないため、${Math.ceil((until-Date.now())/1000)}秒後にこのページを読み込み直して続けます（${count}/${MAX_RETRIES}回目）。`;
      await new Promise(resolve=>setTimeout(resolve,Math.min(1000,Math.max(0,until-Date.now()))));
    }
    if(!await stillCurrent())return true;
    if(recovered())return 'recovered';
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
    let epoch=null,wanted=null;
    try{
      const s=await api().state();render(s);
      if(automatic&&!s.enabled)return;
      epoch=s.epoch;
      let result=await api().capture(JSON.stringify(databaseSite777.read(true)),epoch);
      if(result.prepare_graphs){
        status.textContent='表示されていないグラフを順に読み込んでいます…';
        wanted=result.wanted_racks??null;
        // 最小化などでページが見えない間は、グラフが出ないとは数えずに待つ（2026-11-21。サイトの遅延読み込みが動かない）。
        await databaseSite777.prepare(()=>!alive||token!==mine,wanted,hidden=>{
          status.textContent=hidden?HIDDEN_TEXT:'表示されていないグラフを順に読み込んでいます…';
          if(hidden)try{api().note?.(JSON.stringify({kind:'graph_hidden',day:current?.day,
            page:Number(new URL(location.href).searchParams.get('pan')||1)}))?.catch?.(()=>{});}catch(_){}
        });
        if(!alive||token!==mine)return;
        result=await api().capture(JSON.stringify(databaseSite777.read(false,wanted)),epoch);
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
      if(error?.graph_wait&&alive&&token===mine){
        try{await api().note?.(JSON.stringify({kind:'graph_wait',...error.graph_wait,
          day:current?.day,page:Number(new URL(location.href).searchParams.get('pan')||1)}));}catch(_){}
      }
      if(error?.stalled&&automatic&&alive&&token===mine){
        // 失敗したページでも、既に読める必要台だけを検証して途中保存する。
        // 正常時の保存回数は増やさず、同じページの再試行で既読画像を読み直さない。
        try{
          const ready=databaseSite777.readyRacks?.(wanted)||[];
          if(ready.length){
            const payload=databaseSite777.read(false,ready);
            payload.partial_graphs=true;
            const staged=await api().capture(JSON.stringify(payload),epoch);
            if(!alive||token!==mine)return;
            if(staged.state)render(staged.state);
            if(staged.error||staged.stale)return;
            if(!staged.partial_saved)throw new Error('グラフの途中保存を確認できませんでした。');
            if(wanted!==null)wanted=wanted.filter(r=>!ready.includes(r));
          }
        }catch(failure){
          if(alive&&token===mine)await stop(failure.message||String(failure),'card_error');
          return;
        }
        let retried='storage';
        try{retried=await retryLater(mine,epoch,wanted,error.graph_wait?.rack);}catch(_){}
        if(retried===true||retried==='recovered')return;
        // 3回読み込み直しても出ない台は、グラフなしで保存して続ける（2026-11-13 利用者「グラフなしで進めるようにお願いね」。
        // 1機種で台数の半分まで、1台・2台の機種は1台。2026-11-19）。PCが断ったら今までどおり止める。
        if(retried==='limit'&&Number.isInteger(error.graph_wait?.rack)&&alive&&token===mine){
          let skipped=null;
          try{skipped=await api().skip_graph?.(error.graph_wait.rack,epoch);}catch(_){}
          if(skipped?.ok&&alive&&token===mine){if(skipped.state)render(skipped.state);return;}
        }
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
  // まだ確定していない日（その日の23:30より前。2026-11-10 利用者「23時45分くらいに最終更新」、11/8 は翌0:30だった）を取り込むときは
  // 確かめる。その時点の数値で保存し、23:30以降に取り込み直すと置き換わる（PC・Android・同期で同じ規則）。PCも確認なしの開始・保存を止める。
  // 戻り値：確定前の日を含まない＝false、含んで確かめた＝true、やめた＝null。
  const unfinishedOk=(first,last)=>{
    const from=current?.unfinished_from, [a,b]=[first,last||first].sort();
    if(!from||!a||b<from)return false;
    const label=(a>from?a:from).slice(5).replace('-','/');
    return confirm(`${label}の分はまだ確定していません（閉店23:30・23:45ごろ最終更新）。\n今取り込むと、営業中・更新前の数値で保存されます。その日の23:30以降に取り込み直すと置き換わります。\n今取り込むときは「OK」を押してください。`)?true:null;
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
    try{const s=await api().state();if(alive&&!busy){render(s);markMachines(s);if(s.enabled&&s.ready)await cycle(true);}}
    catch(_){if(alive)status.textContent='PCとの接続を待っています。';}
    if(alive)setTimeout(tick,1000);
  };
  tick();
})();
