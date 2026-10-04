'use strict';
module.exports = async (page) => {
  const checks = [];
  const requests = [];
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.unrouteAll();
  await page.reload();
  await page.setViewportSize({ width: 1536, height: 1024 });
  await page.waitForFunction(() => Data.loaded);
  await page.route('**/api/tasks/T9000', route => route.fulfill({ json: { proposal: {
    summary: '기획 결과를 검토하고 선택한 작업만 붙입니다.',
    questions: ['질문은 바로 읽을 수 있나요?', '긴 질문 '.repeat(18)],
    risks: ['후보 선택은 결재 완료가 아닙니다.'],
    tasks: Array.from({ length: 9 }, (_, i) => ({ title: i === 8 ? '<img src=x onerror=alert(1)> 마지막 후보' : `후보 ${i + 1} 개선`,
      kind: i % 2 ? 'research' : 'build', brief: '현재 동작을 유지하며 읽기 쉬운 화면을 만듭니다.', acceptance: ['전체 기록 표시'], difficulty: 2 }))
  } } }));
  await page.route('**/api/diary?day=*', route => {
    const day = Number(route.request().url().split('day=')[1]);
    return route.fulfill({ json: { day, events: day === 6 ? [] : Array.from({ length: 12 }, (_, i) => ({
      time: `10:${String(i).padStart(2, '0')}`, who: 'sol', name: '솔',
      text: i === 0 ? '긴 기록 '.repeat(28) + 'LONGTOKEN'.repeat(25) : `기록 ${i + 1} 완료`
    })), summary: { done: 12, approvals: 12, runs: 24, firstPass: [10, 12], tomorrow: '다음 업무를 확인합니다.' } } });
  });
  await page.route('**/api/tasks/T90*/report', route => route.fulfill({ json: { title: '완성 보고서',
    conclusion: '실제 문서 열기 화면까지 도달했습니다.', claims: ['내용 확인'], sources: [], unverified: [], body: '# 완성 보고서\n내용' } }));
  await page.route('**/api/tasks/T9000/approve', route => {
    requests.push({ action: 'approve', body: route.request().postDataJSON() });
    return route.fulfill({ json: {} });
  });
  await page.route('**/api/tasks/T9000/request-changes', route => {
    requests.push({ action: 'request-changes', body: route.request().postDataJSON() });
    return route.fulfill({ json: {} });
  });
  await page.route('**/api/trophies/play', route => {
    requests.push({ action: 'play', body: route.request().postDataJSON() });
    return route.fulfill({ json: {} });
  });
  await page.evaluate(() => {
    const s = Data.get(); s.day = 7; s.tasks = [];
    s.tasks.push({ id: 'T9000', kind: 'plan', status: 'awaiting_approval', title: '화면 개선 회의',
      brief: '업무일지·회의실·완성작을 개선합니다.\n긴 지시도 확인할 수 있어야 합니다.', role: 'producer', project: 'studio-docs' });
    for (let i = 1; i <= 10; i++) s.tasks.push({ id: `T90${String(i).padStart(2, '0')}`, kind: i === 10 ? 'build' : 'research', status: 'done', title: `완성작 ${i}`, role: i === 10 ? 'builder' : 'analyst', project: 'studio-docs' });
    s.trophies = Array.from({ length: 10 }, (_, i) => ({ task: `T90${String(i + 1).padStart(2, '0')}`, kind: i === 9 ? 'game' : 'doc', title: i === 6 ? '일곱 번째 완성작 · 긴 제목을 끝까지 읽을 수 있습니다' : `완성작 ${i + 1}` }));
    Popups.init({ notify: () => {}, onOpen: () => {}, onClose: () => {} });
    Popups.closeAll();
  });
  function assert(ok, name) { if (!ok) throw new Error(name); checks.push(name); }
  await page.getByRole('button', { name: '회의실', exact: true }).click();
  await page.locator('.mt-card').nth(8).waitFor();
  assert(await page.locator('.mt-card').count() === 9, '회의실 9개 후보 모두 표시');
  assert(await page.locator('.mt-notes li').count() === 3, '질문 2개·위험 1개 바로 표시');
  const lastCheck = page.locator('.mt-check').nth(8);
  await lastCheck.focus(); await lastCheck.press('Space');
  assert(await page.locator('.mt-check').nth(8).getAttribute('aria-checked') === 'false', '키보드로 마지막 후보 선택 해제');
  assert(await page.evaluate(() => document.activeElement.getAttribute('data-focus-key') === 'meeting-check-8'), '선택 갱신 후 포커스 유지');
  assert((await page.locator('.mt-picked').textContent()) === '선택 8 / 9', '선택 수 동기화');
  assert(await page.locator('.mt-card-title img').count() === 0 && (await page.locator('.mt-card-title').nth(8).textContent()).includes('<img'), '동적 제목 HTML을 텍스트로 표시');
  const scrollBefore = await page.locator('.mt-cards').evaluate(el => el.scrollTop);
  await page.evaluate(() => Popups.refresh());
  assert(await page.locator('.mt-cards').evaluate(el => el.scrollTop) === scrollBefore && scrollBefore > 0, '목록 갱신 후 스크롤 유지');
  await page.screenshot({ path: 'output/playwright/soyun-meeting.png' });
  await page.getByRole('button', { name: '퀘스트로 붙이기', exact: true }).click();
  await page.waitForFunction(() => !Popups.isOpen());
  assert(requests.some(r => r.action === 'approve' && r.body.selected.length === 8 && !r.body.selected.includes(8)), '선택된 8개만 기존 결재 요청으로 전달');
  await page.getByRole('button', { name: '회의실', exact: true }).click();
  await page.getByRole('button', { name: '다시 기획', exact: true }).click();
  const memo = page.getByRole('dialog', { name: '다시 기획', exact: true });
  await memo.getByRole('textbox').fill('질문을 반영해 다시 나눠 주세요.');
  await memo.getByRole('button', { name: '보내기', exact: true }).click();
  await memo.waitFor({ state: 'detached' });
  await page.waitForFunction(() => !Popups.isOpen());
  assert(requests.some(r => r.action === 'request-changes' && r.body.note.includes('질문')), '재기획 요청에 입력 의견 전달');
  await page.evaluate(() => Popups.closeAll());
  await page.getByRole('button', { name: '업무 일지', exact: true }).click();
  await page.locator('.dy-timeline li').nth(11).waitFor();
  assert(await page.locator('.dy-timeline li').count() === 12, '업무일지 12개 전체 기록 표시');
  assert(await page.locator('.dy-timeline .line').first().evaluate(el => getComputedStyle(el).whiteSpace !== 'nowrap' && el.scrollWidth <= el.clientWidth + 1), '긴 한국어·공백 없는 문자열 줄바꿈');
  await page.locator('.dy-timeline').focus(); await page.keyboard.press('End');
  await page.waitForFunction(() => document.querySelector('.dy-timeline').scrollTop > 0);
  assert(await page.locator('.dy-timeline').evaluate(el => el.scrollTop > 0), '기록 목록 키보드 스크롤');
  await page.screenshot({ path: 'output/playwright/soyun-diary.png' });
  await page.getByRole('button', { name: '전날', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.dy-empty')?.textContent === '기록이 없어요');
  await page.waitForFunction(() => !document.querySelector('.turn-layer'));
  assert(await page.locator('.dy-count').textContent() === '기록 0개 · 시간순', '날짜 이동과 빈 기록 상태');
  await page.keyboard.press('Escape');
  assert(await page.getByRole('button', { name: '업무 일지', exact: true }).evaluate(el => el === document.activeElement), 'Esc 후 호출 버튼으로 포커스 복귀');
  await page.getByRole('button', { name: '완성작', exact: true }).click();
  assert(await page.locator('.tr-slot').count() === 10, '완성작 10개 전체 표시');
  await page.locator('.tr-slot').nth(6).getByRole('button', { name: '열기', exact: true }).click();
  await page.getByRole('button', { name: '전체 보기', exact: true }).waitFor();
  assert(await page.locator('.rp-title').textContent() === '완성 보고서', '일곱 번째 작품 보고서 열기');
  await page.keyboard.press('Escape');
  await page.locator('.tr-slot').nth(9).getByRole('button', { name: '플레이', exact: true }).click();
  await page.waitForTimeout(250);
  assert(requests.some(r => r.action === 'play' && r.body.task === 'T9010'), '마지막 게임의 기존 실행 요청 전달');
  await page.screenshot({ path: 'output/playwright/soyun-trophies.png' });
  assert(await page.evaluate(() => {
    const plate = document.querySelector('.tr-plate').getBoundingClientRect();
    const shelf = document.querySelector('.tr-shelves').getBoundingClientRect();
    const command = document.getElementById('command').getBoundingClientRect();
    return plate.top >= shelf.bottom && plate.bottom <= command.top;
  }), '완성작 집계가 목록·명령창에 가리지 않음');
  await page.keyboard.press('Escape');
  await page.evaluate(() => { Data.get().trophies = []; Popups.trophies(); });
  assert((await page.locator('.tr-shelves').textContent()).includes('아직 완성작이 없어요'), '완성작 빈 상태 안내');
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.getByRole('button', { name: '업무 일지', exact: true }).click();
  assert(await page.locator('.dy .x-btn').isVisible(), '축소한 데스크톱 화면에서 닫기 접근');
  await page.screenshot({ path: 'output/playwright/soyun-diary-small.png' });
  await page.keyboard.press('Escape');
  assert(errors.length === 0, '브라우저 스크립트 오류 없음');
  return { status: 'pass', checks, count: checks.length, viewport: [1536, 1024],
    mode: 'real Edge browser, disposable company, deterministic API fixtures',
    production_writes: 0, model_calls: 0, actual_godot_launch: false,
    screenshots: ['soyun-meeting.png', 'soyun-diary.png', 'soyun-trophies.png', 'soyun-diary-small.png'] };
};
