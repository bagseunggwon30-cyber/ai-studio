async (page) => {
  const checks = [], errors = [], writes = [];
  const assert = (ok, name) => { if (!ok) throw new Error(name); checks.push(name); };
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (r.method() === 'POST') writes.push(new URL(r.url()).pathname); });
  assert(new URL(page.url()).host === '127.0.0.1:8798', '격리된 8798 미리보기만 접근');
  await page.setViewportSize({ width: 1585, height: 992 });
  await page.waitForFunction(() => typeof Data !== 'undefined' && Data.loaded);
  assert(await page.evaluate(() => Data.get().studio.fake === true), '기존 테스트 FakeRuntime 확인');
  const saved = await page.evaluate(async () => {
    const catalog = await Data.workbenchGet();
    const titles = ['자료 읽기', '코드 수정', '테스트', '검토·근거 확인', '승인'];
    const ops = ['input', 'implement', 'test', 'review', 'approve'];
    const positions = [{x:410,y:44},{x:685,y:60},{x:960,y:60},{x:1000,y:345},{x:1265,y:370}];
    const nodes = [];
    for (let i = 0; i < ops.length; i++) {
      const original = catalog.nodes.find(n => n.spec.operation === ops[i]);
      const body = { title: titles[i], folder: 'personal', note: original.note, spec: original.spec };
      const note = (await Data.workbenchPost('nodes', body)).node;
      nodes.push({ id: 'visual-' + ops[i], ref: { id: note.id, version: note.version }, params: JSON.parse(JSON.stringify(note.spec.params)), position: positions[i] });
    }
    nodes[0].params.text = '정답 42를 docs/answer.txt에 저장해 주세요. 격리 UI 검증용입니다.';
    nodes[1].params.acceptance = ['테스트 기록', '수정 결과 기록', '결과 파일'];
    nodes[1].params.evidence = [[{ type:'test', name:'answer_is_42' }], [{type:'file',path:'docs/revision.txt'}], [{type:'file',path:'docs/contract.txt'}]];
    const flow = (await Data.workbenchPost('flows', { title:'웹페이지 개선', folder:'personal', project:'demo', allowed_paths:['docs/**'], graph:{nodes,edges:nodes.slice(1).map((n,i)=>({from:nodes[i].id,to:n.id}))} })).flow;
    localStorage.setItem('studio.workbench.draft.v1', JSON.stringify({draft:flow,selected:nodes[0].id,unsaved:false}));
    localStorage.setItem('studio.workbench.surface.v1','workspace');
    return flow;
  });
  await page.reload();
  await page.waitForFunction(() => Data.loaded);
  if (await page.locator('#workbench-screen').isHidden()) await page.locator('.bd-nav').getByRole('button',{name:'기능 작업대',exact:true}).click();
  await page.locator('.wb-node').nth(4).waitFor();
  assert(await page.locator('.wb-node').count() === 5, '저장된 다섯 노드 복원');
  assert(await page.locator('.wb-detail').isHidden(), '기본 상세 접힘');
  assert(!await page.locator('.wb-run-history').evaluate(e=>e.open), '장부 기본 접힘');
  await page.getByRole('button',{name:'실행 계획 확인',exact:true}).click();
  const plan = page.getByRole('dialog',{name:'실행 전 계획 확인',exact:true});
  assert(await plan.getByRole('button',{name:'확인한 계획 실행'}).isDisabled(), '계획과 모델 동의 전 실행 잠금');
  await plan.getByRole('checkbox').nth(0).check(); await plan.getByRole('checkbox').nth(1).check();
  await plan.getByRole('button',{name:'확인한 계획 실행'}).dblclick();
  let run;
  for (let attempt = 0; attempt < 90; attempt++) {
    run = await page.evaluate(async()=>{const ledger=await Data.workbenchGet('/ledger');return ledger.runs.length ? Data.workbenchGet('/runs/'+ledger.runs[0].id):null;});
    if (run?.status==='blocked' && Object.values(run.current_tasks||{}).some(t=>t.status==='awaiting_approval')) break;
    await page.waitForTimeout(1000);
  }
  assert(run?.status==='blocked','누락 파일에서 실제 엔진이 실행을 막음');
  const task = Object.values(run.current_tasks)[0];
  assert(task.evidence.items.filter(i=>i.status==='verified').length===2 && task.evidence.items.filter(i=>i.status==='missing').length===1,'실제 근거 2개 충족·1개 누락');
  await page.locator('[data-node="visual-review"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('.wb-proof-items>li').length===3);
  assert(await page.getByRole('button',{name:'기존 결재 창에서 승인',exact:true}).isDisabled(),'누락 후보 승인 잠금 유지');
  assert(await page.locator('.wb-advanced pre').count()===3 && !await page.locator('.wb-advanced').evaluate(e=>e.open),'JSON은 접힌 고급 상세에 보관');
  assert(writes.filter(p=>p==='/api/workbench/start').length===1,'실행 중복 클릭 방지');
  await page.screenshot({path:'output/playwright/workbench-visual-representative.png',fullPage:true,animations:'disabled'});
  assert(errors.length===0,'브라우저 런타임 오류 없음');
  return {status:'representative_ready_for_visual_review',checks,errors,writes,run:run.id,task:task.task,flow:saved.id,real_model_calls:0,production_writes:0,screenshot:'output/playwright/workbench-visual-representative.png'};
}
