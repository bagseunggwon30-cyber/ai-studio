'use strict';
// 외부 연결 창 점검: node tools/dev/gateway_browser.cjs [--shots] [--port 8805]
// 연습용 임시 회사(tools/dev/gateway_fixture.py: 가짜 실행기, 진짜 직원·Grok·인터넷 없음)를 직접 띄워 Playwright(Edge)로 눌러 본다. 끝나면 서버를 끈다.
// 대시보드는 --port(기본 8805), 연결 문은 그 다음 포트(8806, 127.0.0.1에만)에 열린다. 포트는 8805~8810 안에서만 쓴다.
// 앱 쪽(ChatGPT 흉내)은 node http로 이 PC의 연결 문에만 말을 건다 (터널·인터넷 없음). --shots 면 docs/design/captures/modern-gateway-*.png 를 남긴다.
const { chromium } = (() => {
  for (const p of [process.env.PLAYWRIGHT_CORE, 'playwright-core', 'playwright']) {
    if (!p) continue;
    try { return require(p); } catch (_) { /* 다음 */ }
  }
  throw new Error('playwright-core를 찾지 못했습니다.');
})();
const { spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');

const root = path.resolve(__dirname, '..', '..');
const args = process.argv.slice(2);
const SHOTS = args.includes('--shots');
const PORT = args.includes('--port') ? Number(args[args.indexOf('--port') + 1]) : 8805;
const GW_PORT = PORT + 1;
if (PORT < 8805 || GW_PORT > 8810) throw new Error('포트는 8805~8810 안에서만 쓸 수 있어요.');
const capDir = path.join(root, 'docs', 'design', 'captures');
const edge = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe'].find((p) => fs.existsSync(p));
if (!edge) throw new Error('Microsoft Edge를 찾지 못했습니다.');

const PUBLIC = 'https://gw.example.test';
const CHATGPT = 'https://chatgpt.com/connector_platform_oauth_redirect';
let passed = 0;
const step = (name, ok, extra = {}) => {
  if (!ok) { console.log(`  ✗ ${name} ${JSON.stringify(extra)}`); throw new Error('실패: ' + name + ' ' + JSON.stringify(extra)); }
  passed += 1;
  console.log(`  ✓ ${name}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- 연습용 서버
function startFixture() {
  return new Promise((resolve, reject) => {
    const child = spawn('python', ['-X', 'utf8', 'tools/dev/gateway_fixture.py', '--port', String(PORT), '--gateway-port', String(GW_PORT)], { cwd: root, stdio: ['pipe', 'pipe', 'pipe'] });
    let buf = '';
    let err = '';
    const timer = setTimeout(() => reject(new Error('연습용 서버가 60초 안에 뜨지 않았어요: ' + err)), 60000);
    child.stderr.on('data', (d) => { err += d; });
    child.stdout.on('data', (d) => { buf += d; if (buf.split('\n').some((l) => l.startsWith('{'))) { clearTimeout(timer); resolve({ child, url: `http://127.0.0.1:${PORT}/` }); } });
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
const listening = (port) => new Promise((resolve) => {
  const s = net.connect({ port, host: '127.0.0.1' });
  s.once('connect', () => { s.destroy(); resolve(true); });
  s.once('error', () => resolve(false));
});

// ---- 앱 쪽 흉내 (연결 문에만 말한다. Host는 공개 주소로)
function gw(method, p, { body, type, headers } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: GW_PORT, method, path: p, headers: { Host: 'gw.example.test', ...(type ? { 'Content-Type': type } : {}), ...(body ? { 'Content-Length': Buffer.byteLength(body) } : {}), ...(headers || {}) } }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(chunks).toString('utf8') }));
    });
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}
async function connectApp(code, name, scope = 'studio:read studio:submit') {
  const reg = await gw('POST', '/oauth/register', { type: 'application/json', body: JSON.stringify({ redirect_uris: [CHATGPT], client_name: name, token_endpoint_auth_method: 'none', grant_types: ['authorization_code', 'refresh_token'], response_types: ['code'] }) });
  const client = JSON.parse(reg.text);
  const verifier = crypto.randomBytes(40).toString('base64url');
  const challenge = crypto.createHash('sha256').update(verifier).digest('base64url');
  const q = new URLSearchParams({ response_type: 'code', client_id: client.client_id, redirect_uri: CHATGPT, code_challenge: challenge, code_challenge_method: 'S256', state: 's1', scope, resource: PUBLIC + '/mcp' });
  const page = await gw('GET', '/oauth/authorize?' + q);
  const form = /name="form_id" value="([^"]+)"/.exec(page.text)[1];
  const ok = await gw('POST', '/oauth/authorize', { type: 'application/x-www-form-urlencoded', body: new URLSearchParams({ form_id: form, code, decision: 'allow' }).toString() });
  if (ok.status !== 302) throw new Error('동의가 안 됐어요: ' + ok.status);
  const authCode = new URL(ok.headers.location).searchParams.get('code');
  const tok = await gw('POST', '/oauth/token', { type: 'application/x-www-form-urlencoded', body: new URLSearchParams({ grant_type: 'authorization_code', code: authCode, redirect_uri: CHATGPT, client_id: client.client_id, code_verifier: verifier, resource: PUBLIC + '/mcp' }).toString() });
  return JSON.parse(tok.text);
}
const mcpTools = async (token) => {
  const r = await gw('POST', '/mcp', { type: 'application/json', headers: { Accept: 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-11-25', ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }) });
  return { status: r.status, tools: r.status === 200 ? JSON.parse(r.text).result.tools.map((t) => t.name) : [] };
};

// ---- 페이지 도구
async function newPage(context, base) {
  const page = await context.newPage();
  await page.setViewportSize({ width: 1536, height: 1024 });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) errors.push(m.type() + ': ' + m.text()); });
  const posts = [];
  page.on('request', (r) => { if (r.method() === 'POST') posts.push(new URL(r.url()).pathname); });
  page.errors = errors;
  page.posts = posts;
  page.count = (p) => posts.filter((x) => x === p).length;
  page.base = base;
  return page;
}
async function shot(page, name) {
  if (!SHOTS) return;
  fs.mkdirSync(capDir, { recursive: true });
  await page.waitForFunction(() => { const n = document.querySelector('#notice'); return !n || n.classList.contains('hidden'); }, null, { timeout: 15000 }).catch(() => {});
  await page.mouse.move(5, 5);
  await sleep(250);
  await page.screenshot({ path: path.join(capDir, `modern-gateway-${name}.png`) });
  console.log(`    (캡처 modern-gateway-${name}.png)`);
}
const gwApi = async (page, p = '/api/gateway') => page.evaluate(async (url) => (await fetch(url, { cache: 'no-store' })).json(), p);
const text = (page, sel) => page.locator(sel).first().innerText();

