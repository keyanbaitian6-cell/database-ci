// 閲覧用のGoogleスクリプト2本に、日次学習の公開用の読み出しを組み込む。--check は、配布版が生成元と同じかだけを確かめる。
import fs from 'node:fs';
const root=new URL('./',import.meta.url);
const source=fs.readFileSync(new URL('daily_learning_projection.js',root),'utf8').replace(/\r\n/g,'\n').trim();
const check=process.argv.includes('--check');
for(const name of ['viewer_drive_script.gs','viewer_drive_script_readonly.gs']) {
  const path=new URL(name,root);
  const original=fs.readFileSync(path,'utf8').replace(/\r\n/g,'\n');
  let text=original.replace(/\n*\/\/ BEGIN DAILY_LEARNING\n[\s\S]*?\/\/ END DAILY_LEARNING\n*/,'\n\n');
  if(!text.includes("if (key === 'daily-learning')")) text=text.replace("  const key = (e && e.parameter && e.parameter.file) || '';",
    "  const key = (e && e.parameter && e.parameter.file) || '';\n  if (key === 'daily-learning') return readDailyLearning();");
  // 履歴（build_event_history_share.mjs）と日別読み込み（build_viewer_parts.mjs）の生成は、自分の印から後ろを作り直す。
  // 末尾に置くと消されて照合が合わなくなるので、それらの印より前に置く（2026-11-11）。
  const anchor=['// BEGIN EVENT_HISTORY_SHARED','// BEGIN GENERATED VIEWER PARTS'].map(a=>text.indexOf(a)).find(i=>i>=0);
  if(anchor===undefined) throw Error(`${name}の生成範囲がありません。`);
  text=text.slice(0,anchor).trimEnd()+`\n\n// BEGIN DAILY_LEARNING\n${source}\n// END DAILY_LEARNING\n\n`+text.slice(anchor);
  if(check) { if(text!==original) throw Error(`${name}を再生成してください（node tool/build_daily_learning.mjs）。`); }
  else fs.writeFileSync(path,text);
}
