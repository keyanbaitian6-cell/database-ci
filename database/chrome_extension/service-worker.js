const ALLOWED_HOST = 'meruhenworld.pt.teramoba2.com';
const ALLOWED_PATHS = new Set([
  '/nagamachiminami/standlist_slot',
  '/nagamachiminami/standgraph',
  '/saiwaichou/standlist_slot',
  '/saiwaichou/standgraph',
]);
let running = false;

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function setStatus(tabId, text, color, title) {
  await chrome.action.setBadgeBackgroundColor({tabId, color});
  await chrome.action.setBadgeText({tabId, text});
  await chrome.action.setTitle({tabId, title});
}

async function preparePage(tabId) {
  const [{result}] = await chrome.scripting.executeScript({
    target: {tabId},
    func: async () => {
      const root = document.documentElement;
      root.dataset.databaseCaptureScrollX = String(window.scrollX);
      root.dataset.databaseCaptureScrollY = String(window.scrollY);
      root.dataset.databaseCaptureScrollBehavior = root.style.getPropertyValue('scroll-behavior');
      root.dataset.databaseCaptureScrollPriority = root.style.getPropertyPriority('scroll-behavior');
      root.style.setProperty('scroll-behavior', 'auto', 'important');

      for (const element of document.querySelectorAll('*')) {
        const position = getComputedStyle(element).position;
        // The rack-number column is sticky on this site. Hiding every sticky
        // element removes the rack numbers from the screenshot, so only hide
        // viewport-fixed overlays here.
        if (position !== 'fixed') continue;
        element.dataset.databaseCaptureHidden = '1';
        element.dataset.databaseCaptureVisibility = element.style.getPropertyValue('visibility');
        element.dataset.databaseCaptureVisibilityPriority = element.style.getPropertyPriority('visibility');
        element.style.setProperty('visibility', 'hidden', 'important');
      }
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

      const body = document.body;
      const totalHeight = Math.max(root.scrollHeight, root.offsetHeight,
        body ? body.scrollHeight : 0, body ? body.offsetHeight : 0);
      const viewportHeight = window.innerHeight;
      const viewportWidth = window.innerWidth;
      const finalY = Math.max(0, totalHeight - viewportHeight);
      const positions = [];
      for (let y = 0; y < finalY; y += viewportHeight) positions.push(y);
      positions.push(finalY);

      const url = new URL(location.href);
      const selectedDate = document.querySelector('select')?.value || url.searchParams.get('target_date') || '';
      const captureDate = String(selectedDate).replaceAll('/', '-').match(/\d{4}-\d{2}-\d{2}/)?.[0]
        || new Date().toISOString().slice(0, 10);
      const rack = url.searchParams.get('rack_no');
      const kind = url.pathname.endsWith('/standgraph') ? 'graph' : 'list';
      const store = url.pathname.split('/').filter(Boolean)[0];
      let machineName = url.searchParams.get('machine_name') || '';
      for (let count = 0; count < 3 && machineName; count++) {
        try {
          const decoded = decodeURIComponent(machineName);
          if (decoded === machineName) break;
          machineName = decoded;
        } catch (_) {
          break;
        }
      }
      return {totalHeight, viewportHeight, viewportWidth, positions, captureDate, rack, kind, store, machineName};
    },
  });
  return result;
}

async function scrollPage(tabId, y) {
  const [{result}] = await chrome.scripting.executeScript({
    target: {tabId},
    args: [y],
    func: async (position) => {
      window.scrollTo(0, position);
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      return window.scrollY;
    },
  });
  return Number(result);
}