(async () => {
  console.log('연습용 서버를 띄우는 중…');
  const fixture = await startFixture();
  const browser = await chromium.launch({ executablePath: edge, headless: true });
  const context = await browser.newContext({ permissions: ['clipboard-read', 'clipboard-write'] });
  let ok = false;
  try {
    step('연결 문 포트는 처음에 닫혀 있다 (기본 꺼짐)', !(await listening(GW_PORT)));
    const page = await newPage(context, fixture.url);
    await page.goto(fixture.url + '#view=board');
    await page.locator('.bd-nav-btn[data-action="gateway"]').waitFor({ timeout: 30000 });
    step('왼쪽 메뉴 \'회사\' 묶음에 \'외부 연결\'이 있다 (직원·스킬·MCP·자동 업무 다음)', await page.evaluate(() => {
      const g = [...document.querySelectorAll('.bd-nav-group')].find((x) => x.getAttribute('aria-label') === '회사');
      return g && [...g.querySelectorAll('.bd-nav-btn')].map((b) => b.innerText.trim()).join('|') === '직원|스킬 학습|MCP 보관소|자동 업무|외부 연결' && g.querySelector('[data-action="gateway"] svg');
    }));
    await page.locator('.bd-nav-btn[data-action="gateway"]').click();
    await page.locator('.pop.gw').waitFor();
    await page.locator('.gw-switch:not([disabled])').waitFor();

    // ---------------------------------------------------------------- 1. 처음 모습
    const lead = await page.locator('.gw-lead li').allInnerTexts();
    step('맨 위 쉬운 설명 3줄 (무엇이 가능한지 · 안전장치 · 끄는 법)', lead.length === 3 && /일을 맡기고 결과를 볼 수/.test(lead[0]) && /연결 번호/.test(lead[1]) && /스위치를 끄거나/.test(lead[2]));
    step('스위치는 꺼짐, 칩은 \'꺼짐\', 문이 닫혀 있다는 안내', (await page.getAttribute('.gw-switch', 'aria-checked')) === 'false' && (await text(page, '.gw-power .gw-chip')) === '꺼짐' && /문이 닫혀 있어요/.test(await text(page, '.gw-power .gw-hint:last-child')));
    step('연결 번호 만들기는 꺼져 있는 동안 잠겨 있다 · 붙여 넣을 주소·복사도 비어 잠김', await page.getByRole('button', { name: '연결 번호 만들기' }).isDisabled() && (await page.inputValue('input[aria-label="연결에 붙여 넣을 주소"]')) === '' && await page.getByRole('button', { name: '복사' }).isDisabled());
    step('권한: 읽기만이 기본으로 골라져 있고 프로젝트 두 개가 목록에 있다 (폴더 범위는 기본값)', await page.evaluate(() => {
      const r = document.querySelector('input[name="gw-mode"][value="false"]');
      const rows = [...document.querySelectorAll('.gw-proj')];
      return r.checked && rows.length === 2 && rows.every((x) => !x.querySelector('input[type=checkbox]').checked && x.querySelector('input[data-role=paths]').disabled) && rows[0].querySelector('input[data-role=paths]').value === 'docs/**'
        && document.querySelectorAll('select[data-role=level]').length === 0;
    }));
    step('연결된 앱 · 최근 기록은 비어 있고 위험 안내가 맨 아래에 있다', (await text(page, '.gw-apps')).includes('연결된 앱이 아직 없어요') && (await text(page, '.gw-log')).includes('아직 기록이 없어요')
      && /결재와 완료는 항상 사장님이 해요/.test(await text(page, '.gw-danger')));
    await shot(page, 'off');

    // ---------------------------------------------------------------- 2. 공개 주소 검사 (거절은 서버에 보내지 않는다)
    const before = page.count('/api/gateway/config');
    const bads = [['', '넣어 주세요'], ['http://gw.example.test', 'https://'], ['https://gw.example.test/mcp', '경로'], ['https://127.0.0.1', '숫자 주소'], ['gw.example.test', 'https://']];
    for (const [value, word] of bads) {
      await page.fill('#gw-url', value);
      await page.locator('.gw-switch').click();
      const msg = await text(page, '#gw-url-msg');
      step(`공개 주소 '${value || '(빈 값)'}' 거절: ${msg.slice(0, 28)}…`, msg.includes(word) && (await page.getAttribute('.gw-switch', 'aria-checked')) === 'false' && await page.locator('#gw-url-msg.err').count() === 1);
    }
    step('거절된 주소는 서버에 보내지 않았다', page.count('/api/gateway/config') === before);
    await shot(page, 'error');
    await page.fill('#gw-url', 'https://nas.local');
    await page.getByRole('button', { name: '주소 저장' }).click();
    step('집 안 주소(.local)는 저장 단추에서도 거절', /집 안/.test(await text(page, '#gw-url-msg')) && page.count('/api/gateway/config') === before);

    // ---------------------------------------------------------------- 3. 켜기
    await page.fill('#gw-url', PUBLIC + '/');
    await page.locator('.gw-switch').dblclick(); // 더블클릭해도 한 번만
    await page.waitForFunction(() => document.querySelector('.gw-switch').getAttribute('aria-checked') === 'true');
    await page.waitForFunction(() => !document.querySelector('.gw-switch').disabled);
    step('스위치를 더블클릭해도 요청은 한 번만 간다', page.count('/api/gateway/config') === before + 1, { n: page.count('/api/gateway/config') - before });
    step('켜지면 칩 \'켜짐\', 이 PC 안 주소 안내, 붙여 넣을 주소가 https://…/mcp', (await text(page, '.gw-power .gw-chip')).startsWith('켜짐') && (await text(page, '.gw-power .gw-hint:last-child')).includes(`http://127.0.0.1:${GW_PORT}`)
      && (await page.inputValue('input[aria-label="연결에 붙여 넣을 주소"]')) === PUBLIC + '/mcp' && (await page.inputValue('#gw-url')) === PUBLIC + '/');
    step('이제 연결 문 포트가 127.0.0.1에 열려 있다', await listening(GW_PORT));
    const state = await gwApi(page);
    step('서버 상태: 켜짐·열림, 공개 주소는 정규화돼 저장', state.enabled && state.running && state.public_url === PUBLIC && state.mcp_url === PUBLIC + '/mcp');
    await page.getByRole('button', { name: '복사' }).click();
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    step('복사 단추: 클립보드에 주소가 들어가고 안내가 뜬다', clip === PUBLIC + '/mcp' && /복사했어요/.test(await page.locator('.gw-msg:not([hidden])', { hasText: '복사했어요' }).first().innerText()));

    // ---------------------------------------------------------------- 4. 연결 번호
    const codeBefore = page.count('/api/gateway/code');
    await page.getByRole('button', { name: '연결 번호 만들기' }).dblclick();
    await page.locator('.gw-code').waitFor();
    await page.waitForFunction(() => !document.querySelector('.gw-switch').disabled);
    const code = (await text(page, '.gw-code')).trim();
    step('연결 번호: 큰 글자 XXXX-XXXX, 더블클릭해도 번호는 한 번만 만든다', /^[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}$/.test(code) && page.count('/api/gateway/code') === codeBefore + 1, { code: code.replace(/./g, '*') });
    const left1 = await text(page, '.gw-codeleft');
    await sleep(2200);
    const left2 = await text(page, '.gw-codeleft');
    const secs = (s) => { const m = /(\d+):(\d\d)/.exec(s); return Number(m[1]) * 60 + Number(m[2]); };
    step('남은 시간이 줄어든다 (5분부터)', /남은 시간 [45]:\d\d/.test(left1) && secs(left2) < secs(left1), { left1, left2 });
    const fontPx = await page.locator('.gw-code').evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    step('번호 글자는 크다 (36px 이상)', fontPx >= 36, { fontPx });
    await shot(page, 'on');

    // ---------------------------------------------------------------- 5. 권한 정하기
    await page.locator('label.gw-mode', { hasText: '일 맡기기도 허용' }).click();
    const demo = page.locator('.gw-proj[data-project="demo"]');
    await demo.locator('input[data-focus-key="gw-proj-demo"]').check();
    step('프로젝트를 고르면 폴더 범위 칸이 풀린다', await demo.locator('input[data-role=paths]').isEnabled());
    const levelSel = demo.locator('select[data-role=level]');
    const otherSel = page.locator('.gw-proj:not([data-project="demo"]) select[data-role=level]').first();
    step('일 맡기기 모드에서는 프로젝트마다 단계 선택칸(읽기만·일 맡기기·일 맡기기 + 실행 시작)이 있고, 고른 프로젝트만 풀린다 (처음엔 읽기만)',
      (await levelSel.isEnabled()) && (await levelSel.inputValue()) === 'read' && (await otherSel.isDisabled()) && (await otherSel.inputValue()) === 'read'
      && (await levelSel.getAttribute('data-focus-key')) === 'gw-level-demo'
      && JSON.stringify(await levelSel.locator('option').evaluateAll((os) => os.map((o) => [o.value, o.textContent]))) === JSON.stringify([['read', '읽기만'], ['submit', '일 맡기기'], ['run', '일 맡기기 + 실행 시작']])
      && (await page.locator('input[data-role=write]').count()) === 0);
    step('단계마다 한 줄 설명이 바뀐다 (읽기만 → 일 맡기기: 사장님이 [실행] → 실행 시작: 사용량)', await (async () => {
      const hint = demo.locator('[data-role=level-hint]');
      const a = await hint.innerText();
      await levelSel.selectOption('submit');
      const b = await hint.innerText();
      const warnB = await hint.evaluate((el) => el.classList.contains('warn'));
      await levelSel.selectOption('run');
      const c = await hint.innerText();
      const warnC = await hint.evaluate((el) => el.classList.contains('warn'));
      await levelSel.selectOption('read');
      return /읽기만 해요/.test(a) && /\[실행\]을 눌러야/.test(b) && !warnB && /직접 실행을 시작해요/.test(c) && /사용량/.test(c) && warnC && /읽기만 해요/.test(await hint.innerText());
    })());
    step('프로젝트 줄은 두 줄: 윗줄(체크·폴더 범위) 아래에 단계 선택칸이 있고 칸 밖으로 안 나간다', await demo.evaluate((box) => {
      const b = box.getBoundingClientRect();
      const top = box.querySelector('.gw-proj-top').getBoundingClientRect();
      const lvl = box.querySelector('.gw-proj-level').getBoundingClientRect();
      const sel = box.querySelector('select').getBoundingClientRect();
      return lvl.top >= top.bottom - 1 && sel.right <= b.right + 1 && sel.left >= b.left - 1 && box.scrollWidth <= box.clientWidth + 1;
    }));
    await demo.locator('input[data-role=paths]').fill('../x');
    await page.getByRole('button', { name: '권한 저장' }).click();
    await page.locator('.gw-card:has(.gw-perm) .gw-msg.err').waitFor();
    const permErr = await page.locator('.gw-card:has(.gw-perm) .gw-msg.err').innerText();
    step('잘못된 폴더 범위는 쉬운 오류로 (서버의 기존 검사)', /[가-힣]/.test(permErr) && !(await gwApi(page)).permissions.submit, { permErr });
    await demo.locator('input[data-role=paths]').fill('docs/**, notes/a.md');
    await page.getByRole('button', { name: '권한 저장' }).click();
    await page.locator('.gw-card:has(.gw-perm) .gw-msg', { hasText: '권한을 저장했어요' }).waitFor();
    const perm0 = (await gwApi(page)).permissions;
    step('권한 저장: 단계를 올리지 않은 프로젝트는 읽기만 (write=false, run=false)', perm0.projects.demo.write === false && perm0.projects.demo.run === false, perm0);
    await levelSel.selectOption('submit');
    await page.getByRole('button', { name: '권한 저장' }).click();
    await page.locator('.gw-card:has(.gw-perm) .gw-msg', { hasText: '권한을 저장했어요' }).waitFor();
    const perm = (await gwApi(page)).permissions;
    step('권한 저장: 일 맡기기 허용 + 고른 프로젝트·폴더만, \'일 맡기기\' 단계는 write만 켜고 run은 꺼짐', perm.submit === true && JSON.stringify(Object.keys(perm.projects)) === '["demo"]' && JSON.stringify(perm.projects.demo.paths) === '["docs/**","notes/a.md"]' && perm.projects.demo.write === true && perm.projects.demo.run === false, perm);
    await sleep(6500); // 다시 읽어 와도 입력·선택이 그대로
    step('5초 갱신이 지나도 고른 권한·단계·입력이 지워지지 않는다', await page.evaluate(() => document.querySelector('input[name="gw-mode"][value="true"]').checked && document.querySelector('.gw-proj[data-project="demo"] input[data-role=paths]').value === 'docs/**, notes/a.md'
      && document.querySelector('.gw-proj[data-project="demo"] select[data-role=level]').value === 'submit'));

    // ---------------------------------------------------------------- 6. 앱 연결 (ChatGPT 흉내) → 목록·기록
    const tokens = await connectApp(code, 'ChatGPT 시험');
    step('앱이 연결 번호로 연결됨 (토큰 받음)', Boolean(tokens.access_token) && tokens.scope === 'studio:read studio:submit');
    const tools = await mcpTools(tokens.access_token);
    step('일 맡기기 단계 연결은 도구 8개가 보이고 run_task는 안 보인다', tools.status === 200 && tools.tools.length === 8 && !tools.tools.includes('run_task'), tools);
    await page.locator('.gw-app').first().waitFor({ timeout: 12000 });
    const appName = await text(page, '.gw-app b');
    step('연결된 앱 목록: 이름 · 권한 칩 · 마지막 사용 · [끊기]', appName === 'ChatGPT 시험' && (await text(page, '.gw-app .gw-chip')) === '읽기 + 일 맡기기' && /마지막 사용/.test(await text(page, '.gw-app-meta')) && await page.getByRole('button', { name: 'ChatGPT 시험 끊기' }).isVisible());
    await page.waitForFunction(() => document.querySelectorAll('.gw-log-row').length >= 4, null, { timeout: 12000 });
    const rows = await page.locator('.gw-log-row').allInnerTexts();
    step('최근 기록: 시각 · 무슨 일 · 결과가 쉬운 말로 (번호 만들기·연결 승인·토큰 발급)', rows.some((r) => /연결 번호를 만들었어요/.test(r)) && rows.some((r) => /연결을 승인했어요: ChatGPT 시험/.test(r)) && rows.some((r) => /토큰을 발급했어요/.test(r)) && rows.every((r) => /\d\d:\d\d:\d\d/.test(r) && /(성공|거절|오류)/.test(r)), { rows });
    step('기록에 비밀(토큰·번호)이 없다', !rows.join('\n').includes(tokens.access_token) && !rows.join('\n').includes(code));
    await page.waitForFunction(() => !document.querySelector('.gw-code') || document.querySelector('.gw-codebox').hidden === false);
    await shot(page, 'apps');
    await page.locator('.pop.gw').evaluate((el) => el.scrollTo(0, el.scrollHeight));
    await shot(page, 'log');
    await page.locator('.pop.gw').evaluate((el) => el.scrollTo(0, 0));

    // 6-2. 실행 시작 단계: 고르고 저장하면 이미 연결된 앱의 도구 목록에 run_task가 바로 생기고, 내리면 바로 사라진다
    await levelSel.selectOption('run');
    step('\'일 맡기기 + 실행 시작\'을 고르면 설명에 사용량이 보이고 눈에 띄게 표시된다', /직접 실행을 시작해요/.test(await text(page, '.gw-proj[data-project="demo"] [data-role=level-hint]')) && await page.locator('.gw-proj[data-project="demo"] .gw-level-hint.warn').count() === 1);
    for (const [w, h2] of [[1536, 1024], [1280, 720], [1000, 1000], [1366, 768]]) {
      await page.setViewportSize({ width: w, height: h2 });
      await sleep(250);
      const fit = await page.evaluate(() => {
        const gwEl = document.querySelector('.pop.gw');
        const r = gwEl.getBoundingClientRect();
        const over = [...gwEl.querySelectorAll('*')].filter((el) => { const b = el.getBoundingClientRect(); return b.width > 0 && (b.right > r.right + 1 || b.left < r.left - 1); }).map((el) => el.className);
        const projs = [...document.querySelectorAll('.gw-proj')].every((box) => {
          const b = box.getBoundingClientRect();
          return [...box.querySelectorAll('*')].every((el) => { const c = el.getBoundingClientRect(); return c.width === 0 || (c.right <= b.right + 1 && c.left >= b.left - 1); }) && box.scrollWidth <= box.clientWidth + 1;
        });
        return { doc: document.documentElement.scrollWidth <= window.innerWidth, inside: r.left >= -1 && r.right <= window.innerWidth + 1, innerH: gwEl.scrollWidth <= gwEl.clientWidth + 1, projs, over: over.slice(0, 3) };
      });
      step(`일 맡기기 모드 ${w}×${h2}: 프로젝트 줄(두 줄)이 칸 밖으로 안 나가고 문서 넘침이 없다`, fit.doc && fit.inside && fit.innerH && fit.projs && !fit.over.length, fit);
    }
    await page.setViewportSize({ width: 1536, height: 1024 });
    await shot(page, 'perm-run');
    const runSaves = page.count('/api/gateway/permissions');
    await page.getByRole('button', { name: '권한 저장' }).click();
    await page.locator('.gw-card:has(.gw-perm) .gw-msg', { hasText: '권한을 저장했어요' }).waitFor();
    const permRun = (await gwApi(page)).permissions;
    step('실행 시작 단계 저장: write와 run이 모두 켜진다 (요청은 한 번)', permRun.projects.demo.write === true && permRun.projects.demo.run === true && page.count('/api/gateway/permissions') === runSaves + 1, permRun);
    const withRun = await mcpTools(tokens.access_token);
    step('이미 연결된 앱의 도구 목록에 run_task가 바로 생긴다 (도구 9개, 읽기 6개)', withRun.tools.length === 9 && withRun.tools.includes('run_task'), withRun);
    await sleep(6500);
    step('5초 갱신이 지나도 \'실행 시작\' 단계가 그대로 보인다', (await levelSel.inputValue()) === 'run' && /직접 실행을 시작해요/.test(await text(page, '.gw-proj[data-project="demo"] [data-role=level-hint]')));
    await page.keyboard.press('Escape');
    await page.locator('.bd-nav-btn[data-action="gateway"]').click();
    await page.locator('.pop.gw').waitFor();
    await page.locator('.gw-proj[data-project="demo"] select[data-role=level]').waitFor();
    step('창을 닫았다 다시 열어도 저장된 단계(실행 시작)를 읽어 온다', await page.waitForFunction(() => { const s = document.querySelector('.gw-proj[data-project="demo"] select[data-role=level]'); return s && s.value === 'run' && !s.disabled; }).then(() => true));
    await page.fill('#gw-url', PUBLIC + '/'); // 다시 열면 저장된 주소로 돌아가 있으니, 뒤 단계(취소해도 입력이 그대로)를 위해 처음처럼 입력해 둔다
    await page.locator('.gw-proj[data-project="demo"] select[data-role=level]').selectOption('submit');
    await page.getByRole('button', { name: '권한 저장' }).click();
    await page.locator('.gw-card:has(.gw-perm) .gw-msg', { hasText: '권한을 저장했어요' }).waitFor();
    const backDown = await mcpTools(tokens.access_token);
    step('단계를 \'일 맡기기\'로 내리면 같은 앱의 run_task가 바로 사라진다 (도구 8개)', backDown.tools.length === 8 && !backDown.tools.includes('run_task') && (await gwApi(page)).permissions.projects.demo.run === false, backDown);

    // 끝: 이름에 HTML이 든 앱은 글자 그대로
    await page.getByRole('button', { name: '연결 번호 만들기' }).click();
    await page.waitForFunction((old) => { const el = document.querySelector('.gw-code'); return el && el.textContent.trim() && el.textContent.trim() !== old; }, code);
    const code2 = (await text(page, '.gw-code')).trim();
    await connectApp(code2, '<img src=x onerror=window.__gwx=1>"&');
    await page.waitForFunction(() => document.querySelectorAll('.gw-app').length === 2, null, { timeout: 12000 });
    step('앱 이름의 HTML은 글자로만 보인다 (태그·스크립트가 만들어지지 않음)', await page.evaluate(() => !document.querySelector('.gw img') && !window.__gwx && [...document.querySelectorAll('.gw-app b')].some((b) => b.textContent.startsWith('<img src=x'))));

    // ---------------------------------------------------------------- 7. 권한을 줄이면 바로 적용 · 끊기
    await page.locator('label.gw-mode', { hasText: '읽기만 (기본)' }).click();
    await page.getByRole('button', { name: '권한 저장' }).click();
    await page.locator('.gw-card:has(.gw-perm) .gw-msg', { hasText: '권한을 저장했어요' }).waitFor();
    const lowered = await mcpTools(tokens.access_token);
    step('일 맡기기를 끄면 이미 연결된 앱도 바로 읽기 도구 6개만 보인다', lowered.tools.length === 6 && !lowered.tools.includes('submit_task'), lowered);
    await page.waitForFunction(() => [...document.querySelectorAll('.gw-app .gw-chip')].every((c) => /꺼짐|읽기만/.test(c.textContent)), null, { timeout: 12000 });
    const delBefore = page.count('/api/gateway/revoke');
    await page.getByRole('button', { name: 'ChatGPT 시험 끊기' }).dblclick();
    await page.waitForFunction(() => document.querySelectorAll('.gw-app').length === 1);
    step('[끊기] 한 번만 보내고 목록에서 사라진다', page.count('/api/gateway/revoke') === delBefore + 1);
    const dead = await mcpTools(tokens.access_token);
    step('끊은 앱의 토큰은 바로 401', dead.status === 401, dead);
    await page.getByRole('button', { name: '모두 끊기' }).click();
    await page.locator('.dialog', { hasText: '모두 끊을까요' }).waitFor();
    step('[모두 끊기]는 확인 창이 먼저 뜬다', true);
    await page.locator('.dialog .btn', { hasText: '취소' }).click();
    await page.locator('.pop.gw').waitFor();
    step('취소하면 연결은 그대로, 열려 있던 창으로 돌아온다 (입력도 그대로)', (await page.locator('.gw-app').count()) === 1 && (await page.inputValue('#gw-url')) === PUBLIC + '/');
    await page.fill('#gw-url', 'https://other.example.test');
    await page.getByRole('button', { name: '주소 바꾸기' }).click();
    await page.locator('.dialog', { hasText: '공개 주소를 바꿀까요' }).waitFor();
    const cfgBefore = page.count('/api/gateway/config');
    await page.locator('.dialog .btn', { hasText: '취소' }).click();
    step('주소를 바꾸려 하면 \'연결된 앱이 모두 끊겨요\' 확인 창, 취소하면 보내지 않는다', page.count('/api/gateway/config') === cfgBefore && (await gwApi(page)).public_url === PUBLIC);
    await page.fill('#gw-url', PUBLIC);
    await page.getByRole('button', { name: '모두 끊기' }).click();
    await page.locator('.dialog .btn.danger', { hasText: '모두 끊기' }).click();
    await page.waitForFunction(() => document.querySelectorAll('.gw-app').length === 0);
    step('확인하면 모두 끊긴다', (await gwApi(page)).connections.length === 0);

    // ---------------------------------------------------------------- 8. 끄기
    await page.locator('.gw-switch').click();
    await page.waitForFunction(() => document.querySelector('.gw-switch').getAttribute('aria-checked') === 'false');
    await sleep(300);
    step('끄면 칩 \'꺼짐\'이고 포트가 닫히고 연결 번호 단추도 잠긴다', (await text(page, '.gw-power .gw-chip')) === '꺼짐' && !(await listening(GW_PORT)) && await page.getByRole('button', { name: '연결 번호 만들기' }).isDisabled());
    step('끈 상태로 다시 읽어도 저장된 주소가 남아 있다', (await gwApi(page)).public_url === PUBLIC && !(await gwApi(page)).enabled);

    // ---------------------------------------------------------------- 9. 창 크기·키보드·닫기
    for (const [w, h2] of [[1536, 1024], [1280, 720], [1000, 1000], [1864, 990], [1366, 768]]) {
      await page.setViewportSize({ width: w, height: h2 });
      await sleep(250);
      const fit = await page.evaluate(() => {
        const gwEl = document.querySelector('.pop.gw');
        const r = gwEl.getBoundingClientRect();
        const over = [...gwEl.querySelectorAll('*')].filter((el) => { const b = el.getBoundingClientRect(); return b.width > 0 && (b.right > r.right + 1 || b.left < r.left - 1); }).map((el) => el.className);
        return { doc: document.documentElement.scrollWidth <= window.innerWidth, inside: r.left >= -1 && r.right <= window.innerWidth + 1 && r.top >= -1 && r.bottom <= window.innerHeight + 1, innerH: gwEl.scrollWidth <= gwEl.clientWidth + 1, over: over.slice(0, 3) };
      });
      step(`창 ${w}×${h2}: 문서 넘침 없음 · 창이 화면 안 · 안쪽 칸이 창 밖으로 안 나감`, fit.doc && fit.inside && fit.innerH && !fit.over.length, fit);
    }
    await page.setViewportSize({ width: 1536, height: 1024 });
    await page.locator('#gw-url').focus();
    await page.keyboard.press('Escape');
    step('Esc로 닫힌다', await page.locator('.pop.gw').count() === 0);
    await page.locator('.bd-nav-btn[data-action="gateway"]').click();
    await page.locator('.pop.gw').waitFor();
    step('다시 열면 저장된 설정을 읽어 온다 (끔 · 주소 · 권한은 읽기만)', await page.waitForFunction(() => document.querySelector('#gw-url').value === 'https://gw.example.test' && document.querySelector('.gw-switch').getAttribute('aria-checked') === 'false').then(() => true));
    await page.keyboard.press('Escape');

    // 빠른 찾기에서도 열린다
    await page.keyboard.press('Control+k');
    await page.fill('#board-search', '외부 연결');
    await page.waitForFunction(() => /외부 연결/.test(document.querySelector('.bd-find, #board-find-list, .fd-list, [role=listbox]')?.innerText || document.body.innerText));
    step('빠른 찾기(Ctrl K)에서 \'외부 연결\'을 찾을 수 있다', true);

    // 일부러 보낸 잘못된 폴더 범위(../x) 한 번이 서버에서 400으로 거절된 기록은 브라우저가 콘솔에 남긴다: 그 한 건만 빼고 오류가 없어야 한다
    const real = page.errors.filter((e, i, all) => !(/status of 400/.test(e) && all.findIndex((x) => /status of 400/.test(x)) === i));
    step('페이지 오류·콘솔 오류 0 (일부러 보낸 잘못된 범위 거절 1건 제외)', real.length === 0, { errors: real.slice(0, 3) });
    ok = true;
    console.log(`\n외부 연결 화면 점검 통과 (${passed}개)`);
  } finally {
    await browser.close().catch(() => {});
    await stopFixture(fixture);
    if (!ok) process.exitCode = 1;
  }
})().catch((e) => { console.error(e.message); process.exitCode = 1; });
