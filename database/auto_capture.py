"""Opt-in capture scheduling. No mouse input, challenge interaction or network IO."""
import math
import threading
import time


class AutoCapture:
    def __init__(self, clock=time.monotonic, minimum=0.1, maximum=4.5, default=3.5):
        # メルヘンは0.1〜4.5秒（初期3.5）。サイト固有の待機は_scheduleで設定する。
        self._lock = threading.RLock()
        self._clock = clock
        self._minimum, self._maximum = minimum, maximum
        self._enabled = False
        self._seconds = default
        self._message = '停止中'
        self._generation = 0
        self._deadline = 0.0
        self._seen = set()

    def state(self):
        with self._lock:
            return dict(enabled=self._enabled, seconds=self._seconds, message=self._message,
                        revision=self._generation)

    def _schedule(self):
        self._deadline = self._clock() + self._seconds

    def configure(self, enabled, seconds):
        if not isinstance(enabled, bool):
            raise ValueError('ON/OFFの指定が不正です。')
        message = f'間隔は{self._minimum:g}〜{self._maximum:g}秒で指定してください。'
        if isinstance(seconds, bool):
            raise ValueError(message)
        seconds = float(seconds)
        if not math.isfinite(seconds) or not self._minimum <= seconds <= self._maximum:
            raise ValueError(message)
        with self._lock:
            self._generation += 1
            self._seconds = round(seconds * 10) / 10
            if enabled and not self._enabled:
                self._seen.clear()
            self._enabled = enabled
            self._schedule()
            self._message = '次の取り込みを待っています' if enabled else '停止中（実行済みの保存は完了まで待ちます）'
            return self.state()

    def pause(self, message, generation=None):
        with self._lock:
            if generation is not None and generation != self._generation:
                return
            self._message = message
            self._schedule()

    def loaded(self):
        # Give each new document the chosen interval to finish rendering.
        with self._lock:
            self._generation += 1
            self._schedule()

    def due(self, busy=False):
        with self._lock:
            if not self._enabled:
                return None
            if busy:
                self._schedule()
                self._message = '保存処理中・完了待ち'
                return None
            if self._clock() < self._deadline:
                return None
            return self._generation

    def submit(self, generation, key, action):
        """Recheck OFF/navigation after extraction; serialize admission with OFF."""
        with self._lock:
            if not self._enabled or generation != self._generation:
                return False
            if key in self._seen:
                self.pause('ON・次のページ待ち（同じページは重複保存しません）')
                return False
            if not action():
                self._schedule()
                return False
            self._seen.add(key)
            self._schedule()
            self._message = '保存処理中・完了待ち'
            return True

    def run_current(self, generation, action):
        """Serialize a delayed navigation with OFF, without marking a save."""
        with self._lock:
            if not self._enabled or generation != self._generation:
                return False
            self._schedule()
            return action()


