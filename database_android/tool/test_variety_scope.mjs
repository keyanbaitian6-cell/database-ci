import test from 'node:test';
import assert from 'node:assert/strict';
import {indexRecords, meruhenRecords, idleVarietyRacks, varietyRainbowRows, varietyMaxRacksFor} from '../../share_viewer/data.mjs';

function sample(store) {
  const records=[];
  for(let d=1;d<=8;d++)for(let n=1;n<=4;n++)for(let i=0;i<n;i++)
    records.push({store,day:`2026-10-0${d}`,machine:`${n}台機種`,rack:10*n+i,games:300,bb:1,rb:1});
  return indexRecords(meruhenRecords({records}));
}
test('共有の通常バラエティは幸町1〜2台、長町南1〜3台。3台機種の記録は残る',()=>{
  for(const store of ['saiwaichou','nagamachiminami']) {
    const byDay=sample(store),saiwaichou=store==='saiwaichou';
    assert.equal(varietyMaxRacksFor(store),saiwaichou?2:3);
    assert.equal(byDay.get(`${store}|2026-10-08`).length,10);
    assert.deepEqual(idleVarietyRacks(byDay,store,'2026-10-08').map(x=>x.latest.rack),
      saiwaichou?[10,20,21]:[10,20,21,30,31,32]);
    assert.deepEqual(varietyRainbowRows(byDay,store,'2026-10-08').map(x=>x.rack),
      saiwaichou?[10]:[10,20,21,30,31,32], '幸町の🌈一覧は引き続き1台機種だけ');
  }
});
