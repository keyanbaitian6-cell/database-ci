import fs from 'node:fs';
const root=new URL('./',import.meta.url);
const source=fs.readFileSync(new URL('daily_learning_projection.js',root),'utf8').trim();
for(const name of ['viewer_drive_script.gs','viewer_drive_script_readonly.gs']) {
  const path=new URL(name,root);
  let text=fs.readFileSync(path,'utf8').replace(/\r\n/g,'\n');
  text=text.replace(/\n\/\/ BEGIN DAILY_LEARNING[\s\S]*?\/\/ END DAILY_LEARNING\n?/,'\n');
  if(!text.includes("if (key === 'daily-learning')")) text=text.replace("  const key = (e && e.parameter && e.parameter.file) || '';",
    "  const key = (e && e.parameter && e.parameter.file) || '';\n  if (key === 'daily-learning') return readDailyLearning();");
  text+=`\n// BEGIN DAILY_LEARNING\n${source}\n// END DAILY_LEARNING\n`;
  fs.writeFileSync(path,text);
}
