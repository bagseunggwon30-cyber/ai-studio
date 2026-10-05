'use strict';
// Local Edge + disposable fixture only. No supplier access or downloaded code.
const { chromium } = require('C:/Users/bark/AppData/Local/npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright-core');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const out = path.resolve('output/grok-planner-browser');
fs.mkdirSync(out, { recursive: true });
let browser, fixture, page;
(async () => {
  browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  page = await browser.newPage({ viewport: { width: 1585, height: 1080 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const b64 = await page.evaluate(async () => {
    const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 240;
    const ctx = canvas.getContext('2d'); ctx.fillStyle = '#fff8d7'; ctx.fillRect(0, 0, 320, 240);
    ctx.fillStyle = '#304b40'; ctx.font = 'bold 28px sans-serif'; ctx.fillText('MOCK VIDEO', 65, 120);
    const stream = canvas.captureStream(10), recorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8' });
    const chunks = []; recorder.ondataavailable = e => chunks.push(e.data);
    const stopped = new Promise(resolve => { recorder.onstop = resolve; }); recorder.start();
    let tick = 0; const redraw = setInterval(() => { ctx.fillStyle = '#fff8d7'; ctx.fillRect(0, 150, 320, 80); ctx.fillStyle = '#304b40'; ctx.fillText(String(++tick), 150, 190); }, 100);
    await new Promise(resolve => setTimeout(resolve, 1500)); clearInterval(redraw); recorder.stop(); await stopped;
    stream.getTracks().forEach(t => t.stop());
    const bytes = new Uint8Array(await new Blob(chunks).arrayBuffer());
    return btoa(Array.from(bytes, c => String.fromCharCode(c)).join(''));
  });
  const videoFile = path.join(out, 'mock-video.webm'); fs.writeFileSync(videoFile, Buffer.from(b64, 'base64'));
  fixture = spawn('python', ['tools/dev/workbench_fixture.py', '--port', '8798', '--grok-mock', '--mock-video', videoFile], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  const ready = await new Promise((resolve, reject) => {
    let data = '';
    fixture.stdout.on('data', chunk => { data += chunk; if (data.includes('\n')) resolve(JSON.parse(data.trim().split('\n').at(-1))); });
    fixture.stderr.on('data', chunk => process.stderr.write(chunk));
    fixture.once('exit', code => reject(new Error('Fixture exited ' + code)));
    setTimeout(() => reject(new Error('Fixture readiness timeout')), 60000).unref();
  });
  await page.goto(ready.url); await page.locator('button[data-surface="workspace"]').click();
  await page.locator('.wb-run-history > summary').click();
  await page.locator('.wb-ledger-list .wb-run').first().waitFor();
  const report = { simulation: true, real_model_calls: 0, media: [], errors };
  for (const kind of ['research', 'image', 'video']) {
    await page.locator('.wb-run').filter({ hasText: 'MOCK / 모의 실행 · ' + kind }).click();
    await page.locator('[data-node="provider"]').click();
    await page.locator('.wb-detail').filter({ hasText: 'MOCK / 모의 실행' }).waitFor();
    if (kind === 'image') {
      await page.waitForFunction(() => [...document.querySelectorAll('.wb-provider-artifacts img')].some(i => i.naturalWidth > 0));
      report.media.push(await page.locator('.wb-provider-artifacts img').evaluate(i => ({ kind: 'image', width: i.naturalWidth, height: i.naturalHeight })));
    }
    if (kind === 'video') {
      await page.waitForFunction(() => [...document.querySelectorAll('.wb-provider-artifacts video')].some(v => v.readyState >= 1 && v.videoWidth > 0));
      const media = await page.locator('.wb-provider-artifacts video').evaluate(async v => {
        await v.play(); await new Promise(r => setTimeout(r, 250)); v.pause();
        return { kind: 'video', width: v.videoWidth, duration: Number.isFinite(v.duration) ? v.duration : 'stream metadata', played: v.currentTime > 0 };
      });
      if (!media.played) throw new Error('Mock video did not play'); report.media.push(media);
    }
    await page.screenshot({ path: path.join(out, kind + '-mock.png'), fullPage: true, animations: 'disabled' });
  }
  async function checkHeading() {
    const boxes = await page.evaluate(() => {
      const rect = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return {top:r.top,bottom:r.bottom,left:r.left,right:r.right}; };
      return {title:rect('.wb-work-title h2'), metadata:rect('.wb-work-title p'), run:rect('.wb-run-bar'), settings:rect('.wb-work-settings')};
    });
    if (boxes.metadata.top < boxes.title.bottom || boxes.run.top < boxes.metadata.bottom || boxes.settings.top < boxes.run.bottom) throw new Error('Heading metadata overlap: ' + JSON.stringify(boxes));
    return boxes;
  }
  report.headingDesktop = await checkHeading();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(out, 'narrow-mock.png'), fullPage: true, animations: 'disabled' });
  report.narrowOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  await page.setViewportSize({ width: 1585, height: 1080 });
  await page.locator('button[data-surface="drawer"]').click();
  await page.locator('.wb-folder-card').filter({ hasText: 'MOCK 입력·옵션 확인' }).click();
  await page.locator('button[data-toolbox]').click();
  for (const kind of ['research', 'image', 'video']) {
    const skill = page.locator(`[data-library="builtin-grok_${kind}"]`);
    await skill.waitFor(); if (!await skill.innerText().then(t => t.includes('필수 입력') && t.includes('산출물') && t.includes('비용 알 수 없음'))) throw new Error('Incomplete drawer descriptor');
  }
  await page.screenshot({ path: path.join(out, 'drawer-mock.png'), fullPage: true, animations: 'disabled' });
  await page.keyboard.press('Escape');
  await page.locator('.wb-work-settings > summary').focus(); await page.keyboard.press('Enter');
  await page.getByRole('button', { name: '문서 불러오기', exact: true }).click();
  const importDialog = page.getByRole('dialog', { name: '작업 묶음 불러오기' });
  const badNodes = ['input', 'grok_image', 'format'].map((op, i) => ({ id: String(i), ref: { id: 'builtin-' + op, version: 1 }, params: op === 'input' ? { text: 'MOCK' } : {} }));
  await importDialog.locator('textarea').fill(JSON.stringify({ schema: 'ai-studio-flow/v1', title: 'MOCK invalid', graph: { nodes: badNodes, edges: [{ from: '0', to: '1' }, { from: '1', to: '2' }] } }));
  await importDialog.getByRole('button', { name: '확인하고 불러오기' }).click();
  await importDialog.locator('.wb-dialog-error').waitFor();
  if (!await importDialog.innerText().then(t => t.includes('입출력 형식이 맞지'))) throw new Error('Invalid typed UI graph was not rejected');
  report.invalidConnectionRejected = true;
  await importDialog.locator('header button').click();
  await page.locator('.wb-work-settings > summary').focus(); await page.keyboard.press('Enter');
  await page.locator('[data-prepare="1"]').click();
  const dialog = page.getByRole('dialog', { name: '실행 전 계획 확인' }); await dialog.waitFor();
  const planText = await dialog.innerText();
  if (!planText.includes('MOCK: 계획 확인 요청 / 정확한 입력') || !planText.includes('"count":1') || !planText.includes('"resolution":"1k"') || !planText.includes('비용 알 수 없음')) throw new Error('Concrete approval details missing');
  report.planDetailsVerified = true;
  await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab');
  report.keyboardFocusContained = await dialog.evaluate(d => d.contains(document.activeElement));
  if (!report.keyboardFocusContained) throw new Error('Dialog keyboard focus escaped');
  await page.screenshot({ path: path.join(out, 'plan-mock.png'), fullPage: true, animations: 'disabled' });
  await dialog.getByRole('button', { name: '닫기', exact: true }).last().click();
  await page.locator('[data-prepare="1"]').click(); await dialog.waitFor();
  await dialog.locator('input[type="checkbox"]').first().check();
  const beforeRuns = await page.evaluate(async () => (await (await fetch('/api/workbench/ledger')).json()).runs.length);
  await dialog.locator('footer button').last().evaluate(b => { b.click(); b.click(); });
  await page.waitForFunction(async count => (await (await fetch('/api/workbench/ledger')).json()).runs.length === count + 1, beforeRuns);
  report.mockUiExecutionRecorded = true;
  report.duplicateClickSingleRun = true;
  await page.waitForFunction(async () => {
    const ledger = (await (await fetch('/api/workbench/ledger')).json()).runs;
    return ledger.find(r => r.title === 'MOCK 입력·옵션 확인')?.status === 'succeeded';
  }, null, { timeout: 60000 });
  await page.locator('[data-node="provider"]').click(); await page.locator('.wb-provider-artifacts img').waitFor();
  await page.screenshot({ path: path.join(out, 'executed-mock.png'), fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: '목표로 AI 기획', exact: true }).click();
  await page.locator('[name="planner-goal"]').fill('MOCK saved skills image goal');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '목표로 AI 기획', exact: true }).click();
  await page.locator('[name="planner-goal"]').fill('MOCK saved skills image goal');
  await page.getByRole('button', { name: '보낼 요청 먼저 확인', exact: true }).click();
  await page.locator('[name="planner-model-confirm"]').waitFor();
  const planningRequest = await page.locator('.wb-dialog pre').innerText();
  if (!planningRequest.includes('mock-saved-image-brief') || !planningRequest.includes('contract')) throw new Error('Stored typed skill contract missing');
  await page.locator('[name="planner-model-confirm"]').check();
  await page.getByRole('button', { name: '기획 요청 한 번 보내기', exact: true }).evaluate(b => { b.click(); b.click(); });
  await page.locator('[name="planner-confirm"]').waitFor();
  const plannerId = await page.evaluate(() => localStorage.getItem('studio.workbench.planner'));
  let proposal = await page.evaluate(async id => (await (await fetch('/api/workbench/planner/' + id)).json()), plannerId);
  if (proposal.status !== 'awaiting_approval' || !proposal.simulation) throw new Error('Real existing approval wait missing');
  await page.screenshot({ path: path.join(out, 'planner-approval-mock.png'), fullPage: true, animations: 'disabled' });
  await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '목표로 AI 기획', exact: true }).click();
  await page.getByRole('button', { name: '이전 기획 다시 열기', exact: true }).click();
  await page.locator('[name="planner-confirm"]').check();
  await page.getByRole('button', { name: 'CEO 계획 승인 후 실행', exact: true }).evaluate(b => { b.click(); b.click(); });
  const plannerDeadline = Date.now() + 60000;
  let completedPlan = false;
  while (Date.now() < plannerDeadline) {
    proposal = await page.evaluate(async id => (await (await fetch('/api/workbench/planner/' + id)).json()), plannerId);
    if (proposal.status === 'approved' && proposal.run) {
      const execution = await page.evaluate(async id => (await (await fetch('/api/workbench/runs/' + id)).json()), proposal.run);
      if (execution.status === 'succeeded') { completedPlan = true; break; }
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (!completedPlan) throw new Error('Planner execution did not complete');
  if (proposal.status !== 'approved' || typeof proposal.run !== 'string') throw new Error('Approved proposal missing execution reference: ' + JSON.stringify(proposal));
  await page.getByRole('button', { name: '목표로 AI 기획', exact: true }).click();
  await page.getByRole('button', { name: '이전 기획 다시 열기', exact: true }).click();
  await page.getByRole('button', { name: '검증된 결과를 재사용 묶음으로 저장', exact: true }).click();
  await page.keyboard.press('Escape');
  const plannerTask = await page.evaluate(async id => (await (await fetch('/api/tasks/' + id)).json()), proposal.task);
  if (plannerTask.status !== 'done') throw new Error('Engine CEO approval was not applied');
  report.planner = { simulation: true, id: plannerId, task: proposal.task, run: proposal.run, task_status: plannerTask.status, approval_wait: true, double_click: 'one proposal and execution', close_reopen: true, saved_bundle: true, selected_stored_skill: 'mock-saved-image-brief', real_model_calls: 0 };
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '목표로 AI 기획', exact: true }).click();
  await page.getByRole('button', { name: '이전 기획 다시 열기', exact: true }).click();
  report.headingNarrow = await checkHeading();
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Planner narrow overflow');
  await page.screenshot({ path: path.join(out, 'planner-reopen-narrow-mock.png'), fullPage: true, animations: 'disabled' });
  if (report.narrowOverflow || errors.length) throw new Error('Browser errors or viewport overflow');
  fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
  process.stdout.write(JSON.stringify(report));
})().catch(async e => {
  process.stderr.write(e.stack); process.exitCode = 1;
  if (page) {
    await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true, animations: 'disabled' }).catch(() => {});
    const ledger = await page.evaluate(async () => (await (await fetch('/api/workbench/ledger')).json())).catch(() => null);
    fs.writeFileSync(path.join(out, 'failure-ledger.json'), JSON.stringify(ledger, null, 2));
  }
}).finally(async () => {
  if (fixture) { fixture.stdin.write('stop\n'); await new Promise(resolve => { fixture.once('exit', resolve); setTimeout(() => { if (fixture.exitCode === null) fixture.kill(); resolve(); }, 10000).unref(); }); }
  if (browser) await browser.close();
});
