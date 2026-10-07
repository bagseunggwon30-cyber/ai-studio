/* AI 스튜디오 — 외부 연결 창 (MCP 연결 문)
 *
 * ChatGPT·Dots 같은 바깥 AI 앱이 AI 스튜디오에 일을 맡기고 결과를 읽는 문을 사장님이 켜고 끄는 창.
 * 서버(studio/mcp_gateway.py)는 기본 꺼짐이고 이 PC의 127.0.0.1에만 열린다. 인터넷에 닿게 하는 터널은 사장님이 따로 켠다.
 * 쓰는 API(모두 이 PC의 대시보드에서만): GET /api/gateway · POST /api/gateway/config|permissions|code|revoke
 * 글자는 모두 textContent로 넣는다 (연결된 앱 이름은 앱이 스스로 적은 글이라 믿지 않는다). 인라인 스타일·스크립트 없음.
 * 입력칸이 있어서 창을 keep으로 열고, 데이터가 바뀌어도 통째로 다시 그리지 않고 바뀐 부분만 고친다 (입력 중인 글·초점이 지워지지 않게).
 * 순수 계산(checkUrl·parsePaths·ago·scopeLabel·countdown·levelOf·levelSpec)은 DOM 없이 돈다 — tools/dev/gateway_sim.js가 확인한다.
 */
'use strict';

