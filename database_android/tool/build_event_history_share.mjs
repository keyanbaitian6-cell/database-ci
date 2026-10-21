// Apps Scriptにもブラウザと同じ履歴検証・時刻比較を組み込む。
import fs from 'node:fs/promises';
import {partsDrive} from './build_viewer_parts.mjs';
const api=(await fs.readFile(new URL('../../share_viewer/event_history.mjs',import.meta.url),'utf8')).replace(/\r\n/g,'\n');
const runtime=(await fs.readFile(new URL('event_history_drive.js',import.meta.url),'utf8')).replace(/\r\n/g,'\n');
const begin='// BEGIN EVENT_HISTORY_SHARED', end='// END EVENT_HISTORY_SHARED';
// Apps Scriptの保存時パーサーはBigIntの数値リテラル（1000n）を受け付けない。
// コンストラクターで同じ整数を作り、比較のマイクロ秒精度は維持する。
const portable=api.replace(/\bexport /g,'').replaceAll('Object.hasOwn(', 'Object.prototype.hasOwnProperty.call(')
  .replace(/\b(\d+)n\b/g,'BigInt("$1")');
const block=`${begin}\nconst EVENT_HISTORY_API=(function(){\n${portable}\nreturn {parsePrivateHistory,historyCell,historyEditKey,mergeHistoryCells};\n})();\n${runtime}\n${end}`;
for(const name of ['viewer_drive_script.gs','viewer_drive_script_readonly.gs']) {
  const url=new URL(name,import.meta.url), old=await fs.readFile(url,'utf8');
  const normalized=old.replace(/\r\n/g,'\n');
  const start=normalized.indexOf(begin), stop=normalized.indexOf(end);
  if((start<0)!==(stop<0) || (start>=0 && stop<start)) throw Error(`${name}の生成範囲が不正です。`);
  const without=start<0?normalized:normalized.slice(0,start)+normalized.slice(stop+end.length);
  const parts=without.indexOf('// BEGIN GENERATED VIEWER PARTS\n');
  if(parts<0) throw Error(`${name}の日別読み込みの生成範囲がありません。`);
  // 既存の日別読み込み生成は末尾を置換するため、履歴の生成部分はその前に置く。
  const text=without.slice(0,parts).trimEnd()+'\n\n'+block+'\n// BEGIN GENERATED VIEWER PARTS\n'+partsDrive();
  if(process.argv.includes('--check')) { if(text!==normalized) throw Error(`${name}を再生成してください。`); }
  else await fs.writeFile(url,text,'utf8');
}
