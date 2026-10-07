'use strict';
// 옛 도트 사무실 화면이 어떤 경우에도 나오지 않는지 점검: node tools/dev/office_gone_check.cjs [--url http://127.0.0.1:8791/] [--port 8791]
// 연습용 서버(임시 회사, 가짜 실행기)를 직접 띄워서 Playwright(Edge)로 열어 본다. 끝나면 서버를 끈다. --url 을 주면 이미 떠 있는 연습용 서버를 쓴다 (끄지 않는다).
// 진짜 회사(8765)에는 아무것도 보내지 않는다. 확인하는 것:
//   1) 자바스크립트를 끄고 첫 화면을 열어도 사무실이 없고 모던 바탕만 있다
//   2) 스크립트가 실패해도(app.js 404 · 모든 스크립트 막힘) 사무실이 없다
//   3) 옛 개발용 주소(#view=office · #floor=2 · #demo=rest …)나 기억된 'office' 값으로 열어도 홈이 열린다 (진행판·이미지·영상 작업대 주소는 그대로 열린다)
//   4) 화면 소스·DOM·받아 온 파일 어디에도 office · layer-bg · layer-sprites · office-f1.png 흔적이 없고, 깨진 그림 주소도 없다
//   5) 얼굴·정지 그림은 그대로 그려진다 (직원 상태창 · 꾸미기)
// 결과 그림: output/office-gone/*.png
const { chromium } = (() => {
  for (const p of [process.env.PLAYWRIGHT_CORE, 'playwright-core', 'playwright']) {
    if (!p) continue;
    try { return require(p); } catch (_) { /* 다음 */ }
  }
  throw new Error('playwright-core를 찾지 못했습니다.');
})();
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..', '..');
const args = process.argv.slice(2);
const urlArg = args.includes('--url') ? args[args.indexOf('--url') + 1] : null;
const PORT = args.includes('--port') ? Number(args[args.indexOf('--port') + 1]) : 8791;
const out = path.join(root, 'output', 'office-gone');
fs.mkdirSync(out, { recursive: true });
const edge = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
if (!edge) throw new Error('Microsoft Edge를 찾지 못했습니다.');

const results = [];
const check = (name, ok, extra = {}) => {
  results.push({ name, ok });
  console.log(`${ok ? '  ✓' : '  ✗'} ${name}${ok ? '' : ' ' + JSON.stringify(extra)}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- 연습용 서버 띄우기 / 끄기
function startFixture() {
  return new Promise((resolve, reject) => {
    const child = spawn('python', ['tools/dev/workbench_fixture.py', '--port', String(PORT)], { cwd: root, stdio: ['pipe', 'pipe', 'pipe'] });
    let buf = '';
    let err = '';
    const timer = setTimeout(() => reject(new Error('연습용 서버가 60초 안에 뜨지 않았어요: ' + err)), 60000);
    child.stderr.on('data', (d) => { err += d; });
    child.stdout.on('data', (d) => {
      buf += d;
      if (buf.split('\n').some((l) => l.startsWith('{'))) { clearTimeout(timer); resolve({ child, url: `http://127.0.0.1:${PORT}/` }); }
    });
    child.on('exit', (code) => { clearTimeout(timer); reject(new Error('연습용 서버가 바로 꺼졌어요 ' + code + ' ' + err)); });
  });
}
async function stopFixture(fx) {
  if (!fx) return;
  fx.child.removeAllListeners('exit');
  try { fx.child.stdin.write('stop\n'); } catch (_) { /* 이미 닫힘 */ }
  await Promise.race([new Promise((r) => fx.child.once('exit', r)), sleep(15000)]);
  if (fx.child.exitCode === null) fx.child.kill();
}

// 사무실의 흔적이 될 만한 요소·이름 (DOM)
const OFFICE_SELECTOR = ['#layer-bg', '#layer-sprites', '#floors', '#devpanel', '#wall-clock', '#wall-notes', '#shelf-items', '#skill-notes', '#lounge-sign',
  '.sign', '.hotspot', '.dock', '.dock-btn', '.floors', '.floor-btn', '.actor', '.bubble', '.occluder', '.pouf', '.cat', '.warp-ring', '.wall-note', '.shelf-item', '.skill-note', '.hq',
  'img.bg', 'img[src*="office"]', 'img[src*="cat.png"]', 'canvas.actor'].join(', ');
