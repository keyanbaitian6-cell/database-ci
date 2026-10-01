import {readWebArchive} from './archive.mjs';
import {emptyData, validateData, mergeData, parsePage} from './data.mjs';
import {REMOTE_KEY, fetchDrive, buildBackup, backupFileName} from './sync.mjs';

// Reuse the old database and keys so the already imported records survive.
const open = () => new Promise((resolve, reject) => {
  const request = indexedDB.open('database-pscube-viewer', 1);
  request.onupgradeneeded = () => request.result.createObjectStore('state');
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(request.error);
});
async function read() {
  const db = await open();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('state');
      const data = tx.objectStore('state').get('data'), meta = tx.objectStore('state').get('meta');
      tx.oncomplete = () => resolve({data: data.result, meta: meta.result || {}});
      tx.onerror = tx.onabort = () => reject(tx.error);
    });
  } finally { db.close(); }
}
async function write(data, meta) {
  const db = await open();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction('state', 'readwrite');
      tx.objectStore('state').put(data, 'data');
      tx.objectStore('state').put(meta, 'meta');
      tx.oncomplete = resolve;
      tx.onerror = tx.onabort = () => reject(tx.error || new Error('端末に保存できませんでした。'));
    });
  } finally { db.close(); }
}
function envelope(data, meta = {}) {
  return JSON.stringify({...validateData(data),
    header: {source: 'pscube', exported_at: meta.exported_at ?? null},
    file: meta.file ?? 'P’s CUBE', loaded_at: meta.loaded_at ?? new Date().toISOString()});
}
export async function isPscubeFile(file) {
  if (/\.webarchive$/i.test(file.name)) return true;
  const head = await file.slice(0, 4096).text();
  return head.startsWith('bplist') || head.includes('WebMainResource') ||
    /"format"\s*:\s*"pscube-viewer"/.test(head);
}
export async function readPscubeFiles(files, existing) {
  const old = existing ?? (await read()).data;
  let data = old ? validateData(old) : emptyData();
  let exportedAt = null;
  for (const file of files) {
    let fresh;
    const head = (await file.slice(0, 4096).text()).replace(/^\uFEFF/, '').trimStart();
    if (/\.webarchive$/i.test(file.name) || !head.startsWith('{')) {
      fresh = parsePage(await readWebArchive(await file.arrayBuffer()));
    } else {
      const raw = JSON.parse((await file.text()).replace(/^\uFEFF/, ''));
      fresh = validateData(raw); exportedAt = raw.exported_at ?? null;
    }
    data = mergeData(data, fresh);
  }
  return envelope(data, {file: files.map(f => f.name).join('、'), exported_at: exportedAt});
}
export function createPscubeBridge() {
  return {
    pick() {
      return new Promise((resolve, reject) => {
        const input = document.createElement('input');
        input.type = 'file'; input.multiple = true;
        input.oncancel = () => resolve(null);
        input.onchange = async () => {
          if (!input.files?.length) { resolve(null); return; }
          try { resolve(await readPscubeFiles([...input.files])); } catch (error) { reject(error); }
        };
        input.click();
      });
    },
    async fromUrl(url) {
      if (!url || /^[a-z]+:/i.test(url) || url.startsWith('//')) return null;
      const response = await fetch(url);
      if (!response.ok) return null;
      const doc = await response.json();
      return envelope(validateData(doc), {file: url, exported_at: doc.exported_at});
    },
    async fromRemote(url, known) {
      const result = await fetchDrive(url, known);
      if (result.unchanged) return null;
      const old = (await read()).data;
      return envelope(old ? mergeData(validateData(old), result.data) : result.data,
        {file: 'Googleドライブ（自動）', exported_at: result.exportedAt});
    },
    getRemote() { try { return localStorage.getItem(REMOTE_KEY); } catch { return null; } },
    setRemote(url) {
      try { if (url) localStorage.setItem(REMOTE_KEY, url); else localStorage.removeItem(REMOTE_KEY); } catch {}
    },
    async save(text) {
      const raw = JSON.parse(text), valid = validateData(raw), previous = await read();
      await write(previous.data ? mergeData(validateData(previous.data), valid) : valid,
        {...previous.meta, exported_at: raw.header?.exported_at ?? null,
          file: raw.file ?? 'P’s CUBE', loaded_at: raw.loaded_at ?? new Date().toISOString()});
    },
    async load() {
      const saved = await read();
      return saved.data ? envelope(saved.data, saved.meta) : null;
    },
    async exportBackup() {
      const saved = await read();
      if (!saved.data) throw new Error('まだデータを読み込んでいません。');
      const blob = new Blob([JSON.stringify(buildBackup(saved.data))], {type:'application/json'});
      const url = URL.createObjectURL(blob), a = document.createElement('a');
      a.href = url; a.download = backupFileName(); a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
    async setPscubeType(scope, machine, type) {
      if (![null, 'normal', 'other'].includes(type)) throw new Error('機種タイプが不正です。');
      const saved = await read();
      if (!saved.data) throw new Error('先にデータを読み込んでください。');
      const [, store, rate] = scope.split(':');
      const normalize = s => s.replaceAll('+', ' ').replace(/\s+/g, ' ').trim();
      let found = false;
      const machines = saved.data.machines.map(m => {
        if (m.store === store && m.rate === rate && normalize(m.machine) === machine) {
          found = true; return {...m, machine_type:type};
        }
        return m;
      });
      if (!found) throw new Error('機種情報がありません。');
      const data = validateData({...saved.data, machines});
      await write(data, saved.meta);
      return envelope(data, saved.meta);
    },
  };
}
