(function () {
  const rack = new URL(document.URL).searchParams.get('cd_dai');
  if (!rack || !/^\d+$/.test(rack)) {
    completion(JSON.stringify({error: '台番号を確認できません'}));
    return;
  }
  // URLで営業日を選んでいればその日。省略時は未確定の当日を避けて日本時間の前日。
  const chosen = new URL(document.URL).searchParams.get('YMD_biz');
  const yesterday = new Date(Date.now() - 15 * 60 * 60 * 1000)
    .toISOString().slice(0, 10).replaceAll('-', '');
  const day = /^\d{8}$/.test(chosen || '') ? chosen : yesterday;
  const id = 'pscube_graph_result_' + Date.now();
  const box = document.createElement('div');
  box.id = id;
  box.style.display = 'none';
  document.body.appendChild(box);
  const script = document.createElement('script');
  script.textContent = `
    (function () {
      var box = document.getElementById(${JSON.stringify(id)});
      try {
        if (!window.api || !window.jQuery) throw new Error('サイトの読み込みが未完了です');
        jQuery.ajax({
          url: 'nc-m06-003.php',
          data: {cd_dai: ${JSON.stringify(rack)}, YMD_biz: ${JSON.stringify(day)},
            apikey: api.apikey, _i: api.token._i, _t: api.token._t},
          dataType: 'json'
        }).done(function (data) {
          var graph = data && data.Graph && data.Graph.src;
          box.textContent = JSON.stringify(graph && graph.datas && graph.datas.p
            ? {rack: ${JSON.stringify(rack)}, day: ${JSON.stringify(day)}, graph: graph}
            : {error: 'グラフの形式を確認できません'});
        }).fail(function (xhr, status) {
          box.textContent = JSON.stringify({error: 'サイトの通信が失敗しました',
            status: xhr.status, type: xhr.getResponseHeader('content-type'), result: status});
        });
      } catch (error) {
        box.textContent = JSON.stringify({error: String(error.message || error)});
      }
    })();`;
  document.body.appendChild(script);
  script.remove();
  let count = 0;
  const timer = setInterval(() => {
    if (box.textContent || ++count >= 50) {
      clearInterval(timer);
      const result = box.textContent || JSON.stringify({error: 'ページ内の処理が始まりませんでした'});
      box.remove();
      completion(result);
    }
  }, 200);
})();
