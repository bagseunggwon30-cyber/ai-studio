'use strict';
// 결재 대기 취소 점검: node tools/dev/cancel_waiting_browser.cjs [--shots] [--port 8811]
// 연습용 서버 셋을 직접 띄워 Playwright(Edge)로 눌러 본다 (tools/dev/cancel_waiting_fixture.py: 임시 회사 + 가짜 실행기, 진짜 직원·Grok·진짜 회사(8765)는 안 부른다). 끝나면 서버를 끈다.
//   A(--port, 기본 8811) = 진짜 회사에 쌓인 모양 그대로 Grok 결재 대기 9장 → 결재함 9통 · 한 통 취소 · 모두 취소 · 창 크기 3가지
//   B(그다음 포트 8812)  = 종류가 섞인 결재 대기 10장 → 그룹별 취소(한 그룹만), 결재 창·보고서·회의실·스킬·도구 창의 [결재 취소], 업무 카드 취소, 나중에 보기, 정지 중 잠금, 휴대폰
//   C(그다음 포트 8813)  = 진짜 결재함 모양: Core Courier Grok 9장 + Studio Docs 기획 1장 → 그룹 단추 둘, 한 그룹만 취소해도 다른 그룹은 그대로
// 포트는 8811~8830 안에서만 쓴다. --shots 를 주면 docs/design/captures/modern-inbox-cancel.png(그룹 하나) · modern-inbox-cancel-groups.png(그룹 둘)를 남긴다.
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
const SHOTS = args.includes('--shots');
const PORT = args.includes('--port') ? Number(args[args.indexOf('--port') + 1]) : 8811;
if (PORT < 8811 || PORT + 2 > 8830) throw new Error('포트는 8811~8830 안에서만 쓸 수 있어요.');
const capDir = path.join(root, 'docs', 'design', 'captures');
const edge = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
if (!edge) throw new Error('Microsoft Edge를 찾지 못했습니다.');

let passed = 0;
const step = (name, ok, extra = {}) => {
  if (!ok) { console.log(`  ✗ ${name} ${JSON.stringify(extra)}`); throw new Error('실패: ' + name + ' ' + JSON.stringify(extra)); }
  passed += 1;
  console.log(`  ✓ ${name}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// ---- 연습용 서버 띄우기 / 끄기
function startFixture(port, mode) {
  return new Promise((resolve, reject) => {
    const child = spawn('python', ['-X', 'utf8', 'tools/dev/cancel_waiting_fixture.py', '--port', String(port), '--mode', mode], { cwd: root, stdio: ['pipe', 'pipe', 'pipe'] });
    let buf = '';
    let err = '';
    const timer = setTimeout(() => reject(new Error('연습용 서버가 90초 안에 뜨지 않았어요: ' + err)), 90000);
    child.stderr.on('data', (d) => { err += d; });
    child.stdout.on('data', (d) => {
      buf += d;
      const line = buf.split('\n').find((l) => l.startsWith('{'));
      if (line) { clearTimeout(timer); resolve({ child, url: `http://127.0.0.1:${port}/`, info: JSON.parse(line) }); }
    });
    child.on('exit', (code) => { clearTimeout(timer); reject(new Error('연습용 서버가 바로 꺼졌어요 ' + code + ' ' + err)); });
  });
}
async function stopFixture(fx) {
  if (!fx) return;
  fx.child.removeAllListeners('exit');
  try { fx.child.stdin.write('stop\n'); } catch (_) { /* 이미 닫힘 */ }
  await Promise.race([new Promise((r) => fx.child.once('exit', r)), sleep(20000)]);
  if (fx.child.exitCode === null) fx.child.kill();
}

// ---- 페이지 도구
async function newPage(browser, base, { width = 1536, height = 1024 } = {}) {
  const page = await browser.newPage({ viewport: { width, height } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) errors.push(m.type() + ': ' + m.text()); });
  const posts = [];
  const hosts = new Set();
  page.on('request', (r) => {
    const u = new URL(r.url());
    hosts.add(u.host);
    if (r.method() === 'POST') posts.push({ path: u.pathname, body: r.postData() });
  });
  page.errors = errors;
  page.posts = posts;
  page.hosts = hosts;
  page.countPost = (re) => posts.filter((x) => re.test(x.path)).length;
  page.lastPost = (re) => { const l = posts.filter((x) => re.test(x.path)); return l.length ? JSON.parse(l[l.length - 1].body || 'null') : null; };
  page.base = base;
  return page;
}
async function load(page) {
  await page.goto(page.base);
  await page.waitForFunction(() => typeof Data !== 'undefined' && Data.loaded && Data.get().tasks.length > 0, null, { timeout: 30000 });
  await page.waitForFunction(() => document.querySelector('#stage.view-board') && document.querySelector('#popup-host'), null, { timeout: 30000 });
}
async function openInbox(page) {
  await page.evaluate(() => Popups.inbox());
  await page.locator('.pop.ib').waitFor({ timeout: 10000 });
}
const text = async (page, sel) => (await page.locator(sel).first().innerText()).replace(/\s+/g, ' ').trim();
const texts = async (page, sel) => (await page.locator(sel).allInnerTexts()).map((t) => t.replace(/\s+/g, ' ').trim());
const statuses = (page) => page.evaluate(async () => Object.fromEntries((await (await fetch('/api/state', { cache: 'no-store' })).json()).tasks.map((t) => [t.id, t.status])));
const letterCount = (page) => page.locator('.pop.ib .letter').count();
async function until(fn, ms = 10000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (await fn()) return true; await sleep(100); }
  return false;
}
const dialogTitle = (page) => text(page, '.pop.dialog h2');
const dialogBody = async (page) => (await page.locator('.pop.dialog p').first().innerText());
const dialogBtn = (page, name) => page.locator('.pop.dialog .row-btns .btn', { hasText: name });
async function waitDialog(page, title) {
  await page.locator('.pop.dialog').waitFor({ timeout: 8000 });
  return title ? (await dialogTitle(page)) === title : true;
}
async function noticeText(page) { return text(page, '#notice-text'); }
async function waitNotice(page, part) {
  return until(async () => { const hidden = await page.locator('#notice').evaluate((n) => n.classList.contains('hidden')); return !hidden && (await noticeText(page)).includes(part); }, 8000);
}
async function resize(page, w, h) { await page.setViewportSize({ width: w, height: h }); await sleep(500); }
// 창이 보이는 화면 안에 들어 있고 문서에 가로·세로 넘침이 없는지
async function fit(page, sel) {
  return page.evaluate((s) => {
    const pop = document.querySelector(s);
    const r = pop.getBoundingClientRect();
    const de = document.documentElement;
    const out = [...pop.querySelectorAll('.letter, .letter .btn, .ib-foot .btn, .ib-sign, .x-btn, .row-btns .btn, .ap-actions .btn, .rp-actions .btn, .mt-actions .btn')]
      .filter((n) => { const b = n.getBoundingClientRect(); return b.width > 0 && (b.right > r.right + 1 || b.left < r.left - 1); }).length;
    return { vw: innerWidth, vh: innerHeight, inside: r.left >= 0 && r.top >= 0 && r.right <= innerWidth + 0.5 && r.bottom <= innerHeight + 0.5,
      docX: de.scrollWidth - innerWidth, docY: de.scrollHeight - innerHeight, out, rect: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)] };
  }, sel);
}

