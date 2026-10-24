import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm,access} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {runChecks,summarize} from './run_js_checks.mjs';

async function fixture(t,files) {
  const root=await mkdtemp(path.join(os.tmpdir(),'js-checks-'));
  t.after(()=>rm(root,{recursive:true,force:true}));
  const directory=path.join(root,'android'),work=path.join(root,'logs');
  await mkdir(path.join(directory,'tool'),{recursive:true});
  for(const [name,content] of Object.entries(files)) await writeFile(path.join(directory,'tool',name),content);
  return {root,directory,work};
}
const waitFor=async test=>{
  const limit=Date.now()+10000;
  while(!await test()) {if(Date.now()>limit)throw new Error('合成プロセスの待合せが完了しません。');await new Promise(r=>setTimeout(r,10));}
};

for(const jobs of [1,2]) test(`同時実行数${jobs}でも全ファイルを1回ずつ確認し、1件の失敗を最後まで保持する`,async t=>{
  const f=await fixture(t,{
    'test_alpha.mjs':"console.log('一度だけ：alpha');",
    'test_broken.mjs':"for(let i=0;i<180;i++)console.log('途中'+i);console.log('失敗の元の理由');process.exitCode=9;",
    'test_omega.mjs':"console.log('一度だけ：omega');",
  });
  const output=[];const report=await runChecks({...f,viewerReady:true,jobs,output:s=>output.push(s)});
  assert.deepEqual(report.results.map(r=>[r.name,r.state]),[['test_alpha','passed'],['test_broken','failed'],['test_omega','passed']]);
  assert.ok(report.peak_active<=jobs);
  assert.equal((await readFile(path.join(f.work,'test_alpha.log'),'utf8')).match(/一度だけ：alpha/g).length,1);
  assert.equal((await readFile(path.join(f.work,'test_omega.log'),'utf8')).match(/一度だけ：omega/g).length,1);
  const failure=output.find(s=>s.includes('FAIL'));assert.match(failure,/失敗の元の理由/);assert.match(failure,/::group::.*::endgroup::/s);
  assert.doesNotMatch(failure,/途中0\b/,'CIには末尾だけ、完全なログは別ファイルに残す');
  assert.match(await readFile(path.join(f.work,'test_broken.log'),'utf8'),/途中0\b/);
  assert.equal(await readFile(path.join(f.work,'js-failed.txt'),'utf8'),'test_broken\n');
  assert.equal(await readFile(path.join(f.work,'js-unrun.txt'),'utf8'),'');
  assert.deepEqual(JSON.parse(await readFile(path.join(f.work,'js-results.json'),'utf8')),report);
});

test('2本は実際に重なって進み、終了前に3本目を開始しない',async t=>{
  const child=`import {writeFile,access} from 'node:fs/promises';
    const mine=new URL(import.meta.url).pathname.endsWith('/test_alpha.mjs') ? 'alpha' : 'beta';
    await writeFile(mine+'.started','');
    const limit=Date.now()+10000;
    while(true){try{await access('release');break;}catch{if(Date.now()>limit)throw new Error('待合せ失敗');await new Promise(r=>setTimeout(r,10));}}
    await writeFile(mine+'.done','');`;
  const f=await fixture(t,{'test_alpha.mjs':child,'test_beta.mjs':child,'test_gamma.mjs':"import{writeFile}from'node:fs/promises';await writeFile('gamma.started','');"});
  const exists=name=>access(path.join(f.directory,name)).then(()=>true,()=>false);
  const pending=runChecks({...f,viewerReady:true,jobs:2,output:()=>{}});
  try {
    await waitFor(async()=>await exists('alpha.started') && await exists('beta.started'));
    assert.equal(await exists('gamma.started'),false);
  } finally {await writeFile(path.join(f.directory,'release'),'');}
  const report=await pending;
  assert.equal(report.peak_active,2);assert.ok(report.results.every(r=>r.state==='passed'));assert.equal(await exists('gamma.started'),true);
});

test('新しい閲覧ビルドが無い場合は古い画面を実行せず、未実行を成功と区別する',async t=>{
  // 合成の印を作り、この検証自身を閲覧ページ依存と誤判定させない。
  const marker=['VIEWER_','WEB_ROOT'].join('');
  const f=await fixture(t,{'test_plain.mjs':"console.log('成功');",'test_view.mjs':`// ${marker}\nthrow new Error('古い画面を実行しました');`});
  await mkdir(f.work);await writeFile(path.join(f.work,'test_view.log'),'前回の成功');
  const report=await runChecks({...f,viewerReady:false,jobs:2,output:()=>{}});
  assert.deepEqual(report.results.map(r=>r.state),['passed','unrun']);
  assert.equal(await readFile(path.join(f.work,'js-unrun.txt'),'utf8'),'test_view\n');
  assert.match(await readFile(path.join(f.work,'test_view.log'),'utf8'),/未実行/);
  const fresh=await runChecks({...f,viewerReady:true,jobs:2,output:()=>{}});
  assert.equal(fresh.results[1].state,'failed');
});

test('不正な並列数と空の対象は成功にせず、前回の結果を使わない',async t=>{
  const f=await fixture(t,{});
  await mkdir(f.work);await writeFile(path.join(f.work,'js-results.json'),'前回の成功');
  await assert.rejects(runChecks({...f,jobs:3}),/1または2/);
  await assert.rejects(runChecks({...f,jobs:1}),/見つかりません/);
  await assert.rejects(access(path.join(f.work,'js-results.json')));
});

test('時間と失敗・未実行を残し、遅い試験を要約に載せる',async t=>{
  const f=await fixture(t,{'test_synthetic.mjs':"console.log('成功');"});
  await runChecks({...f,viewerReady:true,jobs:1,output:()=>{}});
  await writeFile(path.join(f.work,'timings.tsv'),'stage\tresult\tseconds\nflutter-test\tpassed\t42\nviewer-build\tfailed\t8\n');
  await summarize(f.work);
  const text=await readFile(path.join(f.work,'timings.md'),'utf8');
  assert.match(text,/flutter-test\|成功\|42/);assert.match(text,/viewer-build\|失敗\|8/);assert.match(text,/test_synthetic/);
});

test('コマンドとしての実行も失敗の終了コードを返す',async t=>{
  const f=await fixture(t,{'test_error.mjs':'process.exitCode=7;'});
  const result=spawnSync(process.execPath,[fileURLToPath(new URL('./run_js_checks.mjs',import.meta.url)),f.work,'true'],{
    cwd:f.directory,env:{...process.env,CHECK_JS_JOBS:'2'},encoding:'utf8',timeout:15000,
  });
  assert.ifError(result.error);assert.equal(result.status,1,result.stderr);assert.match(result.stdout,/FAIL\s+test_error/);
});
