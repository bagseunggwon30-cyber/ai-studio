async (page) => {
  const checks = [], geometry = [], errors = [], writes = [];
  let replySent = false, staleDetailReturned = false;
  const assert = (ok, name) => { if (!ok) throw new Error(name); checks.push(name); };
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (r.method() === 'POST') { const path = new URL(r.url()).pathname; writes.push(path); if (path.endsWith('/request-changes')) replySent = true; } });
  assert(new URL(page.url()).host === '127.0.0.1:8797', '임시 시험 서버에서만 실행');
  await page.unrouteAll();
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.reload();
  await page.setViewportSize({ width: 1536, height: 1024 });
  // 처음 화면은 홈이다 (2026-10-05): 카드는 진행판에 있으니 왼쪽 메뉴에서 진행판으로
  await page.locator('.bd-nav').getByRole('button', { name: '진행판', exact: true }).click();
  await page.waitForFunction(() => Data.loaded && Data.task('T0001')?.needs_plan_input);
  assert(await page.evaluate(() => Data.get().studio.fake === true), '가짜 실행기 회사 확인');
  await page.locator('#project-chip').click();
  assert(await page.locator('.project-option').count() === 2, '작업 대상을 목록에서 명시적으로 선택');
  assert((await page.locator('.project-picker').textContent()).includes('아직 작업 대상으로 등록되지'), '미등록 프로젝트 안내');
  assert((await page.locator('.project-option small').first().textContent()).includes('docs/**'), '허용된 파일 범위 표시');
  await page.locator('.project-option').nth(1).click();
  assert((await page.locator('#project-chip').textContent()).includes('보고서 자료'), '선택한 작업 대상을 명령창에 표시');
  await page.locator('#project-chip').click();
  await page.locator('.project-option').first().click();
  await page.locator('.bd-card[data-id="T0001"]').click();
  await page.waitForFunction(() => document.querySelector('.tc-brief')?.textContent.length > 600);
  assert((await page.locator('.tc-meta').textContent()).includes('답변 필요'), '질문 대기를 실행 고장과 구분');
  assert(await page.locator('.tc-actions').getByRole('button', { name: '재시도', exact: true }).count() === 0, '답변 없는 단순 재시도 숨김');
  assert((await page.locator('.tc-brief').textContent()).includes('LONGTOKEN'), '600자 이후의 전체 요청도 조회');
  for (const [width, height] of [[1536, 1024], [1024, 768], [800, 600], [600, 900]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const measure = await page.locator('.tc').evaluate(el => {
      const box = e => { const r = e.getBoundingClientRect(); return { left:r.left, top:r.top, right:r.right, bottom:r.bottom }; };
      const body = el.querySelector('.tc-body'), footer = el.querySelector('.tc-actions');
      return { modal:box(el), stage:box(document.getElementById('stage')), close:box(el.querySelector('.x-btn')),
        body:box(body), footer:box(footer), width:body.clientWidth, scrollWidth:body.scrollWidth,
        buttons:Array.from(footer.querySelectorAll('.btn'), b => ({ ...box(b), width:b.clientWidth, scrollWidth:b.scrollWidth, height:b.clientHeight, scrollHeight:b.scrollHeight })) };
    });
    const inside = (a,b) => a.left >= b.left-1 && a.top >= b.top-1 && a.right <= b.right+1 && a.bottom <= b.bottom+1;
    assert(inside(measure.modal, measure.stage), `${width}x${height}: 작업창이 화면 안에 유지`);
    assert(inside(measure.close, measure.modal), `${width}x${height}: 닫기 단추 접근`);
    assert(measure.body.bottom <= measure.footer.top+1 && inside(measure.footer, measure.modal), `${width}x${height}: 본문과 행동 영역 분리`);
    assert(measure.scrollWidth <= measure.width+1, `${width}x${height}: 긴 문자열 가로 넘침 없음`);
    assert(measure.buttons.every(b => b.scrollWidth <= b.width+1 && b.scrollHeight <= b.height+1), `${width}x${height}: 버튼 글자가 칸에 맞음`);
    geometry.push({ width, height, ...measure });
    if (width === 1024) await page.screenshot({ path:'output/playwright/task-popup-small.png' });
  }
  await page.setViewportSize({ width:1536, height:1024 });
  await page.locator('.tc-body').focus();
  await page.keyboard.press('End');
  await page.waitForFunction(() => document.querySelector('.tc-body').scrollTop > 0);
  const scroll = await page.locator('.tc-body').evaluate(el => el.scrollTop);
  await page.evaluate(() => Popups.refresh());
  assert(await page.locator('.tc-body').evaluate(el => el.scrollTop) === scroll, '작업 갱신 후 본문 스크롤 유지');
  await page.locator('.tc-body').evaluate(el => { el.scrollTop = 0; });
  await page.locator('.tc .x-btn').focus();
  await page.screenshot({ path:'output/playwright/task-popup-plan.png' });
  await page.getByRole('button', { name:'설명·질문 보기', exact:true }).click();
  await page.locator('.mt-notes').waitFor();
  assert((await page.locator('.panel-status').first().textContent()) === '답변 필요', '회의실에서도 답변 필요 표시');
  assert((await page.locator('.mt-context').textContent()).includes('Core Courier'), '회의실에 현재 프로젝트 명시');
  assert(await page.locator('.mt-footer').getByRole('button', { name:'퀘스트로 붙이기', exact:true }).count() === 0, '질문만 있는 결과를 승인할 수 없음');
  assert(await page.evaluate(() => Math.abs(document.querySelector('.mt-notes').getBoundingClientRect().width - document.querySelector('.mt-content').getBoundingClientRect().width) < 2), '질문만 있는 기획은 내용 영역 전체 사용');
  await page.screenshot({ path:'output/playwright/task-popup-questions.png' });
  await page.getByRole('button', { name:'답변하고 다시 기획', exact:true }).click();
  const memo = page.getByRole('dialog', { name:'기획 질문에 답변', exact:true });
  const answer = '현재 게임의 정답 화면을 고쳐 주세요.';
  await memo.getByRole('textbox').fill(answer);
  await page.evaluate(() => Popups.refresh());
  assert(await memo.getByRole('textbox').inputValue() === answer, '화면 갱신에도 작성 중인 답변 보존');
  // A delayed queued snapshot with the same timestamp must not hide the final proposal.
  await page.route('**/api/tasks/T0001', async route => {
    const response = await route.fetch();
    const data = await response.json();
    if (replySent && !staleDetailReturned) {
      data.status = 'queued'; data.proposal = null; staleDetailReturned = true;
      return route.fulfill({ json:data });
    }
    return route.fulfill({ response });
  });
  await memo.getByRole('button', { name:'답변하고 다시 기획', exact:true }).click();
  await page.waitForFunction(() => Data.task('T0001')?.status === 'awaiting_approval');
  assert(await page.evaluate(() => Data.task('T0001').status === 'awaiting_approval'), '답변 후 실제 임시 API·가짜 실행기로 재기획 완료');
  assert(await page.evaluate(() => Data.task('T0001').usage.runs === 2), '이전 질문 결과를 재사용하지 않고 정확히 1회 새 기획');
  await page.locator('.bd-card[data-id="T0001"]').click();
  await page.locator('.mt-card').nth(1).waitFor();
  assert(await page.locator('.mt-card').count() === 2, '새 기획 후보 2개 표시');
  assert(staleDetailReturned, '뒤늦게 도착한 대기 응답이 최신 기획안을 가리지 않음');
  assert((await page.locator('.panel-status').first().textContent()) === '결재 대기', '재기획 이후 사람의 결재 경계 유지');
  await page.keyboard.press('Escape');
  await page.locator('.bd-card[data-id="T0002"]').click();
  await page.getByRole('button', { name:'재시도', exact:true }).waitFor();
  assert((await page.locator('.tc-meta').textContent()).includes('막힘'), '실제 오류는 기존 막힘·재시도 유지');
  assert(await page.locator('.tc-body').evaluate(el => el.scrollWidth <= el.clientWidth+1), '긴 오류·수용 기준도 가로 넘침 없음');
  await page.screenshot({ path:'output/playwright/task-popup-error.png' });
  assert(writes.length === 1 && writes[0] === '/api/tasks/T0001/request-changes', '답변 요청 1회만 전송·승인/재시도/다른 작업 쓰기 없음');
  assert(errors.length === 0, '브라우저 스크립트 오류 없음');
  return { status:'pass', checks, count:checks.length, geometry, browser:'installed Edge / Playwright CLI',
    environment:'disposable company, actual UI and API, fake runtime; one delayed detail response simulated', stale_detail_response_injected:staleDetailReturned, model_calls:0, production_writes:0,
    screenshots:['task-popup-plan.png','task-popup-small.png','task-popup-questions.png','task-popup-error.png'] };
}
