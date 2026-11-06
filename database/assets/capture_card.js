/* 取り込み窓共通：メルヘンのカードの見た目、移動、倍率、配置保存。 */
(() => {
  if (window.databaseCaptureCard) return;
  window.databaseCaptureCard = ({id, layout={}, save=()=>{}}) => {
    const card = document.createElement('div');
    card.id = id;
    card.style.cssText = 'position:fixed;z-index:2147483647;background:#203044;color:#fff;padding:8px;display:flex;flex-direction:column;gap:6px;font:13px system-ui;border-radius:10px;box-shadow:0 4px 14px rgba(0,0,0,.4);width:176px';
    let scale = Number.isFinite(layout.scale) && layout.scale >= .7 && layout.scale <= 2 ? layout.scale : 1;
    const place = (left, top) => {
      const r = card.getBoundingClientRect();
      card.style.left = Math.min(Math.max(0,left),Math.max(0,innerWidth-r.width-4))/scale+'px';
      card.style.top = Math.min(Math.max(0,top),Math.max(0,innerHeight-r.height-4))/scale+'px';
    };
    const remember = () => {
      const r=card.getBoundingClientRect();
      try { save({left:r.left, top:r.top, scale}); } catch (_) {}
    };
    const grip=document.createElement('div');
    grip.style.cssText='cursor:move;font-size:11px;opacity:.75;padding:2px 4px;user-select:none;touch-action:none;display:flex;align-items:center;gap:4px';
    const label=document.createElement('span');
    label.textContent='database（ドラッグで移動）';
    label.style.cssText='flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
    grip.append(label);
    for(const [text, title, step] of [['－','小さくする',-.15],['＋','大きくする',.15]]) {
      const b=document.createElement('button');
      b.textContent=text; b.title=title;
      b.style.cssText='border:1px solid #5b6b84;border-radius:5px;background:transparent;color:#c9d3e3;cursor:pointer;font-size:11px;line-height:1;padding:2px 5px';
      b.onclick=()=>{const r=card.getBoundingClientRect();scale=Math.min(2,Math.max(.7,Math.round((scale+step)*100)/100));card.style.zoom=scale;place(r.left,r.top);remember();};
      grip.append(b);
    }
    let dragging=null;
    grip.addEventListener('pointerdown', e=>{
      if(e.target.closest('button') || e.button!==0) return;
      const r=card.getBoundingClientRect();dragging={dx:e.clientX-r.left,dy:e.clientY-r.top};
      grip.setPointerCapture(e.pointerId); e.preventDefault();
    });
    grip.addEventListener('pointermove',e=>{if(dragging)place(e.clientX-dragging.dx,e.clientY-dragging.dy);});
    const finish=()=>{if(dragging){dragging=null;remember();}};
    grip.addEventListener('pointerup',finish);grip.addEventListener('pointercancel',finish);
    const mount=()=>{
      document.body.appendChild(card);card.style.zoom=scale;
      place(Number.isFinite(layout.left)?layout.left:innerWidth-196,Number.isFinite(layout.top)?layout.top:12);
    };
    return {card,grip,mount,place,getScale:()=>scale};
  };
})();
