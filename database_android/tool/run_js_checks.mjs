// 試験はファイルごとの別プロセスに保ち、同時実行数だけを制限する。
// ログ・終了コード・未実行を必ず集約し、並行実行中の失敗を取りこぼさない。
import {spawn} from 'node:child_process';
import {openSync,closeSync,appendFileSync} from 'node:fs';
import {mkdir,readdir,readFile,writeFile,rename,open,rm} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

async function tailLog(file) {
  const handle=await open(file,'r');
  try {
    const size=(await handle.stat()).size,buffer=Buffer.alloc(Math.min(size,128*1024));
    await handle.read(buffer,0,buffer.length,Math.max(0,size-buffer.length));
    return buffer.toString('utf8').trimEnd().split(/\r?\n/).slice(-120).join('\n');
  } finally {await handle.close();}
}

export async function runChecks({directory,work,viewerReady,jobs=1,output=text=>process.stdout.write(text)}) {
  if(!Number.isInteger(jobs) || jobs<1 || jobs>2) throw new Error('同時実行数は1または2を指定してください。');
  const started=performance.now(),tool=path.join(directory,'tool');
  await mkdir(work,{recursive:true});
  await Promise.all(['js-results.json','js-failed.txt','js-unrun.txt'].map(name=>rm(path.join(work,name),{force:true})));
  const files=(await readdir(tool)).filter(f=>f.startsWith('test_') && f.endsWith('.mjs')).sort();
  if(!files.length) throw new Error('JavaScriptの試験が見つかりません。');
  if(files.some(f=>/[\r\n\t]/.test(f))) throw new Error('試験のファイル名に改行やタブは使えません。');
  const results=new Array(files.length);let next=0,active=0,peak=0;
  async function execute(file) {
    const name=file.slice(0,-4),log=path.join(work,name+'.log'),begin=performance.now();
    const text=await readFile(path.join(tool,file),'utf8');
    if(!viewerReady && (text.includes('VIEWER_WEB_ROOT') || text.includes('build/web'))) {
      await writeFile(log,'未実行：新しいFlutterビルドが必要です。\n');
      output(`UNRUN ${name} （新しいFlutterビルドが必要）\n`);
      return {file,name,state:'unrun',duration_ms:0};
    }
    active++;peak=Math.max(peak,active);
    let code,signal,spawnError;
    try {
      const fd=openSync(log,'w');
      try {
        await new Promise(resolve=>{
          const env={...process.env};delete env.NODE_TEST_CONTEXT;
          const child=spawn(process.execPath,['--test',path.join('tool',file)],{cwd:directory,env,stdio:['ignore',fd,fd]});
          child.once('error',error=>{spawnError=error.code || '起動失敗';});
          child.once('close',(status,killed)=>{code=status;signal=killed;resolve();});
        });
      } finally {closeSync(fd);}
      if(spawnError) appendFileSync(log,`\n試験プロセスを起動できませんでした：${spawnError}\n`);
    } finally {active--;}
    const state=code===0 && !signal && !spawnError ? 'passed' : 'failed';
    const result={file,name,state,exit_code:code,signal,duration_ms:Math.round((performance.now()-begin)*1000)/1000};
    if(state==='passed') output(`OK    ${name}\n`);
    else output(`FAIL  ${name} （記録：${log}）\n::group::${name} failure log (last 120 lines)\n${await tailLog(log)}\n::endgroup::\n`);
    return result;
  }
  async function worker() {
    for(;;) {
      const index=next++;if(index>=files.length)return;
      results[index]=await execute(files[index]);
    }
  }
  await Promise.all(Array.from({length:jobs},worker));
  const report={version:1,jobs,peak_active:peak,duration_ms:Math.round((performance.now()-started)*1000)/1000,results};
  await writeFile(path.join(work,'js-results.json.tmp'),JSON.stringify(report,null,2));
  await rename(path.join(work,'js-results.json.tmp'),path.join(work,'js-results.json'));
  for(const state of ['failed','unrun']) await writeFile(path.join(work,`js-${state}.txt`),results.filter(r=>r.state===state).map(r=>r.name+'\n').join(''));
  return report;
}

export async function summarize(work) {
  const tsv=await readFile(path.join(work,'timings.tsv'),'utf8');
  const report=JSON.parse(await readFile(path.join(work,'js-results.json'),'utf8'));
  const escape=s=>String(s).replaceAll('|','\\|').replace(/[\r\n]/g,' ');
  const label=s=>({passed:'成功',failed:'失敗',unrun:'未実行'})[s] || s;
  const rows=tsv.trim().split(/\r?\n/).slice(1).map(line=>line.split('\t'));
  const lines=['## 回帰確認の所要時間','','|工程|結果|秒|','|---|---|---:|',
    ...rows.map(([name,state,sec])=>`|${escape(name)}|${label(state)}|${sec}|`),'',
    `JavaScript：${report.results.length}ファイル、同時実行数${report.jobs}（実測最大${report.peak_active}）。`,
    `成功 ${report.results.filter(r=>r.state==='passed').length}・失敗 ${report.results.filter(r=>r.state==='failed').length}・未実行 ${report.results.filter(r=>r.state==='unrun').length}。`,
    '','|時間の長いJavaScript試験|結果|秒|','|---|---|---:|',
    ...report.results.slice().sort((a,b)=>b.duration_ms-a.duration_ms).slice(0,10).map(r=>`|${escape(r.name)}|${label(r.state)}|${(r.duration_ms/1000).toFixed(2)}|`),''];
  await writeFile(path.join(work,'timings.md'),lines.join('\n'));
}

if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  try {
    if(process.argv[2]==='--summary') await summarize(path.resolve(process.argv[3]));
    else {
      const report=await runChecks({directory:process.cwd(),work:path.resolve(process.argv[2]),viewerReady:process.argv[3]==='true',jobs:Number(process.env.CHECK_JS_JOBS || 1)});
      process.exitCode=report.results.some(r=>r.state==='failed') ? 1 : 0;
    }
  } catch(error) {
    console.error(`JavaScript確認を完了できませんでした：${error.message}`);process.exitCode=2;
  }
}