async function restorePage(tabId) {
  await chrome.scripting.executeScript({
    target: {tabId},
    func: () => {
      const root = document.documentElement;
      for (const element of document.querySelectorAll('[data-database-capture-hidden]')) {
        element.style.setProperty('visibility', element.dataset.databaseCaptureVisibility || '',
          element.dataset.databaseCaptureVisibilityPriority || '');
        delete element.dataset.databaseCaptureHidden;
        delete element.dataset.databaseCaptureVisibility;
        delete element.dataset.databaseCaptureVisibilityPriority;
      }
      root.style.setProperty('scroll-behavior', root.dataset.databaseCaptureScrollBehavior || '',
        root.dataset.databaseCaptureScrollPriority || '');
      const x = Number(root.dataset.databaseCaptureScrollX || 0);
      const y = Number(root.dataset.databaseCaptureScrollY || 0);
      delete root.dataset.databaseCaptureScrollX;
      delete root.dataset.databaseCaptureScrollY;
      delete root.dataset.databaseCaptureScrollBehavior;
      delete root.dataset.databaseCaptureScrollPriority;
      window.scrollTo(x, y);
    },
  });
}

function filenameFor(info) {
  const stamp = new Date().toISOString().replaceAll(':', '').replaceAll('.', '-');
  const bytes = new TextEncoder().encode(info.machineName || '');
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  const token = binary ? btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '') : '';
  const storePart = info.store ? `~s${info.store}` : '';
  const machinePart = token ? `~m${token}~` : '';
  if (info.kind === 'graph') {
    if (!/^\d{1,4}$/.test(info.rack || '')) throw new Error('グラフの台番号を確認できません。');
    return `database-graph-rack-${info.rack}-${info.captureDate}${storePart}${machinePart}-${stamp}.png`;
  }
  return `database-list-${info.captureDate}${storePart}${machinePart}-${stamp}.png`;
}

async function capture(tab) {
  if (running || !tab?.id || !tab?.url) return;
  const url = new URL(tab.url);
  if (url.protocol !== 'https:' || url.hostname !== ALLOWED_HOST || !ALLOWED_PATHS.has(url.pathname)) {
    await setStatus(tab.id, '×', '#b00020', 'このページはdatabaseの撮影対象ではありません');
    await delay(2500);
    await chrome.action.setBadgeText({tabId: tab.id, text: ''});
    return;
  }
  if (url.pathname.endsWith('/standlist_slot') && url.searchParams.get('kind_code') !== '21') {
    await setStatus(tab.id, '×', '#b00020', 'database：1000円46枚スロットだけが対象です');
    await delay(2500);
    await chrome.action.setBadgeText({tabId: tab.id, text: ''});
    return;
  }

  running = true;
  let prepared = false;
  try {
    await setStatus(tab.id, '…', '#40536d', 'database：撮影中');
    const info = await preparePage(tab.id);
    prepared = true;
    const captures = [];
    for (let index = 0; index < info.positions.length; index++) {
      const y = await scrollPage(tab.id, info.positions[index]);
      await delay(650); // captureVisibleTab is limited to two calls per second.
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {format: 'png'});
      captures.push({y, dataUrl});
      await chrome.action.setBadgeText({tabId: tab.id, text: `${index + 1}`});
    }
    await restorePage(tab.id);
    prepared = false;

    const jobId = crypto.randomUUID();
    const storageKey = `captureJob-${jobId}`;
    await chrome.storage.local.set({
      [storageKey]: {...info, captures, filename: filenameFor(info)},
    });
    await chrome.tabs.create({url: chrome.runtime.getURL(`stitch.html?job=${jobId}`), active: false});
    await setStatus(tab.id, '✓', '#087f5b', 'database：撮影しました');
    await delay(2500);
    await chrome.action.setBadgeText({tabId: tab.id, text: ''});
  } catch (error) {
    if (prepared) {
      try { await restorePage(tab.id); } catch (_) {}
    }
    console.error('database capture failed', error);
    await setStatus(tab.id, '!', '#b00020', `database：${error.message || error}`);
  } finally {
    running = false;
  }
}

chrome.action.onClicked.addListener(capture);
chrome.commands.onCommand.addListener(async (command) => {
  if (command !== 'capture-full-page') return;
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  await capture(tab);
});
