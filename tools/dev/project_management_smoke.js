async (page) => {
  const checks = [], errors = [], geometry = [];
  const assert = (ok, label) => { if (!ok) throw new Error(label); checks.push(label); };
  assert(new URL(page.url()).host === '127.0.0.1:8797', 'temporary server only');
  page.on('pageerror', e => errors.push(e.message));
  await page.reload();
  await page.waitForFunction(() => Data.loaded && Data.task('T0001'));
  assert(await page.evaluate(() => Data.get().studio.fake), 'fake employees only');
  await page.locator('#project-chip').click();
  await page.getByRole('button', { name: '프로젝트 등록', exact: true }).click();
  await page.getByRole('button', { name: 'AI Studio 자체 입력', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('input[aria-label="프로젝트 ID (영문 소문자)"]')?.value === 'ai-studio');
  const root = await page.getByLabel('Git 폴더 전체 경로', { exact: true }).inputValue();
  assert(root.includes('studio-test-'), 'preset uses temporary company');
  assert((await page.getByLabel('수정 허용 경로 (한 줄에 하나)', { exact: true }).inputValue()).includes('ui/**'), 'self preset has explicit UI scope');
  for (const [width, height] of [[1536, 1024], [1024, 768], [800, 600], [600, 900]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const g = await page.locator('.project-form').evaluate(el => {
      const r = el.getBoundingClientRect(), footer = el.querySelector('.row-btns').getBoundingClientRect();
      const body = el.querySelector('.project-form-body');
      return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, footerBottom: footer.bottom,
        overflow: body.scrollWidth > body.clientWidth + 1 };
    });
    assert(g.x >= -1 && g.y >= -1 && g.right <= width + 1 && g.bottom <= height + 1, `registration fits ${width}x${height}`);
    assert(!g.overflow && g.footerBottom <= height + 1, `registration body/footer fits ${width}x${height}`);
    geometry.push({ width, height, ...g });
  }
  await page.setViewportSize({ width: 1536, height: 1024 });
  await page.getByLabel('프로젝트 이름', { exact: true }).fill('새 대상 <시험>');
  await page.getByLabel('프로젝트 ID (영문 소문자)', { exact: true }).fill('target');
  await page.getByLabel('Git 폴더 전체 경로', { exact: true }).fill(root + '/projects/target');
  await page.getByLabel('기준 브랜치', { exact: true }).fill('main');
  await page.getByLabel('수정 허용 경로 (한 줄에 하나)', { exact: true }).fill('docs/**');
  await page.getByRole('button', { name: '확인하고 등록', exact: true }).click();
  await page.getByRole('alert').waitFor();
  assert((await page.getByRole('alert').textContent()).includes('확인'), 'scope confirmation required');
  await page.locator('.project-confirm input').check();
  await page.getByLabel('수정 허용 경로 (한 줄에 하나)', { exact: true }).fill('../escape');
  await page.getByRole('button', { name: '확인하고 등록', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.project-form [role="alert"]')?.textContent.includes('상대'));
  assert(await page.evaluate(() => !Data.get().projects.some(p => p.key === 'target')), 'invalid scope creates no profile');
  await page.getByLabel('수정 허용 경로 (한 줄에 하나)', { exact: true }).fill('docs/**');
  await page.getByRole('button', { name: '확인하고 등록', exact: true }).click();
  await page.waitForFunction(() => Data.currentProject()?.key === 'target');
  assert((await page.locator('#project-chip').textContent()).includes('새 대상 <시험>'), 'new project selected and text escaped');
  assert(await page.evaluate(() => Data.get().projects.find(p => p.key === 'target').has_qa === false), 'QA absence explicit');
  await page.keyboard.press('Escape');
  await page.evaluate(() => Popups.taskCard('T0001'));
  await page.getByRole('button', { name: '작업 대상 변경', exact: true }).waitFor();
  await page.getByRole('button', { name: '작업 대상 변경', exact: true }).click();
  assert(await page.getByLabel('새 작업 대상', { exact: true }).inputValue() === 'target', 'replacement target selection');
  let request = null;
  page.on('request', r => { if (r.url().endsWith('/T0001/retarget') && r.method() === 'POST') request = r.postDataJSON(); });
  await page.getByRole('button', { name: '대상 변경 · 실행 대기', exact: true }).click();
  await page.waitForFunction(() => Data.task('T0002')?.status === 'blocked');
  const state = await page.evaluate(() => ({ old: Data.task('T0001'), fresh: Data.task('T0002'), runs: Data.get().runs }));
  assert(state.old.status === 'cancelled', 'old task closed with history preserved');
  assert(state.fresh.project === 'target' && !state.fresh.run_requested, 'new task paused on correct target');
  assert(!state.fresh.qa && !state.fresh.review && state.fresh.usage.runs === 0, 'no old verification or model calls reused');
  assert(await page.getByRole('button', { name: '재시도', exact: true }).count() === 1, 'human can start reviewed replacement');
  const replay = await page.evaluate(async body => Data.retarget('T0001', body), request);
  assert(replay.task === 'T0002', 'resubmission returns existing replacement');
  assert(await page.evaluate(() => Data.get().tasks.length === 2), 'no duplicate tasks');
  await page.screenshot({ path: 'output/playwright/project-target-paused.png' });
  assert(errors.length === 0, 'no browser script errors');
  return { status: 'pass', checks, geometry, errors, real_model_calls: 0, mode: 'temporary company / actual UI+API / fake employees' };
}