# Injected INSIDE the existing overlay closure, sharing its extraction functions.
AUTO_CAPTURE_JS = r'''
  const autoButton = document.createElement('button');
  autoButton.id = 'database-auto-toggle';
  autoButton.type = 'button';
  autoButton.style.cssText = 'padding:10px;border:2px solid #b8c5d8;border-radius:6px;color:white;cursor:pointer;font-size:14px;font-weight:bold;width:100%';
  autoButton.textContent = '自動取り込み：OFF';
  autoButton.style.background = '#526078';
  autoButton.disabled = true;
  const autoLabel = document.createElement('label');
  autoLabel.style.cssText = 'font-size:12px;display:block';
  const autoSeconds = document.createElement('input');
  autoSeconds.id = 'database-auto-interval';
  autoSeconds.type = 'range';
  autoSeconds.min = '0.1'; autoSeconds.max = '4.5'; autoSeconds.step = '0.1'; autoSeconds.value = '3.5';
  autoSeconds.style.width = '100%';
  const autoValue = document.createElement('span');
  autoValue.textContent = '間隔：3.5秒';
  autoLabel.append(autoValue, autoSeconds);
  const autoStatus = document.createElement('span');
  autoStatus.id = 'database-auto-status';
  autoStatus.style.cssText = 'font-size:11px;white-space:normal;word-break:break-word';
  autoStatus.textContent = '確認画面ではONのまま待機。確認は手動で操作してください。';
  // 日付指定取り込み：取り込む営業日を決める（日本時間の午前3時までは前日）。
  // 上から／下から：機種を一覧のどちら側から取り込むか。どちらも押すと自動取り込みをONにする。
  const autoDayBox = document.createElement('div');
  autoDayBox.style.cssText = 'font-size:12px;display:block';
  const autoDayText = document.createElement('span');
  autoDayText.textContent = '日付指定取り込み（取り込む日）';
  const autoDay = document.createElement('select');
  autoDay.id = 'database-auto-day';
  autoDay.setAttribute('aria-label', '日付指定取り込み（取り込む日）');
  autoDay.style.cssText = 'width:100%;margin-top:4px;padding:4px;font-size:12px';
  autoDayBox.append(autoDayText, autoDay);
  const tablesOnlyBox = document.createElement('label');
  tablesOnlyBox.style.cssText = 'font-size:12px;display:flex;align-items:center;gap:5px';
  const tablesOnlyInput = document.createElement('input');
  tablesOnlyInput.type = 'checkbox';
  tablesOnlyInput.id = 'database-tables-only';
  tablesOnlyInput.disabled = true;
  tablesOnlyBox.append(tablesOnlyInput, document.createTextNode('表だけ取り込む（グラフを省略）'));
  const autoStartRow = document.createElement('div');
  autoStartRow.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:6px';
  const makeStart = (id, text) => {
    const button = document.createElement('button');
    button.id = id; button.type = 'button'; button.textContent = text; button.disabled = true;
    button.style.cssText = 'padding:8px 2px;border:2px solid #b8c5d8;border-radius:6px;background:#304d6e;color:white;cursor:pointer;font-size:12px;font-weight:bold';
    return button;
  };
  const autoTop = makeStart('database-auto-top', '上から取り込む');
  const autoBottom = makeStart('database-auto-bottom', '下から取り込む');
  autoStartRow.append(autoTop, autoBottom);
  card.insertBefore(autoButton, captureBtn);
  card.insertBefore(autoLabel, captureBtn);
  card.insertBefore(autoDayBox, captureBtn);
  card.insertBefore(tablesOnlyBox, captureBtn);
  card.insertBefore(autoStartRow, captureBtn);
  card.insertBefore(autoStatus, captureBtn);
  let autoEnabled = false;
  let autoChanging = false;
  let autoRevision = -1;
  let autoCancelled = false;
  let tablesOnly = false;
  window.__databaseRenderAuto = state => {
    if (state.revision < autoRevision) return;
    autoRevision = state.revision;
    autoEnabled = !!state.enabled;
    autoButton.textContent = autoEnabled ? '自動取り込み：ON（押すと停止）' : '自動取り込み：OFF（押すと開始）';
    autoButton.style.background = autoEnabled ? '#087d59' : '#526078';
    autoButton.setAttribute('aria-pressed', String(autoEnabled));
    autoButton.disabled = autoChanging;
    autoSeconds.disabled = autoEnabled || autoChanging;
    const modeChanged = tablesOnly !== !!state.tables_only;
    tablesOnly = !!state.tables_only;
    tablesOnlyInput.checked = tablesOnly;
    tablesOnlyInput.disabled = autoEnabled || autoChanging;
    if (modeChanged) { refreshProgress(); markMachines(); }
    autoSeconds.value = String(state.seconds);
    autoValue.textContent = '間隔：' + Number(state.seconds).toFixed(1) + '秒';
    // 取り込み日の選択肢は、午前3時で営業日が変わるので、画面を開いたままでも毎回つくり直す。
    const days = Array.isArray(state.days) ? state.days : [];
    if (JSON.stringify(days) !== autoDay.dataset.days) {
      autoDay.dataset.days = JSON.stringify(days);
      autoDay.textContent = '';
      const none = document.createElement('option');
      none.value = ''; none.textContent = '指定なし（サイトの表示どおり）';
      autoDay.append(none);
      days.forEach((day, i) => {
        const option = document.createElement('option');
        const d = new Date(day + 'T00:00:00');
        option.value = day;
        option.textContent = (d.getMonth() + 1) + '/' + d.getDate() + '（' + '日月火水木金土'[d.getDay()] + '）' + (i === 0 ? '　今の営業日' : '');
        autoDay.append(option);
      });
    }
    autoDay.value = state.target_day || '';
    autoDay.disabled = autoEnabled || autoChanging;
    for (const button of [autoTop, autoBottom]) {
      button.disabled = autoEnabled || autoChanging;
      button.style.opacity = button.disabled ? '.5' : '1';
      // いまの向きを、自動取り込みのOFFの間も示す（手動の「次へ」もこの向きで次の機種を選ぶ）。
      const chosen = button === (state.direction === 'bottom' ? autoBottom : autoTop);
      button.style.outline = chosen ? '3px solid #087d59' : '';
      button.setAttribute('aria-pressed', String(chosen));
    }
    autoStatus.textContent = state.message;
    captureBtn.disabled = autoEnabled;
    captureBtn.style.opacity = autoEnabled ? '.5' : '1';
    undoBtn.disabled = autoEnabled;
  };
  autoSeconds.oninput = () => { autoValue.textContent = '間隔：' + Number(autoSeconds.value).toFixed(1) + '秒'; };
  const toggleAuto = async (enable, direction) => {
    if (autoChanging) return;
    moveEpoch++;
    moveCommitted = false;
    pendingMachineFallback = null;
    autoCancelled = autoEnabled;
    autoChanging = true;
    autoButton.disabled = true;
    autoTop.disabled = autoBottom.disabled = true;
    try {
      const state = await window.pywebview.api.set_auto_capture(enable, Number(autoSeconds.value), autoDay.value, direction);
      autoChanging = false;
      autoCancelled = !state.enabled;
      window.__databaseRenderAuto(state);
    } catch (error) {
      autoChanging = false;
      autoCancelled = false;
      autoButton.disabled = false;
      autoTop.disabled = autoBottom.disabled = autoEnabled;
      autoStatus.textContent = '切り替えに失敗しました。必要ならブラウザを閉じて停止してください。';
    }
  };
  autoButton.onclick = () => toggleAuto(!autoEnabled, null);
  autoTop.onclick = () => { if (!autoEnabled) toggleAuto(true, 'top'); };
  autoBottom.onclick = () => { if (!autoEnabled) toggleAuto(true, 'bottom'); };
  autoDay.onchange = async () => {
    try { window.__databaseRenderAuto(await window.pywebview.api.set_target_day(autoDay.value, null)); }
    catch (error) { autoStatus.textContent = '取り込み日を変えられませんでした：' + String(error && error.message || error); }
  };
  tablesOnlyInput.onchange = async () => {
    if (autoChanging || autoEnabled) { tablesOnlyInput.checked = tablesOnly; return; }
    const enabled = tablesOnlyInput.checked;
    autoChanging = true;
    tablesOnlyInput.disabled = true;
    autoButton.disabled = autoTop.disabled = autoBottom.disabled = true;
    try {
      const state = await window.pywebview.api.set_tables_only(enabled);
      moveEpoch++;
      moveCommitted = false;
      pendingMachineFallback = null;
      autoChanging = false;
      window.__databaseRenderAuto(state);
      status.textContent = state.tables_only ? '表だけ取り込みます。表を保存したら次の機種へ進みます。' : '表とグラフを取り込みます。';
    } catch (error) {
      autoChanging = false;
      tablesOnlyInput.checked = tablesOnly;
      try { window.__databaseRenderAuto(await window.pywebview.api.get_auto_capture()); }
      catch (_) { autoButton.disabled = tablesOnlyInput.disabled = false; autoTop.disabled = autoBottom.disabled = false; }
      status.textContent = '取り込みモードを変えられませんでした：' + String(error && error.message || error);
    }
  };
  const autoWaitReason = () => {
    if (document.readyState !== 'complete') return {error: 'ON・読み込み完了待ち'};
    if (window.jQuery && window.jQuery.active) return {error: 'ON・通信完了待ち'};
    const visible = el => !!(el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
    const challenges = document.querySelectorAll('iframe[src*="captcha" i], iframe[src*="challenge" i], .g-recaptcha, .h-captcha, #challenge-running, #challenge-stage, dialog[open], [role="dialog"]');
    if (Array.from(challenges).some(visible)) return {error: 'ON・確認画面で待機中。手動で確認してください。'};
    const bodyText = document.body ? document.body.innerText.replace(card.innerText, '') : '';
    if (/人間である|ロボットでは|セキュリティチェック|verify you are human|checking your browser|確認ダイアログ|同意してください|(?:利用規約|利用条件)[\s\S]{0,120}(?:同意する|確認してください)/i.test(bodyText))
      return {error: 'ON・確認画面で待機中。手動で確認してください。'};
    if (Array.from(document.querySelectorAll('[aria-busy="true"], .loading, .loader, #loading')).some(visible))
      return {error: 'ON・読み込み完了待ち'};
    return null;
  };
  window.__databaseAutoWaitReason = autoWaitReason;
  // 台ページは曲線を先に描き、グラフ内の数字（総回転数・BIG・REG・最大持玉）を少し遅れて
  // 入れることがある（2026-10-16、空のまま読んだ送信データを確認。曲線は後の保存と同じ）。
  // 幸町は一覧に最大持玉が無いので、空のまま送ると「N番台の数値を確認できません」で止まる。
  // 数字がすべて空のあいだは送らずに待つ。入らないままの台で止まり続けないよう、
  // 同じページで GRAPH_NUMBERS_WAIT_MS 待っても空なら、これまでどおり送る。
  const GRAPH_NUMBERS_WAIT_MS = 20000;
  let graphNumbersEmpty = null;
  const graphNumbersPending = payload => {
    const values = Object.values(payload.info || {});
    if (!values.length || values.some(value => String(value).trim() !== '')) {
      graphNumbersEmpty = null;
      return false;
    }
    if (!graphNumbersEmpty || graphNumbersEmpty.url !== location.href)
      graphNumbersEmpty = {url: location.href, since: Date.now()};
    return Date.now() - graphNumbersEmpty.since < GRAPH_NUMBERS_WAIT_MS;
  };
  window.__databaseAutoProbe = () => {
    if (autoCancelled || autoChanging) return {error: '切り替え待ち'};
    const waiting = autoWaitReason();
    if (waiting) return waiting;
    const id = pageIdentity();
    let kind, raw;
    if (id.rack !== null && tablesOnly) return {kind: 'table_only_return', url: location.href, ...id};
    if (id.rack !== null) { kind = 'graph'; raw = extractGraph(); }
    else if (id.machine) {
      // サイトに台情報が無い機種の表（「該当する台情報が見つかりませんでした」）は飛ばす。
      if (id.day && noRacksShown()) return {kind: 'no_racks', url: location.href, ...id};
      kind = 'table'; raw = extractTable();
    }
    else if (/rack_info_kt/.test(location.pathname)) {
      if (!machineLinks().length) return {error: 'ON・機種一覧の読み込み待ち'};
      return {kind: 'machines', url: location.href};
    }
    else return {error: 'ON・対象ページ待ち（確認操作は行いません）'};
    const payload = JSON.parse(raw);
    if (payload.error) return {error: payload.error};
    if (kind === 'graph' && graphNumbersPending(payload))
      return {error: '台の数値（総回転数・最大持玉など）の表示待ち'};
    return {kind, raw, url: location.href};
  };
  window.__databaseAutoMoveMachine = revision => {
    if (autoCancelled || autoChanging || autoWaitReason()) return false;
    // Python calls this on every interval, including when WebView2 is hidden.
    // A JavaScript setTimeout may be throttled while minimized, so retry a
    // row that did not navigate here instead of leaving ON stuck on the list.
    if (moveCommitted) {
      const pending = pendingMachineFallback;
      if (!pending || pending.epoch !== moveEpoch || pending.before !== location.href ||
          Date.now() - pending.started < 3000) return false;
      const fallback = new URL(pending.url, location.href);
      const day = pageIdentity().day;
      if (day && /^\d{4}-\d{2}-\d{2}$/.test(day)) fallback.searchParams.set('target_date', day);
      if (fallback.origin === location.origin &&
          fallback.pathname.startsWith('/' + currentStore + '/standlist_slot/') &&
          fallback.searchParams.get('kind_code') === '21' && fallback.searchParams.get('target_date')) {
        pendingMachineFallback = null;
        status.textContent = '機種の行が反応しなかったため、対象日を保って開きます。';
        location.href = fallback.href;
        return true;
      }
      status.textContent = pending.machine + ' の行を押しても移動しませんでした。日付を選んでください。';
      return false;
    }
    if (moveBusy) return false;
    moveToNextMachine(revision).catch(error => { autoStatus.textContent = 'ON・移動できません：' + String(error); });
    return true;
  };
  window.__databaseAutoAdvance = url => {
    if (autoCancelled || autoChanging || autoWaitReason()) return false;
    location.href = url;
    return true;
  };
  window.pywebview.api.get_auto_capture().then(state => {
    window.__databaseRenderAuto(state);
    // The Python scheduler owns movement while ON; the legacy continuation
    // only runs once on an untouched OFF document.
    if (!state.enabled && state.manual_continuation && moveEpoch === 0 && new URLSearchParams(location.hash.replace(/^#/, '')).get('database_next_machine') === '1')
      moveToNextMachine().catch(error => { status.textContent = String(error); });
  }).catch(() => {
    autoStatus.textContent = '自動取り込みの接続に失敗しました。ブラウザを開き直してください。';
  });
  const fitCard = () => {
    card.style.boxSizing = 'border-box';
    card.style.width = Math.min(216, (window.innerWidth - 8) / sizeScale) + 'px';
    card.style.maxHeight = Math.max(60, (window.innerHeight - 8) / sizeScale) + 'px';
    card.style.overflowY = 'auto';
    for (const child of card.children) child.style.flexShrink = '0';
    const rect = card.getBoundingClientRect();
    place(rect.left, rect.top);
  };
  // Keep the stop control near the top, including in short windows.
  card.insertBefore(autoButton, switchBtn);
  card.insertBefore(autoLabel, switchBtn);
  card.insertBefore(autoDayBox, switchBtn);
  card.insertBefore(tablesOnlyBox, switchBtn);
  card.insertBefore(autoStartRow, switchBtn);
  window.addEventListener('resize', fitCard);
  new ResizeObserver(fitCard).observe(card);
  fitCard();
'''
