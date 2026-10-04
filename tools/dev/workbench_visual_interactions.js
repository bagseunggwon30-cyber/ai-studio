async (page) => {
  const checks = [], errors = [];
  const assert = (ok, name) => { if (!ok) throw new Error(name); checks.push(name); };
  page.on('pageerror', e => errors.push(e.message));
  assert(new URL(page.url()).host === '127.0.0.1:8798', '격리 미리보기만 검사');
  assert(await page.evaluate(() => Data.get().studio.fake === true), '기존 FakeRuntime 사용');
  const root = page.locator('#workbench-screen');
  await page.getByRole('button',{name:'기능 꺼내기 ＋',exact:true}).click();
  assert(await page.locator('.wb-drawer').isVisible(), '큰 폴더의 기능 꺼내기 동작');
  await page.keyboard.press('Escape');
  assert(await page.locator('.wb-drawer').isHidden(), 'Escape로 도구함 접기');
  assert(await page.locator('[data-toolbox]').evaluate(e=>document.activeElement===e), '도구함 접은 뒤 초점 복귀');
  await page.locator('[data-node="visual-review"]').focus(); await page.keyboard.press('Enter');
  assert(await page.locator('.wb-detail').isVisible(), '키보드 Enter로 근거 펼침');
  await page.getByRole('button',{name:'상세 접기',exact:true}).focus(); await page.keyboard.press('Escape');
  assert(await page.locator('.wb-detail').isHidden(), 'Escape로 근거 접기');
  assert(await page.locator('[data-node="visual-review"]').evaluate(e=>document.activeElement===e), '근거 접은 뒤 노드 초점 복귀');
  await page.keyboard.press('Enter');
  await page.locator('.wb-advanced > summary').click();
  assert(await page.locator('.wb-advanced').evaluate(e=>e.open), '고급 입력·출력은 요청할 때 펼침');
  await page.locator('.wb-advanced > summary').click();
  assert(!await page.locator('.wb-advanced').evaluate(e=>e.open), '고급 상세 다시 접기');
  const overlap = await page.locator('.wb-canvas').evaluate(canvas=>{
    const p=canvas.querySelector('.wb-detail').getBoundingClientRect();
    return [...canvas.querySelectorAll('[data-node]')].some(e=>{const n=e.getBoundingClientRect();return n.left<p.right&&n.right>p.left&&n.top<p.bottom&&n.bottom>p.top;});
  });
  assert(!overlap,'근거 패널이 다른 노드를 가리지 않음');
  await page.locator('.wb-header').getByRole('button',{name:'진행판',exact:true}).click();
  await page.locator('.bd-nav').getByRole('button',{name:'기능 작업대',exact:true}).click();
  assert(await page.locator('.wb-proof-items > li').count()===3,'닫기·재열기에서 실행 근거 유지');
  for (const [width,height] of [[1024,900],[390,844]]) {
    await page.setViewportSize({width,height});
    await page.locator('[data-node="visual-review"]').click();
    const size=await root.evaluate(e=>({width:e.clientWidth,scroll:e.scrollWidth}));
    assert(size.scroll<=size.width+1,`${width}px 화면 바깥 가로 넘침 없음`);
    assert(await page.getByRole('button',{name:'기존 결재 창에서 승인',exact:true}).isDisabled(),`${width}px 누락 후보 승인 잠금 유지`);
  }
  await page.emulateMedia({reducedMotion:'reduce'});
  assert(await page.locator('.wb-detail').evaluate(e=>getComputedStyle(e).animationName==='none'),'reduced-motion 적용');
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.setViewportSize({width:1585,height:1080});
  const rejected=await page.evaluate(async()=>{
    const ledger=await Data.workbenchGet('/ledger'); const run=await Data.workbenchGet('/runs/'+ledger.runs[0].id);
    const graph={nodes:run.snapshot.graph.nodes.map(({definition,...n})=>n),edges:[...run.snapshot.graph.edges,{from:'visual-approve',to:'visual-input'}]};
    try {await Data.workbenchPost('validate',{graph});return false;} catch(e) {return Boolean(e.message);}
  });
  assert(rejected,'순환 연결은 기존 검증이 거부');
  let aborted=false;
  await page.route('**/api/workbench/runs/*',async route=>{
    if (!aborted&&route.request().method()==='GET'){aborted=true;return route.abort();}return route.continue();
  });
  await page.evaluate(()=>Workbench.refresh());
  assert(aborted,'실행 조회의 일시적 연결 실패 검증');
  await page.unroute('**/api/workbench/runs/*');
  await page.evaluate(()=>Workbench.refresh());
  assert(await page.locator('.wb-proof-items > li').count()===3,'조회 실패 뒤 같은 근거 기록 복구');
  const runs=await page.evaluate(()=>Data.workbenchGet('/ledger'));
  assert(runs.runs.length===1,'실패 복구가 작업을 재제출하지 않음');
  await page.locator('[data-node="visual-review"]').click();
  if (await page.locator('.wb-run-history').evaluate(e=>e.open)) await page.locator('.wb-run-history > summary').click();
  await page.evaluate(()=>{document.querySelector('#workbench-screen').scrollTop=0;document.querySelector('.wb-graph-scroll').scrollLeft=0;});
  await page.screenshot({path:'output/playwright/workbench-visual-interactions.png',fullPage:true,animations:'disabled'});
  assert(errors.length===0,'브라우저 런타임 오류 없음');
  return {status:'pass',count:checks.length,checks,errors,real_model_calls:0,production_writes:0};
}
