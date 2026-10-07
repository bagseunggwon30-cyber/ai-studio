'use strict';
// 이미지·영상 작업대 점검: node tools/dev/media_browser.cjs [--shots] [--url http://127.0.0.1:8798/]
// 연습용 모의 서버(임시 회사 + MOCK Grok: 미디어는 가짜, 실제 Grok 호출 없음)를 직접 띄워서 Playwright(Edge)로 화면을 눌러 본다. 끝나면 서버를 끈다.
// --port 8803 처럼 포트를 고를 수 있다 (없으면 8798). 다른 점검이 같은 포트를 쓰고 있을 때 쓴다.
//   python tools/dev/workbench_fixture.py --port 8798 --grok-mock --mock-video tests/fixtures/mock-video-10s.webm --mock-video-duration 10
// --url 을 주면 이미 떠 있는 모의 서버를 쓴다 (서버를 끄지 않는다). --shots 를 주면 docs/design/captures/modern-media-*.png 를 남긴다.
// 진짜 Grok·진짜 회사(8765)에는 아무것도 보내지 않는다: 진짜 경로(승인 체크·Grok 승인·시작)는 page.route 로 가로채 가짜 응답만 돌려준다.
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
const PORT = args.includes('--port') ? Number(args[args.indexOf('--port') + 1]) : 8798;
const out = path.join(root, 'output', 'media-browser');
const capDir = path.join(root, 'docs', 'design', 'captures');
fs.mkdirSync(out, { recursive: true });
const edge = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
if (!edge) throw new Error('Microsoft Edge를 찾지 못했습니다.');

