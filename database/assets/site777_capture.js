/* 表示済みDOM・画像だけを読む。取得・再読み込み・URLの推測は行わない。 */
(() => {
  if (window.databaseSite777) return;
  const norm = value => String(value || '').normalize('NFKC').replace(/\s+/g, ' ').trim();
  const keys = ['pmc', 'clc', 'urt', 'mdc', 'bn', 'soc', 'sw', 'pan', 'dsgk', 'dtdd', 'data', 'dn'];
  const paths = new Set(['/f/D0300.do', '/f/D2300.do', '/f/D3300.do', '/f/D4300.do']);
  const clean = raw => {
    if (typeof raw !== 'string' || !raw) return null;
    const u = new URL(raw, location.href);
    if (u.origin !== 'https://m.site777.jp' || !paths.has(u.pathname) ||
        u.searchParams.get('pmc') !== '04034001' || u.searchParams.get('urt') !== '2000' ||
        (u.searchParams.has('clc') && u.searchParams.get('clc') !== '03')) return null;
    const safe = new URL(u.origin + u.pathname);
    for (const key of keys) {
      const values = u.searchParams.getAll(key);
      if (values.length > 1 || (values.length && !/^-?\d+$/.test(values[0]))) return null;
      if (values.length) safe.searchParams.set(key, values[0]);
    }
    return safe.href;
  };
  const samePage=(first,second)=>{const value=clean(first);return value!==null&&value===clean(second);};
  const visible = el => {
    if (el.closest('[aria-hidden="true"]')) return false;
    for (let p = el; p; p = p.parentElement) {
      const style = getComputedStyle(p);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
    }
    return el.getClientRects().length > 0;
  };
  const link = (selector, text) => Array.from(document.querySelectorAll(selector))
    .find(a => (!text || norm(a.textContent) === text) && clean(a.href));
  const remember = urls => {
    try {
      const old = JSON.parse(sessionStorage.getItem('database-site777-links') || '[]');
      sessionStorage.setItem('database-site777-links', JSON.stringify([...new Set([...old,...urls].map(clean).filter(Boolean))].slice(-5000)));
    } catch (_) {}
  };
  // 表と同様に非表示の複製を除く。台番を先に読むことで、画像の無い対象外の台も識別できる。
  const graphBoxes = (allowEmpty=false) => {
    const boxes = Array.from(document.querySelectorAll('.lite-graph .graph-box')).filter(visible);
    const racks = new Set();
    const result = boxes.map(box => {
      const match = norm(box.querySelector('span')?.textContent).match(/^\[(\d+)\]$/);
      const rack = match ? Number(match[1]) : null;
      if (!Number.isSafeInteger(rack) || rack <= 0 || racks.has(rack))
        throw new Error('グラフ一覧の台番号が不明か重複しています。');
      racks.add(rack);
      return {box, rack};
    });
    if ((!allowEmpty && !result.length) || result.length > 20) throw new Error('表示中のグラフ一覧の台数を確認できません。');
    return result;
  };
  const imageReady = img => !!img && img.complete && img.naturalWidth > 0 &&
    new URL(img.currentSrc || img.src, location.href).pathname === '/chart/RequestSPDedamaTransitionChartForPortal.do';
  // 表示済みの状態を調べるだけ。スクロール・srcの設定・追加取得をしない。
  const readyRacks = (wantedRacks=null) => graphBoxes().filter(({box,rack}) =>
    (wantedRacks === null || wantedRacks.includes(rack)) && imageReady(box.querySelector('img'))).map(g=>g.rack);
  const read = (metadataOnly=false, wantedRacks=null) => {
    const sourceUrl = location.href;
    const url = clean(sourceUrl);
    if (!url) throw new Error('P-STATIONの20円スロットの機種一覧・表・グラフ一覧を開いてください。');
    const u = new URL(url);
    const hall = norm(document.querySelector('h2.page-title')?.textContent);
    if (hall.replace(/\s/g, '') !== 'P-STATION&IIスロット館' || document.querySelector('input[type=password]'))
      throw new Error('店舗を確認できません。ログイン等の操作は手動で行ってください。');
    const kind = {'/f/D0300.do':'index', '/f/D2300.do':'model', '/f/D3300.do':'table', '/f/D4300.do':'graphs'}[u.pathname];
    const main = document.querySelector('#main');
    const title = norm(main?.querySelector('.mod-center > p:not(.hd-style-radius)')?.textContent);
    const countText = norm(main?.querySelector('.hd-style-radius')?.textContent);
    const count = countText.match(/^(\d+)台\s*\/【20】スロ$/);
    if ((kind === 'table' || kind === 'graphs') && !count)
      throw new Error('表示台数・20円スロットの表示を確認できません。');
    const tabs = Array.from(document.querySelectorAll('.tab-style-data a')).map(a => {
      const href = clean(a.href), label = norm(a.textContent);
      return href && /^\d{1,2}\/\d{1,2}$/.test(label) ?
        {label, url:href, active:a.parentElement.classList.contains('active')} : null;
    }).filter(Boolean);
    const active = tabs.filter(t => t.active && new URL(t.url).searchParams.get('dtdd') === u.searchParams.get('dtdd'));
    const selected = [...new Set(active.map(t => t.label))];
    if ((kind === 'table' || kind === 'graphs') && selected.length !== 1)
      throw new Error('選択中の日付を一つに特定できません。');
    const pages = Array.from(document.querySelectorAll('.pager-style a')).map(a => {
      const n = norm(a.textContent), href = a.getAttribute('href') || '';
      if (!/^\d+$/.test(n)) return null;
      const current = a.classList.contains('active');
      if (!current && !new RegExp("^javascript:changePage\\(['\"]" + n + "['\"]\\);?$").test(href)) return null;
      return {number:Number(n), current};
    }).filter(Boolean);
    const result = {url, kind, hall, model_id:u.searchParams.get('mdc'), machine:title,
      count:count ? Number(count[1]) : null, selected_md:selected[0] || null, days:tabs,
      pages, page:Number(u.searchParams.get('pan') || 1), updated:norm(document.querySelector('#details p')?.textContent),
      index_url:clean(link('a', '設置機種')?.href || ''),
      table_url:clean(link('a', '大当り一覧')?.href || ''),
      graph_url:clean(link('.tab-style-b a', '出玉推移一覧')?.href || '')};
    if (kind === 'index') {
      result.machines = Array.from(document.querySelectorAll('a.imageSet')).map(a => {
        const href = clean(a.href);
        if (!href || new URL(href).pathname !== '/f/D2300.do') return null;
        const label = norm(a.querySelector('strong')?.textContent || a.textContent);
        const match = label.match(/^(.*?)\s*\[(\d+)\]$/);
        // 1台だけの機種は「[1]」を付けずに名前だけで出る（2026-11-07、本物の機種一覧で確認。台数の多い順の最後に並ぶ）。
        // 角かっこが全く無いときだけ1台とし、角かっこがあるのに読めないときは不明（null）のまま。
        return {name:match ? match[1].trim() : label, count:match ? Number(match[2]) : (/[\[［]/.test(label) ? null : 1),
          model_id:new URL(href).searchParams.get('mdc'), url:href};
      }).filter(Boolean);
      remember(result.machines.map(m=>m.url));
    } else if (kind === 'table') {
      const tables = Array.from(document.querySelectorAll('table[id="dedama_data_list"]')).filter(visible);
      if (tables.length !== 1) throw new Error('表示中の表を一つに特定できません。');
      result.headers = Array.from(tables[0].querySelectorAll('thead tr:first-child > td, thead tr:first-child > th'))
        .map(el => norm(el.textContent));
      result.rows = Array.from(tables[0].querySelectorAll('tbody tr')).filter(tr => tr.querySelector('.daiData a'))
        .map(tr => Array.from(tr.children).map(td => norm(td.textContent)));
    } else if (kind === 'graphs') {
      const boxes = graphBoxes();
      result.graph_racks = boxes.map(g => g.rack);
      if (metadataOnly) {
        result.deferred_images=true;
        return result;
      }
      result.graphs = boxes.filter(g => wantedRacks === null || wantedRacks.includes(g.rack)).map(({box, rack}) => {
        const img = box.querySelector('img');
        if (!rack || !imageReady(img))
          throw new Error('グラフの読み込み完了を待ってください。仮の背景は保存しません。');
        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
        canvas.getContext('2d').drawImage(img, 0, 0);
        let png;
        try { png = canvas.toDataURL('image/png'); }
        catch (_) { throw new Error('表示済みグラフを読み出せません。追加取得は行いません。'); }
        return {rack, width:canvas.width, height:canvas.height, png,
          my_label:norm(box.querySelector('.max-num')?.textContent)};
      });
    }
    if (!samePage(sourceUrl, location.href)) throw new Error('読み取り中にページが変わりました。');
    return result;
  };
  const go = action => {
    let target;
    if ((action.type === 'link' || action.type === 'listed') && clean(action.url))
      target = Array.from(document.querySelectorAll('a[href]')).find(a => samePage(a.href, action.url));
    if (!target && action.type === 'listed' && clean(action.url)) {
      let known=[];
      try {known=JSON.parse(sessionStorage.getItem('database-site777-links')||'[]');} catch (_) {}
      if (Array.isArray(known) && known.includes(clean(action.url))) {
        target=document.createElement('a');target.href=clean(action.url);target.target='_self';
        document.body.appendChild(target);target.click();target.remove();return true;
      }
    }
    if (action.type === 'page' && Number.isInteger(action.number))
      target = Array.from(document.querySelectorAll('.pager-style a[href]')).find(a =>
        norm(a.textContent) === String(action.number) &&
        new RegExp("^javascript:changePage\\(['\"]" + action.number + "['\"]\\);?$").test(a.getAttribute('href')));
    if (!target) throw new Error('移動先のリンクが表示中のページにありません。自動取り込みを止めます。');
    target.click();
    return true;
  };
  const prepare = async (cancelled, wantedRacks=null) => {
    // サイト自身の遅延読み込みを通常の表示操作で進める。URLの直接取得や再試行はしない。
    for (const {box, rack} of graphBoxes()) {
      if (cancelled()) throw new Error('停止しました。');
      if (wantedRacks !== null && !wantedRacks.includes(rack)) continue;
      // 遅延読み込みでimgや親boxが置き換わる場合も、同じ台の現在の要素を調べる。
      // 一時的に要素が消えても既存の12秒の中で待つ。重複・不明台の拒否は維持する。
      const current = () => graphBoxes(true).find(g=>g.rack===rack);
      const ready = () => imageReady(current()?.box.querySelector('img'));
      if (ready()) continue;
      box.scrollIntoView({block:'center', behavior:'instant'});
      const until = Date.now() + (window.__site777GraphWaitMs || 12000);
      while (!ready() && Date.now() < until) {
        if (cancelled()) throw new Error('停止しました。');
        await new Promise(resolve => setTimeout(resolve, 250));
      }
      if (!ready()) {
        // 自動取り込み中なら、カード側が1分待ってページを読み込み直し、続ける（同じページで3回まで。2026-11-07 利用者の依頼）。
        const error = new Error('グラフが読み込まれないため停止しました。');
        error.stalled = true;
        // URLや画像・会員情報は記録せず、次回は止まった台と画像の状態を区別できるようにする。
        const latest=current(), img=latest?.box.querySelector('img');
        error.graph_wait = {rack, complete:!!img?.complete, width:img?.naturalWidth||0,
          image_kind:!img ? 'missing' : new URL(img.currentSrc || img.src, location.href).pathname === '/chart/RequestSPDedamaTransitionChartForPortal.do'
            ? 'chart' : 'placeholder', visible:!!latest&&visible(latest.box)};
        throw error;
      }
    }
  };
  window.databaseSite777 = {read, go, prepare, samePage, readyRacks};
})();
