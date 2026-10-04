async (page) => {
  const checks=[], errors=[], geometry=[];
  const assert=(ok,name)=>{if(!ok)throw new Error(name);checks.push(name);};
  page.on('pageerror',e=>errors.push(e.message));
  assert(new URL(page.url()).host==='127.0.0.1:8798','격리 미리보기만 검사');
  const run=await page.evaluate(async()=>{const rows=await Data.workbenchGet('/ledger');return Data.workbenchGet('/runs/'+rows.runs[0].id);});
  const task=Object.values(run.current_tasks)[0];
  assert(run.nodes['visual-test'].status==='blocked'&&run.nodes['visual-review'].status==='skipped','기존 엔진 상태 보존');
  assert(task.qa.verdict==='pass'&&task.evidence.suite_current===true&&!task.evidence.complete&&!task.approval.allowed,'테스트 통과와 누락 승인 차단의 실제 근거');
  const select=()=>page.locator('[data-node="visual-review"]').click();
  await select();
  assert((await page.locator('[data-node="visual-test"]').innerText()).includes('테스트 통과 · 승인 근거 누락'),'테스트 통과와 승인 근거 누락을 구별');
  assert((await page.locator('[data-node="visual-approve"]').innerText()).includes('근거 누락 · 승인 차단'),'승인 차단 이유를 카드에서 읽음');
  assert((await page.locator('[data-node="visual-review"] .wb-node-description').innerText()).endsWith('있습니다.'),'검토 문장의 의미를 끝까지 표시');
  assert((await page.locator('[data-node="visual-approve"] .wb-node-description').innerText()).endsWith('있습니다.'),'승인 문장의 의미를 끝까지 표시');
  assert(!(await page.locator('.wb-main').innerText()).includes(task.candidate_sha.slice(0,10))&&!(await page.locator('.wb-main').innerText()).includes('docs/'),'후보 해시와 파일 경로는 접힌 상세에 보관');
  assert(await page.locator('[data-proof-link]').count()===3,'선택 노드에서 실제 근거 세 장으로 연결');
  assert(await page.locator('.wb-wire').evaluateAll(rows=>rows.every(e=>getComputedStyle(e).strokeDasharray==='none'&&parseFloat(getComputedStyle(e).strokeWidth)>=1.8)),'방향이 읽히는 실선과 화살표');
  const shape=()=>page.locator('.wb-canvas').evaluate(canvas=>{
    const pane=canvas.querySelector('.wb-detail'),close=pane.querySelector('.wb-detail-close'),badge=pane.querySelector('.wb-proof-badge');
    const nodes=[...canvas.querySelectorAll('[data-node]')].map(e=>e.getBoundingClientRect());
    const overlaps=r=>nodes.some(n=>r.left<n.right&&r.right>n.left&&r.top<n.bottom&&r.bottom>n.top);
    const p=pane.getBoundingClientRect(),c=canvas.getBoundingClientRect(),hint=pane.querySelector('#wb-proof-reason').getBoundingClientRect(),ledger=document.querySelector('.wb-run-history').getBoundingClientRect();
    return {closeOverlaps:overlaps(close.getBoundingClientRect()),badgeOverlaps:overlaps(badge.getBoundingClientRect()),paneBottom:p.bottom,canvasBottom:c.bottom,hintBottom:hint.bottom,ledgerTop:ledger.top,
      outerWidth:document.querySelector('#workbench-screen').clientWidth,outerScroll:document.querySelector('#workbench-screen').scrollWidth,
      canvasWidth:canvas.offsetWidth,graphWidth:canvas.parentElement.clientWidth,graphScroll:canvas.parentElement.scrollWidth};
  });
  for(const [width,height] of [[1585,1080],[1280,900],[390,844]]){
    await page.setViewportSize({width,height});await select();
    let g=await shape();geometry.push({width,height,...g});
    assert(!g.closeOverlaps&&!g.badgeOverlaps,`${width}px 접기/상태가 노드 경계에 걸치지 않음`);
    assert(g.paneBottom+15<=g.canvasBottom&&g.hintBottom+15<=g.canvasBottom&&g.ledgerTop>=g.paneBottom+15,`${width}px 안내와 상세가 장부 구분선에서 잘리지 않음`);
    assert(g.outerScroll<=g.outerWidth+1,`${width}px 화면 바깥 가로 넘침 없음`);
    if(width<1585){
      assert(g.graphScroll>g.graphWidth,`${width}px 작업면 내부 가로 스크롤 유지`);
      await page.locator('.wb-graph-scroll').evaluate(e=>{e.scrollLeft=e.scrollWidth;});
      const accessible=await page.locator('[data-node="visual-approve"]').evaluate(node=>{const n=node.getBoundingClientRect(),g=node.closest('.wb-graph-scroll').getBoundingClientRect();return n.right<=g.right+1&&n.left>=g.left;});
      assert(accessible,`${width}px 가로 스크롤로 마지막 승인 카드 접근`);
      await select();
    }
  }
  await page.setViewportSize({width:1585,height:1080});await select();
  await page.locator('.wb-proof-references').first().getByText('근거 상세',{exact:true}).click();
  assert((await page.locator('.wb-proof-references').first().innerText()).includes('answer_is_42'),'근거 상세에서 실제 검사 이름 조회');
  await page.locator('.wb-proof-references').first().getByText('근거 상세',{exact:true}).click();
  await page.locator('.wb-advanced > summary').click();
  const expanded=await shape();
  assert(expanded.paneBottom+15<=expanded.canvasBottom&&expanded.ledgerTop>=expanded.paneBottom+15,'고급 기록을 펼쳐도 내용 높이에 맞게 장부가 내려감');
  await page.locator('.wb-advanced > summary').click();
  await page.getByRole('button',{name:'상세 접기',exact:true}).focus();await page.keyboard.press('Escape');
  assert(await page.locator('.wb-detail').isHidden(),'키보드 Escape로 근거 접기');
  await page.keyboard.press('Enter');
  assert(await page.locator('.wb-detail').isVisible(),'노드 초점 복귀 뒤 Enter로 재열기');
  await page.emulateMedia({reducedMotion:'reduce'});
  assert(await page.locator('.wb-detail').evaluate(e=>getComputedStyle(e).animationName==='none'),'reduced-motion에서 펼침 애니메이션 제거');
  await page.emulateMedia({reducedMotion:'no-preference'});
  const contrast=await page.locator('.wb-node-mode').first().evaluate(e=>{
    const rgb=getComputedStyle(e).color.match(/[\d.]+/g).slice(0,3).map(Number);
    const luminance=rgb.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
    return {font:parseFloat(getComputedStyle(e).fontSize),ratio:1.05/(luminance+.05)};
  });
  assert(contrast.font>=12&&contrast.ratio>=4.5,'작은 보조 문구 12px 이상·대비 4.5 이상');
  assert(await page.locator('.folder-paper-edge').count()>=3,'폴더 서류의 겹침과 종이 두께 표시');
  assert(await page.getByRole('button',{name:'기존 결재 창에서 승인',exact:true}).isDisabled(),'전체 조작 뒤에도 누락 후보 승인 잠금');
  assert(errors.length===0,'브라우저 런타임 오류 없음');
  await page.evaluate(()=>{document.querySelector('#workbench-screen').scrollTop=0;document.querySelector('.wb-graph-scroll').scrollLeft=0;});
  await page.screenshot({path:'output/playwright/workbench-visual-polished.png',fullPage:true,animations:'disabled'});
  return {status:'pass',count:checks.length,checks,geometry,contrast,errors,run:run.id,task:task.task,real_model_calls:0,production_writes:0};
}
