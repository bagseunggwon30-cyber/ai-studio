/* Decode the actual recorded WebM with the already-installed Edge browser. */
const {chromium}=require(process.argv[2]);
const fs=require('node:fs');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {createHash}=require('node:crypto');
const {spawnSync}=require('node:child_process');
(async()=>{
  const name=path.resolve('output/playwright/workbench-current-flow.webm');
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const page=await browser.newPage({viewport:{width:1585,height:1080}});
  try{
    await page.goto(pathToFileURL(name).href);await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2);
    await page.evaluate(async()=>{const v=document.querySelector('video');v.muted=true;v.currentTime=3;await v.play();});
    await page.waitForTimeout(1400);
    const info=await page.evaluate(()=>{const v=document.querySelector('video');return{duration:v.duration,width:v.videoWidth,height:v.videoHeight,currentTime:v.currentTime,decodedFrames:v.webkitDecodedFrameCount,readyState:v.readyState,mediaError:v.error?.message||null};});
    if(info.currentTime<=4||info.decodedFrames<20||info.mediaError)throw new Error('Video did not decode and play');
    await page.evaluate(()=>document.querySelector('video').pause());
    await page.screenshot({path:'output/playwright/workbench-current-flow-video-frame.png'});
    const report={status:'pass',path:name,bytes:fs.statSync(name).size,sha256:createHash('sha256').update(fs.readFileSync(name)).digest('hex'),...info,real_model_calls:0};
    const p=spawnSync('python',['-X','utf8','-c','import sys,json;from pathlib import Path;from studio.util import atomic_write_json;atomic_write_json(Path(sys.argv[1]),json.load(sys.stdin))','docs/verification/workbench-current-flow-video.json'],{input:JSON.stringify(report),encoding:'utf8'});
    if(p.status)throw new Error(p.stderr);console.log(JSON.stringify(report));
  }finally{await page.close();await browser.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
