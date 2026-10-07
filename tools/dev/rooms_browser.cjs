'use strict';
// 소설 집필실·디자인 작업실 점검: node tools/dev/rooms_browser.cjs [--shots] [--port 8801] [--url http://127.0.0.1:8801/]
// 연습용 서버(임시 회사 + 가짜 실행기 + 소설·디자인 예시 프로젝트, tools/dev/rooms_fixture.py)를 직접 띄워서 Playwright(Edge)로 화면을 눌러 본다. 끝나면 서버를 끈다.
// 처음 쓰는 화면(프로젝트 없음)은 두 번째 연습용 서버(--empty, 포트+1)로 본다. --url 을 주면 이미 떠 있는 연습용 서버만 쓴다 (서버를 끄지 않고, 처음 쓰는 화면 점검은 건너뛴다).
// --shots 를 주면 docs/design/captures/modern-novel-*.png · modern-design-*.png 를 남긴다.
// 진짜 서버(8765)·진짜 직원·진짜 Grok에는 아무것도 보내지 않는다: 이 점검이 보내는 요청은 모두 연습용 서버(가짜 실행기)로만 간다.
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
const urlArg = args.includes('--url') ? args[args.indexOf('--url') + 1] : null;
const PORT = args.includes('--port') ? Number(args[args.indexOf('--port') + 1]) : 8801;
const out = path.join(root, 'output', 'rooms-browser');
const capDir = path.join(root, 'docs', 'design', 'captures');
fs.mkdirSync(out, { recursive: true });
const edge = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
if (!edge) throw new Error('Microsoft Edge를 찾지 못했습니다.');