// 결재함 캡처 (알림 띠 치우고 마우스 치우고 맨 위로)
async function shotInbox(page, file) {
  fs.mkdirSync(capDir, { recursive: true });
  await page.locator('.ib-tray').evaluate((n) => { n.scrollTop = 0; });
  await page.evaluate(() => document.querySelector('#notice') && document.querySelector('#notice').classList.add('hidden'));
  await page.mouse.move(5, 5);
  await sleep(400);
  await page.screenshot({ path: path.join(capDir, file) });
}
// 창 크기 세 가지(1536×1024 · 1280×720 · 1864×990)에서 모두 넘치지 않는지: 어긋난 크기 목록(비어 있으면 통과)
async function fitAll(page, sel, needInside = true) {
  const bad = [];
  for (const [w, h] of [[1536, 1024], [1280, 720], [1864, 990]]) {
    await resize(page, w, h);
    const f = await fit(page, sel);
    if (!((!needInside || f.inside) && f.docX <= 0 && f.docY <= 0 && f.out === 0)) bad.push({ w, h, ...f });
  }
  await resize(page, 1536, 1024);
  return bad;
}

(async () => {
  let fxA = null;
  let fxB = null;
  let fxC = null;
  const browser = await chromium.launch({ executablePath: edge, headless: true });
  try {
    console.log('연습용 서버를 띄우는 중…');
    [fxA, fxB, fxC] = await Promise.all([startFixture(PORT, 'grok'), startFixture(PORT + 1, 'mixed'), startFixture(PORT + 2, 'real')]);
    step('연습용 서버 셋: 결재 대기 Grok 9장 · 종류가 섞인 10장 · 진짜 결재함 모양 10장 (모두 임시 회사, 진짜 모델 호출 0)',
      fxA.info.waiting.length === 9 && fxB.info.waiting.length === 10 && fxC.info.waiting.length === 10
      && [fxA, fxB, fxC].every((f) => f.info.real_model_calls === 0));
    const pagesAll = [];

    // ======================================================================== A. 결재함 9통
    const A = await newPage(browser, fxA.url);
    pagesAll.push(A);
    await load(A);
    const idsA = fxA.info.waiting;
    step('처음 상태: 서버에 결재 대기 9건', Object.values(await statuses(A)).filter((s) => s === 'awaiting_approval').length === 9);
    await openInbox(A);
    await A.locator('.pop.ib .letter').nth(8).waitFor({ timeout: 10000 });
    step('결재함 제목 "결재함 9" · 편지 9통이 모두 있다 · "그 밖에 N통" 안내는 없다',
      (await text(A, '.ib-sign')) === '결재함 9' && (await letterCount(A)) === 9 && (await A.locator('.ib-more').count()) === 0);
    step('왼쪽 위 숫자(결재함 배지)도 9', (await text(A, '#hud-inbox')) === '9' || (await texts(A, '.bd-nav-btn')).some((t) => /결재함\s*9$/.test(t)));
    const tray = await A.locator('.ib-tray').evaluate((n) => ({ sh: n.scrollHeight, ch: n.clientHeight, oy: getComputedStyle(n).overflowY, tab: n.tabIndex, role: n.getAttribute('role') }));
    step('편지 칸은 스크롤되는 칸이다 (내용이 칸보다 길고, 키보드로 초점을 받고, 이름표가 있다)', tray.sh > tray.ch && tray.oy === 'auto' && tray.tab === 0 && tray.role === 'region', tray);
    // 9통 모두 칸 안에서 보이는 자리까지 올 수 있다 (스크롤)
    const reach = [];
    for (let i = 0; i < 9; i += 1) {
      const letter = A.locator('.pop.ib .letter').nth(i);
      await letter.scrollIntoViewIfNeeded();
      const lb = await letter.boundingBox();
      const tb = await A.locator('.ib-tray').boundingBox();
      reach.push(lb.y >= tb.y - 2 && lb.y + lb.height <= tb.y + tb.height + 2);
    }
    step('9통 모두 스크롤하면 칸 안에 온전히 보인다', reach.every(Boolean), reach);
    step('마지막(아홉 번째) 편지의 [열기]가 눌린다 → 보고서 창에 [결재 취소]가 있다, Esc로 닫으면 결재함이 그대로',
      await (async () => {
        await A.locator('.pop.ib .letter').nth(8).locator('.btn', { hasText: '열기' }).click();
        await A.locator('.pop.rp').waitFor({ timeout: 8000 });
        const has = (await A.locator('.pop.rp .rp-actions .btn', { hasText: '결재 취소' }).count()) === 1;
        await A.keyboard.press('Escape');
        await A.locator('.pop.ib').waitFor({ timeout: 8000 });
        return has && (await letterCount(A)) === 9;
      })());
    const titles = await texts(A, '.pop.ib .letter .letter-title');
    const cancelLabels = await A.locator('.pop.ib .letter .btn.ib-cancel').evaluateAll((els) => els.map((e) => e.getAttribute('aria-label')));
    step('편지마다 작은 [취소]가 있고 접근성 이름은 "<제목> 취소"', cancelLabels.length === 9 && cancelLabels.every((l, i) => l === `${titles[i]} 취소`), cancelLabels);
    step('그룹이 하나뿐(프로젝트 하나·보고서 9장)이라 아래에 [모두 취소 (9)] 하나만 있다 (그룹 이름 없이)',
      eq(await texts(A, '.ib-foot .ib-cancel-group'), ['모두 취소 (9)']) && (await A.locator('.ib-cancel-all').count()) === 0);
    // 창 크기 세 가지: 창이 화면 안, 문서 넘침 0, 단추가 창 밖으로 안 나감
    for (const [w, h] of [[1536, 1024], [1280, 720], [1864, 990]]) {
      await resize(A, w, h);
      const f = await fit(A, '.pop.ib');
      const foot = await A.locator('.ib-foot .ib-cancel-group').first().boundingBox();
      step(`결재함 9통 · ${w}×${h}: 창이 화면 안, 문서 가로·세로 넘침 없음, [모두 취소]가 보인다`,
        f.inside && f.docX <= 0 && f.docY <= 0 && f.out === 0 && foot && foot.y + foot.height <= h && foot.x + foot.width <= w, { ...f, foot });
    }
    await resize(A, 1536, 1024);
    if (SHOTS) await shotInbox(A, 'modern-inbox-cancel.png');

    // ---- 한 통 취소: '아니요'면 아무것도 안 바뀐다
    const firstTitle = titles[0];
    await A.locator('.pop.ib .letter').nth(0).locator('.btn.ib-cancel').click();
    step('[취소]를 누르면 확인 창이 뜬다: 제목·작업 이름·되돌릴 수 없고 결과 파일은 지우지 않는다는 안내',
      await waitDialog(A, '결재 대기 중인 작업을 취소할까요?')
      && (await dialogBody(A)).includes(firstTitle) && (await dialogBody(A)).includes('취소하면 작업이 끝나고 되돌릴 수 없어요. 만들어진 결과 파일은 지우지 않아요.'));
    step('확인 창 단추는 [아니요] [취소하기]', eq(await texts(A, '.pop.dialog .row-btns .btn'), ['아니요', '취소하기']));
    await dialogBtn(A, '아니요').click();
    await A.locator('.pop.ib').waitFor({ timeout: 5000 });
    await sleep(600);
    step("'아니요'면 아무것도 안 바뀐다: 서버로 보낸 취소 0번 · 편지 9통 · 서버 결재 대기 9건",
      A.countPost(/\/cancel/) === 0 && (await letterCount(A)) === 9 && Object.values(await statuses(A)).filter((s) => s === 'awaiting_approval').length === 9);
    // 맨 아래 편지를 스크롤해서 취소: 한 통씩 연달아 취소할 때 스크롤 자리가 맨 위로 튀지 않는다
    await A.locator('.pop.ib .letter').nth(8).scrollIntoViewIfNeeded();
    const scrollBefore = await A.locator('.ib-tray').evaluate((n) => n.scrollTop);
    const lastId = idsA[8];
    await A.locator('.pop.ib .letter').nth(8).locator('.btn.ib-cancel').click();
    await waitDialog(A);
    await dialogBtn(A, '취소하기').click();
    step('[취소하기] → 그 한 건만 서버로 취소가 간다 (경로·번호가 맞다)', await until(() => A.countPost(/\/api\/tasks\/T\d+\/cancel$/) === 1) && A.posts.at(-1).path === `/api/tasks/${lastId}/cancel`);
    step('편지가 사라진다 (8통) · 제목 "결재함 8" · 서버 상태 cancelled · 알림 "취소했어요"',
      await until(async () => (await letterCount(A)) === 8) && (await text(A, '.ib-sign')) === '결재함 8' && (await statuses(A))[lastId] === 'cancelled' && await waitNotice(A, '취소했어요'));
    const scrollAfter = await A.locator('.ib-tray').evaluate((n) => n.scrollTop);
    step('다시 그려도 스크롤 자리를 지킨다 (맨 위로 튀지 않는다)', scrollBefore > 0 && scrollAfter > 0, { scrollBefore, scrollAfter });
    step('결재함 배지가 8로 줄었다', (await text(A, '#hud-inbox')) === '8' || (await texts(A, '.bd-nav-btn')).some((t) => /결재함\s*8$/.test(t)));

    // ---- 모두 취소
    await A.locator('.ib-foot .ib-cancel-group').click();
    const body = await dialogBody(A);
    const lines = body.split('\n').map((l) => l.trim()).filter(Boolean);
    step('[모두 취소 (8)] 확인 창: 제목 "보고서 8건을 모두 취소할까요?" · 앞 5건 제목(번호 포함) · "외 3건" · 되돌릴 수 없고 결과 파일은 지우지 않는다는 안내',
      (await waitDialog(A, '보고서 8건을 모두 취소할까요?')) && lines.filter((l) => /^· T\d{4} Grok (image|video)$/.test(l)).length === 5
      && lines.includes('외 3건') && lines.at(-1) === '취소하면 되돌릴 수 없고 결과 파일은 지우지 않아요.', lines);
    step('확인 창 단추: [아니요] [8건 모두 취소]', eq(await texts(A, '.pop.dialog .row-btns .btn'), ['아니요', '8건 모두 취소']));
    await dialogBtn(A, '아니요').click();
    await A.locator('.pop.ib').waitFor({ timeout: 5000 });
    await sleep(500);
    step("'아니요'면 아무것도 안 바뀐다: 묶음 취소 요청 0번 · 편지 8통", A.countPost(/cancel-waiting/) === 0 && (await letterCount(A)) === 8);
    await A.locator('.ib-foot .ib-cancel-group').click();
    await waitDialog(A);
    await dialogBtn(A, '8건 모두 취소').click();
    step('[8건 모두 취소] → 묶음 취소 요청이 한 번, 남은 8건의 번호가 모두 들어 있다',
      await until(() => A.countPost(/cancel-waiting/) === 1) && eq([...A.lastPost(/cancel-waiting/).ids].sort(), idsA.slice(0, 8).sort()), A.lastPost(/cancel-waiting/));
    step('결재함이 비었다: "결재할 게 없어요" · [모두 취소] 단추가 없다 · 제목 "결재함 0" · 알림 "8건을 모두 취소했어요"',
      await until(async () => (await letterCount(A)) === 0)
      && (await text(A, '.ib-empty')).includes('결재할 게 없어요') && (await A.locator('.ib-cancel-group').count()) === 0
      && (await text(A, '.ib-sign')) === '결재함 0' && await waitNotice(A, '8건을 모두 취소했어요'));
    const afterAll = await statuses(A);
    step('서버 쪽도 9건 모두 cancelled · 결재 대기 0건', Object.values(afterAll).filter((s) => s === 'cancelled').length === 9 && Object.values(afterAll).filter((s) => s === 'awaiting_approval').length === 0, afterAll);
    step('결재함 배지가 사라졌다 (0건)', await until(async () => (await A.locator('#hud-inbox').evaluate((n) => n.hidden || n.textContent === '0')) === true));
    step('A 화면: 콘솔 오류·경고 0 · 이 연습용 서버 밖으로 나간 요청 0', A.errors.length === 0 && [...A.hosts].every((h) => h === `127.0.0.1:${PORT}`), { errors: A.errors, hosts: [...A.hosts] });

    // ======================================================================== C. 진짜 결재함 모양 (그룹 둘)
    const C = await newPage(browser, fxC.url);
    pagesAll.push(C);
    await load(C);
    const grokC = fxC.info.waiting.slice(0, 9);
    const planC = fxC.info.waiting[9];
    await openInbox(C);
    await C.locator('.pop.ib .letter').nth(9).waitFor({ timeout: 10000 });
    step('C 결재함 10통 (Core Courier Grok 보고서 9 + Studio Docs 기획 1), 편지에 프로젝트 이름이 보인다',
      (await letterCount(C)) === 10 && (await text(C, '.ib-sign')) === '결재함 10'
      && (await texts(C, '.pop.ib .letter .letter-proj')).filter((t) => t === 'Core Courier').length === 9 && (await texts(C, '.pop.ib .letter .letter-proj')).includes('Studio Docs'));
    const cLabels = await texts(C, '.ib-foot .ib-cancel-group');
    step('그룹별 단추 둘: "Core Courier 보고서 모두 취소 (9)" · "Studio Docs 기획 회의 모두 취소 (1)" · 전부 한꺼번에 지우는 단추는 없다',
      eq(cLabels, ['Core Courier 보고서 모두 취소 (9)', 'Studio Docs 기획 회의 모두 취소 (1)']) && (await C.locator('.ib-cancel-all').count()) === 0
      && !(await C.locator('.pop.ib').innerText()).includes('전부'), cLabels);
    { const bad = await fitAll(C, '.pop.ib'); step('그룹 단추가 둘인 결재함: 세 가지 창 크기 모두 화면 안, 문서 넘침 없음, 단추가 창 밖으로 안 나감', bad.length === 0, bad); }
    if (SHOTS) await shotInbox(C, 'modern-inbox-cancel-groups.png');
    await C.locator('.ib-foot .ib-cancel-group', { hasText: 'Core Courier 보고서' }).click();
    const cLines = (await dialogBody(C)).split('\n').map((l) => l.trim()).filter(Boolean);
    step('Grok 그룹 확인 창: 제목 "Core Courier 보고서 9건을 모두 취소할까요?" · 그 그룹의 앞 5건 · "외 4건" · 되돌릴 수 없고 결과 파일은 지우지 않는다는 안내',
      (await waitDialog(C, 'Core Courier 보고서 9건을 모두 취소할까요?')) && cLines.filter((l) => /^· T\d{4} Grok (image|video)$/.test(l)).length === 5
      && cLines.includes('외 4건') && cLines.at(-1) === '취소하면 되돌릴 수 없고 결과 파일은 지우지 않아요.' && !cLines.some((l) => l.includes('동네 서점')), cLines);
    await dialogBtn(C, '아니요').click();
    await C.locator('.pop.ib').waitFor({ timeout: 5000 });
    await sleep(500);
    step("'아니요'면 아무것도 안 바뀐다: 묶음 취소 요청 0번 · 편지 10통", C.countPost(/cancel-waiting/) === 0 && (await letterCount(C)) === 10);
    await C.locator('.ib-foot .ib-cancel-group', { hasText: 'Core Courier 보고서' }).click();
    await waitDialog(C);
    await dialogBtn(C, '9건 모두 취소').click();
    step('[9건 모두 취소] → 묶음 취소 요청이 한 번, 보낸 번호는 Grok 9건뿐이다 (Studio Docs 기획 번호는 없다)',
      await until(() => C.countPost(/cancel-waiting/) === 1) && eq([...C.lastPost(/cancel-waiting/).ids].sort(), [...grokC].sort()) && !C.lastPost(/cancel-waiting/).ids.includes(planC), C.lastPost(/cancel-waiting/));
    const afterC = await until(async () => (await letterCount(C)) === 1) && await until(async () => Object.values(await statuses(C)).filter((x) => x === 'cancelled').length === 9);
    const stC = await statuses(C);
    step('다른 그룹은 그대로: Studio Docs 기획 카드는 결재 대기로 남고 Grok 9건만 서버에서 cancelled',
      afterC && stC[planC] === 'awaiting_approval' && grokC.every((id) => stC[id] === 'cancelled'), stC);
    step('결재함에는 그 기획 한 통만 남고, 그룹이 하나로 줄어 단추는 [모두 취소 (1)] · 알림 "9건을 모두 취소했어요"',
      (await text(C, '.ib-sign')) === '결재함 1' && (await text(C, '.pop.ib .letter .letter-title')).includes('동네 서점 소개')
      && eq(await texts(C, '.ib-foot .ib-cancel-group'), ['모두 취소 (1)']) && await waitNotice(C, '9건을 모두 취소했어요'));
    step('C 화면: 콘솔 오류·경고 0 · 이 연습용 서버 밖으로 나간 요청 0', C.errors.length === 0 && [...C.hosts].every((h) => h === `127.0.0.1:${PORT + 2}`), { errors: C.errors, hosts: [...C.hosts] });

    // ======================================================================== B. 종류별 창
    const B = await newPage(browser, fxB.url);
    pagesAll.push(B);
    await load(B);
    const [bBuild, bPlan, bBuild2, bGrokA, bGrokB, bResearch, bSkill, bTool, bHireA, bHireB] = fxB.info.waiting;
    await openInbox(B);
    await B.locator('.pop.ib .letter').nth(9).waitFor({ timeout: 10000 });
    step('B 결재함 10통', (await letterCount(B)) === 10 && (await text(B, '.ib-sign')) === '결재함 10');

    // 그룹별 취소: 프로젝트(하나뿐이라 이름은 안 붙음) + 종류마다 단추 하나, 전부 취소 단추는 없다
    const bLabels = await texts(B, '.ib-foot .ib-cancel-group');
    step('그룹별 단추 6개: 개발 2 · 기획 회의 1 · 보고서 3 · 스킬 공부 1 · MCP 만들기 1 · 새 직원 2 (개발 카드는 검사 결과가 아니라 종류 이름으로 묶는다) · 전부 취소 단추는 없다',
      eq(bLabels, ['개발 모두 취소 (2)', '기획 회의 모두 취소 (1)', '보고서 모두 취소 (3)', '스킬 공부 모두 취소 (1)', 'MCP 만들기 모두 취소 (1)', '새 직원 모두 취소 (2)'])
      && !(await B.locator('.pop.ib').innerText()).includes('전부'), bLabels);
    { const bad = await fitAll(B, '.pop.ib'); step('그룹 단추가 여섯(여러 줄)인 결재함: 세 가지 창 크기 모두 화면 안, 문서 넘침 없음, 단추가 창 밖으로 안 나감', bad.length === 0, bad); }
    await B.locator('.ib-foot .ib-cancel-group', { hasText: '새 직원 모두 취소 (2)' }).click();
    const hireLines = (await dialogBody(B)).split('\n').map((l) => l.trim()).filter(Boolean);
    step('새 직원 그룹 확인 창: 제목 "새 직원 2건을 모두 취소할까요?" · 그 그룹의 두 건만 · "외 N건" 줄 없음 · 되돌릴 수 없고 결과 파일은 지우지 않는다는 안내',
      (await waitDialog(B, '새 직원 2건을 모두 취소할까요?')) && hireLines.filter((l) => /^· T\d{4} 새 직원 시험 [12]$/.test(l)).length === 2
      && !hireLines.some((l) => l.startsWith('외 ')) && hireLines.at(-1) === '취소하면 되돌릴 수 없고 결과 파일은 지우지 않아요.', hireLines);
    await dialogBtn(B, '아니요').click();
    await B.locator('.pop.ib').waitFor({ timeout: 5000 });
    await sleep(500);
    step("'아니요'면 아무것도 안 바뀐다: 묶음 취소 요청 0번 · 편지 10통", B.countPost(/cancel-waiting/) === 0 && (await letterCount(B)) === 10);
    await B.locator('.ib-foot .ib-cancel-group', { hasText: '새 직원 모두 취소 (2)' }).click();
    await waitDialog(B);
    await dialogBtn(B, '2건 모두 취소').click();
    step('그 그룹의 두 건만 서버로 간다 (보낸 번호가 새 직원 둘뿐)',
      await until(() => B.countPost(/cancel-waiting/) === 1) && eq([...B.lastPost(/cancel-waiting/).ids].sort(), [bHireA, bHireB].sort()), B.lastPost(/cancel-waiting/));
    const stB1 = await (async () => { await until(async () => (await statuses(B))[bHireA] === 'cancelled' && (await statuses(B))[bHireB] === 'cancelled'); return statuses(B); })();
    step('다른 그룹 카드 8장은 그대로 결재 대기, 새 직원 둘만 cancelled · 결재함 8통 · 단추는 다섯 그룹',
      [bBuild, bPlan, bBuild2, bGrokA, bGrokB, bResearch, bSkill, bTool].every((id) => stB1[id] === 'awaiting_approval')
      && stB1[bHireA] === 'cancelled' && stB1[bHireB] === 'cancelled'
      && await until(async () => (await letterCount(B)) === 8) && (await text(B, '.ib-sign')) === '결재함 8'
      && eq(await texts(B, '.ib-foot .ib-cancel-group'), ['개발 모두 취소 (2)', '기획 회의 모두 취소 (1)', '보고서 모두 취소 (3)', '스킬 공부 모두 취소 (1)', 'MCP 만들기 모두 취소 (1)']), stB1);

    // 정지 중에는 못 누른다 (기존 needsRun 규칙)
    await B.evaluate(() => Data.setStopped(true));
    step('긴급 정지 중에는 [취소]와 그룹별 [모두 취소]가 모두 잠긴다 ("정지 중이에요")',
      await until(async () => (await B.locator('.pop.ib .letter .btn.ib-cancel:disabled').count()) === 8)
      && (await B.locator('.ib-cancel-group:disabled').count()) === 5 && (await B.locator('.ib-cancel-group').first().getAttribute('title')) === '정지 중이에요');
    await B.evaluate(() => Data.setStopped(false));
    step('다시 시작하면 풀린다', await until(async () => (await B.locator('.pop.ib .letter .btn.ib-cancel:enabled').count()) === 8));

    const openLetter = async (id) => {
      const idx = (await B.evaluate((x) => Data.inbox(false).map((t) => t.id).indexOf(x), id));
      await B.locator('.pop.ib .letter').nth(idx).locator('.btn', { hasText: '열기' }).click();
    };
    const confirmCancel = async (dialogTitleText = '결재 대기 중인 작업을 취소할까요?') => {
      const ok = await waitDialog(B, dialogTitleText);
      await dialogBtn(B, '취소하기').click();
      return ok;
    };

    // 결재 창(개발)
    await openLetter(bBuild2);
    await B.locator('.pop.ap').waitFor({ timeout: 8000 });
    const apBtns = await texts(B, '.pop.ap .ap-actions .btn, .pop.ap .ap-actions .stamp-btn');
    step('결재 창(개발): [승인][수정 요청][결재 취소]가 한 줄에 있다 (결재 취소가 맨 오른쪽)', eq(apBtns, ['승인', '수정 요청', '결재 취소']), apBtns);
    { const bad = await fitAll(B, '.pop.ap'); step('결재 창은 세 가지 창 크기 모두에서 화면 안, 넘침 없음', bad.length === 0, bad); }
    await B.locator('.pop.ap .ap-actions .btn', { hasText: '결재 취소' }).click();
    await waitDialog(B);
    await dialogBtn(B, '아니요').click();
    await B.locator('.pop.ap').waitFor({ timeout: 5000 });
    step("결재 창에서 '아니요'면 창이 그대로고 서버로 간 취소 0번", B.countPost(/\/api\/tasks\/T\d+\/cancel$/) === 0 && (await statuses(B))[bBuild2] === 'awaiting_approval');
    await B.locator('.pop.ap .ap-actions .btn', { hasText: '결재 취소' }).click();
    step('결재 창 [결재 취소] → 확인 창 글이 맞다', await confirmCancel() );
    step('취소되면 결재 창이 닫히고 결재함으로 돌아간다 · 서버 cancelled · 알림 "취소했어요" · 결재함 7통',
      await until(async () => (await B.locator('.pop.ap').count()) === 0) && (await B.locator('.pop.ib').count()) === 1
      && (await statuses(B))[bBuild2] === 'cancelled' && await waitNotice(B, '취소했어요') && (await letterCount(B)) === 7);

    // 업무 카드 → 결재 창 위에서 취소: 둘 다 닫힌다
    await openLetter(bBuild);
    await B.locator('.pop.ap').waitFor({ timeout: 8000 });
    await B.locator('.pop.ap .btn', { hasText: '진행 단계·완료 근거' }).click();
    await B.locator('.pop.tc').waitFor({ timeout: 8000 });
    const tcBtns = await texts(B, '.pop.tc .tc-actions .btn');
    step('업무 카드(결재 대기)에 [열기]와 위험 색 [취소]가 있다', tcBtns.includes('열기') && tcBtns.includes('취소'), tcBtns);
    const danger = await B.evaluate(() => { // 눈금 갱신으로 다시 그려질 수 있어서 그 자리에서 찾아 읽는다
      const n = [...document.querySelectorAll('.pop.tc .tc-actions .btn')].find((b) => b.textContent.trim() === '취소');
      return { cls: n.className, bg: getComputedStyle(n).backgroundColor, color: getComputedStyle(n).color };
    });
    step('그 [취소]는 위험(붉은) 색이다', danger.cls.includes('danger') && /^rgb\(25[0-9], 2[0-9]{2}, 2[0-9]{2}\)$/.test(danger.bg), danger);
    await B.locator('.pop.tc .tc-actions .btn', { hasText: /^취소$/ }).click();
    step('업무 카드 [취소] → 결재 대기용 확인 창 (되돌릴 수 없어요 · 결과 파일은 지우지 않아요)',
      await waitDialog(B, '결재 대기 중인 작업을 취소할까요?') && (await dialogBody(B)).includes('결과 파일은 지우지 않아요'));
    await dialogBtn(B, '취소하기').click();
    step('취소되면 업무 카드와 그 밑의 결재 창이 함께 닫히고 결재함이 남는다 · 서버 cancelled',
      await until(async () => (await B.locator('.pop.tc').count()) === 0 && (await B.locator('.pop.ap').count()) === 0 && (await B.locator('.pop.ib').count()) === 1)
      && (await statuses(B))[bBuild] === 'cancelled' && (await letterCount(B)) === 6);

    // 업무 카드(결재 대기가 아닌 상태)는 예전 글 그대로: 막힌 카드를 하나 취소하는 모양만 본다 → 서버에서 상태를 바꿀 수 없으니 글만 확인 (코드 경로: 결재 대기가 아니면 예전 확인 창)
    step('결재 대기가 아닌 카드의 확인 창 글은 예전 그대로 ("작업을 취소할까요?")', await B.evaluate(() => {
      const src = Popups.taskCard.toString();
      return src.includes("dialog('작업을 취소할까요?', t.title") && src.includes("t.status === 'awaiting_approval' ? cancelWaiting");
    }));

    // 보고서(리서치)
    await openLetter(bResearch);
    await B.locator('.pop.rp').waitFor({ timeout: 8000 });
    await B.locator('.pop.rp .rp-actions').waitFor({ timeout: 8000 });
    const rpBtns = await texts(B, '.pop.rp .rp-actions .btn');
    step('보고서 창: [확인 완료][질문하기][결재 취소] + 보관 단추', eq(rpBtns.slice(0, 3), ['확인 완료', '질문하기', '결재 취소']) && rpBtns.length === 4, rpBtns);
    { const bad = await fitAll(B, '.pop.rp'); step('보고서 창은 세 가지 창 크기 모두에서 화면 안, 넘침 없음', bad.length === 0, bad); }
    await B.locator('.pop.rp .rp-actions .btn', { hasText: '결재 취소' }).click();
    await confirmCancel();
    step('보고서에서 취소 → 창이 닫히고 서버 cancelled', await until(async () => (await B.locator('.pop.rp').count()) === 0) && (await statuses(B))[bResearch] === 'cancelled');

    // 회의실(기획)
    await openLetter(bPlan);
    await B.locator('.pop.mt').waitFor({ timeout: 8000 });
    await B.locator('.pop.mt .mt-actions').waitFor({ timeout: 8000 });
    const mtBtns = await texts(B, '.pop.mt .mt-actions .btn');
    step('회의실 창: [결재 취소][다시 기획][퀘스트로 붙이기]', eq(mtBtns, ['결재 취소', '다시 기획', '퀘스트로 붙이기']), mtBtns);
    { const bad = await fitAll(B, '.pop.mt', false); step('회의실 창은 세 가지 창 크기 모두에서 문서 넘침 없음, 단추가 창 밖으로 안 나감', bad.length === 0, bad); }
    await B.locator('.pop.mt .mt-actions .btn', { hasText: '결재 취소' }).click();
    await confirmCancel();
    step('회의실에서 취소 → 창이 닫히고 서버 cancelled', await until(async () => (await B.locator('.pop.mt').count()) === 0) && (await statuses(B))[bPlan] === 'cancelled');

    // 스킬 공부 확인 창
    await openLetter(bSkill);
    await B.locator('.pop.skd').waitFor({ timeout: 8000 });
    const skBtns = await texts(B, '.pop.skd .row-btns .btn');
    step('스킬 확인 창: [결재 취소][다시 공부][배우기 승인]', eq(skBtns, ['결재 취소', '다시 공부', '배우기 승인']), skBtns);
    { const bad = await fitAll(B, '.pop.skd'); step('스킬 확인 창은 세 가지 창 크기 모두에서 화면 안, 넘침 없음', bad.length === 0, bad); }
    await B.locator('.pop.skd .row-btns .btn', { hasText: '결재 취소' }).click();
    await confirmCancel();
    step('스킬 확인 창에서 취소 → 창이 닫히고 서버 cancelled', await until(async () => (await B.locator('.pop.skd').count()) === 0) && (await statuses(B))[bSkill] === 'cancelled');

    // MCP 만들기 확인 창
    await openLetter(bTool);
    await B.locator('.pop.skd.tlr').waitFor({ timeout: 8000 });
    const tlBtns = await texts(B, '.pop.skd.tlr .row-btns .btn');
    step('도구 확인 창: [결재 취소][다시 만들기][승인하고 꽂기]', eq(tlBtns, ['결재 취소', '다시 만들기', '승인하고 꽂기']), tlBtns);
    { const bad = await fitAll(B, '.pop.skd.tlr'); step('도구 확인 창은 세 가지 창 크기 모두에서 화면 안, 넘침 없음', bad.length === 0, bad); }
    await B.locator('.pop.skd.tlr .row-btns .btn', { hasText: '결재 취소' }).click();
    await confirmCancel();
    step('도구 확인 창에서 취소 → 창이 닫히고 서버 cancelled', await until(async () => (await B.locator('.pop.skd').count()) === 0) && (await statuses(B))[bTool] === 'cancelled');

    // 이제 남은 것: Grok 리서치 둘. 하나를 '나중에 보기'로 미룬다 → 그 탭의 모두 취소는 그 한 건만
    step('남은 결재 대기는 Grok 2장 (결재함 2통)', (await letterCount(B)) === 2 && (await text(B, '.ib-sign')) === '결재함 2');
    await B.evaluate((x) => Data.act(x, 'archive'), bGrokB);
    step('한 장을 나중에 보기로 미뤘다 → 결재함 1통 · [나중에 보기 1]', await until(async () => (await text(B, '.ib-sign')) === '결재함 1') && (await text(B, '.ib-later')) === '나중에 보기 1');
    step('결재함 탭의 [모두 취소 (1)]는 이 탭의 한 건만 센다 (그룹이 하나뿐)', eq(await texts(B, '.ib-cancel-group'), ['모두 취소 (1)']));
    await B.locator('.ib-later').click();
    step('나중에 보기 탭: 제목 "나중에 보기 1" · [모두 취소 (1)] · [결재함으로]',
      (await text(B, '.ib-sign')) === '나중에 보기 1' && (await text(B, '.ib-cancel-group')) === '모두 취소 (1)' && (await text(B, '.ib-later')) === '결재함으로');
    await B.locator('.ib-cancel-group').click();
    step('나중에 보기 탭의 확인 창: 한 건 · 외 N건 줄 없음', await waitDialog(B, '보고서 1건을 모두 취소할까요?') && !(await dialogBody(B)).includes('외 '));
    await dialogBtn(B, '1건 모두 취소').click();
    step('그 한 건만 취소된다 (보낸 번호 1개) · 결재함 탭의 다른 한 건은 그대로 결재 대기',
      await until(() => B.countPost(/cancel-waiting/) === 2) && eq(B.lastPost(/cancel-waiting/).ids, [bGrokB])
      && await until(async () => (await statuses(B))[bGrokB] === 'cancelled') && (await statuses(B))[bGrokA] === 'awaiting_approval');
    step('나중에 보기 탭이 비었다 → [결재함으로]만 남는다 (모두 취소 단추 없음)', await until(async () => (await B.locator('.ib-empty').count()) === 1) && (await B.locator('.ib-cancel-group').count()) === 0 && (await text(B, '.ib-later')) === '결재함으로');
    await B.locator('.ib-later').click();
    step('결재함 탭으로 돌아오면 남은 한 통이 있다', (await letterCount(B)) === 1 && (await text(B, '.ib-sign')) === '결재함 1');

    // 결재 대기 중 일부가 이미 끝났다면(다른 곳에서 결재/취소): 서버가 건너뛰고 쉬운 글로 알린다
    await B.locator('.ib-cancel-group').click();
    await waitDialog(B);
    const raced = await B.evaluate((x) => fetch(`/api/tasks/${x}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Studio-Token': document.querySelector('meta[name="studio-token"]').content }, body: '{}' }).then((r) => r.status), bGrokA);
    step('확인 창이 떠 있는 사이 다른 곳에서 그 카드가 먼저 취소됐다 (서버 200)', raced === 200);
    await dialogBtn(B, '1건 모두 취소').click();
    step('그래도 오류 없이 끝난다: 서버가 건너뛰고 알림에 쉬운 글 이유가 나온다',
      await until(() => B.countPost(/cancel-waiting/) === 3) && await waitNotice(B, '건너뛰었어요') && (await noticeText(B)).includes('이미 끝난 작업이에요.'));
    step('B 화면: 콘솔 오류·경고 0 · 이 연습용 서버 밖으로 나간 요청 0', B.errors.filter((e) => !/status of 400/.test(e)).length === 0 && [...B.hosts].every((h) => h === `127.0.0.1:${PORT + 1}`), { errors: B.errors, hosts: [...B.hosts] });

    // ======================================================================== 휴대폰 (B 서버의 /m)
    // 새 연습용 서버를 하나 더 쓰지 않고, B에서 개발 카드 한 장을 진짜 흐름(가짜 실행기)으로 결재 대기까지 올린다
    const token = (page) => page.evaluate(() => document.querySelector('meta[name="studio-token"]').content);
    const phoneId = await B.evaluate(async (tk) => {
      const post = (path, body) => fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Studio-Token': tk }, body: JSON.stringify(body) }).then((r) => r.json());
      const made = await post('/api/tasks', { project: 'demo', kind: 'build', title: '휴대폰에서 취소할 일', brief: 'docs/answer.txt에 42', acceptance: ['검사 통과'], allowed_paths: ['docs/**'] });
      await post(`/api/tasks/${made.task}/run`, {});
      return made.task;
    }, await token(B));
    step('휴대폰 시험용 결재 대기가 생겼다 (개발 카드, 가짜 실행기)', await B.waitForFunction((x) => (Data.task(x) || {}).status === 'awaiting_approval', phoneId, { timeout: 120000 }).then(() => true).catch(() => false));
    const code = (await B.evaluate(() => Data.remotePair())).code;
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
    const P = await ctx.newPage();
    const perrors = [];
    P.on('pageerror', (e) => perrors.push('pageerror: ' + e.message));
    P.on('console', (m) => { if (['error', 'warning'].includes(m.type())) perrors.push(m.type() + ': ' + m.text()); });
    const pposts = [];
    P.on('request', (r) => { if (r.method() === 'POST') pposts.push({ path: new URL(r.url()).pathname, body: r.postData() }); });
    const dialogs = [];
    let answer = false;
    P.on('dialog', (d) => { dialogs.push(d.message()); (answer ? d.accept() : d.dismiss()); });
    await P.goto(`${fxB.url}m#pair=${code}`);
    await P.locator('.card.tap').first().waitFor({ timeout: 30000 });
    await P.locator('.card.tap', { hasText: '휴대폰에서 취소할 일' }).first().click();
    await P.locator('.actbar').waitFor({ timeout: 10000 });
    const pBtns = await texts(P, '.actbar .btn');
    step('휴대폰 상세(결재 대기): [승인][수정 요청][취소]가 있다 · 묶음 취소는 없다', pBtns.includes('취소') && pBtns.includes('승인') && !pBtns.some((t) => t.includes('모두')), pBtns);
    step('휴대폰 화면: 가로 넘침 없음 (390px)', await P.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await P.locator('.actbar .btn.danger').click();
    await sleep(500);
    step("휴대폰 [취소]는 확인 창을 먼저 띄운다: 결재 대기용 글 · 거절하면 아무것도 안 바뀐다",
      dialogs.length === 1 && dialogs[0].includes('결재 대기 작업을 취소할까요?') && dialogs[0].includes('되돌릴 수 없어요') && dialogs[0].includes('결과 파일은 지우지 않아요')
      && pposts.filter((x) => x.path === '/m/api/act').length === 0 && (await statuses(B))[phoneId] === 'awaiting_approval', dialogs);
    answer = true;
    await P.locator('.actbar .btn.danger').click();
    step('확인하면 /m/api/act(cancel)로 한 번 간다 · 서버 cancelled · 화면에 "취소했어요"',
      await until(() => pposts.filter((x) => x.path === '/m/api/act').length === 1)
      && eq(JSON.parse(pposts.at(-1).body), { task: phoneId, action: 'cancel' })
      && await until(async () => (await statuses(B))[phoneId] === 'cancelled') && await until(async () => (await P.locator('#banner').innerText()).includes('취소했어요')));
    const phoneNo = await P.evaluate(async () => {
      const token = localStorage.getItem('ais.device');
      const r = await fetch('/m/api/cancel-waiting', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Device-Token': token }, body: JSON.stringify({ ids: ['T0001'] }) });
      return r.status;
    });
    step('휴대폰 길에는 묶음 취소가 없다 (/m/api/cancel-waiting → 404)', phoneNo === 404, phoneNo);
    step('휴대폰 화면: 콘솔 오류·경고 0 (확인 창 거절 때 생긴 400 제외)', perrors.filter((e) => !/status of 40[04]/.test(e)).length === 0, perrors);
    await ctx.close();

    console.log(`\ncancel_waiting_browser: ${passed}개 확인 통과`);
  } finally {
    await browser.close().catch(() => {});
    await stopFixture(fxA);
    await stopFixture(fxB);
    await stopFixture(fxC);
  }
})().catch((e) => {
  console.error(e.stack || e);
  process.exit(1);
});
