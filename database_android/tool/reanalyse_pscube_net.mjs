// 取得済みの元数値を再解析する。元ファイルを上書きせず、サイトへ通信しない。
import {readFile,mkdtemp,open,link,rm} from 'node:fs/promises';
import {resolve,dirname,join} from 'node:path';
import {reanalyseNetCaptures} from '../web/pscube/graph_probe.mjs';
import {buildBackup} from '../web/pscube/sync.mjs';

async function main() {
  const [input,output]=process.argv.slice(2);
  if (!input || !output || resolve(input)===resolve(output)) throw new Error('入力と異なる新しい出力ファイルを指定してください。');
  const raw=JSON.parse((await readFile(input,'utf8')).replace(/^\uFEFF/,''));
  const result=reanalyseNetCaptures(raw);
  if (result.filled) {
    // 同じフォルダの一時ファイルを完成させた後だけ公開し、既存の出力も上書きしない。
    const temp=await mkdtemp(join(dirname(resolve(output)),'.pscube-reanalyse-'));
    try {
      const staged=join(temp,'backup.json'),file=await open(staged,'wx');
      try {await file.writeFile(JSON.stringify(buildBackup(result.data)));await file.sync();}
      finally {await file.close();}
      await link(staged,resolve(output));
    } finally {await rm(temp,{recursive:true,force:true});}
  }
  console.log(JSON.stringify({補完件数:result.filled,未取得件数:result.missing,書き出し:result.filled ? output : '補完できる元数値なし'},null,2));
}
main().catch(error=>{
  console.error(error.code==='EEXIST' ? '出力先は既に存在します。別の新しいファイル名を指定してください。' :
    error.code ? 'ファイルの読み書きに失敗しました。元ファイルは変更していません。' : `再解析できませんでした：${error.message}`);
  process.exitCode=1;
});