const results = [];
const step = (name, ok, extra = {}) => {
  results.push({ name, ok });
  console.log(`${ok ? '  ✓' : '  ✗'} ${name}${ok ? '' : ' ' + JSON.stringify(extra)}`);
  if (!ok) throw new Error('실패: ' + name + ' ' + JSON.stringify(extra));
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// ---- 연습용 서버 띄우기 / 끄기
function startFixture(port, extra = []) {
  return new Promise((resolve, reject) => {
    const child = spawn('python', ['tools/dev/rooms_fixture.py', '--port', String(port), ...extra], { cwd: root, stdio: ['pipe', 'pipe', 'pipe'] });
    let buf = '';
    let err = '';
    const timer = setTimeout(() => reject(new Error('연습용 서버가 60초 안에 뜨지 않았어요: ' + err)), 60000);
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
async function newPage(browser, base, { ignore = [] } = {}) {
  const page = await browser.newPage({ viewport: { width: 1536, height: 1024 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (['error', 'warning'].includes(m.type()) && !ignore.some((re) => re.test(m.text()))) errors.push(m.type() + ': ' + m.text()); });
  const posts = [];
  const gets = [];
  const hosts = new Set();
  page.on('request', (r) => {
    const u = new URL(r.url());
    hosts.add(u.host);
    if (r.method() === 'POST') posts.push({ path: u.pathname, body: r.postData() });
    else if (r.method() === 'GET') gets.push(u.pathname);
  });
  page.errors = errors;
  page.posts = posts;
  page.hosts = hosts;
  page.countPost = (p) => posts.filter((x) => x.path === p).length;
  page.lastPost = (p) => { const l = posts.filter((x) => x.path === p); return l.length ? JSON.parse(l[l.length - 1].body || 'null') : null; };
  page.countGet = (p) => gets.filter((x) => x === p).length;
  page.base = base;
  return page;
}
async function openRoom(page, mode, hash = null) {
  await page.goto(page.base + (hash || `#view=${mode}`));
  await page.locator(`.bd-page-${mode}:not([hidden]) .rm-grid`).waitFor({ timeout: 30000 });
  await page.locator(`.bd-page-${mode} .rm-hello h2`).waitFor();
}
async function waitNoticeGone(page) {
  await page.waitForFunction(() => { const n = document.querySelector('#notice'); return !n || n.classList.contains('hidden'); }, null, { timeout: 15000 }).catch(() => {});
}
// 캡처: keep=true(기본)는 docs/design/captures/modern-<이름>.png, false는 눈으로만 볼 중간 그림(output/rooms-browser/)
async function shot(page, name, keep = true) {
  if (!SHOTS) return;
  fs.mkdirSync(capDir, { recursive: true });
  await waitNoticeGone(page);
  await page.mouse.move(5, 5);
  await sleep(300);
  await page.screenshot({ path: keep ? path.join(capDir, `modern-${name}.png`) : path.join(out, `tmp-${name}.png`) });
}
// 조건이 될 때까지 기다린다 (밀리초)
async function until(fn, ms = 8000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (await fn()) return true; await sleep(100); }
  return false;
}
// 요청을 가로채 가짜 응답을 준다. 돌려받은 함수를 부르면 풀린다
async function stub(page, match, handler) {
  await page.route(match, handler);
  return () => page.unroute(match, handler);
}
const text = async (page, sel) => (await page.locator(sel).first().innerText()).replace(/\s+/g, ' ').trim();
const taskStatus = (page, id) => page.evaluate((x) => (Data.task(x) || {}).status || null, id);
const taskIdByTitle = (page, project, title, kind = null) => page.evaluate(([p, t, k]) => (Data.get().tasks.find((x) => x.project === p && x.title === t && (!k || x.kind === k)) || {}).id || null, [project, title, kind]);

// 한 일을 눌러서 실행 → 결재 기다림 → 결재(승인) → 완료까지 (가짜 실행기). 방 화면이 열려 있는 채로 한다
async function runAndApprove(page, id) {
  await page.evaluate((x) => Data.act(x, 'run'), id);
  await page.waitForFunction((x) => (Data.task(x) || {}).status === 'awaiting_approval', id, { timeout: 90000 });
  await page.evaluate((x) => Data.act(x, 'approve'), id);
  await page.waitForFunction((x) => (Data.task(x) || {}).status === 'done', id, { timeout: 60000 });
}

(async () => {
  let fixture = null;
  let empty = null;
  let base = urlArg;
  if (!base) {
    console.log('연습용 서버를 띄우는 중…');
    fixture = await startFixture(PORT);
    base = fixture.url;
    empty = await startFixture(PORT + 1, ['--empty']);
  }
  const browser = await chromium.launch({ executablePath: edge, headless: true });
  const pages = [];
  try {
    // ======================================================================== 1. 소설 집필실
    const page = await newPage(browser, base, { ignore: [/status of 400/] });
    pages.push(page);
    await openRoom(page, 'novel');
    await page.locator('.bd-page-novel .rm-proj').first().waitFor({ timeout: 30000 });
    step('주소 #view=novel 로 열린다: 큰 제목·한 줄 설명·왼쪽 메뉴에서 켜진 단추', (await text(page, '.bd-page-novel .rm-hello h2')) === '소설 집필실'
      && (await text(page, '.bd-page-novel .rm-sub')) === '작품을 고르고 아래 시작 버튼으로 일을 맡기면 직원들이 기획·집필·검토해요.'
      && (await text(page, '.bd-nav-btn.on')).includes('소설 집필실'));
    step('왼쪽 메뉴 "작업" 묶음 순서: 홈 · 진행판 · 이미지·영상 작업대 · 소설 집필실 · 디자인 작업실 · 결재함 · 회의실',
      eq((await page.locator('.bd-nav-group').first().locator('.bd-nav-btn').allInnerTexts()).map((t) => t.replace(/\s+/g, ' ').trim().replace(/ \d+$/, '')), ['홈', '진행판', '이미지·영상 작업대', '소설 집필실', '디자인 작업실', '결재함', '회의실']));
    step('프로젝트 고르기: 소설 프로젝트 하나만 칩으로 있고 골라져 있다 (개발·디자인 프로젝트는 없다)',
      eq(await page.locator('.bd-page-novel .rm-proj').allInnerTexts(), ['비 오는 날의 서점']) && (await page.locator('.bd-page-novel .rm-proj.on').getAttribute('aria-pressed')) === 'true');
    step('[새 작품 만들기] 단추가 위쪽에 있다', (await text(page, '.bd-page-novel .rm-tools .rm-pill')) === '새 작품 만들기');

    // ---- 왼쪽: 파일 목록
    await page.locator('.bd-page-novel .rm-file').first().waitFor();
    const tree = await page.evaluate(() => fetch('/api/projects/novel-1/tree').then((r) => r.json()));
    const chapterChars = tree.files.filter((f) => /^chapters\/\d+\.md$/.test(f.path)).reduce((s, f) => s + Math.round(f.size / 3), 0);
    const comma = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    step('요약 숫자: "원고 3개 장 · 약 N자" (N = 원고 바이트÷3의 합)', (await text(page, '.bd-page-novel .rm-summary')) === `원고 3개 장 · 약 ${comma(chapterChars)}자`, { got: await text(page, '.bd-page-novel .rm-summary'), chapterChars });
    step('폴더 묶음 순서: 설정집 · 원고 · 메모 · 기타', eq(await page.locator('.bd-page-novel .rm-group-title span:first-child').allInnerTexts(), ['설정집', '원고', '메모', '기타']));
    step('원고는 번호순 "1장 · 2장 · 3장"(번호 아닌 안내 파일은 맨 뒤)이고 글자 수 어림("약 N자")이 붙는다',
      eq(await page.locator('.bd-page-novel .rm-group[aria-label="원고"] .rm-file-name').allInnerTexts(), ['1장', '2장', '3장', '원고 폴더 안내'])
      && /^약 [\d,]+자$/.test(await text(page, '.bd-page-novel .rm-file[data-path="chapters/001.md"] .rm-file-meta')));
    step('설정집 이름표: 한 줄 소개 · 인물 · 세계 · 줄거리 · 문체, 메모: 연속성 장부',
      eq(await page.locator('.bd-page-novel .rm-group[aria-label="설정집"] .rm-file-name').allInnerTexts(), ['한 줄 소개', '인물', '세계', '줄거리', '문체'])
      && eq(await page.locator('.bd-page-novel .rm-group[aria-label="메모"] .rm-file-name').allInnerTexts(), ['연속성 장부']));
    step('눌러 고르기 전에는 읽기 화면이 빈 안내다', (await text(page, '.bd-page-novel .rm-center')).includes('왼쪽에서 파일을 고르거나 오른쪽 시작 버튼으로 일을 맡겨 보세요'));
    step('안내 한 줄: 결재한 뒤에 나타난다', (await text(page, '.bd-page-novel .rm-center')).includes('사장님이 결재한 뒤에 여기에 나타나요'));

    // ---- 가운데: 원고 읽기
    await page.locator('.bd-page-novel .rm-file[data-path="chapters/001.md"]').click();
    await page.locator('.bd-page-novel .rm-read.chapter').waitFor();
    const info = await text(page, '.bd-page-novel .rm-readhead');
    step('위쪽 줄: 파일 경로 · 크기 · 승인된(기준 브랜치) 내용이에요', info.includes('chapters/001.md') && /약 [\d,]+자/.test(info) && info.includes('승인된(기준 브랜치) 내용이에요'), { info });
    step('큰 제목 줄(# )은 제목으로, 문단은 4개', (await text(page, '.bd-page-novel .rm-read .rm-h1')) === '제1장 비가 오는 아침' && (await page.locator('.bd-page-novel .rm-read .rm-p').count()) === 4);
    const metrics = await page.evaluate(() => {
      const read = document.querySelector('.bd-page-novel .rm-read.chapter');
      const paper = document.querySelector('.bd-page-novel .rm-paper');
      const r = read.getBoundingClientRect();
      const p = paper.getBoundingClientRect();
      const cs = getComputedStyle(read);
      const para = getComputedStyle(read.querySelector('.rm-p'));
      return { width: r.width, centerGap: Math.abs((r.left + r.right) / 2 - (p.left + p.right) / 2), lineRatio: parseFloat(para.lineHeight) / parseFloat(para.fontSize), margin: parseFloat(para.marginBottom), font: cs.fontSize };
    });
    step('원고 읽기 모양: 읽기 폭 680 이하 · 가운데 · 줄 간격 1.8 · 문단 사이 간격', metrics.width <= 680.5 && metrics.centerGap < 12 && Math.abs(metrics.lineRatio - 1.8) < 0.02 && metrics.margin > 8, metrics);
    await shot(page, 'novel-read');

    // 키보드: ↑↓로 옮기고 Enter로 고른다
    await page.locator('.bd-page-novel .rm-file[data-path="chapters/001.md"]').focus();
    await page.keyboard.press('ArrowDown');
    step('키보드 ↓: 다음 파일로 초점이 옮겨 간다 (아직 고르지는 않는다)', (await page.evaluate(() => document.activeElement.getAttribute('data-path'))) === 'chapters/002.md' && (await page.locator('.bd-page-novel .rm-file.on').getAttribute('data-path')) === 'chapters/001.md');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('.bd-page-novel .rm-readpath')?.textContent === 'chapters/002.md');
    step('Enter: 그 파일이 골라지고 읽힌다', (await text(page, '.bd-page-novel .rm-read .rm-h1')) === '제2장 오래된 시집' && (await page.locator('.bd-page-novel .rm-file.on').getAttribute('aria-selected')) === 'true');
    await page.keyboard.press('Home');
    step('Home: 맨 위 파일로 초점', (await page.evaluate(() => document.activeElement.getAttribute('data-path'))) === 'bible/premise.md');

    // 설정집(설명 글)은 문서 모양
    await page.locator('.bd-page-novel .rm-file[data-path="bible/premise.md"]').click();
    await page.locator('.bd-page-novel .rm-read.doc').waitFor();
    step('설정집은 문서 모양: 제목 · 목록(- ) 줄이 목록으로', (await text(page, '.bd-page-novel .rm-read.doc .rm-h1')).includes('한 줄 소개') && (await page.locator('.bd-page-novel .rm-read.doc .rm-bullets li').count()) >= 5);

    // ---- 믿지 않는 글: HTML·스크립트는 글자로만
    const freeNovel = await stub(page, (u) => u.pathname === '/api/projects/novel-1/file' && u.searchParams.get('path') === 'chapters/003.md', (route) => route.fulfill({
      json: { path: 'chapters/003.md', size: 120, text: '# 제3장 <i>시험</i>\n\n<b>x</b> 굵게가 아니에요 <img src=x onerror="window.__rmProbe=1">\n\n<script>window.__rmProbe=2</script>\n\n- <u>목록</u> 하나\n\n* * *\n\n끝' } }));
    await page.locator('.bd-page-novel .rm-file[data-path="chapters/003.md"]').click();
    await page.locator('.bd-page-novel .rm-read.chapter').waitFor();
    await sleep(500);
    const probe = await page.evaluate(() => ({
      probe: window.__rmProbe || null,
      tags: document.querySelectorAll('.bd-page-novel .rm-read b, .bd-page-novel .rm-read i, .bd-page-novel .rm-read u, .bd-page-novel .rm-read img, .bd-page-novel .rm-read script').length,
      title: document.querySelector('.bd-page-novel .rm-read .rm-h1').textContent,
      p: [...document.querySelectorAll('.bd-page-novel .rm-read .rm-p')].map((e) => e.textContent),
      li: [...document.querySelectorAll('.bd-page-novel .rm-read li')].map((e) => e.textContent),
      breaks: document.querySelectorAll('.bd-page-novel .rm-read hr.rm-break').length,
    }));
    step('원고 안의 <b>·<script>·<img onerror>가 글자로만 보이고 아무것도 실행되지 않는다', probe.probe === null && probe.tags === 0
      && probe.title === '제3장 <i>시험</i>' && probe.p[0].includes('<b>x</b>') && probe.p[0].includes('<img src=x onerror=') && probe.p[1] === '<script>window.__rmProbe=2</script>'
      && eq(probe.li, ['<u>목록</u> 하나']) && probe.breaks === 1, probe);
    await freeNovel();
    await page.locator('.bd-page-novel .rm-file[data-path="chapters/001.md"]').click();
    await page.waitForFunction(() => document.querySelector('.bd-page-novel .rm-readpath')?.textContent === 'chapters/001.md');

    // ---- 오른쪽: 시작 버튼
    const tplTitles = await page.locator('.bd-page-novel .rm-tpl-head b').allInnerTexts();
    step('시작 버튼 카드는 서버(/api/modes)의 소설 템플릿 5개 그대로', eq(tplTitles, ['작품 기획 시작', '다음 장 쓰기', '장 다듬기 (퇴고)', '설정·복선 점검', '자료 조사']), { tplTitles });
    step('처음에는 모두 접혀 있고 아무것도 보내지 않았다', (await page.locator('.bd-page-novel .rm-tpl.open').count()) === 0 && page.countPost('/api/modes/start') === 0);
    step('위쪽 안내: 하나가 기획안을 먼저 올리고 사장님이 결재해야 시작된다', (await text(page, '.bd-page-novel .rm-rintro')) === '일을 맡기면 하나가 먼저 기획안을 올리고, 사장님이 결재해야 시작돼요.');
    await page.locator('.bd-page-novel .rm-tpl-head[data-fk="tpl:novel-start"]').click();
    const ideaBox = page.locator('.bd-page-novel .rm-tpl.open textarea');
    step('펼치면 입력칸이 보인다: 필수 표시 · 글자 수 제한 · 안내 글', (await page.locator('.bd-page-novel .rm-tpl.open .rm-label').innerText()).replace(/\s+/g, ' ').includes('작품 아이디어 필수')
      && (await ideaBox.getAttribute('maxlength')) === '1500' && (await text(page, '.bd-page-novel .rm-tpl.open .rm-count')) === '0 / 1500'
      && (await ideaBox.getAttribute('placeholder')).startsWith('예: 폐업 직전 동네 서점'));
    step('보내기 전 확인 줄: 하나가 기획안을 먼저 올려요 · 진행판에서 결재 · 구독 사용량', (await text(page, '.bd-page-novel .rm-tpl.open .rm-notice')) === '하나가 기획안을 먼저 올려요. 진행판에서 결재하면 직원들이 일해요. 직원 일은 구독 사용량을 써요.');
    step('펼치면 첫 입력칸에 초점이 간다', await ideaBox.evaluate((el) => el === document.activeElement));
    await page.locator('.bd-page-novel .rm-go').click();
    step('필수 칸을 비우고 누르면 막히고 아무것도 보내지 않는다 (쉬운 오류 글)', (await text(page, '.bd-page-novel .rm-tpl.open .rm-err')) === "'작품 아이디어'을 적어 주세요." && page.countPost('/api/modes/start') === 0);
    await shot(page, 'novel-start-empty', false);
    const idea = '폐업 직전 동네 서점에 밤마다 사라진 책의 주인이 찾아온다';
    await ideaBox.fill(idea);
    step('글을 쓰면 글자 수가 바뀌고 오류 글이 사라진다', (await text(page, '.bd-page-novel .rm-tpl.open .rm-count')) === `${[...idea].length} / 1500` && (await page.locator('.bd-page-novel .rm-tpl.open .rm-err').isHidden()));
    // 입력 중에 데이터가 바뀌어도 글과 초점이 그대로
    await ideaBox.focus();
    await page.evaluate(() => { Data.setProject('novel-1'); Data.setProject('novel-1'); });
    await sleep(300);
    step('입력 중에 화면 데이터가 갱신돼도 쓰던 글과 초점이 그대로다', (await ideaBox.inputValue()) === idea && (await ideaBox.evaluate((el) => el === document.activeElement)));
    await shot(page, 'novel-start');

    // ---- 보내기: 두 번 눌러도 한 번만
    await page.route('**/api/modes/start', async (route) => { await sleep(500); await route.continue(); });
    const tasksBefore = await page.evaluate(() => Data.get().tasks.length);
    await page.locator('.bd-page-novel .rm-go').dblclick();
    await page.waitForFunction(() => document.querySelector('.bd-page-novel .rm-sentbox'), null, { timeout: 30000 });
    await sleep(300);
    step('더블클릭해도 POST /api/modes/start 는 정확히 1번', page.countPost('/api/modes/start') === 1);
    const body = page.lastPost('/api/modes/start');
    step('요청 본문: project · template · values(칸 key → 값)', eq(body, { project: 'novel-1', template: 'novel-start', values: { idea } }), body);
    step('성공 알림: 기획을 시작했어요 — 진행판에서 확인해 주세요', (await text(page, '#notice-text')).includes('기획을 시작했어요 — 진행판에서 확인해 주세요'));
    step('오른쪽 위에 안내 상자와 [진행판에서 보기] 단추가 남는다', (await text(page, '.bd-page-novel .rm-sentbox')).includes('하나가 기획을 시작했어요 — 진행판에서 확인해 주세요') && (await page.locator('.bd-page-novel .rm-sentbox .rm-pill').innerText()) === '진행판에서 보기');
    step('보낸 뒤 입력칸은 비워진다 (같은 일을 또 보내지 않게)', (await ideaBox.inputValue().catch(() => '')) === '');
    await page.unroute('**/api/modes/start');
    await page.waitForFunction((n) => Data.get().tasks.length > n, tasksBefore, { timeout: 30000 });
    await page.waitForFunction(() => [...document.querySelectorAll('.bd-page-novel .rm-task')].some((e) => e.textContent.includes('작품 기획 시작')), null, { timeout: 30000 });
    const rows = await page.locator('.bd-page-novel .rm-task').allInnerTexts();
    const rowText = rows.map((r) => r.replace(/\s+/g, ' '));
    step('이 프로젝트의 일: 방금 맡긴 기획이 맨 위에 있고 종류 칩은 "기획"', rowText[0].includes('기획') && rowText[0].includes('작품 기획 시작'), { rows: rowText });
    step('소설 프로젝트의 개발 일은 "집필", 조사 일은 "자료 조사"로 보인다', rowText.some((r) => r.includes('집필') && r.includes('제4장 쓰기')) && rowText.some((r) => r.includes('자료 조사') && r.includes('1990년대 동네 서점')), { rows: rowText });
    step('일 줄에는 상태 칩(점+글자)과 담당 얼굴이 있다', (await page.locator('.bd-page-novel .rm-task').first().locator('.rm-state .rm-dot').count()) === 1 && (await page.locator('.bd-page-novel .rm-task').first().locator('.rm-face').count()) === 1);
    step('일 목록은 최대 8개', (await page.locator('.bd-page-novel .rm-task').count()) <= 8);
    await shot(page, 'novel-sent', false);
    await page.locator('.bd-page-novel .rm-task', { hasText: '제4장 쓰기' }).first().click();
    await page.locator('.pop.tc').waitFor();
    step('일을 누르면 기존 작업 카드 창이 열린다', (await text(page, '.pop.tc h2')) === '제4장 쓰기');
    await page.keyboard.press('Escape');
    await page.locator('.pop.tc').waitFor({ state: 'detached' });

    // ---- 진행판으로
    await page.locator('.bd-page-novel .rm-sentbox .rm-pill').click();
    await page.locator('.bd-page-board:not([hidden])').waitFor();
    step('[진행판에서 보기]: 진행판이 열리고 고른 프로젝트의 일만 보인다', (await page.locator('.bd-page-board .bd-seg button[aria-pressed="true"]').first().innerText()).includes('비 오는 날의 서점') && (await page.evaluate(() => Data.currentProject().key)) === 'novel-1');
    const cardKinds = await page.locator('.bd-page-board .bd-card').evaluateAll((els) => els.map((e) => [e.querySelector('.bd-title').textContent, e.querySelector('.bd-kind').textContent]));
    step('진행판 카드의 종류 이름: 집필 · 자료 조사 · 기획', cardKinds.some((c) => c[0] === '제4장 쓰기' && c[1] === '집필') && cardKinds.some((c) => c[0] === '1990년대 동네 서점 자료 조사' && c[1] === '자료 조사') && cardKinds.some((c) => c[1] === '기획'), { cardKinds });
    await shot(page, 'novel-board', false);
    // 목록·CSV
    await page.locator('.bd-page-board .bd-modes button[aria-label="목록 보기"]').click();
    const rowKinds = await page.locator('.bd-page-board .bd-row').evaluateAll((els) => els.map((e) => [e.querySelector('.bd-row-title').textContent, e.querySelector('.bd-row-kind').textContent]));
    step('진행판 목록의 종류 이름도 집필·자료 조사', rowKinds.some((r) => r[0] === '제4장 쓰기' && r[1] === '집필') && rowKinds.some((r) => r[1] === '자료 조사'), { rowKinds });
    const [download] = await Promise.all([page.waitForEvent('download'), page.locator('.bd-page-board .bd-iconbtn[data-fk="export"]').click()]);
    const csv = fs.readFileSync(await download.path(), 'utf8');
    step('표 파일(CSV)의 종류 칸에도 집필·자료 조사', csv.includes('제4장 쓰기') && /제4장 쓰기[^\n]*집필/.test(csv) && csv.includes('자료 조사'), { head: csv.slice(0, 300) });
    await page.locator('.bd-page-board .bd-modes button[aria-label="칸반 보기"]').click();

    // ---- 새 작품 만들기 창
    await page.locator('.bd-nav-btn[data-action="novel"]').click();
    await page.locator('.bd-page-novel:not([hidden]) .rm-grid').waitFor();
    await page.locator('.bd-page-novel .rm-tools .rm-pill').click();
    await page.locator('.rm-dlg').waitFor();
    step('새 작품 창: 제목 · 설명 글 · 폴더 안내 · ID 자동 제안(novel-1이 있으니 novel-2)', (await text(page, '.rm-dlg h2')) === '새 작품 만들기'
      && (await text(page, '.rm-dlg .rm-plain')).includes('새 Git 저장소가 projects 폴더에 만들어지고 기본 뼈대 파일이 들어가요')
      && (await text(page, '.rm-dlg .rm-plain')).includes('직원은 허용된 폴더(bible/·chapters/·notes/ 등)만 고칠 수 있어요')
      && (await page.locator('#rm-new-key').inputValue()) === 'novel-2');
    step('입력 한도: 이름 80자 · 설명 1000자 · ID 40자', (await page.locator('#rm-new-title').getAttribute('maxlength')) === '80' && (await page.locator('#rm-new-desc').getAttribute('maxlength')) === '1000' && (await page.locator('#rm-new-key').getAttribute('maxlength')) === '40');
    await shot(page, 'novel-new-empty', false);
    await page.locator('.rm-dlg .btn.primary').click();
    step('이름을 비우고 만들면 막힌다 (쉬운 오류 글, 아무것도 보내지 않음)', (await text(page, '.rm-dlg .rm-err')) === '작품 이름을 적어 주세요.' && page.countPost('/api/projects/new') === 0);
    await page.locator('#rm-new-title').fill('새 이야기');
    await page.locator('#rm-new-key').fill('Bad ID');
    await page.locator('.rm-dlg .btn.primary').click();
    step('잘못된 ID는 소문자 영문 규칙을 알려 주며 막힌다', (await text(page, '.rm-dlg .rm-err')) === '프로젝트 ID는 소문자 영문으로 시작하고 영문·숫자·-만 사용하세요 (40자까지).' && page.countPost('/api/projects/new') === 0);
    await page.locator('#rm-new-key').fill('novel-1');
    await page.locator('.rm-dlg .btn.primary').click();
    step('이미 있는 ID도 막는다', (await text(page, '.rm-dlg .rm-err')).includes('이미 있는 프로젝트 ID') && page.countPost('/api/projects/new') === 0);
    // 서버가 거절하면 그 글 그대로
    await page.locator('#rm-new-key').fill('novel-2');
    const desc = '밤마다 한 권씩 사라지는 책의 주인을 찾는 이야기.';
    await page.locator('#rm-new-desc').fill(desc);
    step('글을 고치면 옛 오류 글은 사라진다', await page.locator('.rm-dlg .rm-err').isHidden());
    await shot(page, 'novel-new');
    const freeNew = await stub(page, '**/api/projects/new', (route) => route.fulfill({ status: 400, json: { error: '같은 이름의 폴더가 이미 있습니다. 다른 ID를 쓰세요. (시험용 응답)' } }));
    await page.locator('.rm-dlg .btn.primary').click();
    await page.locator('.rm-dlg .rm-err:not([hidden])').waitFor();
    step('서버 오류 글은 그대로 보이고 창이 남아 다시 고칠 수 있다', (await text(page, '.rm-dlg .rm-err')) === '같은 이름의 폴더가 이미 있습니다. 다른 ID를 쓰세요. (시험용 응답)' && !(await page.locator('.rm-dlg .btn.primary').isDisabled()) && page.countPost('/api/projects/new') === 1);
    await freeNew();
    await page.locator('.rm-dlg .btn.primary').dblclick();
    await page.locator('.rm-dlg').waitFor({ state: 'detached', timeout: 30000 });
    step('만들기: 요청 본문은 key · title · kind · description, 더블클릭해도 새로 보낸 것은 1번', page.countPost('/api/projects/new') === 2 && eq(page.lastPost('/api/projects/new'), { key: 'novel-2', title: '새 이야기', kind: 'novel', description: desc }), page.lastPost('/api/projects/new'));
    await page.waitForFunction(() => document.querySelector('.bd-page-novel .rm-proj.on .rm-proj-name')?.textContent === '새 이야기', null, { timeout: 30000 });
    step('새 프로젝트가 칩으로 늘고 바로 골라진다', eq(await page.locator('.bd-page-novel .rm-proj').allInnerTexts(), ['비 오는 날의 서점', '새 이야기']));
    await page.locator('.bd-page-novel .rm-group').first().waitFor();
    step('새 프로젝트의 기본 뼈대 파일이 목록에 보인다 (원고 0개 장)', (await text(page, '.bd-page-novel .rm-summary')) === '원고 0개 장 · 약 0자' && (await page.locator('.bd-page-novel .rm-file[data-path="bible/premise.md"]').count()) === 1);
    step('성공 알림이 뜬다', (await text(page, '#notice-text')).includes('‘새 이야기’ 작품을 만들었어요'));
    step('새로 만든 프로젝트가 명령창의 대상으로도 골라진다', (await page.evaluate(() => Data.currentProject().key)) === 'novel-2' && (await text(page, '#project-chip')).startsWith('대상: 소설 · 새 이야기'));
    step('일 목록은 비어 있다는 안내', (await text(page, '.bd-page-novel .rm-tasks')).includes('아직 맡긴 일이 없어요'));
    // 프로젝트를 다시 고르면 그 프로젝트 파일이 읽힌다. 고른 프로젝트는 이 브라우저에 기억된다
    await page.locator('.bd-page-novel .rm-proj', { hasText: '비 오는 날의 서점' }).click();
    await page.locator('.bd-page-novel .rm-file[data-path="chapters/001.md"]').waitFor();
    step('칩을 눌러 프로젝트를 고르면 명령창의 대상도 그 프로젝트가 된다', (await page.evaluate(() => Data.currentProject().key)) === 'novel-1');
    step('다른 프로젝트를 고르면 파일 목록·읽기 화면·시작 버튼 입력이 그 프로젝트 것으로 바뀐다', (await text(page, '.bd-page-novel .rm-summary')).startsWith('원고 3개 장') && (await text(page, '.bd-page-novel .rm-center')).includes('왼쪽에서 파일을 고르거나'));

    // ======================================================================== 2. 디자인 작업실
    await page.locator('.bd-nav-btn[data-action="design"]').click();
    await page.locator('.bd-page-design:not([hidden]) .rm-file').first().waitFor({ timeout: 30000 });
    step('디자인 작업실: 제목·한 줄 설명·단추 이름·프로젝트 칩(디자인 프로젝트만)', (await text(page, '.bd-page-design .rm-hello h2')) === '디자인 작업실'
      && (await text(page, '.bd-page-design .rm-tools .rm-pill')) === '새 디자인 프로젝트 만들기' && eq(await page.locator('.bd-page-design .rm-proj').allInnerTexts(), ['동네 카페 메뉴판']));
    step('폴더 묶음 순서: 기획서 · 규칙 · 시안 · 그림 · 점검 · 기타, 요약은 시안 N개 · 그림 N개',
      eq(await page.locator('.bd-page-design .rm-group-title span:first-child').allInnerTexts(), ['기획서', '규칙', '시안', '그림', '점검', '기타']) && (await text(page, '.bd-page-design .rm-summary')) === '시안 1개 · 그림 2개');
    step('디자인 시작 버튼 5개 (서버 템플릿)', eq(await page.locator('.bd-page-design .rm-tpl-head b').allInnerTexts(), ['디자인 기획서 쓰기', '디자인 규칙 정리', '화면 시안 만들기', '그림 요청서 쓰기', '디자인 점검']));
    step('시작 버튼 설명의 코드 표시(`)는 화면에서 빠진다', !(await text(page, '.bd-page-design .rm-tpls')).includes('`'));

    // 시안(html)은 원문으로만
    const freeDesign = await stub(page, (u) => u.pathname === '/api/projects/design-1/file' && u.searchParams.get('path') === 'screens/login.html', (route) => route.fulfill({
      json: { path: 'screens/login.html', size: 90, text: '<!doctype html>\n<html><body><h1>시안</h1><script>window.__designProbe=1</script><iframe src="about:blank"></iframe></body></html>\n' } }));
    await page.locator('.bd-page-design .rm-file[data-path="screens/login.html"]').click();
    await page.locator('.bd-page-design .rm-raw').waitFor();
    await sleep(400);
    const html = await page.evaluate(() => ({ probe: window.__designProbe || null, frames: document.querySelectorAll('.bd-page-design iframe, .bd-page-design .rm-paper h1, .bd-page-design .rm-paper script').length, raw: document.querySelector('.bd-page-design .rm-raw').textContent, mono: getComputedStyle(document.querySelector('.bd-page-design .rm-raw')).fontFamily }));
    step('.html 시안은 고정폭 원문으로만 보이고 실행·렌더되지 않는다', html.probe === null && html.frames === 0 && html.raw.includes('<script>window.__designProbe=1</script>') && html.raw.includes('<iframe') && /mono|Consolas/i.test(html.mono), html);
    await freeDesign();
    await page.locator('.bd-page-design .rm-file[data-path="screens/login.html"]').click();
    await page.waitForFunction(() => document.querySelector('.bd-page-design .rm-raw')?.textContent.includes(':root'), null, { timeout: 15000 });
    step('진짜 시안 파일도 원문 그대로 (<!doctype · <style> · 색 값)', (await text(page, '.bd-page-design .rm-raw')).includes('<!doctype html>') && (await text(page, '.bd-page-design .rm-raw')).includes('<style>') && (await page.locator('.bd-page-design .rm-paper h1').count()) === 0);
    await shot(page, 'design-screen');

    // 그림(svg)은 <img>로 크게, 원문으로 바꿔 볼 수 있다
    await page.locator('.bd-page-design .rm-file[data-path="assets/logo.svg"]').click();
    await page.locator('.bd-page-design .rm-imgbox img.rm-img').waitFor();
    await page.waitForFunction(() => { const i = document.querySelector('.bd-page-design .rm-img'); return i && i.complete && i.naturalWidth > 0; }, null, { timeout: 15000 });
    const svg = await page.evaluate(() => { const i = document.querySelector('.bd-page-design .rm-img'); return { w: i.naturalWidth, src: i.getAttribute('src'), shown: i.getBoundingClientRect().width }; });
    step('SVG 그림이 <img>로 열린다 (naturalWidth > 0, 주소는 /api/projects/<ID>/raw?path=…)', svg.w > 0 && svg.src === '/api/projects/design-1/raw?path=assets%2Flogo.svg' && svg.shown >= 160, svg);
    await shot(page, 'design-image');
    await page.locator('.bd-page-design .rm-seg', { hasText: '글(원문)으로' }).click();
    await page.locator('.bd-page-design .rm-raw').waitFor();
    step('같은 SVG를 "글(원문)으로" 바꾸면 원문 글자만 보이고 그림은 없다', (await text(page, '.bd-page-design .rm-raw')).startsWith('<svg xmlns') && (await page.locator('.bd-page-design .rm-img').count()) === 0 && (await page.locator('.bd-page-design .rm-seg.on').innerText()) === '글(원문)으로');
    // PNG
    await page.locator('.bd-page-design .rm-file[data-path="assets/sample.png"]').click();
    await page.waitForFunction(() => { const i = document.querySelector('.bd-page-design .rm-img'); return i && i.complete && i.naturalWidth > 0; }, null, { timeout: 15000 });
    step('PNG 그림도 <img>로 열린다 (96×64)', (await page.evaluate(() => { const i = document.querySelector('.bd-page-design .rm-img'); return [i.naturalWidth, i.naturalHeight]; })).join('x') === '96x64' && (await page.locator('.bd-page-design .rm-seg').count()) === 0);
    // 그림이 아닌 글(.md)은 글로
    await page.locator('.bd-page-design .rm-file[data-path="brief/brief.md"]').click();
    await page.locator('.bd-page-design .rm-read.doc').waitFor();
    step('기획서(.md)는 읽기 모양: 파일 이름표 "디자인 기획서"', (await text(page, '.bd-page-design .rm-readhead')).includes('디자인 기획서') && (await text(page, '.bd-page-design .rm-read .rm-h1')) === '디자인 기획서');

    // 디자인 시작 버튼: 처음 값(default)이 채워져 있다
    await page.locator('.bd-page-design .rm-tpl-head[data-fk="tpl:design-screen"]').click();
    const fields = page.locator('.bd-page-design .rm-tpl.open .rm-input');
    step('"화면 시안 만들기": 파일 이름 칸에 처음 값 screen, 필수 칸 둘', (await fields.count()) === 2 && (await fields.nth(1).inputValue()) === 'screen' && (await page.locator('.bd-page-design .rm-tpl.open .rm-req').count()) === 2);
    await fields.nth(0).fill('로그인 화면');
    await fields.nth(1).fill('login');
    await shot(page, 'design-start');
    await page.locator('.bd-page-design .rm-go').click();
    await page.waitForFunction(() => document.querySelector('.bd-page-design .rm-sentbox'), null, { timeout: 30000 });
    step('디자인 요청 본문: project=design-1 · template=design-screen · values', eq(page.lastPost('/api/modes/start'), { project: 'design-1', template: 'design-screen', values: { screen: '로그인 화면', file: 'login' } }), page.lastPost('/api/modes/start'));
    await page.waitForFunction(() => [...document.querySelectorAll('.bd-page-design .rm-task')].some((e) => e.textContent.includes('기획') && e.textContent.includes('화면 시안 만들기')), null, { timeout: 30000 }).catch(() => {});
    const dRows = (await page.locator('.bd-page-design .rm-task').allInnerTexts()).map((r) => r.replace(/\s+/g, ' '));
    step('디자인 프로젝트의 개발 일은 "디자인"으로 보인다', dRows.some((r) => r.includes('디자인') && r.includes('메뉴 카드 시안 만들기')) && dRows.length >= 2, { dRows });

    // 새 디자인 프로젝트 (설명 없이): 요청 본문의 kind
    await page.locator('.bd-page-design .rm-tools .rm-pill').click();
    await page.locator('.rm-dlg').waitFor();
    step('새 디자인 프로젝트 창: 제목과 폴더 안내(brief/·system/·screens/), ID는 design-2', (await text(page, '.rm-dlg h2')) === '새 디자인 프로젝트 만들기' && (await text(page, '.rm-dlg .rm-plain')).includes('(brief/·system/·screens/ 등)') && (await page.locator('#rm-new-key').inputValue()) === 'design-2');
    await page.locator('#rm-new-title').fill('가게 포스터');
    await page.locator('.rm-dlg .btn.primary').click();
    await page.locator('.rm-dlg').waitFor({ state: 'detached', timeout: 30000 });
    step('디자인 프로젝트 만들기: kind=design, 설명은 빈 글', eq(page.lastPost('/api/projects/new'), { key: 'design-2', title: '가게 포스터', kind: 'design', description: '' }), page.lastPost('/api/projects/new'));
    await page.waitForFunction(() => document.querySelector('.bd-page-design .rm-proj.on .rm-proj-name')?.textContent === '가게 포스터', null, { timeout: 30000 });
    step('디자인 프로젝트 칩이 늘고 소설 집필실에는 나타나지 않는다', eq(await page.locator('.bd-page-design .rm-proj').allInnerTexts(), ['동네 카페 메뉴판', '가게 포스터']) && eq(await page.locator('.bd-page-novel .rm-proj').allInnerTexts(), ['비 오는 날의 서점', '새 이야기']));
    await page.locator('.bd-page-design .rm-proj', { hasText: '동네 카페 메뉴판' }).click();
    await page.locator('.bd-page-design .rm-file[data-path="assets/logo.svg"]').waitFor();

    // ======================================================================== 3. 끝난 일: 파일 목록이 저절로 늘고, 완성작 이름이 갈린다
    const novelTask = await taskIdByTitle(page, 'novel-1', '제4장 쓰기', 'build');
    const designTask = await taskIdByTitle(page, 'design-1', '메뉴 카드 시안 만들기', 'build');
    step('예시 일(소설 4장 쓰기 · 디자인 시안)을 찾았다', Boolean(novelTask) && Boolean(designTask), { novelTask, designTask });
    await page.locator('.bd-nav-btn[data-action="novel"]').click();
    await page.locator('.bd-page-novel .rm-proj', { hasText: '비 오는 날의 서점' }).click();
    await page.locator('.bd-page-novel .rm-file[data-path="chapters/003.md"]').waitFor();
    await sleep(800);
    const treeGets = page.countGet('/api/projects/novel-1/tree');
    await runAndApprove(page, novelTask);
    await page.locator('.bd-page-novel .rm-file[data-path="chapters/004.md"]').waitFor({ timeout: 30000 });
    step('일이 끝나면(결재 뒤 병합) 파일 목록을 저절로 다시 읽어 "4장"이 나타난다', (await text(page, '.bd-page-novel .rm-summary')).startsWith('원고 4개 장') && page.countGet('/api/projects/novel-1/tree') > treeGets, { gets: page.countGet('/api/projects/novel-1/tree'), before: treeGets });
    await page.locator('.bd-page-novel .rm-file[data-path="chapters/004.md"]').click();
    await page.locator('.bd-page-novel .rm-read.chapter').waitFor();
    step('새로 생긴 4장도 읽힌다 (직원이 쓴 글)', (await text(page, '.bd-page-novel .rm-read .rm-h1')) === '제4장 두 잔의 보리차');
    // 완성작
    await page.evaluate((id) => Popups.taskCard(id), novelTask);
    await page.locator('.pop.tc .btn', { hasText: '완성작에 올리기' }).click();
    await page.waitForFunction(() => Data.get().trophies.some((t) => t.kind === 'novel'), null, { timeout: 15000 });
    step('소설 프로젝트의 끝난 일은 완성작에 kind=novel 로 올라간다', eq(page.lastPost('/api/trophies/add'), { task: novelTask, kind: 'novel' }), page.lastPost('/api/trophies/add'));
    await page.keyboard.press('Escape');
    await page.locator('.bd-nav-btn[data-action="trophies"]').click();
    await page.locator('.pop.tr .tr-slot.novel').waitFor();
    step('완성작 진열장: 소설은 "소설"로 보이고 "열기"는 소설 집필실을 연다', (await text(page, '.pop.tr .tr-slot.novel .panel-kicker')) === '소설' && (await text(page, '.pop.tr .tr-slot.novel .btn')).includes('열기'));
    await shot(page, 'novel-trophy', false);
    await page.locator('.pop.tr .tr-slot.novel .btn').click();
    await page.locator('.bd-page-novel:not([hidden]) .rm-grid').waitFor();
    step('"열기" → 소설 집필실이 그 프로젝트로 열린다', (await page.locator('.bd-page-novel .rm-proj.on').innerText()) === '비 오는 날의 서점' && !(await page.locator('.pop.tr').count()));
    // 디자인
    await page.locator('.bd-nav-btn[data-action="design"]').click();
    await page.locator('.bd-page-design .rm-file[data-path="assets/logo.svg"]').waitFor();
    await sleep(500);
    await runAndApprove(page, designTask);
    await page.locator('.bd-page-design .rm-file[data-path="screens/cards.html"]').waitFor({ timeout: 30000 });
    step('디자인도 끝난 일이 병합되면 시안 목록이 저절로 늘어난다 (시안 2개)', (await text(page, '.bd-page-design .rm-summary')) === '시안 2개 · 그림 2개');
    await page.evaluate((id) => Popups.taskCard(id), designTask);
    await page.locator('.pop.tc .btn', { hasText: '완성작에 올리기' }).click();
    await page.waitForFunction(() => Data.get().trophies.some((t) => t.kind === 'design'), null, { timeout: 15000 });
    step('디자인 프로젝트의 끝난 일은 kind=design 으로 올라간다', eq(page.lastPost('/api/trophies/add'), { task: designTask, kind: 'design' }), page.lastPost('/api/trophies/add'));
    await page.keyboard.press('Escape');
    await page.locator('.bd-nav-btn[data-action="trophies"]').click();
    await page.locator('.pop.tr .tr-slot.design').waitFor();
    step('완성작 진열장: 디자인은 "디자인", 소설은 "소설" (보고서가 아니다)', (await text(page, '.pop.tr .tr-slot.design .panel-kicker')) === '디자인' && (await text(page, '.pop.tr .tr-slot.novel .panel-kicker')) === '소설');
    await shot(page, 'design-trophy', false);
    await page.keyboard.press('Escape');

    // ---- 홈·빠른 찾기
    await page.locator('.bd-nav-btn[data-action="home"]').click();
    await page.locator('.bd-home:not([hidden])').waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('.bd-home .hm-next.done .hm-next-sub')].some((e) => e.textContent.includes('집필')), null, { timeout: 15000 });
    step('홈 "최근 끝난 일"에도 집필·디자인 이름이 보인다', (await page.locator('.bd-home .hm-next.done .hm-next-sub').allInnerTexts()).some((t) => t.includes('집필 · 비 오는 날의 서점')) && (await page.locator('.bd-home .hm-next.done .hm-next-sub').allInnerTexts()).some((t) => t.startsWith('디자인 ·')));
    await page.locator('#board-search').fill('집필');
    await page.locator('.finder-item').first().waitFor();
    step('빠른 찾기: "집필"로 소설 프로젝트의 개발 일이 찾아진다 (종류 이름도 찾는 글)', (await page.locator('.finder-item').allInnerTexts()).some((t) => t.includes('제4장 쓰기')));
    await page.locator('#board-search').fill('소설');
    step('빠른 찾기: "소설"은 화면 바로가기에서 소설 집필실을 찾는다', (await page.locator('.finder-item').allInnerTexts()).some((t) => t.includes('소설 집필실')));
    await page.locator('.finder-item', { hasText: '소설 집필실' }).first().click();
    await page.locator('.bd-page-novel:not([hidden]) .rm-grid').waitFor();
    step('빠른 찾기에서 고르면 소설 집필실이 열린다', (await text(page, '.bd-nav-btn.on')).includes('소설 집필실'));
    await page.evaluate(() => { const b = document.getElementById('board-search'); b.value = ''; b.blur(); });

    // ======================================================================== 4. 프로젝트 고르기·등록 창, 스킬 조건
    await page.locator('#project-chip').click();
    await page.locator('.project-picker').waitFor();
    const options = await page.locator('.project-picker .project-option').evaluateAll((els) => els.map((e) => ({ kind: (e.querySelector('.pj-kind') || {}).textContent || '', title: e.querySelector('b').textContent, desc: e.querySelector('span').textContent })));
    step('프로젝트 고르는 창: 프로젝트마다 종류 칩(개발·소설·디자인)', options.some((o) => o.title === 'Demo' && o.kind === '개발') && options.some((o) => o.title === '비 오는 날의 서점' && o.kind === '소설') && options.some((o) => o.title === '동네 카페 메뉴판' && o.kind === '디자인'), { options });
    step('설명이 없는 프로젝트는 종류에 맞는 기본 글 (소설 작품 · 디자인 프로젝트)', options.some((o) => o.title === '가게 포스터' && o.desc === '디자인 프로젝트'));
    await page.evaluate(() => { for (const p of Data.get().projects) if (p.key === 'novel-1') p.description = ''; Popups.refresh(); });
    step('설명이 없는 소설 프로젝트의 기본 글은 "소설 작품"', (await page.locator('.project-picker .project-option', { hasText: '비 오는 날의 서점' }).locator('span').first().innerText()) === '소설 작품');
    step('작업실로 가는 길: 새 작품·새 디자인 프로젝트 만들기 안내', (await text(page, '.project-picker .pj-rooms')).includes('새 작품 만들기 (소설 집필실)') && (await text(page, '.project-picker .pj-rooms')).includes('새 디자인 프로젝트 만들기 (디자인 작업실)'));
    await shot(page, 'project-picker', false);
    await page.locator('.project-picker .pj-rooms .btn', { hasText: '디자인 작업실' }).click();
    await page.locator('.bd-page-design:not([hidden]) .rm-grid').waitFor();
    step('안내 단추를 누르면 창이 닫히고 디자인 작업실로 간다', (await page.locator('.pop').count()) === 0);
    // 등록 창: 종류 고르기
    await page.locator('#project-chip').click();
    await page.locator('.project-picker .btn.primary').click();
    await page.locator('.project-form').waitFor();
    const kinds = await page.locator('.project-form .pj-kindchip').allInnerTexts();
    step('프로젝트 등록 창: 종류 고르기 (일반 개발 · Godot 게임 · 문서 · 디자인 · 소설), 기본은 일반 개발', eq(kinds, ['일반 개발', 'Godot 게임', '문서', '디자인', '소설'])
      && (await page.locator('.project-form .pj-kindchip[aria-checked="true"]').innerText()) === '일반 개발');
    await page.locator('.project-form input[aria-label="프로젝트 이름"]').fill('시험 등록');
    await page.locator('.project-form input[aria-label="프로젝트 ID (영문 소문자)"]').fill('reg-test');
    await page.locator('.project-form input[aria-label="Git 폴더 전체 경로"]').fill('C:/not-a-real-folder');
    await page.locator('.project-form input[aria-label="기준 브랜치"]').fill('main');
    await page.locator('.project-form textarea[aria-label="수정 허용 경로 (한 줄에 하나)"]').fill('docs/**');
    const freeRegister = await stub(page, '**/api/projects', (route) => (route.request().method() === 'POST' ? route.fulfill({ status: 400, json: { error: '시험용 응답: 실제 등록은 하지 않았어요.' } }) : route.continue()));
    await page.locator('.project-form .project-confirm input').check();
    await page.locator('.project-form .btn.primary').click();
    await page.locator('.project-form .tc-blocked').waitFor();
    step('종류를 건드리지 않으면 kind=generic 으로 보낸다', page.lastPost('/api/projects') && page.lastPost('/api/projects').kind === 'generic' && page.lastPost('/api/projects').key === 'reg-test', page.lastPost('/api/projects'));
    await page.locator('.project-form .pj-kindchip', { hasText: '소설' }).click();
    step('"소설"을 고르면 눌린 표시가 옮겨 간다', (await page.locator('.project-form .pj-kindchip[aria-checked="true"]').innerText()) === '소설' && (await page.locator('.project-form .pj-kindchip[aria-checked="true"]').count()) === 1);
    await page.locator('.project-form .btn.primary').click();
    await until(() => page.countPost('/api/projects') === 2);
    step('소설을 고르면 kind=novel 이 서버로 간다', page.lastPost('/api/projects').kind === 'novel' && page.countPost('/api/projects') === 2, page.lastPost('/api/projects'));
    await freeRegister();
    step('등록 창에도 작업실로 가는 길이 있다', (await text(page, '.project-form .pj-rooms')).includes('새 작품 만들기 (소설 집필실)'));
    await shot(page, 'register-kind', false);
    await page.locator('.project-form .pj-rooms .btn', { hasText: '소설 집필실' }).click();
    await page.locator('.bd-page-novel:not([hidden]) .rm-grid').waitFor();
    step('등록 창의 안내 단추: 창을 모두 닫고 소설 집필실로 간다', (await page.locator('.pop').count()) === 0);
    // 위쪽 바 대상 칩
    step('명령창의 대상 칩에 소설·디자인 프로젝트는 종류가 보인다', await page.evaluate(() => { Data.setProject('novel-1'); return document.querySelector('#project-chip').textContent; }) === '대상: 소설 · 비 오는 날의 서점'
      && (await page.evaluate(() => { Data.setProject('design-1'); return document.querySelector('#project-chip').textContent; })) === '대상: 디자인 · 동네 카페 메뉴판'
      && (await page.evaluate(() => { Data.setProject('demo'); return document.querySelector('#project-chip').textContent; })) === '대상: Demo');
    // 스킬 쓰는 곳: 소설 작품 일 칩
    await page.locator('.bd-nav-btn[data-action="skills"]').click();
    await page.locator('.pop.sk .btn', { hasText: '직접 가르치기' }).click();
    await page.locator('.sk-form').waitFor();
    const chip = page.locator('.sk-form .sk-chip[data-value="novel"]');
    step('스킬 쓰는 곳: "소설 작품 일" 조건 칩 (도움말 포함), "디자인 일" 칩 옆에 있다', (await chip.innerText()) === '소설 작품 일' && (await chip.getAttribute('title')) === '소설 프로젝트의 일일 때만 붙어요'
      && eq(await page.locator('.sk-form .sk-chip[data-value="design"], .sk-form .sk-chip[data-value="novel"]').evaluateAll((els) => els.map((e) => e.dataset.value)), ['design', 'novel']));
    await chip.click();
    step('칩을 누르면 눌린 상태가 되고 "모든 일"은 풀린다', (await chip.getAttribute('aria-pressed')) === 'true' && (await page.locator('.sk-form .sk-scope-row', { hasText: '일 종류' }).locator('.sk-chip.all').getAttribute('aria-pressed')) === 'false');
    await page.locator('.sk-form input[aria-label="스킬 제목"]').fill('소설 시험');
    await page.locator('.sk-form input[aria-label="언제 쓰는 스킬인지"]').fill('소설 일 때');
    await page.locator('.sk-form textarea[aria-label="지침"]').fill('짧게 쓴다');
    const freeSkills = await stub(page, '**/api/skills', (route) => (route.request().method() === 'POST' ? route.fulfill({ json: { ok: true } }) : route.continue()));
    await page.locator('.sk-form .btn.primary').click();
    await page.waitForFunction(() => !document.querySelector('.sk-form'));
    step('스킬 가르치기 요청: kinds=["novel"] (시험용 응답, 실제 스킬은 만들지 않음)', eq(page.lastPost('/api/skills').kinds, ['novel']), page.lastPost('/api/skills'));
    await freeSkills();
    await page.keyboard.press('Escape');

    // ======================================================================== 5. 기억·옛 화면
    await page.locator('.bd-nav-btn[data-action="design"]').click();
    await page.locator('.bd-page-design .rm-proj', { hasText: '가게 포스터' }).click();
    await page.locator('.bd-page-design .rm-proj.on', { hasText: '가게 포스터' }).waitFor();
    await page.goto(base); // 주소 없이 다시 열면 마지막으로 본 화면과 고른 프로젝트를 기억한다
    await page.locator('.bd-page-design:not([hidden]) .rm-grid').waitFor({ timeout: 30000 });
    await page.locator('.bd-page-design .rm-proj.on').waitFor({ timeout: 30000 });
    step('다시 열면 마지막 화면(디자인 작업실)과 고른 프로젝트를 기억한다', (await page.locator('.bd-page-design .rm-proj.on').innerText()) === '가게 포스터');
    for (const [hash, sel, label] of [['#view=home', '.bd-home:not([hidden])', '홈'], ['#view=board', '.bd-page-board:not([hidden])', '진행판'], ['#view=media', '.bd-page-media:not([hidden]) .md-grid', '이미지·영상 작업대'], ['#view=workbench', '#workbench-screen:not([hidden])', '노드 편집기']]) {
      await page.goto(base + '?x=' + Date.now() + hash);
      await page.locator(sel).waitFor({ timeout: 30000 });
      step(`기존 화면 ${hash} (${label})가 그대로 열린다`, true);
    }
    await page.goto(base + '?y=' + Date.now() + '#view=novel');
    await page.locator('.bd-page-novel:not([hidden]) .rm-grid').waitFor();
    step('소설 집필실을 직접 주소로 다시 열어도 열린다', (await text(page, '.bd-nav-btn.on')).includes('소설 집필실'));

    // ======================================================================== 6. 처음 쓰는 화면 (프로젝트 없음)
    if (empty) {
      const ep = await newPage(browser, empty.url, { ignore: [/status of 400/] });
      pages.push(ep);
      await openRoom(ep, 'novel');
      await ep.locator('.bd-page-novel .rm-noproject').waitFor({ timeout: 30000 });
      step('프로젝트가 없으면 큰 안내와 [새 작품 만들기]', (await text(ep, '.bd-page-novel .rm-noproject b')) === '아직 작품이 없어요' && (await text(ep, '.bd-page-novel .rm-noproject .rm-pill')) === '새 작품 만들기');
      step('프로젝트가 없으면 위쪽 칩 줄·왼쪽·오른쪽도 안내만 (시작 버튼은 숨김)', (await text(ep, '.bd-page-novel .rm-projects')).includes('아직 작품이 없어요') && (await text(ep, '.bd-page-novel .rm-left')).includes('작품을 만들면 여기에 파일이 보여요')
        && (await text(ep, '.bd-page-novel .rm-right')).includes('먼저 작품을 만들어 주세요.') && (await ep.locator('.bd-page-novel .rm-tpl').count()) === 0);
      await shot(ep, 'novel-empty');
      await ep.locator('.bd-nav-btn[data-action="design"]').click();
      await ep.locator('.bd-page-design .rm-noproject').waitFor();
      step('디자인 작업실도 프로젝트가 없으면 안내와 [새 디자인 프로젝트 만들기]', (await text(ep, '.bd-page-design .rm-noproject b')) === '아직 디자인 프로젝트가 없어요' && (await text(ep, '.bd-page-design .rm-noproject .rm-pill')) === '새 디자인 프로젝트 만들기'
        && (await text(ep, '.bd-page-design .rm-right')).includes('먼저 디자인 프로젝트를 만들어 주세요.'));
      await shot(ep, 'design-empty');
      await ep.locator('.bd-page-design .rm-noproject .rm-pill').click();
      await ep.locator('.rm-dlg').waitFor();
      step('안내 안의 단추로도 같은 만들기 창이 열린다 (ID 제안은 design-1)', (await ep.locator('#rm-new-key').inputValue()) === 'design-1');
      await ep.locator('#rm-new-title').fill('첫 디자인');
      await ep.locator('.rm-dlg .btn.primary').click();
      await ep.locator('.rm-dlg').waitFor({ state: 'detached', timeout: 30000 });
      await ep.locator('.bd-page-design .rm-proj.on').waitFor();
      await ep.locator('.bd-page-design .rm-file[data-path="brief/brief.md"]').waitFor({ timeout: 30000 });
      await ep.locator('.bd-page-design .rm-tpl').first().waitFor({ timeout: 30000 });
      step('첫 프로젝트를 만들면 바로 파일 목록과 시작 버튼이 나타난다', (await ep.locator('.bd-page-design .rm-tpl').count()) === 5 && (await ep.locator('.bd-page-design .rm-file[data-path="brief/brief.md"]').count()) === 1 && (await ep.locator('.bd-page-design .rm-noproject').count()) === 0);
      await ep.locator('.bd-nav-btn[data-action="novel"]').click();
      step('디자인 프로젝트를 만들어도 소설 집필실은 여전히 비어 있다', (await ep.locator('.bd-page-novel .rm-noproject').count()) === 1);
    }

    // ======================================================================== 7. 마무리: 오류·바깥 요청
    for (const p of pages) {
      const label = p === page ? '기본 연습용 서버' : '처음 쓰는 연습용 서버';
      step(`${label}: 페이지 오류·콘솔 오류 없음 (일부러 막은 400 응답 제외)`, p.errors.length === 0, { errors: p.errors });
      const hosts = [...p.hosts].filter(Boolean);
      step(`${label}: 연습용 서버 말고는 어디에도 요청하지 않았다 (진짜 서버 8765 포함)`, hosts.every((h) => /^127\.0\.0\.1:(88\d\d)$/.test(h)) && !hosts.some((h) => h.endsWith(':8765')), { hosts });
    }
    await page.screenshot({ path: path.join(out, 'last.png') });
  } finally {
    await browser.close();
    await stopFixture(fixture);
    await stopFixture(empty);
  }
  const failed = results.filter((r) => !r.ok);
  fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify({ total: results.length, failed: failed.map((f) => f.name), results }, null, 2));
  console.log(failed.length ? `\n소설 집필실·디자인 작업실 점검 실패 ${failed.length}개 / ${results.length}개` : `\n소설 집필실·디자인 작업실 점검 통과 (${results.length}개)`);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error(e.message); process.exit(1); });
