async (page) => {
  const checks = [], errors = [];
  const assert = (ok, name) => { if (!ok) throw new Error(name); checks.push(name); };
  page.on('pageerror', e => errors.push(e.message));
  assert(new URL(page.url()).host === '127.0.0.1:8798' && await page.evaluate(() => Data.get().studio.fake === true), '격리된 가짜 회사만 조작');
  const back = page.getByRole('button', { name: '내 작업대로 돌아가기', exact: true });
  if (await back.count()) await back.click();
  const n = page.locator('.wb-node').filter({ has: page.locator('strong', { hasText: /^입력 노트$/ }) });
  await n.click();
  const before = await page.evaluate(() => JSON.parse(localStorage.getItem('studio.workbench.draft.v1')).draft.graph);
  const id = await n.getAttribute('data-node'), box = await n.boundingBox();
  await page.mouse.move(box.x + 30, box.y + 35); await page.mouse.down();
  await page.mouse.move(box.x + 68, box.y + 57, { steps: 6 }); await page.mouse.up();
  const after = await page.evaluate(() => JSON.parse(localStorage.getItem('studio.workbench.draft.v1')).draft.graph);
  const old = before.nodes.find(row => row.id === id), moved = after.nodes.find(row => row.id === id);
  assert(moved.position.x === old.position.x + 38 && moved.position.y === old.position.y + 22, '실제 포인터 드래그 좌표를 저장');
  assert(after.nodes.filter(row => row.id !== id).every(row => JSON.stringify(row.position) === JSON.stringify(before.nodes.find(old => old.id === row.id).position)), '상세 옆 이웃 배치는 저장 원본 좌표를 바꾸지 않음');
  const endpoints = await page.locator('.wb-canvas').evaluate(canvas => {
    const origin = canvas.getBoundingClientRect();
    return [...canvas.querySelectorAll('.wb-wire')].every(wire => {
      const to = wire.dataset.edge.split(':')[1], rect = canvas.querySelector(`[data-node="${to}"]`).getBoundingClientRect();
      const match = wire.getAttribute('d').match(/([\d.]+),([\d.]+)$/);
      return match && Math.abs(+match[1] - (rect.left - origin.left)) < 1.5 && Math.abs(+match[2] - (rect.top - origin.top + 76)) < 1.5;
    });
  });
  assert(endpoints, '드래그 뒤 모든 실제 연결선이 표시된 도착 포트에 맞음');
  assert(await page.locator('.wb-canvas').evaluate(canvas => {
    const pane = canvas.querySelector('.wb-detail').getBoundingClientRect();
    return [...canvas.querySelectorAll('.wb-node')].every(el => { const r = el.getBoundingClientRect(); return r.left >= pane.right || r.right <= pane.left || r.top >= pane.bottom || r.bottom <= pane.top; });
  }), '드래그로 상세 위치가 바뀌어도 이웃 노드를 가리지 않음');
  await n.focus(); await page.keyboard.press('ArrowDown');
  assert(await n.evaluate(el => el.offsetTop) === moved.position.y + 20, '드래그 후 방향키 이동도 연속 작동');
  assert(errors.length === 0, '브라우저 실행 오류 없음');
  return { status: 'pass', count: checks.length, checks, errors, real_model_calls: 0, production_writes: 0 };
}
