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
