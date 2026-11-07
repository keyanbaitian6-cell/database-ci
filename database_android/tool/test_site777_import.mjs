import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {validateData,mergeData} from '../web/pscube/data.mjs';
import {pscubeRecords} from '../../share_viewer/data.mjs';
import {netCaptureLabel} from '../web/capture_health.mjs';
import {buildCloudScript} from './build_pscube_cloud_sync.mjs';

const fixture=()=>JSON.parse(readFileSync(new URL('../test/fixtures/site777_backup.json',import.meta.url),'utf8'));
const plain=value=>JSON.parse(JSON.stringify(value));

test('サイトセブンの未知ART・MY・差枚・出典が往復で保持される',()=>{
  const parsed=validateData(fixture());
  assert.equal(parsed.records[0].at_art,null);
  assert.equal(parsed.records[1].at_art,0);
  assert.equal(parsed.records[0].my,900);
  assert.equal(parsed.records[0].net_medals,null);
  assert.deepEqual(validateData(plain(parsed)),parsed);
  assert.equal(parsed.records[0].source_captured_at,fixture().records[0].source_captured_at);
  const missing=fixture();missing.records[1].my=null;
  assert.equal(validateData(missing).records[1].my,null);
  assert.equal(pscubeRecords(validateData(missing))[1].output,null);
});

test('共有カレンダーも差枚を0にせず、MYと出典を表示用データへ保持する',()=>{
  const result=pscubeRecords(validateData(fixture()));
  assert.equal(result.length,2);
  assert.equal(result[0].output,900);
  assert.equal(result[0].net,null);
  assert.equal(result[0].source_site,'site777');
  assert.equal(netCaptureLabel(fixture().records[0]),'出典に差枚なし');
});

test('既存の台・日は、別名でもサイトセブンで上書きしない',()=>{
  const stored=fixture();
  stored.records=[stored.records[0]];
  stored.records[0].games=1234;
  const incoming=fixture();
  incoming.machines[0].machine='別表記';
  incoming.records.forEach(r=>r.machine='別表記');
  const merged=mergeData(stored,incoming);
  assert.equal(merged.records.length,2);
  assert.equal(merged.records.find(r=>r.rack===101).games,1234);
});

test('P’s CUBEの本来の記録はサイトセブンより優先し、再復元でも戻らない',()=>{
  const old=fixture(),fresh=fixture();
  fresh.machines[0].url='https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v05-011.php?cd_ps=2&bai=20';
  delete fresh.machines[0].source_site;
  fresh.records=[{...fresh.records[0],source_site:undefined,at_art:0,my:123,games:100,
    detail_url:'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=101#20261106'}];
  const merged=mergeData(old,fresh);
  assert.equal(merged.records.find(r=>r.rack===101).my,123);
  assert.equal(mergeData(merged,old).records.find(r=>r.rack===101).my,123);
});

test('別店舗・別日・架空の差枚・型違い・重複項目を拒否する',()=>{
  for(const patch of [{source_day_label:'11/5'},{rate:'5'},{net_medals:0},{my:'900'},
    {source_url:fixture().records[0].source_url+'&dtdd=2'},
    {source_url:fixture().records[0].source_url.replace('04034001','1234')},
    {source_captured_at:'2026-12-01T00:00:00+09:00'}]){
    const value=fixture();Object.assign(value.records[0],patch);
    assert.throws(()=>validateData(value));
  }
});

test('読み取れない曲線は明示的な理由つきの不明を保持する',()=>{
  const value=fixture();
  value.records[0].graph=null;
  value.records[0].source_graph.error='curve_unknown';
  assert.equal(validateData(value).records[0].graph,null);
  delete value.records[0].source_graph.error;
  assert.throws(()=>validateData(value));
});

test('生成するGoogle同期スクリプトとブラウザの検証結果が同じになる',()=>{
  const context=vm.createContext({});
  vm.runInContext(buildCloudScript(),context,{timeout:5000});
  const result=context.validateData(fixture());
  assert.deepEqual(plain(result),plain(validateData(fixture())));
  const invalid=fixture();invalid.records[0].source_url+='&mdc=999';
  assert.throws(()=>context.validateData(invalid));
});

// グラフ画像の目盛りから読んだ推定差枚（PC site777_net.py、2026-11-07）。
const estimate=(value,sure=true)=>({value,sure,method:'site777-axis-pixels-v1'});

test('サイトセブンの推定差枚を保持し、共有カレンダーでは推定（確かでなければ※）として数える',()=>{
  const value=fixture();
  value.records[0].net_estimate=estimate(-700);
  value.records[1].net_estimate=estimate(50,false);
  const parsed=validateData(value);
  assert.deepEqual(parsed.records[0].net_estimate,estimate(-700));
  assert.equal(parsed.records[0].net_medals,null);
  assert.deepEqual(validateData(plain(parsed)),parsed);
  const shown=pscubeRecords(parsed);
  assert.deepEqual([shown[0].net,shown[0].needsCheck,shown[0].estimated],[-700,false,true]);
  assert.deepEqual([shown[1].net,shown[1].needsCheck],[50,true]);
  assert.equal(shown[0].output,900,'MYはMYのまま');
  assert.equal(netCaptureLabel(parsed.records[0]),'出典に差枚なし（推定あり）');
  assert.equal(pscubeRecords(validateData(fixture()))[0].net,null,'推定の無い台は差枚なしのまま（MYを入れない）');
});

test('方式・出典の合わない推定差枚や50枚単位でない値は拒否する',()=>{
  for(const bad of [{...estimate(-700),method:'anaslo-graph-v1'},estimate(-703),{value:-700,sure:true}]){
    const value=fixture();value.records[0].net_estimate=bad;
    assert.throws(()=>validateData(value),/推定差枚|サイトセブン/);
  }
  const anaslo={source_site:'anaslo',net_medals:null,net_estimate:estimate(-700)};
  assert.equal(pscubeRecords({format:'pscube-viewer',records:[{...fixture().records[0],...anaslo}]})[0].net,null);
});

test('同じ表・同じ画像から後で付けた推定差枚だけを保存済みの台へ移す',()=>{
  const later=fixture();
  later.records[0].net_estimate=estimate(-700);
  later.records[1].net_estimate=estimate(300);
  later.records[1].source_graph={...later.records[1].source_graph,image_sha256:'f'.repeat(64)};
  const merged=mergeData(validateData(fixture()),validateData(later));
  assert.deepEqual(merged.records.find(r=>r.rack===later.records[0].rack).net_estimate,estimate(-700));
  assert.equal('net_estimate' in merged.records.find(r=>r.rack===later.records[1].rack),false);
});

test('生成するGoogle同期スクリプトも推定差枚を落とさない',()=>{
  const context=vm.createContext({});
  vm.runInContext(buildCloudScript(),context,{timeout:5000});
  const value=fixture();value.records[0].net_estimate=estimate(-700);
  assert.deepEqual(plain(context.validateData(value)),plain(validateData(value)));
  assert.deepEqual(plain(context.validateData(value)).records[0].net_estimate,estimate(-700));
});
