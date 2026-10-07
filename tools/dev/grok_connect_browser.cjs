'use strict';
// Grok 그림·영상 연결 창 확인: node tools/dev/grok_connect_browser.cjs [주소=http://127.0.0.1:8794/]
// 연습용 회사(가짜 실행기)에서만 쓴다. 연결 창을 열고 → 허용 → 연결 → 다시 열기 → 끊기까지 눌러 보고, 작업대가 그림·영상만 켜는지 본다.
// Grok에 그림·영상을 실제로 요청하지 않는다 (로그인 확인 'grok models'만 서버가 한다).
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const fs = require('fs');
const path = require('path');
const url = (process.argv[2] || 'http://127.0.0.1:8794/') + '#view=workbench';
const out = path.resolve('output/grok-official-browser');
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  const page = await browser.newPage({ viewport: { width: 1585, height: 1080 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  const report = { url, steps: [], errors };
  const step = (name, ok, extra = {}) => { report.steps.push({ name, ok, ...extra }); if (!ok) throw new Error('실패: ' + name + ' ' + JSON.stringify(extra)); };
  const capability = async (id) => page.evaluate(async (key) => {
    const catalog = await (await fetch('/api/workbench')).json();
    const node = (catalog.nodes || []).find((n) => n.id === 'builtin-' + key);
    return node ? node.capability : null;
  }, id);
  try {
    await page.goto(url);
    await page.getByRole('button', { name: 'Grok 그림·영상 연결' }).waitFor({ timeout: 30000 });
    let image = await capability('grok_image');
    step('연결 전에는 그림 노드가 꺼져 있다', image && image.enabled === false, { image });
    await page.getByRole('button', { name: 'Grok 그림·영상 연결' }).click();
    const dialog = page.locator('dialog.wb-dialog[open]');
    await dialog.waitFor();
    await dialog.getByText('아직 연결되지 않았어요').waitFor();
    const found = await dialog.locator('.wb-hint').first().innerText();
    step('찾은 프로그램이 보인다', /grok(\.exe)?/i.test(found), { found });
    const connect = dialog.getByRole('button', { name: '연결하기' });
    step('허용 전에는 연결 단추가 꺼져 있다', await connect.isDisabled());
    await page.screenshot({ path: path.join(out, 'connect-1-before.png') });
    await dialog.locator('input[name="grok-connect-confirm"]').check();
    step('허용하면 연결 단추가 켜진다', !(await connect.isDisabled()));
    await connect.click();
    await page.locator('.wb-message').filter({ hasText: '연결을 켰어요' }).waitFor({ timeout: 60000 });
    image = await capability('grok_image');
    const video = await capability('grok_video');
    const research = await capability('grok_research');
    step('연결 뒤 그림·영상만 켜지고 조사는 꺼져 있다', image.enabled && video.enabled && !research.enabled, { image, video, research });
    await page.getByRole('button', { name: 'Grok 그림·영상 연결' }).click();
    await dialog.getByText('연결됨').waitFor();
    await page.screenshot({ path: path.join(out, 'connect-2-connected.png') });
    await dialog.getByRole('button', { name: '연결 끊기' }).click();
    await page.locator('.wb-message').filter({ hasText: '껐어요' }).waitFor({ timeout: 30000 });
    image = await capability('grok_image');
    step('끊으면 다시 꺼진다', image.enabled === false, { image });
    step('페이지 오류가 없다', errors.length === 0, { errors });
  } finally {
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
  console.log(JSON.stringify(report, null, 2));
})().catch((e) => { console.error(e.message); process.exit(1); });
