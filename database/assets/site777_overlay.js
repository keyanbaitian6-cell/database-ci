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
  const dayLabel=document.createElement('label'), day=document.createElement('select');
  dayLabel.textContent='日付指定取り込み（から）';day.id='database-site777-day';day.setAttribute('aria-label','取り込む日付（から）');
  day.style.cssText='width:100%;padding:5px;margin-top:4px';dayLabel.append(day);
  // 範囲の終わり（2026-11-07）。始まりと同じ日なら1日だけ。古い日から順に取り込む。
  const untilLabel=document.createElement('label'), until=document.createElement('select');
  untilLabel.textContent='（まで）';until.id='database-site777-until';until.setAttribute('aria-label','取り込む日付（まで）');
  until.style.cssText='width:100%;padding:5px;margin-top:4px';untilLabel.append(until);
  const progress=document.createElement('div');progress.id='database-site777-range';progress.style.cssText='font-size:11px;white-space:normal;overflow-wrap:anywhere';
  const interval=document.createElement('div');interval.textContent='間隔：10〜20秒ランダム';interval.style.fontSize='11px';
  const status=document.createElement('div');status.id='database-site777-status';status.style.cssText='font-size:11px;white-space:normal;overflow-wrap:anywhere';
  card.append(grip,capture,auto,dayLabel,untilLabel,progress,interval,status);mount();
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
    day.disabled=until.disabled=busy||s.enabled;capture.disabled=busy||s.enabled;
    const rest=s.queue||[];
    progress.textContent=(s.finished_days||[]).length||rest.length
      ?`済み：${(s.finished_days||[]).join('、')||'なし'}／この後：${rest.join('、')||'なし'}`:'';
    auto.textContent=s.enabled?'自動取り込み：ON（押すと停止）':'自動取り込み：OFF（押すと開始）';
    auto.style.background=s.enabled?'#b74237':'#304d6e';
    status.textContent=s.status;
  };
  const stop=async message=>{
    token++;
    const s=await api().pause(message||null);render(s);
  };
  const cycle=async automatic=>{
    if(busy||!alive)return;
    busy=true;
    const mine=token;
    try{
      const s=await api().state();render(s);
      if(automatic&&!s.enabled)return;
      const epoch=s.epoch;
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
            if(databaseSite777.samePage(databaseSite777.read(true).url,before))await stop('リンクを押しても移動しないため停止しました。画面を確認してください。');
          }catch(_){}
        },8000);
      }
    }catch(error){
      if(alive&&token===mine)await stop(error.message||String(error));
    }finally{
      busy=false;
      if(alive&&current)render(current);
    }
  };
  capture.onclick=()=>cycle(false);
  auto.onclick=async()=>{
    try{
      if(current?.enabled){await stop();return;}
      token++;render(await api().configure(true,day.value||null,until.value&&until.value!==day.value?until.value:null));
    }catch(error){status.textContent=error.message||String(error);}
  };
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