const GONE_TEXT = ['office', 'layer-bg', 'layer-sprites', 'office-f1.png', 'scene.js', 'floors.json'];
const OFFICE_FILES = /\/(scene\.js|assets\/bg\/(office|floors)[^/]*|assets\/ui\/(cat|screen-[a-z]+|note-[a-z]+)\.png)(\?|$)/;
const BG = 'rgb(231, 233, 238)'; // --bd-bg

async function openPage(browser, { js = true, block = null, storage = null } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1536, height: 1024 }, javaScriptEnabled: js });
  const page = await ctx.newPage();
  page.problems = [];
  page.requested = [];
  page.bad = [];
  page.on('pageerror', (e) => page.problems.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) page.problems.push(m.type() + ': ' + m.text()); });
  page.on('request', (r) => page.requested.push(new URL(r.url()).pathname));
  page.on('response', (r) => { if (r.status() >= 400 && /\.(png|json|js|css|woff2|svg)$/.test(new URL(r.url()).pathname)) page.bad.push(`${r.status()} ${new URL(r.url()).pathname}`); });
  if (block) await page.route(block.pattern, (route) => (block.abort ? route.abort() : route.fulfill({ status: 404, body: 'not found' })));
  if (storage) await ctx.addInitScript((kv) => { try { for (const [k, v] of Object.entries(kv)) localStorage.setItem(k, v); } catch (_) { /* 무시 */ } }, storage);
  page.ctx = ctx;
  return page;
}

