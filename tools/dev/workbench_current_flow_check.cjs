/* Browser checks against an isolated TempStudio and its existing FakeRuntime.
 * Supply the already-installed Playwright module and the fixture root as argv.
 * API failure probes below are browser-local read responses, never store writes.
 */
const { chromium } = require(process.argv[2]);
const fs = require('node:fs/promises');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const output = path.resolve('output/playwright');
const fixture = path.resolve(process.argv[3]);
if (!fixture.startsWith(path.join(process.env.TEMP, 'studio-test-'))) throw new Error('Temporary fixture root required');
const atomic = (name, value) => {
  const p = spawnSync('python', ['-X', 'utf8', '-c', 'import json,sys;from pathlib import Path;from studio.util import atomic_write_json;atomic_write_json(Path(sys.argv[1]),json.load(sys.stdin))', name], {input:JSON.stringify(value),encoding:'utf8'});
  if (p.status) throw new Error(p.stderr);
};
const release = stage => {
  const p = spawnSync('python', ['-c', 'import sys;from pathlib import Path;from studio.util import atomic_write_text;atomic_write_text(Path(sys.argv[1]),"release")', path.join(fixture, 'flow-release-' + stage)], {encoding:'utf8'});
  if (p.status) throw new Error(p.stderr);
};
(async () => {
  const checks = [], errors = [], writes = [], observations = [];
  const assert = (value, name) => { if (!value) throw new Error(name); checks.push(name); };
  const browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const context = await browser.newContext({viewport:{width:1585,height:1080}});
  const page = await context.newPage();
  const watch = p => { p.on('pageerror', e=>errors.push(e.message)); p.on('request', r=>{if(r.method()==='POST')writes.push(new URL(r.url()).pathname);}); };
  watch(page);
  const node = (p,id) => p.locator('.wb-node[data-node="visual-'+id+'"]');
  const current = p => p.evaluate(async()=>{const l=await Data.workbenchGet('/ledger');return Data.workbenchGet('/runs/'+l.runs[0].id);});
  const settleActive = async p => { await node(p,'implement').waitFor(); await p.waitForFunction(()=>document.querySelector('[data-node="visual-implement"]').dataset.flow==='active'); };
  let recording;
  try {
    await fs.mkdir(output,{recursive:true});
    const response = await page.goto('http://127.0.0.1:8798/');
    await page.waitForFunction(()=>typeof Data!=='undefined'&&Data.loaded);
    assert(response.status()===200 && response.headers()['content-security-policy'].includes("script-src 'self'"),'격리 미리보기와 원래 CSP');
    assert(await page.evaluate(()=>Data.get().studio.fake===true),'기존 FakeRuntime 회사 확인');
    const saved = await page.evaluate(async()=>{
      const c=await Data.workbenchGet(),titles=['자료 읽기','코드 수정','테스트','검토·근거 확인','승인'],ops=['input','implement','test','review','approve'];
      const positions=[{x:410,y:44},{x:685,y:60},{x:960,y:60},{x:1000,y:345},{x:1265,y:370}],nodes=[];
      for(let i=0;i<ops.length;i++){
        const d=c.nodes.find(n=>n.spec.operation===ops[i]);
        const n=(await Data.workbenchPost('nodes',{title:titles[i],folder:'personal',note:d.note,spec:d.spec})).node;
        nodes.push({id:'visual-'+ops[i],ref:{id:n.id,version:n.version},params:JSON.parse(JSON.stringify(n.spec.params)),position:positions[i]});
      }
      nodes[0].params.text='정답 42를 docs/answer.txt에 저장해 주세요. 격리 UI 검증용입니다.';
      nodes[1].params.acceptance=['테스트 기록','수정 결과 기록','결과 파일'];
      nodes[1].params.evidence=[[{type:'test',name:'answer_is_42'}],[{type:'file',path:'docs/revision.txt'}],[{type:'file',path:'docs/contract.txt'}]];
      const f=(await Data.workbenchPost('flows',{title:'웹페이지 개선',folder:'personal',project:'demo',allowed_paths:['docs/**'],graph:{nodes,edges:nodes.slice(1).map((n,i)=>({from:nodes[i].id,to:n.id}))}})).flow;
      localStorage.setItem('studio.workbench.draft.v1',JSON.stringify({draft:f,selected:nodes[0].id,unsaved:false}));
      localStorage.setItem('studio.workbench.surface.v1','workspace'); return f;
    });
    await page.reload(); await page.waitForFunction(()=>Data.loaded);
    if(await page.locator('#workbench-screen').isHidden())await page.locator('.bd-nav').getByRole('button',{name:'기능 작업대',exact:true}).click();
    await node(page,'approve').waitFor();
    assert(await page.locator('.wb-node').count()===5,'기존 다섯 종이 노드와 저장 복원');
    assert(await page.locator('.wb-flow-current').count()===4,'원래 네 연결의 SVG 장식만 추가');
    const geometry=await page.locator('.wb-node').evaluateAll(ns=>ns.map(n=>({id:n.dataset.node,x:n.style.getPropertyValue('--node-x'),y:n.style.getPropertyValue('--node-y')})));
    await page.getByRole('button',{name:'실행 계획 확인',exact:true}).click();
    const plan=page.getByRole('dialog',{name:'실행 전 계획 확인',exact:true});
    assert(await plan.getByRole('button',{name:'확인한 계획 실행'}).isDisabled(),'계획·모델 동의 전 잠금');
    await plan.getByRole('checkbox').nth(0).check();await plan.getByRole('checkbox').nth(1).check();
    await plan.getByRole('button',{name:'확인한 계획 실행'}).dblclick();
    await settleActive(page);
    const building=await current(page), task=Object.values(building.current_tasks)[0];
    const summary=await page.evaluate(id=>Data.task(id),task.task);
    assert(task.status==='running'&&summary.progress.steps.some(s=>s.status==='running'&&s.stage.startsWith('build')&&s.run_id),'실제 엔진 일지의 실행 단계·번호');
    assert(await page.locator('.wb-edge[data-flow="active"]').count()===1,'실제로 실행 중인 구현 노드의 입력선 하나만 흐름');
    assert(await node(page,'test').getAttribute('data-flow')==='idle'&&await node(page,'review').getAttribute('data-flow')==='idle','향후 검증·근거 노드는 전류 없음');
    assert((await node(page,'implement').textContent()).includes('실행 중 · 구현'),'단계명을 글자로 함께 표시');
    const edge=await page.locator('.wb-edge[data-flow="active"]').elementHandle();
    const spark=page.locator('.wb-edge[data-flow="active"] .wb-flow-current');
    const first=await spark.evaluate(n=>({offset:getComputedStyle(n).strokeDashoffset,time:n.getAnimations()[0].currentTime}));
    await page.waitForTimeout(320);
    assert(await spark.evaluate((n,v)=>getComputedStyle(n).strokeDashoffset!==v.offset,first),'진행 방향으로 실제 CSS 전류 이동');
    await page.waitForTimeout(1900);
    assert(await edge.evaluate(n=>n.isConnected),'동일 실행 조회가 SVG 연결을 재생성하지 않음');
    assert(await spark.evaluate((n,v)=>n.getAnimations()[0].currentTime>v.time+1000,first),'동일 조회에서 애니메이션 위상 유지');
    await page.screenshot({path:path.join(output,'workbench-current-flow-active.png'),fullPage:true});
    await page.emulateMedia({reducedMotion:'reduce'});
    assert(await spark.evaluate(n=>getComputedStyle(n).display==='none'),'동작 감소에서 이동 전류 숨김');
    assert(await node(page,'implement').evaluate(n=>getComputedStyle(n).animationName==='none'),'동작 감소에서 정적 실행 표시');
    assert((await node(page,'implement').getAttribute('aria-label')).includes('실행 중'),'동작 감소·보조 기술에서 실행 텍스트 유지');
    await page.screenshot({path:path.join(output,'workbench-current-flow-reduced.png'),fullPage:true});
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.evaluate(()=>Fx.setMotion(false));
    assert(await spark.evaluate(n=>getComputedStyle(n).display==='none'),'기존 효과 끄기 설정도 전류 숨김');
    assert(await page.locator('[data-transfer],.wb-complete-pulse').count()===0,'효과 끄기에서 남은 완료 효과 제거');
    await page.evaluate(()=>Fx.setMotion(true));
    let broken=true;
    await page.route('**/api/workbench/runs/**',r=>broken?r.abort():r.continue());
    await page.waitForFunction(()=>document.querySelector('#workbench-screen').dataset.flowOnline==='false');
    assert(await page.locator('.wb-flow-current').evaluateAll(ns=>ns.every(n=>getComputedStyle(n).animationName==='none')),'단일 실행 기록 조회 실패 즉시 전류 중단');
    broken=false;await settleActive(page);await page.unroute('**/api/workbench/runs/**');
    assert((await current(page)).id===building.id,'연결 복구가 같은 실행을 복원');
    assert(await page.locator('[data-transfer],.wb-complete-pulse').count()===0,'복구 뒤 지나간 완료 효과 재생 없음');
    await page.getByRole('button',{name:'진행판',exact:true}).click();
    assert(await page.locator('#workbench-screen').getAttribute('data-flow-online')==='false','화면 닫기에서 전류 정지');
    await page.locator('.bd-nav').getByRole('button',{name:'기능 작업대',exact:true}).click();await settleActive(page);
    assert(await page.locator('[data-transfer],.wb-complete-pulse').count()===0,'재열기에서 기록 재생 없음');
    const reopenedEdge=await page.locator('.wb-edge[data-flow="active"]').elementHandle();
    await node(page,'implement').focus();await page.keyboard.press('Enter');
    assert(await page.locator('.wb-detail').isVisible(),'키보드 노드 상세 열기');
    await page.getByRole('button',{name:'상세 접기',exact:true}).click();
    assert(await page.locator('.wb-detail').isHidden(),'실행 중 상세 접기');
    assert(await reopenedEdge.evaluate(n=>n.isConnected),'상세 열고 닫기에서 기존 연결 보존');
    for(const width of [1024,390]){
      await page.setViewportSize({width,height:900});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${width}px 바깥 넘침 없음`);
      assert(await page.locator('.wb-graph-scroll').evaluate(n=>n.scrollWidth>n.clientWidth),`${width}px 원래 작업면 내부 스크롤`);
    }
    await page.setViewportSize({width:1585,height:1080});
    // A separate recording shows only actual existing Engine/FakeRuntime transitions.
    recording=await browser.newContext({viewport:{width:1585,height:1080},storageState:await context.storageState(),recordVideo:{dir:output,size:{width:1585,height:1080}}});
    const film=await recording.newPage();watch(film);
    await film.goto('http://127.0.0.1:8798/');await film.waitForFunction(()=>Data.loaded);
    if(await film.locator('#workbench-screen').isHidden())await film.locator('.bd-nav').getByRole('button',{name:'기능 작업대',exact:true}).click();
    await film.locator('.wb-run-history > summary').click();await film.locator('.wb-run').first().click();
    if(await film.locator('.wb-run-history').evaluate(n=>n.open))await film.locator('.wb-run-history > summary').click();
    await settleActive(film);await film.waitForTimeout(2800);
    release('build');
    await film.waitForFunction(()=>document.querySelector('[data-node="visual-implement"]')?.textContent.includes('실행 중 · 읽기 전용 검토'));
    const reviewing=await current(film),reviewTask=Object.values(reviewing.current_tasks)[0];
    assert(reviewTask.qa.verdict==='pass'&&reviewTask.qa.candidate_sha===reviewTask.candidate_sha,'실제 후보와 QA 통과 기록 일치');
    assert(await node(film,'implement').getAttribute('data-flow')==='active'&&await node(film,'test').getAttribute('data-flow')==='idle','실제 리뷰 실행은 구현 카드에서만 표시');
    await film.screenshot({path:path.join(output,'workbench-current-flow-review.png'),fullPage:true});
    await film.waitForTimeout(2000);release('review');
    await film.waitForFunction(()=>document.querySelector('[data-node="visual-review"]')?.dataset.flow==='missing');
    const finished=await current(film),finishedTask=Object.values(finished.current_tasks)[0];
    assert(finished.status==='blocked'&&finishedTask.status==='awaiting_approval','근거 누락에서 기존 엔진이 결재를 차단');
    assert(finishedTask.evidence.items.filter(i=>i.status==='verified').length===2&&finishedTask.evidence.items.filter(i=>i.status==='missing').length===1,'실제 테스트 통과와 완료 근거 2/3 구분');
    assert(await film.locator('.wb-edge[data-flow="active"]').count()===0,'끝난 실제 실행의 지속 전류 없음');
    await node(film,'review').click();await film.locator('.wb-proof-items>li').nth(2).waitFor();
    assert(await film.getByRole('button',{name:'기존 결재 창에서 승인',exact:true}).isDisabled(),'승인 근거 누락 잠금 유지');
    await film.waitForTimeout(1400);await film.screenshot({path:path.join(output,'workbench-current-flow-missing.png'),fullPage:true});
    const video=film.video();await recording.close();recording=null;
    await video.saveAs(path.join(output,'workbench-current-flow.webm'));
    observations.push({run:building.id,task:task.task,flow:saved.id,real_builder:summary.progress.steps.filter(s=>s.status==='running'),review_candidate:reviewTask.candidate_sha,qa:finishedTask.qa.verdict,evidence:finishedTask.evidence.items.map(i=>i.status),geometry});
    // Exercise failure/cancellation/revision rendering through local GET responses.
    let probe='failed',probeVersion=0;
    await page.route('**/api/state',async r=>{
      const res=await r.fetch(),s=await res.json();s.version=`flow-probe-${probe}-${++probeVersion}`;
      const t=s.tasks.find(t=>t.id===task.task);t.status=probe==='cancelled'?'cancelled':'blocked';
      t.progress={steps:[],last:{status:probe==='uncertain'?'unknown_outcome':probe==='paused'?'interrupted':'failed'}};s.status.current=null;
      await r.fulfill({response:res,json:s});
    });
    await page.route('**/api/workbench/runs/**',async r=>{
      const v=JSON.parse(JSON.stringify(finished));v.status=probe==='cancelled'?'cancelled':'blocked';
      const t=v.current_tasks[task.task];t.status=probe==='cancelled'?'cancelled':'blocked';t.evidence=null;
      v.nodes['visual-implement'].status=probe==='cancelled'?'cancelled':'blocked';
      await r.fulfill({json:v});
    });
    for(const mode of ['failed','uncertain','paused','cancelled']){
      probe=mode;await page.evaluate(()=>Data.refresh());
      await page.waitForFunction(m=>document.querySelector('[data-node="visual-implement"]')?.dataset.flow===m,mode);
      assert(await page.locator('.wb-edge[data-flow="active"]').count()===0,`${mode} 기록에서 전류 없음`);
      assert(await node(page,'implement').evaluate(n=>getComputedStyle(n).animationName==='none'),`${mode} 기록에서 실행 광택 없음`);
      assert(!(await page.locator('.wb-flow-announcement').textContent()).includes('실행 중'),`${mode} 알림에서 이전 실행 중 문구 제거`);
      if(mode==='failed')await page.screenshot({path:path.join(output,'workbench-current-flow-failure.png'),fullPage:true});
    }
    await page.unroute('**/api/state');await page.unroute('**/api/workbench/runs/**');await page.evaluate(()=>Data.refresh());
    await page.waitForFunction(()=>document.querySelector('[data-node="visual-review"]')?.dataset.flow==='missing');
    assert(await page.locator('[data-transfer],.wb-complete-pulse').count()===0,'실패 probe 원복 시 이전 완료 재생 없음');
    assert(JSON.stringify(await page.locator('.wb-node').evaluateAll(ns=>ns.map(n=>({id:n.dataset.node,x:n.style.getPropertyValue('--node-x'),y:n.style.getPropertyValue('--node-y')}))))===JSON.stringify(geometry),'효과·상태 변화가 원래 노드 배치를 보존');
    assert(writes.filter(p=>p==='/api/workbench/start').length===1,'중복 클릭·복구·영상에서 실행 제출 한 번');
    assert(!writes.some(p=>/cancel|approve|revision|stop/.test(p)),'검증 중 결재·취소·수정 요청 없음');
    assert(errors.length===0,'브라우저 pageerror 없음');
    atomic('docs/verification/workbench-current-flow-browser.json',{status:'pass',count:checks.length,checks,errors,writes,observations,screenshots:['active','reduced','review','missing','failure'].map(n=>'output/playwright/workbench-current-flow-'+n+'.png'),video:'output/playwright/workbench-current-flow.webm',real_model_calls:0,production_writes:0});
    console.log(JSON.stringify({status:'pass',count:checks.length,errors,run:building.id,real_model_calls:0}));
  } catch(e) {
    await page.screenshot({path:path.join(output,'workbench-current-flow-debug.png'),fullPage:true}).catch(()=>{});
    atomic('output/workbench-current-flow-browser-failure.json',{error:e.message,checks,errors,writes});throw e;
  } finally { if(recording)await recording.close();await context.close();await browser.close(); }
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