const report = { steps: [], notes: [] };
const step = (name, ok, extra = {}) => {
  report.steps.push({ name, ok, ...extra });
  console.log(`${ok ? '  ✓' : '  ✗'} ${name}${ok ? '' : ' ' + JSON.stringify(extra)}`);
  if (!ok) throw new Error('실패: ' + name + ' ' + JSON.stringify(extra));
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- 모의 서버 띄우기 / 끄기
function startFixture() {
  return new Promise((resolve, reject) => {
    const child = spawn('python', ['tools/dev/workbench_fixture.py', '--port', String(PORT), '--grok-mock', '--mock-video', 'tests/fixtures/mock-video-10s.webm', '--mock-video-duration', '10'], { cwd: root, stdio: ['pipe', 'pipe', 'pipe'] });
    let buf = '';
    let err = '';
    const timer = setTimeout(() => reject(new Error('모의 서버가 60초 안에 뜨지 않았어요: ' + err)), 60000);
    child.stderr.on('data', (d) => { err += d; });
    child.stdout.on('data', (d) => {
      buf += d;
      const line = buf.split('\n').find((l) => l.startsWith('{'));
      if (line) { clearTimeout(timer); resolve({ child, url: `http://127.0.0.1:${PORT}/` }); }
    });
    child.on('exit', (code) => { clearTimeout(timer); reject(new Error('모의 서버가 바로 꺼졌어요 ' + code + ' ' + err)); });
  });
}
async function stopFixture(fx) {
  if (!fx) return;
  fx.child.removeAllListeners('exit');
  try { fx.child.stdin.write('stop\n'); } catch (_) { /* 이미 닫힘 */ }
  await Promise.race([new Promise((r) => fx.child.once('exit', r)), sleep(15000)]);
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
  page.on('request', (r) => {
    const p = new URL(r.url()).pathname;
    if (r.method() === 'POST') posts.push({ path: p, body: r.postData() });
    else if (r.method() === 'GET') gets.push(p);
  });
  page.errors = errors;
  page.posts = posts;
  page.gets = gets;
  page.countPost = (p) => posts.filter((x) => x.path === p).length;
  page.countGet = (p) => gets.filter((x) => x === p).length;
  page.base = base;
  return page;
}
async function openMedia(page) {
  await page.goto(page.base + '#view=media');
  await page.locator('.bd-page-media:not([hidden]) .md-grid').waitFor({ timeout: 30000 });
  await page.locator('.md-hello h2').waitFor();
}
async function shot(page, name, hover = null) {
  if (!SHOTS) return;
  fs.mkdirSync(capDir, { recursive: true });
  await page.waitForFunction(() => { const n = document.querySelector('#notice'); return !n || n.classList.contains('hidden'); }, null, { timeout: 15000 }).catch(() => {}); // 위쪽 알림 말풍선이 가릴 수 있어서 사라질 때까지
  if (hover) await page.hover(hover);
  else await page.mouse.move(5, 5);
  await sleep(300);
  await page.screenshot({ path: path.join(capDir, `modern-media-${name}.png`) });
  report.notes.push(`캡처 modern-media-${name}.png`);
}
async function patchMedia(page, mutate) {
  await page.route('**/api/workbench/media', async (route) => {
    const res = await route.fetch();
    const data = await res.json();
    mutate(data);
    await route.fulfill({ response: res, json: data });
  });
}
const REAL_CONN = { enabled: true, configured: true, mode: 'official_cli', auth_verified: false, reason: '공식 Grok CLI 연결됨', config_hash: 'cfg-hash-1' };
const realCaps = () => ({ image: { enabled: true, reason: '연결됨', mode: 'model', simulation: false }, video: { enabled: true, reason: '연결됨', mode: 'model', simulation: false } });
const offCaps = () => ({ image: { enabled: false, reason: 'blocked', mode: 'unsupported' }, video: { enabled: false, reason: 'blocked', mode: 'unsupported' } });
const iso = (secondsAgo) => new Date(Date.now() - secondsAgo * 1000).toISOString();
const fakeJob = (id, o = {}) => ({ id: `${id}/b`, run: id, node: 'b', title: o.title || '그림', created_at: iso(o.ago || 60), kind: 'image', status: 'succeeded', run_status: 'succeeded', error: '', prompt: o.prompt || '샘플', duration: null,
  simulation: false, transport: null, requested_duration: null, measured_duration_s: null, duration_check: null, model_verified: false, task: null, assets: [], ...o });

(async () => {
  let fixture = null;
  let base = urlArg;
  if (!base) { console.log('모의 서버를 띄우는 중…'); fixture = await startFixture(); base = fixture.url; }
  const browser = await chromium.launch({ executablePath: edge, headless: true });
  let ok = false;
  try {
    // ======================================================================== 1. 연습용 모의 서버에서 한 바퀴
    const page = await newPage(browser, base);
    await openMedia(page);
    step('열기: 제목과 왼쪽 메뉴 이름', (await page.locator('.md-hello h2').innerText()) === '이미지·영상 작업대' && (await page.locator('.bd-nav-btn.on').innerText()).includes('이미지·영상 작업대'));
    step('왼쪽 메뉴에서 옛 이름 "기능 작업대"는 없다', (await page.locator('.bd-nav-btn[data-action="workbench"]').count()) === 0);
    step('연습용 표시가 위쪽에 보인다', (await page.locator('.md-conn.sim').innerText()).includes('연습용 · 실제 생성 아님'));
    step('모의 서버가 만들어 둔 작업물 2개(그림 1 · 영상 1)가 목록에 있다', (await page.locator('.md-card').count()) === 2 && (await page.locator('.md-fchip[data-filter="all"] b').innerText()) === '2'
      && (await page.locator('.md-fchip[data-filter="image"] b').innerText()) === '1' && (await page.locator('.md-fchip[data-filter="video"] b').innerText()) === '1');
    step('선택이 없으면 빈 화면 안내와 예시 3개', (await page.locator('.md-empty').count()) === 1 && (await page.locator('.md-empty .md-example').count()) === 3);
    step('빈 화면에서는 [만들기]가 꺼져 있다 (글이 없음)', await page.locator('.md-go').isDisabled());
    await shot(page, 'tmp-empty-sim');

    // 예시 누르기 = 글상자만 채움, 보내지 않음
    await page.locator('.md-example').first().click();
    const exampleText = await page.locator('#md-text').inputValue();
    step('예시를 누르면 글상자만 채워진다 (보내지 않음)', exampleText.length > 5 && page.countPost('/api/workbench/start') === 0 && page.countPost('/api/workbench/plan') === 0);
    await page.locator('#md-text').fill('');

    // ---- 그림 만들기
    await page.locator('.md-new[data-kind="image"]').click();
    const imagePrompt = '작은 파란 종이배가 잔잔한 물 위에 떠 있어요';
    await page.locator('#md-text').fill(imagePrompt);
    step('글자 수가 보인다', (await page.locator('#md-count').innerText()) === `${[...imagePrompt].length} / 4000`);
    step('흐름도 첫 칸에 지시 글이 보인다', (await page.locator('.md-node[data-node="text"] .md-node-sub').innerText()).includes('작은 파란 종이배'));
    await page.locator('.md-go').click();
    await page.locator('.md-dlg').waitFor();
    const dlgText = await page.locator('.md-dlg').innerText();
    step('연습용이면 체크 없이 "연습용 · 실제 생성 아님"을 크게 보인다', dlgText.includes('연습용 · 실제 생성 아님') && (await page.locator('.md-dlg input[type="checkbox"]').count()) === 0);
    step('확인 창에 정확한 지시 글·종류가 그대로 보인다', (await page.locator('.md-exact').innerText()) === imagePrompt && dlgText.includes('그림'));
    const before = page.countPost('/api/workbench/start');
    await page.locator('.md-send').click();
    await page.locator('.md-dlg').waitFor({ state: 'detached', timeout: 30000 });
    step('그림: 시작 요청은 정확히 1번', page.countPost('/api/workbench/start') === before + 1);
    step('새 작업물이 선택되고 오른쪽 칸이 작업 정보로 바뀐다', (await page.locator('.md-card.on').count()) === 1 && (await page.locator('.md-view .md-prompt').innerText()) === imagePrompt);
    await page.waitForFunction(() => { const i = document.querySelector('.md-result img.md-media'); return i && i.complete && i.naturalWidth > 0; }, null, { timeout: 90000 });
    const img = await page.evaluate(() => { const i = document.querySelector('.md-result img.md-media'); return { w: i.naturalWidth, h: i.naturalHeight, src: i.getAttribute('src') }; });
    step('그림 미리보기가 열린다 (naturalWidth > 0, 같은 출처 주소)', img.w > 0 && img.src.startsWith('/api/workbench/runs/'), img);
    step('그림 결과 아래에 연습용 표시·모델 미확인 글이 있다', (await page.locator('.md-caption').innerText()).includes('MOCK / 연습용') && (await page.locator('.md-caption').innerText()).includes('모델은 확인되지 않았어요'));
    step('목록의 새 카드 상태가 끝남이다', (await page.locator('.md-card.on .md-state').innerText()).includes('끝남'));
    await shot(page, 'image');

    // ---- 영상 만들기 (길이 범위 밖 값은 맞추고 알린다)
    await page.locator('.md-new[data-kind="video"]').click();
    step('영상을 고르면 길이 칸이 보이고 기본은 6초', (await page.locator('.md-dur').isVisible()) && (await page.locator('#md-dur-num').inputValue()) === '6');
    await page.locator('#md-dur-num').fill('99');
    await page.locator('#md-dur-num').blur();
    step('15를 넘는 길이는 15초로 맞추고 알려 준다', (await page.locator('#md-dur-num').inputValue()) === '15' && (await page.locator('#md-note').innerText()).includes('15초로 맞췄어요'));
    await page.locator('#md-dur-num').fill('0');
    await page.locator('#md-dur-num').blur();
    step('1보다 작은 길이는 1초로 맞춘다', (await page.locator('#md-dur-num').inputValue()) === '1');
    await page.locator('.md-step[aria-label="1초 늘리기"]').click();
    step('+ 단추는 1초씩 늘린다', (await page.locator('#md-dur-num').inputValue()) === '2');
    await page.locator('#md-dur-num').fill('10');
    await page.locator('#md-dur-num').blur();
    step('슬라이더가 숫자와 같이 움직인다', (await page.locator('.md-range').inputValue()) === '10');
    const videoPrompt = '파란 종이배가 잔잔한 물 위를 천천히 흘러가요';
    await page.locator('#md-text').fill(videoPrompt);
    step('흐름도 가운데 칸이 "영상 만들기 · 10초"이고 장면 그림 안내가 있다', (await page.locator('.md-node[data-node="make"] .md-node-name').innerText()) === '영상 만들기 · 10초'
      && (await page.locator('.md-node[data-node="make"] .md-node-sub').innerText()).includes('먼저 장면 그림 한 장을 만들고'));
    await page.locator('.md-go').click();
    await page.locator('.md-dlg').waitFor();
    const vdlg = await page.locator('.md-dlg').innerText();
    step('영상 확인 창에 길이 10초·화면·두 번 요청 안내가 보인다', vdlg.includes('10초') && vdlg.includes('16:9') && vdlg.includes('요청이 두 번'));
    const vBefore = page.countPost('/api/workbench/start');
    await page.locator('.md-send').click();
    await page.locator('.md-dlg').waitFor({ state: 'detached', timeout: 30000 });
    step('영상: 시작 요청은 정확히 1번', page.countPost('/api/workbench/start') === vBefore + 1);
    await page.waitForFunction(() => { const v = document.querySelector('.md-result video.md-media'); return v && v.readyState >= 1; }, null, { timeout: 90000 });
    const vid = await page.evaluate(async () => {
      const v = document.querySelector('.md-result video.md-media');
      let d = v.duration;
      if (!Number.isFinite(d)) { v.currentTime = 1e101; await new Promise((r) => setTimeout(r, 600)); d = v.duration; v.currentTime = 0; }
      return { duration: d, w: v.videoWidth, h: v.videoHeight, controls: v.controls, src: v.getAttribute('src') };
    });
    step('영상 미리보기가 열리고 길이가 약 10초다 (controls, 같은 출처 주소)', vid.controls && Math.abs(vid.duration - 10) < 0.6 && vid.src.startsWith('/api/workbench/runs/'), vid);
    step('영상 결과 아래에 요청 길이 글이 있다', (await page.locator('.md-caption').innerText()).includes('요청 10초'));
    await shot(page, 'tmp-video');

    // ---- 목록: 거르기 · 선택 · 키보드
    await page.locator('.md-fchip[data-filter="video"]').click();
    const kinds = await page.locator('.md-card .md-kind').allInnerTexts();
    step('영상만 거르면 영상 카드만 남는다', kinds.length >= 2 && kinds.every((t) => t === '영상'), { kinds });
    await page.locator('.md-fchip[data-filter="all"]').click();
    const total = await page.locator('.md-card').count();
    step('전체로 돌아오면 모두 보인다 (모의 2 + 방금 만든 2 = 4)', total === 4 && (await page.locator('.md-fchip[data-filter="all"] b').innerText()) === '4', { total });
    await page.locator('.md-card').last().focus();
    await page.keyboard.press('ArrowUp');
    const focusedIdx = await page.evaluate(() => [...document.querySelectorAll('.md-card')].indexOf(document.activeElement));
    step('목록에서 ↑ 키로 한 칸 위로 간다', focusedIdx === total - 2, { focusedIdx });
    await page.keyboard.press('Enter');
    step('Enter로 고르면 그 작업물이 선택된다', (await page.locator('.md-card.on').count()) === 1 && (await page.locator('.md-view').count()) === 1);
    const tabbable = await page.evaluate(() => [...document.querySelectorAll('.md-card')].filter((c) => c.tabIndex === 0).length);
    step('목록은 탭 한 번에 한 칸만 잡힌다 (roving tabindex)', tabbable === 1, { tabbable });

    // ---- 같은 지시로 다시 만들기 = 글상자만 채움
    const startsBefore = page.countPost('/api/workbench/start');
    const planBefore = page.countPost('/api/workbench/plan');
    const chosenPrompt = await page.locator('.md-view .md-prompt').innerText();
    await page.locator('.md-view .md-pill.dark').click();
    step('"같은 지시로 다시 만들기"는 글상자만 채우고 자동으로 보내지 않는다', (await page.locator('#md-text').inputValue()) === chosenPrompt && (await page.locator('.md-card.on').count()) === 0
      && page.countPost('/api/workbench/start') === startsBefore && page.countPost('/api/workbench/plan') === planBefore);
    step('글상자에 초점이 가 있다', await page.evaluate(() => document.activeElement && document.activeElement.id === 'md-text'));

    // ---- 더블클릭해도 요청은 1번
    await page.locator('.md-new[data-kind="image"]').click();
    await page.locator('#md-text').fill('더블클릭 점검 그림');
    const dStart = page.countPost('/api/workbench/start');
    const dPlan = page.countPost('/api/workbench/plan');
    await page.locator('.md-go').dblclick();
    await page.locator('.md-dlg').waitFor();
    await sleep(300);
    step('[만들기]를 두 번 눌러도 확인 창은 하나, 계획 요청은 1번', (await page.locator('.md-dlg').count()) === 1 && page.countPost('/api/workbench/plan') === dPlan + 1);
    await page.locator('.md-send').dblclick();
    await page.locator('.md-dlg').waitFor({ state: 'detached', timeout: 30000 });
    await sleep(500);
    step('[보내기]를 두 번 눌러도 시작 요청은 1번', page.countPost('/api/workbench/start') === dStart + 1);
    await page.waitForFunction(() => document.querySelector('.md-result img.md-media'), null, { timeout: 90000 });

    // ---- 3초 읽기: 끝난 작업만 있으면 멈춘다
    await sleep(500);
    const idleBefore = page.countGet('/api/workbench/media');
    await sleep(7500);
    step('만드는 중인 작업이 없으면 3초 읽기를 하지 않는다', page.countGet('/api/workbench/media') === idleBefore, { idleBefore, now: page.countGet('/api/workbench/media') });

    // ---- 다른 화면과 옛 노드 편집기
    await page.locator('.bd-nav-btn[data-action="home"]').click();
    step('홈이 열린다', await page.locator('.bd-home:not([hidden])').isVisible() && await page.locator('.bd-page-media').isHidden());
    await page.locator('.bd-nav-btn[data-action="board"]').click();
    step('진행판이 열린다', await page.locator('.bd-page-board:not([hidden])').isVisible());
    await page.locator('.bd-nav-btn[data-action="media"]').click();
    step('메뉴에서 다시 이미지·영상 작업대로 온다', await page.locator('.bd-page-media:not([hidden])').isVisible() && (await page.locator('.md-card').count()) === 5);
    await page.locator('.md-tools .md-pill', { hasText: '노드 편집기 (고급)' }).click();
    await page.locator('#workbench-screen:not([hidden])').waitFor({ timeout: 15000 });
    step('"노드 편집기 (고급)"으로 옛 편집기가 열린다', (await page.locator('#workbench-screen').getAttribute('aria-label')) === '노드 편집기');
    await page.goto(base + '#view=workbench');
    await page.locator('#workbench-screen:not([hidden])').waitFor({ timeout: 15000 });
    step('#view=workbench 주소로도 옛 편집기가 열린다', true);
    step('모의 서버 한 바퀴: 페이지 오류 없음', page.errors.length === 0, { errors: page.errors });
    await page.close();

    // ======================================================================== 2. 진짜 경로 (가로챈 가짜 응답만): 승인 체크 · Grok 승인 순서 · 실패 · 연결 · 중단 · 읽기 · 보존
    const real = await newPage(browser, base, { ignore: [/Failed to load resource/] });
    const runningJob = fakeJob('Wrunning', { title: '영상 · 막 시작', prompt: '구름이 천천히 지나가는 하늘', kind: 'video', status: 'running', run_status: 'running', duration: 6, ago: 72 });
    const blockedJob = fakeJob('Wblocked', { title: '그림 · 막힌 일', prompt: '막힌 그림 지시', status: 'blocked', run_status: 'blocked', error: 'grok login required (code 401)' });
    const cancelledJob = fakeJob('Wstop', { title: '영상 · 중단', prompt: '중단한 영상', kind: 'video', status: 'cancelled', run_status: 'cancelled', duration: 8 });
    await patchMedia(real, (data) => {
      data.connection = REAL_CONN;
      data.capabilities = realCaps();
      for (const j of data.jobs) { if (j.kind === 'video') { j.measured_duration_s = 10.04; j.duration_check = 'ok'; j.requested_duration = 10; } }
      data.jobs = [runningJob, blockedJob, cancelledJob, ...data.jobs];
    });
    const calls = [];
    const fulfill = (body, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) });
    let consentFails = false;
    let planOverride = null;
    await real.route('**/api/workbench/plan', (route) => {
      const body = JSON.parse(route.request().postData());
      calls.push('workbench-plan');
      const node = body.graph.nodes[1];
      const kind = node.ref.id.endsWith('video') ? 'video' : 'image';
      const text = body.graph.nodes[0].params.text;
      route.fulfill(fulfill(planOverride || { hash: 'plan-hash-1', uses_models: false, provider_requests: [{ node: 'b', kind, input: text, options: kind === 'video' ? { duration: node.params.duration } : {}, simulation: false, model: 'grok-imagine' }] }));
    });
    await real.route('**/api/workbench/planner', (route) => { calls.push('planner'); route.fulfill(fulfill({ config_hash: 'cfg-hash-1', enabled: true })); });
    await real.route('**/api/grok-everywhere/plan', (route) => { calls.push('grok-plan'); route.fulfill(fulfill({ request_hash: 'req-hash-1', approval_checklist: ['one-use', 'cost-unknown'] })); });
    await real.route('**/api/grok-everywhere/consent', (route) => {
      calls.push('consent');
      if (consentFails) route.fulfill(fulfill({ error: '승인 값이 맞지 않아요' }, 400));
      else route.fulfill(fulfill({ grant_id: 'grant-1' }));
    });
    await real.route('**/api/workbench/start', (route) => { calls.push('start'); route.fulfill(fulfill({ run: { id: 'Wnew1', status: 'running' } })); });
    await real.route('**/api/workbench/runs/*/halt', (route) => { calls.push('halt'); route.fulfill(fulfill({ id: 'Wrunning', status: 'cancelled' })); });
    await openMedia(real);
    step('연결됨 표시와 [만들기] 단추', (await real.locator('.md-conn.on').innerText()).includes('Grok 연결됨') && (await real.locator('.md-go').innerText()).includes('만들기'));
    step('목록에 상태 칩이 글자로 있다 (만드는 중·막힘·중단·끝남)', await (async () => {
      const t = (await real.locator('.md-card .md-state').allInnerTexts()).join('|');
      return ['만드는 중', '막힘', '중단', '끝남'].every((s) => t.includes(s));
    })());

    // 만드는 중: 경과 시간·중단 단추(한 번만)
    await real.locator('.md-card[data-id="Wrunning/b"]').click();
    const workText = await real.locator('.md-working').innerText();
    step('만드는 중: 경과 시간과 "1~3분 걸려요" 안내', /만드는 중 · 1분 \d+초/.test(workText) && workText.includes('1~3분 걸려요'), { workText });
    const e1 = await real.locator('.md-elapsed').innerText();
    await sleep(2200);
    const e2 = await real.locator('.md-elapsed').innerText();
    step('경과 시간이 1초마다 올라간다', e1 !== e2, { e1, e2 });
    step('흐름도 가운데 칸이 만드는 중 상태다', (await real.locator('.md-node[data-node="make"]').getAttribute('data-state')) === 'work');
    await shot(real, 'working');
    calls.length = 0;
    await real.locator('.md-working .md-pill.stop').dblclick();
    await sleep(500);
    step('[중단]을 두 번 눌러도 중단 요청은 1번', calls.filter((c) => c === 'halt').length === 1, { calls });

    // 막힘·중단 화면
    await real.locator('.md-card[data-id="Wblocked/b"]').click();
    const probText = await real.locator('.md-problem').innerText();
    step('막힘: 이유 글과 "자동으로 다시 보내지 않아요" 안내와 다시 만들기 단추', probText.includes('grok login required') && probText.includes('자동으로 다시 보내지 않아요') && probText.includes('같은 지시로 다시 만들기'));
    await shot(real, 'tmp-blocked');
    await real.locator('.md-card[data-id="Wstop/b"]').click();
    step('중단한 작업: "중단했어요"', (await real.locator('.md-problem').innerText()).includes('중단했어요'));

    // 진짜 요청: 체크가 있어야 보낼 수 있다
    await real.locator('.md-new[data-kind="video"]').click();
    await real.locator('#md-dur-num').fill('7');
    await real.locator('#md-dur-num').blur();
    const realPrompt = '정확한 지시 글\n둘째 줄 <b>태그처럼 보이는 글</b>';
    await real.locator('#md-text').fill(realPrompt);
    await real.locator('.md-go').click();
    await real.locator('.md-dlg').waitFor();
    const rtext = await real.locator('.md-dlg').innerText();
    step('진짜 확인 창: 종류·길이·정확한 지시 글·비용 알 수 없음', rtext.includes('영상') && rtext.includes('7초') && rtext.includes('비용은 알 수 없어요') && (await real.locator('.md-exact').innerText()) === realPrompt);
    step('지시 글의 태그 모양 글자는 글자로만 보인다 (HTML로 해석하지 않음)', (await real.locator('.md-exact b').count()) === 0);
    step('체크 전에는 [한 번 보내기]가 꺼져 있다', await real.locator('.md-send').isDisabled() && (await real.locator('.md-send').innerText()) === '한 번 보내기');
    step('체크 글: "이 요청을 Grok에 한 번 보냅니다 · 비용 알 수 없음"', (await real.locator('.md-check').innerText()).includes('이 요청을 Grok에 한 번 보냅니다 · 비용 알 수 없음'));
    await shot(real, 'confirm');
    await real.locator('input[name="media-send-confirm"]').check();
    step('체크하면 켜진다', !(await real.locator('.md-send').isDisabled()));
    calls.length = 0;
    await real.locator('.md-send').dblclick();
    await real.locator('.md-dlg').waitFor({ state: 'detached', timeout: 15000 });
    await sleep(400);
    step('호출 순서: 계획(확인 때) → planner → Grok 계획 → 동의 → 시작, 시작은 1번', JSON.stringify(calls) === JSON.stringify(['planner', 'grok-plan', 'consent', 'start']), { calls });
    const startBody = JSON.parse(real.posts.filter((p) => p.path === '/api/workbench/start').pop().body);
    step('시작 본문: 승인 번호·계획 해시·확인함·같은 요청 번호·영상 길이', startBody.provider_grants.b === 'grant-1' && startBody.plan_hash === 'plan-hash-1' && startBody.confirmed === true && /^[0-9a-f]{32}$/.test(startBody.request_id)
      && startBody.graph.nodes[1].params.duration === 7 && startBody.graph.nodes[0].params.text === realPrompt && startBody.project !== undefined, { startBody });
    const consentBody = JSON.parse(real.posts.filter((p) => p.path === '/api/grok-everywhere/consent').pop().body);
    step('동의 본문: 정확한 요청(글·종류·길이)과 요청 해시·설정 해시', consentBody.request.kind === 'video' && consentBody.request.text === realPrompt && consentBody.request.duration === 7 && consentBody.request_hash === 'req-hash-1' && consentBody.config_hash === 'cfg-hash-1');
    step('시작되면 방금 만든 작업이 바로 선택돼 보인다', (await real.locator('.md-card.on').count()) === 1 && (await real.locator('.md-view .md-prompt').innerText()) === realPrompt);
    step('새 카드가 목록 맨 위에 있다', (await real.locator('.md-card').first().getAttribute('data-id')) === 'Wnew1/b');

    // 승인 실패: 시작하지 않고, 자동으로 다시 보내지 않는다고 알린다
    consentFails = true;
    await real.locator('.md-new[data-kind="image"]').click();
    step('보낸 뒤 새 요청 칸의 글상자는 비워져 있다 (같은 글을 실수로 또 보내지 않게)', (await real.locator('#md-text').inputValue()) === '');
    await real.locator('#md-text').fill('승인이 실패하는 요청');
    await real.locator('.md-go').click();
    await real.locator('.md-dlg').waitFor();
    await real.locator('input[name="media-send-confirm"]').check();
    calls.length = 0;
    await real.locator('.md-send').click();
    await real.locator('.md-err:not([hidden])').waitFor({ timeout: 10000 });
    const errText = await real.locator('.md-err').innerText();
    step('승인 실패: Grok에 보내지 않았다고, 자동으로 다시 보내지 않는다고 알린다 (시작은 부르지 않음)', errText.includes('Grok에는 아무것도 보내지 않았어요') && errText.includes('자동으로 다시 보내지 않아요') && !calls.includes('start'), { errText, calls });
    step('실패 뒤 [보내기]는 잠겨 있다 (같은 창에서 다시 보내지 못함)', await real.locator('.md-send').isDisabled());
    await shot(real, 'tmp-confirm-failed');
    await real.locator('.md-dlg-btns .btn', { hasText: '닫기' }).click();
    await real.locator('.md-dlg').waitFor({ state: 'detached' });
    consentFails = false;
    calls.length = 0;
    await real.locator('.md-go').click();
    await real.locator('.md-dlg').waitFor();
    step('다시 만들려면 새 확인 창이 열리고 체크도 처음부터 다시 받는다', await real.locator('.md-send').isDisabled() && !(await real.locator('input[name="media-send-confirm"]').isChecked()) && calls.includes('workbench-plan'));
    await real.locator('.md-dlg .x-btn').click();
    await real.locator('.md-dlg').waitFor({ state: 'detached' });

    // 읽기·보존: 3초 읽기가 돌고 있는 동안 입력·초점·재생이 끊기지 않는다
    await real.locator('.md-new[data-kind="image"]').click();
    await real.locator('#md-text').fill('읽는 중에도 지켜져야 하는 글');
    await real.locator('#md-text').focus();
    const g0 = real.countGet('/api/workbench/media');
    await sleep(7500);
    const g1 = real.countGet('/api/workbench/media');
    step('만드는 중인 작업이 있으면 약 3초마다 읽는다', g1 - g0 >= 2 && g1 - g0 <= 4, { read: g1 - g0 });
    step('읽는 동안에도 글상자 내용과 초점이 그대로다', (await real.locator('#md-text').inputValue()) === '읽는 중에도 지켜져야 하는 글' && (await real.evaluate(() => document.activeElement.id)) === 'md-text');
    // 재생 중인 영상: 선택(끝난 영상) → 재생 → 읽기가 지나가도 같은 <video>가 계속 재생된다
    const doneVideo = real.locator('.md-card', { hasText: '끝남' }).filter({ hasText: '영상' }).first();
    await doneVideo.click();
    await real.waitForFunction(() => { const v = document.querySelector('.md-result video.md-media'); return v && v.readyState >= 2; }, null, { timeout: 30000 });
    const pre = await real.evaluate(() => { const v = document.querySelector('.md-result video.md-media'); v.dataset.tag = 'same'; v.muted = true; return v.play().then(() => true, () => false); });
    await sleep(4500);
    const post = await real.evaluate(() => { const v = document.querySelector('.md-result video.md-media'); return { tag: v && v.dataset.tag, paused: v && v.paused, t: v && v.currentTime }; });
    step('재생 중인 영상은 읽기가 지나가도 끊기지 않는다 (같은 요소·계속 재생)', pre && post.tag === 'same' && post.paused === false && post.t > 1.5, post);
    step('영상 결과 아래에 "실제 10.04초"가 보인다', (await real.locator('.md-caption').innerText()).includes('실제 10.04초'));
    await shot(real, 'video', '.md-preview');
    // 화면을 떠나면 읽기가 멈춘다
    await real.locator('.bd-nav-btn[data-action="board"]').click();
    await sleep(500);
    const h0 = real.countGet('/api/workbench/media');
    await sleep(6500);
    step('이 화면을 떠나면 3초 읽기가 멈춘다', real.countGet('/api/workbench/media') === h0, { h0, now: real.countGet('/api/workbench/media') });
    await real.locator('.bd-nav-btn[data-action="media"]').click();
    await sleep(600);
    step('돌아오면 다시 읽기 시작한다', real.countGet('/api/workbench/media') > h0);
    step('진짜 경로 한 바퀴: 페이지 오류 없음', real.errors.length === 0, { errors: real.errors });
    await real.close();

    // ======================================================================== 2b. 처음 쓰는 모습: 연결됨 + 만든 것이 아직 없음
    const fresh = await newPage(browser, base);
    await patchMedia(fresh, (data) => { data.connection = REAL_CONN; data.capabilities = realCaps(); data.jobs = []; });
    await openMedia(fresh);
    step('처음 쓰는 모습: 연결됨 · 목록은 안내 한 줄 · 빈 화면 안내와 예시 3개', (await fresh.locator('.md-conn.on').count()) === 1 && (await fresh.locator('.md-listnote').innerText()).includes('아직 만든 것이 없어요')
      && (await fresh.locator('.md-empty .md-example').count()) === 3 && (await fresh.locator('.md-card').count()) === 0);
    await shot(fresh, 'empty');
    step('처음 쓰는 모습: 페이지 오류 없음', fresh.errors.length === 0, { errors: fresh.errors });
    await fresh.close();

    // ======================================================================== 3. 연결 안 됨 + 연결 창
    const off = await newPage(browser, base, { ignore: [/Failed to load resource/] });
    await patchMedia(off, (data) => { data.connection = { enabled: false, configured: false, auth_verified: false, reason: 'blocked' }; data.capabilities = offCaps(); data.jobs = []; });
    let configureBody = null;
    await off.route('**/api/grok-everywhere/catalog', (route) => route.fulfill(fulfill({ skills: [], connection: { enabled: false, configured: false, auth_verified: false } })));
    await off.route('**/api/grok-everywhere/connection-plan', (route) => route.fulfill(fulfill({ review_hash: 'review-1', consents: ['read-only-login', 'media-only'], cli_version: 'grok 1.2.3', config: { cli_path: 'C:/Tools/grok/grok.exe' } })));
    await off.route('**/api/grok-everywhere/configure', (route) => { configureBody = JSON.parse(route.request().postData()); route.fulfill(fulfill({ ok: true })); });
    await openMedia(off);
    step('연결 안 됨: 칩과 [연결하기] 단추, 목록은 빈 안내', (await off.locator('.md-conn.off').innerText()).includes('Grok 연결 안 됨') && (await off.locator('.md-head .md-pill.dark').innerText()).includes('연결하기')
      && (await off.locator('.md-listnote').innerText()).includes('아직 만든 것이 없어요'));
    await off.locator('#md-text').fill('연결 전에 적어 둔 글');
    step('연결 안 됨이면 [만들기]가 "연결하고 만들기"로 바뀌고 켜져 있다', (await off.locator('.md-go').innerText()).includes('연결하고 만들기') && !(await off.locator('.md-go').isDisabled()));
    await off.locator('.md-go').click();
    await off.locator('.md-dlg').waitFor();
    const ctext = await off.locator('.md-dlg').innerText();
    step('연결 창: 쉬운 설명 4줄과 찾은 프로그램', ctext.includes('아직 연결되지 않았어요') && ctext.includes('로그인 정보 파일은 AI 스튜디오가 읽지 않아요') && ctext.includes('요청마다 한 번씩 승인') && ctext.includes('구독 요금제로 되는지는 확인되지 않았어요') && ctext.includes('grok.exe'));
    step('허용 체크 전에는 [연결하기]가 꺼져 있다', await off.locator('.md-dlg .btn.primary').isDisabled());
    await shot(off, 'connect');
    await off.locator('input[name="media-connect-confirm"]').check();
    await off.locator('.md-dlg .btn.primary').click();
    await off.locator('.md-dlg').waitFor({ state: 'detached', timeout: 10000 });
    step('연결하기: configure에 방식·검토 해시·동의 목록을 보낸다', configureBody && configureBody.mode === 'official_cli' && configureBody.review_hash === 'review-1' && JSON.stringify(configureBody.consents) === JSON.stringify(['read-only-login', 'media-only']), { configureBody });
    step('연결 안 됨 화면: 페이지 오류 없음', off.errors.length === 0, { errors: off.errors });
    await off.close();

    ok = true;
  } finally {
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
    await browser.close();
    await stopFixture(fixture);
  }
  console.log(ok ? `\n이미지·영상 작업대 브라우저 점검 통과 (${report.steps.length}개)` : '\n점검 실패');
  process.exit(ok ? 0 : 1);
})().catch(async (e) => { console.error(e.message); process.exit(1); });
