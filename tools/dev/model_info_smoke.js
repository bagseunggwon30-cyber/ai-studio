async (page) => {
  const checks = [], errors = [], writes = [], geometry = [];
  const assert = (ok, name) => { if (!ok) throw new Error(name); checks.push(name); };
  assert(new URL(page.url()).host === '127.0.0.1:8797', 'temporary fixture only');
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (r.method() === 'POST') writes.push(new URL(r.url()).pathname); });
  await page.waitForFunction(() => Data.loaded && Data.get().studio.fake);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1536, height: 1024 });
  const open = async id => {
    await page.evaluate(task => Popups.taskCard(task), id);
    await page.locator('.tc-execution').waitFor();
  };
  await open('T0001');
  let text = await page.locator('.tc-execution').textContent();
  assert(await page.locator('.tc-execution dt').count() === 3, 'selected AI/program/response have separate labels');
  assert(text.includes('gpt-6.1-sol') && text.includes('codex-cli 0.160.0'), 'requested model and executable visible');
  assert(text.includes('로그에 모델 ID가 제공되지 않음'), 'missing response metadata has explicit reason');
  assert(!text.includes('확인 불가'), 'vague missing-model label removed');
  assert(text.includes('이 표시 자체는 연결 오류를 뜻하지 않습니다'), 'normal metadata absence distinguished from failure');
  await page.screenshot({ path: 'output/playwright/model-info-missing.png' });
  await page.keyboard.press('Escape');
  await open('T0002');
  assert((await page.locator('.tc-execution dd').last().textContent()) === 'served-model-example', 'response model shown only with metadata');
  await page.getByText('모델 확인 근거', { exact: true }).click();
  assert((await page.locator('.tc-execution details').textContent()).includes('response.completed.response.model'), 'exact response field retained');
  await page.keyboard.press('Escape');
  await open('T0003');
  text = await page.locator('.tc-execution').textContent();
  assert(text.includes('실행 오류 · 모델 ID 기록 없음'), 'execution failure is distinct');
  assert(!text.includes('이 표시 자체는 연결 오류'), 'failure does not receive normal-connection reassurance');
  await page.keyboard.press('Escape');
  await open('T0004');
  text = await page.locator('.tc-execution').textContent();
  assert(text.includes('실제 모델 호출 없음') && text.includes('시험용'), 'fake runtime never presented as actual model');
  await page.keyboard.press('Escape');
  await open('T0005');
  text = await page.locator('.tc-execution').textContent();
  assert(text.includes('Grok · grok-4.7') && text.includes('codex-cli'), 'requested provider separated from replacement executable');
  assert(text.includes('대체 실행: 시험용 대체 사유'), 'fallback reason shown');
  await page.keyboard.press('Escape');
  await open('T0006');
  assert(await page.locator('.tc-execution img').count() === 0, 'model text cannot inject HTML');
  for (const [width, height] of [[1536, 1024], [1024, 768], [800, 600], [600, 900]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const g = await page.locator('.tc-execution').evaluate(el => {
      const body = el.closest('.tc-body'), card = el.closest('.tc').getBoundingClientRect();
      return { overflow: el.scrollWidth > el.clientWidth + 1, bodyOverflow: body.scrollWidth > body.clientWidth + 1,
        x: card.x, y: card.y, right: card.right, bottom: card.bottom };
    });
    assert(!g.overflow && !g.bodyOverflow, `long model wraps ${width}x${height}`);
    assert(g.x >= -1 && g.y >= -1 && g.right <= width + 1 && g.bottom <= height + 1, `card fits ${width}x${height}`);
    geometry.push({ width, height, ...g });
  }
  assert(errors.length === 0, 'browser script errors 0');
  assert(writes.length === 0, 'UI inspection writes 0');
  return { status: 'pass', checks, errors, geometry, real_model_calls: 0,
    mode: 'actual Edge UI/API; controlled record examples; no employee execution' };
}
