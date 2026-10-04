async (page) => {
  const checks = [], errors = [], writes = [];
  const assert = (ok, name) => { if (!ok) throw new Error(name); checks.push(name); };
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (r.method() === 'POST') writes.push(new URL(r.url()).pathname); });
  const readRun = () => page.evaluate(async () => {
    const rows = await Data.workbenchGet('/ledger');
    return Data.workbenchGet('/runs/' + rows.runs[0].id);
  });
  const phase = await page.evaluate(() => localStorage.getItem('workbench-evidence-qa-phase'));
  assert(new URL(page.url()).host === '127.0.0.1:8798', '격리 미리보기만 검사');
  assert(await page.evaluate(() => Data.get().studio.fake === true), '실제 모델 호출 없는 기존 가짜 회사');
  await page.setViewportSize({ width: 1536, height: 1140 });
  await page.locator('.wb-node').filter({ has: page.locator('strong', { hasText: /^테스트$/ }) }).click();
  let run = await readRun();
  const taskId = Object.keys(run.current_tasks)[0], before = run.usage.total;
  if (phase !== 'restore-and-approve') {
    await page.locator('.wb-detail .wb-proof-badge.missing').waitFor();
    assert(!run.current_tasks[taskId].approval.allowed, '변경된 근거로 API 승인 불가');
    assert(await page.getByRole('button', { name: '기존 결재 창에서 승인', exact: true }).isDisabled(), '근거 변경 시 화면 승인 잠금');
    assert((await page.locator('.wb-detail .wb-approval-reasons').textContent()).includes('변경'), '근거 변경 이유 표시');
    await page.screenshot({ path: `output/playwright/workbench-evidence-${phase}.png`, fullPage: true, animations: 'disabled' });
  } else {
    const reconcile = page.getByRole('button', { name: '기록 다시 확인', exact: true });
    if (await reconcile.count()) await reconcile.click();
    await page.waitForFunction(() => document.querySelector('.wb-proof-badge')?.textContent === '모든 기준 확인');
    run = await readRun();
    assert(run.current_tasks[taskId].approval.allowed, '원본 근거 복구 뒤 동일 후보 승인 가능');
    assert(run.usage.total === before, '기록 다시 확인은 모델 재호출 없음');
    await page.getByRole('button', { name: '기존 결재 창에서 승인', exact: true }).click();
    const approval = page.getByRole('dialog', { name: '결재 · 구현', exact: true });
    await approval.getByRole('button', { name: '승인', exact: true }).dblclick();
    await page.waitForFunction(id => Data.task(id)?.status === 'done', taskId);
    await page.keyboard.press('Escape');
    await page.locator('.bd-nav').getByRole('button', { name: '기능 작업대', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.wb-run-bar strong')?.textContent.startsWith('완료'));
    run = await readRun();
    assert(run.status === 'succeeded', '같은 실행이 기존 승인 뒤 완료');
    assert(Object.values(run.nodes).every(n => n.status === 'succeeded'), '최신 후보의 모든 노드 실제 완료');
    const summary = run.snapshot.graph.nodes.find(n => n.definition.spec.operation === 'summary');
    const result = run.nodes[summary.id].output.result;
    assert(result.candidate_sha === result.merged_sha && result.evidence.complete, '결과정리의 승인 후보·근거 일치');
    assert(run.versions.length === 1 && run.versions[0].candidate_sha !== result.candidate_sha, '완료 뒤 이전 후보 이력 보존');
    assert(run.usage.total === before, '승인·완료 뒤 추가 모델 호출 없음');
    assert(writes.filter(p => p === `/api/tasks/${taskId}/approve`).length === 1, '승인 중복 클릭도 한 번만 전송');
    await page.locator('.wb-node').filter({ has: page.locator('strong', { hasText: /^결과정리$/ }) }).click();
    await page.screenshot({ path: 'output/playwright/workbench-evidence-completed.png', fullPage: true, animations: 'disabled' });
  }
  assert(errors.length === 0, '브라우저 실행 오류 없음');
  return { status: 'pass', phase, count: checks.length, checks, errors, writes,
    run: run.id, task: taskId, usage: run.usage, real_model_calls: 0, production_writes: 0 };
}
