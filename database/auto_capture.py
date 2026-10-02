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
  card.insertBefore(autoButton, captureBtn);
  card.insertBefore(autoLabel, captureBtn);
  card.insertBefore(autoStatus, captureBtn);
  let autoEnabled = false;
  let autoChanging = false;
  let autoRevision = -1;
  let autoCancelled = false;
  window.__databaseRenderAuto = state => {
    if (state.revision < autoRevision) return;
    autoRevision = state.revision;
    autoEnabled = !!state.enabled;
    autoButton.textContent = autoEnabled ? '自動取り込み：ON（押すと停止）' : '自動取り込み：OFF（押すと開始）';
    autoButton.style.background = autoEnabled ? '#087d59' : '#526078';
    autoButton.setAttribute('aria-pressed', String(autoEnabled));
    autoButton.disabled = autoChanging;
    autoSeconds.disabled = autoEnabled || autoChanging;
    autoSeconds.value = String(state.seconds);
    autoValue.textContent = '間隔：' + Number(state.seconds).toFixed(1) + '秒';
    autoStatus.textContent = state.message;
    captureBtn.disabled = autoEnabled;
    captureBtn.style.opacity = autoEnabled ? '.5' : '1';
    undoBtn.disabled = autoEnabled;
  };
  autoSeconds.oninput = () => { autoValue.textContent = '間隔：' + Number(autoSeconds.value).toFixed(1) + '秒'; };
  autoButton.onclick = async () => {
    if (autoChanging) return;
    moveEpoch++;
    moveCommitted = false;
    pendingMachineFallback = null;
    autoCancelled = autoEnabled;
    autoChanging = true;
    autoButton.disabled = true;
    try {
      const state = await window.pywebview.api.set_auto_capture(!autoEnabled, Number(autoSeconds.value));
      autoChanging = false;
      autoCancelled = !state.enabled;
      window.__databaseRenderAuto(state);
    } catch (error) {
      autoChanging = false;
      autoButton.disabled = false;
      autoStatus.textContent = '切り替えに失敗しました。必要ならブラウザを閉じて停止してください。';
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
  window.__databaseAutoProbe = () => {
    if (autoCancelled || autoChanging) return {error: '切り替え待ち'};
    const waiting = autoWaitReason();
    if (waiting) return waiting;
    const id = pageIdentity();
    let kind, raw;
    if (id.rack !== null) { kind = 'graph'; raw = extractGraph(); }
    else if (id.machine) { kind = 'table'; raw = extractTable(); }
    else if (/rack_info_kt/.test(location.pathname)) {
      if (!machineLinks().length) return {error: 'ON・機種一覧の読み込み待ち'};
      return {kind: 'machines', url: location.href};
    }
    else return {error: 'ON・対象ページ待ち（確認操作は行いません）'};
    const payload = JSON.parse(raw);
    if (payload.error) return {error: payload.error};
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
  window.addEventListener('resize', fitCard);
  new ResizeObserver(fitCard).observe(card);
  fitCard();
'''