// 지금 화면에 사무실의 흔적이 있는가: { elements: [...], text: [...], files: [...] }
async function officeTraces(page) {
  const found = await page.evaluate(({ sel, gone }) => {
    const html = document.documentElement.outerHTML;
    return { elements: [...document.querySelectorAll(sel)].map((n) => n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') + (n.className && n.className.baseVal === undefined ? '.' + String(n.className).split(' ').join('.') : '')), text: gone.filter((t) => html.includes(t)) };
  }, { sel: OFFICE_SELECTOR, gone: GONE_TEXT });
  return { ...found, files: page.requested.filter((p) => OFFICE_FILES.test(p)) };
}
const clean = (t) => t.elements.length === 0 && t.text.length === 0 && t.files.length === 0;

async function stageLooksModern(page) {
  return page.evaluate(() => {
    const stage = document.getElementById('stage');
    const board = document.getElementById('layer-board');
    const shown = Boolean(board) && !board.hidden && getComputedStyle(board).display !== 'none' && getComputedStyle(board).visibility !== 'hidden';
    return { cls: stage.className, bg: getComputedStyle(stage).backgroundColor, boardShown: shown };
  });
}

(async () => {
  let fixture = null;
  let base = urlArg;
  if (!base) { console.log('연습용 서버를 띄우는 중…'); fixture = await startFixture(); base = fixture.url; }
  const browser = await chromium.launch({ executablePath: edge, headless: true });
  try {
    // ============================================================ 1. 자바스크립트를 끈 첫 화면
    {
      const page = await openPage(browser, { js: false });
      await page.goto(base);
      await sleep(600);
      const t = await officeTraces(page);
      check('자바스크립트 꺼짐: 사무실 요소·이름·그림 파일이 없다', clean(t), t);
      const s = await stageLooksModern(page);
      check('자바스크립트 꺼짐: 무대가 처음부터 모던 화면 바탕이다 (view-board, 회색 바탕, 흰 판)', s.cls.split(' ').includes('view-board') && s.bg === BG && s.boardShown, s);
      check('자바스크립트 꺼짐: 깨진 그림·파일 주소가 없다', page.bad.length === 0, { bad: page.bad });
      await page.screenshot({ path: path.join(out, 'nojs.png') });
      await page.ctx.close();
    }

    // ============================================================ 2. 스크립트가 실패해도
    for (const [name, block] of [
      ['app.js가 404', { pattern: '**/app.js', abort: false }],
      ['모든 스크립트가 막힘', { pattern: '**/*.js', abort: true }],
      ['stills.js와 looks.js가 404', { pattern: /\/(stills|looks)\.js$/, abort: false }],
    ]) {
      const page = await openPage(browser, { block });
      await page.goto(base);
      await sleep(800);
      const t = await officeTraces(page);
      check(`스크립트 실패(${name}): 사무실이 없다`, clean(t), t);
      const s = await stageLooksModern(page);
      check(`스크립트 실패(${name}): 모던 바탕이 그대로다`, s.cls.split(' ').includes('view-board') && s.bg === BG && s.boardShown, s);
      await page.screenshot({ path: path.join(out, `broken-${name.includes('app') ? 'app' : name.includes('모든') ? 'all' : 'stills'}.png`) });
      await page.ctx.close();
    }

    // ============================================================ 3. 옛 주소·기억된 값
    const OLD = [
      ['#view=office', null], ['#floor=2', null], ['#floor=2&demo=crowd', null], ['#demo=rest', null], ['#demo=work', null], ['#demo=blocked', null],
      ['#demo=call', null], ['#demo=warp', null], ['#demo=stop', null], ['#demo=bodies', null], ['#demo=bodieswork', null], ['#demo=crowdrest', null],
      ['', { 'studio.view': 'office' }], ['#view=office', { 'studio.view': 'office' }],
    ];
    for (const [hash, storage] of OLD) {
      const page = await openPage(browser, { storage });
      await page.goto(base + hash);
      await page.locator('.bd-nav').waitFor({ timeout: 30000 });
      await page.waitForFunction(() => typeof Data !== 'undefined' && Data.loaded, null, { timeout: 30000 });
      await sleep(300);
      const label = `${hash || '(주소 없음)'}${storage ? ' + 기억값 office' : ''}`;
      const t = await officeTraces(page);
      const home = await page.evaluate(() => { const h = document.querySelector('.bd-home'); return Boolean(h) && !h.hidden && getComputedStyle(h).display !== 'none'; });
      check(`옛 주소 ${label}: 홈이 열리고 사무실 흔적이 없다`, home && clean(t), { home, ...t });
      check(`옛 주소 ${label}: 페이지 오류·깨진 파일 없음`, page.problems.length === 0 && page.bad.length === 0, { problems: page.problems, bad: page.bad });
      if (hash === '#view=office' && !storage) await page.screenshot({ path: path.join(out, 'old-view-office.png') });
      await page.ctx.close();
    }
    // 새 화면 주소는 그대로 열린다
    for (const [hash, selector, label] of [
      ['#view=home', '.bd-home:not([hidden])', '홈'], ['#view=board', '.bd-page-board:not([hidden])', '진행판'], ['#view=media', '.bd-page-media:not([hidden])', '이미지·영상 작업대'],
      ['#view=board&boarddemo=states', '.bd-page-board:not([hidden])', '진행판 개발용 주소'], ['#view=board&demo=boardflip', '.bd-page-board:not([hidden])', '진행판 뒤집기 개발용 주소'],
    ]) {
      const page = await openPage(browser);
      await page.goto(base + hash);
      await page.locator(selector).waitFor({ timeout: 30000 });
      const t = await officeTraces(page);
      check(`새 화면 주소 ${hash}: ${label}이 열리고 사무실 흔적이 없다`, clean(t), t);
      check(`새 화면 주소 ${hash}: 페이지 오류·깨진 파일 없음`, page.problems.length === 0 && page.bad.length === 0, { problems: page.problems, bad: page.bad });
      await page.ctx.close();
    }
    {
      const page = await openPage(browser);
      await page.goto(base + '#view=workbench');
      await page.locator('#workbench-screen:not([hidden])').waitFor({ timeout: 30000 });
      check('#view=workbench: 옛 노드 편집기가 열리고 진행판 껍데기는 숨는다', (await page.locator('#stage').isHidden()) && clean(await officeTraces(page)));
      await page.ctx.close();
    }

    // ============================================================ 4. 평소 화면: 왼쪽 메뉴·F2·받아 온 파일
    {
      const page = await openPage(browser);
      await page.goto(base);
      await page.waitForFunction(() => typeof Data !== 'undefined' && Data.loaded, null, { timeout: 30000 });
      await page.locator('.bd-nav').waitFor();
      const menu = await page.locator('.bd-nav-btn').allInnerTexts();
      check('왼쪽 메뉴에 "사무실"이 없다', !menu.some((m) => m.includes('사무실')), { menu });
      await page.keyboard.press('F2');
      await sleep(200);
      check('F2를 눌러도 개발 패널·레이어 표시가 생기지 않는다', (await page.locator('#devpanel').count()) === 0 && !(await page.locator('#stage.debug').count()));
      for (const key of ['team', 'skills', 'mcp', 'schedules', 'diary', 'trophies', 'meeting', 'inbox']) {
        await page.locator(`.bd-nav-btn[data-action="${key}"]`).click();
        await sleep(250);
        await page.keyboard.press('Escape');
      }
      const t = await officeTraces(page);
      check('메뉴를 모두 눌러 본 뒤에도 사무실 흔적이 없다', clean(t), t);
      const reqs = [...new Set(page.requested)];
      check('받아 온 파일에 사무실 스크립트·그림이 없다', !reqs.some((p) => OFFICE_FILES.test(p)), { files: reqs.filter((p) => OFFICE_FILES.test(p)) });
      check('평소 화면: 페이지 오류·깨진 파일 없음', page.problems.length === 0 && page.bad.length === 0, { problems: page.problems, bad: page.bad });
      await page.ctx.close();
    }

    // ============================================================ 5. 얼굴·정지 그림
    {
      const page = await openPage(browser);
      await page.goto(base + '#open=sheet');
      await page.locator('.pop .face, .pop canvas.sprite-still, .pop [class*="face"]').first().waitFor({ timeout: 30000 });
      await sleep(800);
      const face = await page.evaluate(() => {
        const el = document.querySelector('.pop .face.sol, .pop .face');
        if (!el) return null;
        const cs = getComputedStyle(el);
        return { image: cs.backgroundImage, w: el.getBoundingClientRect().width, h: el.getBoundingClientRect().height, visibility: cs.visibility };
      });
      check('직원 상태창: 얼굴 그림이 보인다', Boolean(face) && face.image !== 'none' && face.w > 20 && face.h > 20 && face.visibility === 'visible', { face });
      await page.ctx.close();

      const p2 = await openPage(browser);
      await p2.goto(base + '#open=customize');
      await p2.locator('.pop canvas.sprite-still').waitFor({ timeout: 30000 });
      await sleep(1000);
      const still = await p2.evaluate(() => {
        const c = document.querySelector('.pop canvas.sprite-still');
        if (!c || !c.width || !c.height) return { w: c ? c.width : 0, h: c ? c.height : 0, painted: false };
        const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
        let painted = 0;
        for (let i = 3; i < data.length; i += 4) if (data[i] > 0) painted++;
        return { w: c.width, h: c.height, painted: painted > 500 };
      });
      check('꾸미기: 서 있는 정지 그림(캔버스)이 그려져 있다', still.w > 50 && still.h > 100 && still.painted, still);
      check('꾸미기: 페이지 오류·깨진 파일 없음', p2.problems.length === 0 && p2.bad.length === 0, { problems: p2.problems, bad: p2.bad });
      await p2.screenshot({ path: path.join(out, 'customize.png') });
      await p2.ctx.close();
    }
  } finally {
    await browser.close();
    await stopFixture(fixture);
  }
  const failed = results.filter((r) => !r.ok);
  fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify({ total: results.length, failed: failed.map((f) => f.name), results }, null, 2));
  console.log(failed.length ? `\n사무실 점검 실패 ${failed.length}개 / ${results.length}개` : `\n사무실이 안 나오는지 점검 통과 (${results.length}개)`);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error(e.message); process.exit(1); });