const Gateway = (() => {
  const TOKEN = typeof document !== 'undefined' ? ((document.querySelector('meta[name="studio-token"]') || {}).content || '') : '';
  const POLL_MS = 5000;
  const OFFLINE = '감독 프로그램과 연결이 끊겼어요';
  const RESULT = { ok: '성공', denied: '거절', error: '오류' };

  // ---------------------------------------------------------------- 순수 계산
  // 공개 주소 검사 (서버 mcp_gateway.parse_public_url과 같은 규칙, 쉬운 말). 맞으면 '' 아니면 이유.
  function checkUrl(value) {
    const raw = String(value == null ? '' : value).trim();
    const low = raw.toLowerCase();
    if (!raw) return '공개 주소를 넣어 주세요. 터널 프로그램이 알려 준 https:// 주소예요.';
    if (/\s/.test(raw)) return '주소 안에 띄어쓰기가 있어요.';
    if (low.startsWith('http://')) return 'https:// 로 시작하는 주소만 쓸 수 있어요. (http는 안 돼요)';
    if (!low.startsWith('https://')) return '주소는 https:// 로 시작해야 해요.';
    if (/[?#@\\]/.test(low)) return '주소 뒤에 경로·물음표·# 같은 것을 붙이지 말고 https://이름.도메인 만 넣어 주세요.';
    const m = /^https:\/\/((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)(?::([0-9]{1,5}))?\/?$/.exec(low);
    if (!m) {
      if (/^https:\/\/[^/]+\/.+/.test(low)) return '주소 뒤에 경로를 붙이지 말고 https://이름.도메인 만 넣어 주세요. (/mcp는 자동으로 붙여 드려요)';
      return '주소 모양이 맞지 않아요. 영문 이름과 점이 있는 https:// 주소만 쓸 수 있어요.';
    }
    const host = m[1];
    if (/^[0-9]+$/.test(host.split('.').pop()) || /\.(local|localhost|internal|lan|home\.arpa)$/.test(host)) return '집 안·이 PC 주소나 숫자 주소는 쓸 수 없어요. 터널이 알려 준 인터넷 주소를 넣어 주세요.';
    if (m[2] && (Number(m[2]) < 1 || Number(m[2]) > 65535)) return '포트 번호가 올바르지 않아요.';
    return '';
  }

  // '폴더 범위' 입력 글 → 목록 (쉼표·줄바꿈으로 나눔, 빈 것 버림). 모양 검사는 서버가 기존 규칙으로 한다.
  function parsePaths(text) {
    return String(text || '').split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
  }

  function ago(ts, now) {
    if (!ts) return '';
    const s = Math.max(0, Math.round((now - ts) / 1000));
    if (s < 60) return '방금';
    if (s < 3600) return `${Math.floor(s / 60)}분 전`;
    if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
    return `${Math.floor(s / 86400)}일 전`;
  }

  // 연결 목록의 권한 이름: 허용한 것(granted)과 지금 CEO 설정이 허용하는 것(scopes)을 같이 본다
  function scopeLabel(conn) {
    const has = (list, s) => Array.isArray(list) && list.includes(s);
    if (has(conn.scopes, 'studio:submit')) return { text: '읽기 + 일 맡기기', tone: 'on' };
    if (has(conn.granted, 'studio:submit')) return { text: '읽기만 (일 맡기기는 꺼짐)', tone: 'soft' };
    return { text: '읽기만', tone: 'soft' };
  }

  // 프로젝트마다 고르는 단계: 읽기만 · 일 맡기기(실행은 사장님이 눌러요) · 일 맡기기 + 실행 시작(앱이 직접 시작, 사용량을 써요)
  const LEVELS = {
    read: { label: '읽기만', hint: '읽기만 해요. 일은 못 맡겨요.' },
    submit: { label: '일 맡기기', hint: '사장님이 [실행]을 눌러야 직원이 움직여요.' },
    run: { label: '일 맡기기 + 실행 시작', hint: '앱이 직접 실행을 시작해요. 사용량을 써요.' },
  };
  // 저장된 값 {write, run} → 단계 (저장된 값이 없으면 읽기만)
  function levelOf(saved) {
    if (!saved) return 'read';
    return saved.run ? 'run' : (saved.write !== false ? 'submit' : 'read');
  }
  // 단계 → 저장할 값 (모르는 단계는 읽기만)
  function levelSpec(level) {
    return { write: level === 'submit' || level === 'run', run: level === 'run' };
  }

  // 연결 번호 남은 시간 '4:59' (0이면 '')
  function countdown(msLeft) {
    if (msLeft <= 0) return '';
    const s = Math.ceil(msLeft / 1000);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  function clock(iso) {
    const m = /T(\d\d:\d\d:\d\d)/.exec(String(iso || ''));
    return m ? m[1] : '';
  }

  const logic = { checkUrl, parsePaths, ago, scopeLabel, countdown, clock, levelOf, levelSpec, LEVELS };
  if (typeof document === 'undefined') return { logic };

  // ---------------------------------------------------------------- 화면
  const h = Popups.h;
  const ICONS = {
    copy: '<svg viewBox="0 0 24 24"><rect x="8.5" y="8.5" width="11" height="11" rx="2.5"/><path d="M15.5 8.5V6.5A2 2 0 0 0 13.5 4.5h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/></svg>',
    globe: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.4 3.8 5.2 3.8 8.5s-1.2 6.1-3.8 8.5M12 3.5C9.4 5.9 8.2 8.7 8.2 12s1.2 6.1 3.8 8.5"/></svg>',
  };
  const icon = (name) => { const el = h('span', { class: 'gw-ico', 'aria-hidden': 'true' }); el.innerHTML = ICONS[name]; return el; }; // 고정 SVG만

  async function request(method, path, body) {
    const opts = { method, cache: 'no-store', headers: {} };
    if (method === 'POST') {
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-Studio-Token'] = TOKEN;
      opts.body = JSON.stringify(body || {});
    }
    let res;
    try { res = await fetch(path, opts); } catch (_) { throw new Error(OFFLINE); }
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok) throw new Error((data && data.error) || `요청 실패 (${res.status})`);
    return data;
  }

  function open() {
    Popups.open((st) => {
      if (!st.root) build(st);
      ensureTimers(st); // 다른 창(확인 창)에 잠깐 가려졌다 돌아와도 다시 돈다
      return st.root;
    }, { keep: true });
  }

  function build(st) {
    st.data = null;
    st.busy = false;
    st.perm = null; // 편집 중인 권한 {submit, projects:{키:{on, level, paths}}}
    st.permDirty = false;
    st.code = null; // {text, until}
    st.msg = { power: { text: '', bad: false }, perm: { text: '', bad: false }, code: { text: '', bad: false }, apps: { text: '', bad: false } };
    st.refs = {};
    const r = st.refs;

    const closeBtn = h('button', { type: 'button', class: 'x-btn', 'aria-label': '닫기', onclick: () => Popups.close() }, Popups.icon('x'));
    r.chip = h('span', { class: 'gw-chip off', text: '불러오는 중' });
    r.sw = h('button', { type: 'button', class: 'gw-switch', role: 'switch', 'aria-checked': 'false', 'aria-label': '외부 연결 받기', 'data-focus-key': 'gw-switch', disabled: true, onclick: () => onSwitch(st) }, h('i'));
    r.url = h('input', { type: 'text', class: 'gw-input', id: 'gw-url', inputmode: 'url', autocomplete: 'off', spellcheck: 'false', maxlength: '200', placeholder: 'https://이름.trycloudflare.com', 'data-focus-key': 'gw-url', 'aria-describedby': 'gw-url-msg', oninput: () => { st.msg.power = { text: '', bad: false }; paintMsgs(st); paintPower(st); } });
    r.save = h('button', { type: 'button', class: 'gw-btn', 'data-focus-key': 'gw-url-save', onclick: () => onSaveUrl(st) }, '주소 저장');
    r.powerMsg = h('p', { class: 'gw-msg', id: 'gw-url-msg', role: 'status', hidden: true });
    r.local = h('p', { class: 'gw-hint' });
    r.mcp = h('input', { type: 'text', class: 'gw-input mono', readonly: true, 'aria-label': '연결에 붙여 넣을 주소', 'data-focus-key': 'gw-mcp' });
    r.copy = h('button', { type: 'button', class: 'gw-btn', 'data-focus-key': 'gw-copy', onclick: () => onCopy(st) }, icon('copy'), h('span', { text: '복사' }));
    r.copyMsg = h('p', { class: 'gw-msg', role: 'status', hidden: true });
    r.permBox = h('div', { class: 'gw-perm' });
    r.permMsg = h('p', { class: 'gw-msg', role: 'status', hidden: true });
    r.permSave = h('button', { type: 'button', class: 'gw-btn primary', 'data-focus-key': 'gw-perm-save', onclick: () => onSavePerm(st) }, '권한 저장');
    r.codeBtn = h('button', { type: 'button', class: 'gw-btn primary', 'data-focus-key': 'gw-code', onclick: () => onCode(st) }, '연결 번호 만들기');
    r.codeBox = h('div', { class: 'gw-codebox', hidden: true });
    r.codeText = h('b', { class: 'gw-code', 'aria-live': 'off' });
    r.codeLeft = h('span', { class: 'gw-codeleft' });
    r.codeMsg = h('p', { class: 'gw-msg', role: 'status', hidden: true });
    r.codeHint = h('p', { class: 'gw-hint' });
    r.codeBox.append(r.codeText, r.codeLeft);
    r.appsCount = h('span', { class: 'gw-count', text: '0' });
    r.apps = h('ul', { class: 'gw-apps' });
    r.revokeAll = h('button', { type: 'button', class: 'gw-btn danger', 'data-focus-key': 'gw-revoke-all', onclick: () => onRevokeAll(st) }, '모두 끊기');
    r.appsMsg = h('p', { class: 'gw-msg', role: 'status', hidden: true });
    r.log = h('ul', { class: 'gw-log', tabindex: '0', 'aria-label': '최근 기록' });

    const card = (cls, title, ...kids) => h('section', { class: `gw-card ${cls}` }, h('h3', { text: title }), ...kids);
    st.root = h('div', { class: 'pop gw paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': '외부 연결' },
      closeBtn,
      h('h2', { text: '외부 연결' }),
      h('ul', { class: 'gw-lead' },
        h('li', { text: 'ChatGPT나 Dots 같은 바깥 AI 앱이 AI 스튜디오에 일을 맡기고 결과를 볼 수 있게 하는 문이에요.' }),
        h('li', { text: '안전장치: 꺼져 있으면 문이 열리지 않아요. 켜도 사장님이 만든 연결 번호를 아는 앱만 들어오고, 읽기만 허용이 기본이에요.' }),
        h('li', { text: '끄는 법: 아래 스위치를 끄거나, 연결된 앱 옆 [끊기]를 누르면 바로 막혀요.' })),
      h('div', { class: 'gw-grid' },
        h('div', { class: 'gw-col' },
          h('section', { class: 'gw-card gw-power' },
            h('div', { class: 'gw-head' }, icon('globe'), h('h3', { text: '외부 연결 받기' }), r.chip, r.sw),
            h('label', { class: 'gw-label', for: 'gw-url', text: '공개 주소' }),
            h('div', { class: 'gw-row' }, r.url, r.save),
            r.powerMsg,
            h('p', { class: 'gw-hint', text: '터널 프로그램이 알려 준 주소를 넣어요 · 이 PC 밖으로 문을 여는 일이라 사장님이 직접 켜요.' }),
            r.local),
          card('gw-addr', '연결에 붙여 넣을 주소',
            h('div', { class: 'gw-row' }, r.mcp, r.copy),
            r.copyMsg,
            h('p', { class: 'gw-hint', text: 'ChatGPT 설정의 앱·커넥터 추가 칸에 붙여 넣고, 로그인 방식은 OAuth로 골라요.' }))),
        h('div', { class: 'gw-col' },
          card('gw-permcard', '권한', r.permBox, r.permMsg, h('div', { class: 'gw-actions' }, r.permSave))),
        h('div', { class: 'gw-col' },
          card('gw-codecard', '연결 번호',
            h('p', { class: 'gw-hint', text: '앱의 동의 화면에 이 번호를 넣어야 연결돼요. 5분 동안, 한 번만 써요. 5번 틀리면 1분 막혀요.' }),
            h('div', { class: 'gw-actions' }, r.codeBtn), r.codeBox, r.codeHint, r.codeMsg),
          h('section', { class: 'gw-card gw-appscard' },
            h('div', { class: 'gw-head' }, h('h3', { text: '연결된 앱' }), r.appsCount, h('span', { class: 'gw-grow' }), r.revokeAll),
            r.apps, r.appsMsg)),
        card('gw-logcard', '최근 기록', r.log)),
      h('p', { class: 'gw-danger', role: 'note', text: '연결한 앱은 사장님 대신 일을 맡기거나 결과를 읽을 수 있어요. "실행 시작"을 허용한 프로젝트에서는 직접 실행도 시작시켜요 (구독 사용량을 써요). 결재와 완료는 항상 사장님이 해요.' }));

    paint(st);
    load(st);
  }

  // 5초마다 다시 읽는다 (창이 화면에 붙어 있고 탭이 보일 때만). 창이 1분 넘게 안 보이면(닫힘) 멈추고, 연결 번호도 화면에서 지운다.
  function ensureTimers(st) {
    if (st.timers) return;
    st.timers = true;
    st.away = 0;
    st.poll = setInterval(() => {
      if (!st.root.isConnected) { if (++st.away >= 12) halt(st); return; }
      st.away = 0;
      if (!document.hidden) load(st, true);
    }, POLL_MS);
    st.tick = setInterval(() => { if (st.root.isConnected && st.code) paintCode(st); }, 1000);
  }

  function halt(st) {
    clearInterval(st.poll);
    clearInterval(st.tick);
    st.timers = false;
    st.code = null;
  }

  async function load(st, quiet) {
    if (st.loading) return;
    st.loading = true;
    try {
      st.data = await request('GET', '/api/gateway');
      st.error = '';
    } catch (e) {
      st.error = e.message;
      if (!quiet) st.msg.power = { text: e.message, bad: true };
    } finally {
      st.loading = false;
    }
    if (st.root.isConnected) paint(st);
  }

  // 한 번에 하나만: 누르는 순간 잠그고, 끝나면 푼다 (더블클릭 방지)
  async function act(st, area, work) {
    if (st.busy) return;
    st.busy = true;
    st.msg[area] = { text: '', bad: false };
    st.root.setAttribute('aria-busy', 'true');
    paintBusy(st);
    try {
      await work();
    } catch (e) {
      st.msg[area] = { text: e.message || String(e), bad: true };
    } finally {
      st.busy = false;
      st.root.removeAttribute('aria-busy');
      paint(st);
    }
  }

  function apply(st, data) {
    st.data = data;
  }

  function onSwitch(st) {
    const d = st.data;
    if (!d) return;
    if (d.enabled) {
      act(st, 'power', async () => apply(st, await request('POST', '/api/gateway/config', { enabled: false })));
      return;
    }
    const bad = checkUrl(st.refs.url.value);
    if (bad) { st.msg.power = { text: bad, bad: true }; paintMsgs(st); st.refs.url.focus(); return; }
    act(st, 'power', async () => apply(st, await request('POST', '/api/gateway/config', { enabled: true, public_url: st.refs.url.value.trim() })));
  }

  function onSaveUrl(st) {
    const d = st.data;
    if (!d) return;
    const bad = checkUrl(st.refs.url.value);
    if (bad) { st.msg.power = { text: bad, bad: true }; paintMsgs(st); st.refs.url.focus(); return; }
    const send = () => act(st, 'power', async () => { apply(st, await request('POST', '/api/gateway/config', { public_url: st.refs.url.value.trim() })); st.msg.power = { text: '주소를 저장했어요.', bad: false }; });
    const changed = d.public_url && d.public_url !== normalizeUrl(st.refs.url.value);
    if (changed && d.connections.length) {
      Popups.dialog('공개 주소를 바꿀까요?', '주소를 바꾸면 지금 연결된 앱이 모두 끊겨요. 앱에서 새 주소로 다시 연결해야 해요.', [
        { label: '취소' }, { label: '바꾸기', kind: 'danger', run: send }]);
      return;
    }
    send();
  }

  function normalizeUrl(value) {
    return String(value || '').trim().toLowerCase().replace(/\/+$/, '').replace(/:443$/, '');
  }

  async function onCopy(st) {
    const text = st.data && st.data.mcp_url;
    if (!text) return;
    let ok = false;
    try { await navigator.clipboard.writeText(text); ok = true; } catch (_) { /* 아래에서 선택해 둔다 */ }
    if (!ok) { st.refs.mcp.focus(); st.refs.mcp.select(); }
    st.refs.copyMsg.textContent = ok ? '복사했어요. 앱의 주소 칸에 붙여 넣어 주세요.' : '자동 복사가 안 돼서 주소를 선택해 뒀어요. Ctrl+C로 복사해 주세요.';
    st.refs.copyMsg.classList.toggle('err', !ok);
  }

  function onCode(st) {
    act(st, 'code', async () => {
      const res = await request('POST', '/api/gateway/code', {});
      st.code = { text: res.code, until: Date.now() + res.expires_in * 1000 };
      st.data = await request('GET', '/api/gateway');
    });
  }

  function onRevoke(st, conn) {
    act(st, 'apps', async () => apply(st, await request('POST', '/api/gateway/revoke', { id: conn.id })));
  }

  function onRevokeAll(st) {
    if (!st.data || !st.data.connections.length) return;
    Popups.dialog('연결된 앱을 모두 끊을까요?', `지금 연결된 ${st.data.connections.length}개 앱이 바로 막혀요. 필요하면 앱에서 다시 연결할 수 있어요.`, [
      { label: '취소' },
      { label: '모두 끊기', kind: 'danger', run: () => act(st, 'apps', async () => apply(st, await request('POST', '/api/gateway/revoke', { all: true }))) }]);
  }

  function onSavePerm(st) {
    if (!st.perm) return;
    const projects = {};
    for (const [key, p] of Object.entries(st.perm.projects)) if (p.on) projects[key] = { paths: parsePaths(p.paths), ...levelSpec(p.level) };
    act(st, 'perm', async () => {
      apply(st, await request('POST', '/api/gateway/permissions', { submit: st.perm.submit, projects }));
      st.permDirty = false;
      st.perm = null;
      st.msg.perm = { text: '권한을 저장했어요.', bad: false };
    });
  }

  // ---------------------------------------------------------------- 그리기 (바뀐 부분만)
  function paint(st) {
    paintPower(st);
    paintAddress(st);
    paintPerm(st);
    paintCode(st);
    paintApps(st);
    paintLog(st);
    paintMsgs(st);
    paintBusy(st);
  }

  function paintBusy(st) {
    const r = st.refs;
    const d = st.data;
    const lock = st.busy || !d;
    r.sw.disabled = lock;
    r.save.disabled = lock;
    r.permSave.disabled = lock;
    r.revokeAll.disabled = lock || !d || !d.connections.length;
    r.codeBtn.disabled = lock || !d || !d.running;
    for (const b of r.apps.querySelectorAll('button')) b.disabled = lock;
    for (const el of r.permBox.querySelectorAll('input, select')) {
      if (el.dataset.role === 'paths' || el.dataset.role === 'level') el.disabled = lock || !el.dataset.key || !st.perm || !st.perm.projects[el.dataset.key].on;
      else el.disabled = lock;
    }
  }

  function paintMsgs(st) {
    const r = st.refs;
    const set = (el, m) => { el.textContent = m.text; el.classList.toggle('err', Boolean(m.text) && m.bad); el.hidden = !m.text; };
    set(r.powerMsg, st.msg.power);
    set(r.permMsg, st.msg.perm);
    set(r.codeMsg, st.msg.code);
    set(r.appsMsg, st.msg.apps);
    r.copyMsg.hidden = !r.copyMsg.textContent;
  }

  function paintPower(st) {
    const r = st.refs;
    const d = st.data;
    if (!d) return;
    r.sw.setAttribute('aria-checked', String(d.enabled));
    const state = d.enabled ? (d.running ? { t: '켜짐 · 기다리는 중', c: 'on' } : { t: '켜졌지만 문이 안 열렸어요', c: 'warn' }) : { t: '꺼짐', c: 'off' };
    r.chip.textContent = state.t;
    r.chip.className = `gw-chip ${state.c}`;
    if (document.activeElement !== r.url && !st.urlTouched) r.url.value = d.public_url || r.url.value;
    if (document.activeElement === r.url) st.urlTouched = true;
    r.local.textContent = d.running ? `이 PC 안에서만 열려 있어요: http://127.0.0.1:${d.port} · 터널 프로그램에 이 주소를 알려 주세요.` : '지금은 문이 닫혀 있어요. 아무도 들어올 수 없어요.';
    const typed = normalizeUrl(r.url.value);
    r.save.textContent = d.public_url && typed !== d.public_url ? '주소 바꾸기' : '주소 저장';
  }

  function paintAddress(st) {
    const r = st.refs;
    const d = st.data;
    r.mcp.value = d && d.mcp_url ? d.mcp_url : '';
    r.mcp.placeholder = '공개 주소를 저장하면 여기에 나와요';
    r.copy.disabled = !d || !d.mcp_url;
  }

  function ensurePerm(st) {
    const d = st.data;
    if (!d || (st.perm && st.permDirty)) return;
    const next = { submit: Boolean(d.permissions.submit), projects: {} };
    for (const p of d.projects) {
      const saved = d.permissions.projects[p.key];
      // 일 맡기기·실행 시작은 프로젝트마다 따로 고른다: 저장된 값이 없으면 읽기만 — 새로 열어 주는 곳은 CEO가 직접 올려야 한다.
      next.projects[p.key] = { on: Boolean(saved), level: levelOf(saved), paths: (saved ? saved.paths : p.default_allowed_paths).join(', ') };
    }
    const same = st.perm && JSON.stringify(st.perm) === JSON.stringify(next);
    if (!same) { st.perm = next; st.permSig = ''; }
  }

  function paintPerm(st) {
    const r = st.refs;
    const d = st.data;
    if (!d) return;
    ensurePerm(st);
    const sig = JSON.stringify([d.projects.map((p) => p.key), st.perm.submit]);
    if (st.permSig === sig) { // 모양이 같으면 다시 만들지 않는다 (입력 중인 글을 지키려고)
      for (const [key, p] of Object.entries(st.perm.projects)) {
        const box = r.permBox.querySelector(`[data-project="${CSS.escape(key)}"]`);
        if (!box) continue;
        box.classList.toggle('on', p.on);
        const hint = box.querySelector('[data-role="level-hint"]');
        if (hint) { hint.textContent = (LEVELS[p.level] || LEVELS.read).hint; hint.classList.toggle('warn', p.level === 'run'); }
      }
      return;
    }
    st.permSig = sig;
    const mode = (value, title, text) => h('label', { class: `gw-mode ${st.perm.submit === value ? 'on' : ''}` },
      h('input', { type: 'radio', name: 'gw-mode', value: String(value), checked: st.perm.submit === value, 'data-focus-key': `gw-mode-${value}`,
        onchange: () => { st.perm.submit = value; st.permDirty = true; st.permSig = ''; paintPerm(st); paintBusy(st); } }),
      h('span', { class: 'gw-mode-text' }, h('b', { text: title }), h('span', { text })));
    const rows = d.projects.length
      ? d.projects.map((p) => {
        const cur = st.perm.projects[p.key];
        // 아랫줄(일 맡기기 모드에서만): 이 프로젝트에 허용할 단계 + 한 줄 설명
        const level = st.perm.submit
          ? h('div', { class: 'gw-proj-level' },
            h('select', { class: 'gw-select', 'data-role': 'level', 'data-key': p.key, 'data-focus-key': `gw-level-${p.key}`, disabled: !cur.on, 'aria-label': `${p.title}에 허용할 단계`,
              onchange: (e) => { cur.level = LEVELS[e.target.value] ? e.target.value : 'read'; st.permDirty = true; paintPerm(st); paintBusy(st); } },
            ...Object.entries(LEVELS).map(([value, lv]) => h('option', { value, selected: cur.level === value, text: lv.label }))),
            h('span', { class: `gw-level-hint ${cur.level === 'run' ? 'warn' : ''}`, 'data-role': 'level-hint', text: (LEVELS[cur.level] || LEVELS.read).hint }))
          : null;
        return h('div', { class: `gw-proj ${cur.on ? 'on' : ''}`, 'data-project': p.key },
          h('div', { class: 'gw-proj-top' },
            h('label', { class: 'gw-check' },
              h('input', { type: 'checkbox', checked: cur.on, 'data-focus-key': `gw-proj-${p.key}`, 'aria-label': `${p.title} 열어 주기`,
                onchange: (e) => { cur.on = e.target.checked; st.permDirty = true; paintPerm(st); paintBusy(st); } }),
              h('span', { class: 'gw-proj-name', title: `${p.title} (${p.key})`, text: p.title })),
            h('input', { type: 'text', class: 'gw-input slim mono', 'data-role': 'paths', 'data-key': p.key, 'data-focus-key': `gw-paths-${p.key}`, value: cur.paths, disabled: !cur.on,
              'aria-label': `${p.title} 폴더 범위`, placeholder: p.default_allowed_paths.join(', ') || 'docs/**', spellcheck: 'false',
              oninput: (e) => { cur.paths = e.target.value; st.permDirty = true; } })),
          level);
      })
      : [h('p', { class: 'gw-empty', text: '등록된 프로젝트가 아직 없어요.' })];
    r.permBox.replaceChildren(
      h('div', { class: 'gw-modes' },
        mode(false, '읽기만 (기본)', '일 목록·상태·진행·결과 파일 읽기. 일은 못 맡겨요.'),
        mode(true, '일 맡기기도 허용', '아래에서 프로젝트마다 단계를 골라요. 일 맡기기·자기 일 취소는 고른 폴더 안에서만, 직접 실행 시작은 "실행 시작"을 고른 프로젝트에서만 돼요.')),
      h('p', { class: 'gw-sub', text: '열어 줄 프로젝트와 폴더 범위' }),
      h('p', { class: 'gw-hint', text: '폴더 범위는 쉼표로 나눠요. 예: docs/**, ui/app.js · 읽기만이어도 여기서 고른 곳의 결과만 볼 수 있어요.' }),
      ...rows);
    paintBusy(st);
  }

  function paintCode(st) {
    const r = st.refs;
    const d = st.data;
    const left = st.code ? st.code.until - Date.now() : 0;
    if (st.code && left <= 0) { st.code = null; st.msg.code = { text: '시간이 지났어요. 필요하면 새로 만들어 주세요.', bad: false }; paintMsgs(st); }
    r.codeBox.hidden = !st.code;
    if (st.code) {
      r.codeText.textContent = st.code.text;
      r.codeLeft.textContent = `남은 시간 ${countdown(left)}`;
      if (st.msg.code.text) { st.msg.code = { text: '', bad: false }; paintMsgs(st); }
    }
    r.codeHint.textContent = d && !d.running ? '먼저 위의 스위치를 켜야 번호를 만들 수 있어요.' : '';
    r.codeHint.hidden = !r.codeHint.textContent;
    if (d) r.codeBtn.disabled = st.busy || !d.running;
  }

  function paintApps(st) {
    const r = st.refs;
    const d = st.data;
    if (!d) return;
    r.appsCount.textContent = String(d.connections.length);
    const now = Date.now();
    const rows = d.connections.length
      ? d.connections.map((c) => {
        const label = scopeLabel(c);
        const when = c.last_used_ts ? `마지막 사용 ${ago(c.last_used_ts * 1000, now)}` : '아직 안 썼어요';
        return h('li', { class: 'gw-app', 'data-conn': c.id },
          h('div', { class: 'gw-app-main' }, h('b', { text: c.name, title: c.name }), h('span', { class: 'gw-app-meta', text: `${when} · 연결 ${ago(c.created_ts * 1000, now) || '방금'}`, title: `${when} · 연결 ${ago(c.created_ts * 1000, now) || '방금'}` })),
          h('span', { class: `gw-chip ${label.tone}`, text: label.text }),
          h('button', { type: 'button', class: 'gw-btn danger small', 'aria-label': `${c.name} 끊기`, 'data-focus-key': `gw-revoke-${c.id}`, disabled: st.busy, onclick: () => onRevoke(st, c) }, '끊기'));
      })
      : [h('li', { class: 'gw-empty', text: '연결된 앱이 아직 없어요.' })];
    const sig = JSON.stringify(d.connections.map((c) => [c.id, c.scopes, c.granted, Math.floor((c.last_used_ts || 0) / 30)]));
    if (st.appsSig !== sig) { st.appsSig = sig; r.apps.replaceChildren(...rows); }
    r.revokeAll.disabled = st.busy || !d.connections.length;
  }

  function paintLog(st) {
    const r = st.refs;
    const d = st.data;
    if (!d) return;
    const sig = JSON.stringify(d.audit);
    if (st.logSig === sig) return;
    st.logSig = sig;
    r.log.replaceChildren(...(d.audit.length
      ? d.audit.map((a) => h('li', { class: 'gw-log-row' },
        h('span', { class: 'gw-log-at', text: clock(a.at) }),
        h('span', { class: 'gw-log-text', text: a.text || a.type, title: a.text || a.type }),
        h('span', { class: `gw-chip ${a.result === 'ok' ? 'on' : a.result === 'denied' ? 'warn' : 'bad'}`, text: RESULT[a.result] || a.result || '' })))
      : [h('li', { class: 'gw-empty', text: '아직 기록이 없어요.' })]));
  }

  return { open, logic };
})();

if (typeof module !== 'undefined') module.exports = Gateway; // tools/dev/gateway_sim.js (node)
