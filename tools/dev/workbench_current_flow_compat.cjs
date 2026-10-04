/* Re-run unchanged established visual/interaction checks on the new effects. */
const { chromium }=require(process.argv[2]);
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
(async()=>{
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const context=await browser.newContext({viewport:{width:1585,height:1080}}),page=await context.newPage();
  try {
    await page.goto('http://127.0.0.1:8798/');await page.waitForFunction(()=>Data.loaded);
    if(!await page.evaluate(()=>Data.get().studio.fake===true))throw new Error('Existing fake runtime only');
    await page.evaluate(async()=>{
      const c=await Data.workbenchGet(),f=c.flows.find(f=>f.title==='웹페이지 개선'),l=await Data.workbenchGet('/ledger');
      localStorage.setItem('studio.workbench.draft.v1',JSON.stringify({draft:f,selected:'visual-review',unsaved:false}));
      localStorage.setItem('studio.workbench.surface.v1','workspace');localStorage.setItem('studio.workbench.lastRun',l.runs[0].id);
    });
    await page.reload();await page.waitForFunction(()=>Data.loaded);
    if(await page.locator('#workbench-screen').isHidden())await page.locator('.bd-nav').getByRole('button',{name:'기능 작업대',exact:true}).click();
    await page.locator('.wb-run-history > summary').click();await page.locator('.wb-run').first().click();
    if(await page.locator('.wb-run-history').evaluate(n=>n.open))await page.locator('.wb-run-history > summary').click();
    await page.waitForFunction(()=>document.querySelector('[data-node="visual-review"]')?.dataset.flow==='missing');
    const screenshot=page.screenshot.bind(page);
    page.screenshot=options=>screenshot({...options,path:path.join('output/playwright','workbench-current-flow-compat-'+path.basename(options.path))});
    const reports=[];
    for(const name of ['workbench_visual_polish.js','workbench_visual_interactions.js'])reports.push({source:name,...await vm.runInNewContext('('+fs.readFileSync(path.join('tools/dev',name),'utf8')+')',{URL})(page)});
    const result={status:'pass',count:reports.reduce((n,r)=>n+r.count,0),reports,real_model_calls:0,production_writes:0};
    const p=spawnSync('python',['-X','utf8','-c','import sys,json;from pathlib import Path;from studio.util import atomic_write_json;atomic_write_json(Path(sys.argv[1]),json.load(sys.stdin))','docs/verification/workbench-current-flow-compat.json'],{input:JSON.stringify(result),encoding:'utf8'});
    if(p.status)throw new Error(p.stderr);console.log(JSON.stringify({status:result.status,count:result.count}));
  } finally {await context.close();await browser.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
