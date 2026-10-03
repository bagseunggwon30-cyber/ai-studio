// 휴대폰 리모컨 (/m): 결재·지시·긴급 정지. 서버 글은 모두 textContent로 넣는다 (innerHTML 없음).
// 짝짓기: PC 화면 QR의 주소 끝 #pair=번호 → /m/api/pair → 기기 토큰을 이 휴대폰에만 저장 (localStorage).
(() => {
  'use strict';
  const KEY = 'ais.device';
  const $ = (s) => document.querySelector(s);
  const app = $('#app');
  let token = '';
  let state = null;
  let tab = 'inbox';
  let view = null; // { id } 작업 자세히 보기
  let timer = null;
  let loadError = ''; // 처음 불러오다 실패한 이유 (있으면 '불러오는 중…' 대신 다시 시도 단추)

  try { token = localStorage.getItem(KEY) || ''; } catch (_) { token = ''; }

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
    return el;
  }

  function banner(text, info = false) {
    const b = $('#banner');
    b.hidden = !text;
    b.textContent = text || '';
    b.classList.toggle('info', info);
  }

  async function api(path, body) {
    const opts = { headers: { 'X-Device-Token': token }, cache: 'no-store' };
    if (body !== undefined) {
      opts.method = 'POST';
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    // PC가 대답하지 않으면 무한 로딩 대신 15초 뒤에 이유를 알려 준다
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 15000);
    opts.signal = ctl.signal;
    let res;
    let data = {};
    try {
      res = await fetch(path, opts);
      try { data = await res.json(); } catch (_) { data = {}; }
    } catch (e) {
      throw new Error(e && e.name === 'AbortError'
        ? 'PC가 대답하지 않아요. 같은 와이파이인지, PC의 윈도우 방화벽이 막고 있지 않은지 확인해 주세요.'
        : 'PC에 닿지 않아요. 같은 와이파이인지(모바일 데이터가 아닌지) 확인해 주세요.');
    } finally {
      clearTimeout(timer);
    }
    if (res.status === 401) { forget(); throw new Error(data.error || '다시 연결해 주세요.'); }
    if (!res.ok) throw new Error(data.error || `오류 ${res.status}`);
    return data;
  }

  function forget() {
    token = '';
    try { localStorage.removeItem(KEY); } catch (_) { /* 저장소를 못 써도 괜찮다 */ }
    state = null;
    render();
  }

  // ---------------------------------------------------------------- 짝짓기
  function deviceName() {
    const ua = navigator.userAgent;
    if (/iPhone/.test(ua)) return 'iPhone';
    if (/iPad/.test(ua)) return 'iPad';
    if (/Android/.test(ua)) return 'Android 휴대폰';
    return '휴대폰';
  }

  async function pair(code) {
    try {
      const r = await api('/m/api/pair', { code, name: deviceName() });
      token = r.token;
      try { localStorage.setItem(KEY, token); } catch (_) { banner('이 브라우저는 저장을 막아 두어서, 창을 닫으면 다시 연결해야 해요.'); }
      banner('연결됐어요!', true);
      setTimeout(() => banner(''), 2500);
      await refresh();
    } catch (e) {
      banner(e.message);
      render();
    }
  }

  function pairScreen() {
    const input = h('input', { type: 'text', maxlength: '9', placeholder: 'ABCD-EFGH', autocomplete: 'off', 'aria-label': '짝짓기 번호' });
    return h('section', { class: 'pair' },
      h('h2', { text: '휴대폰 연결' }),
      h('p', { text: 'PC의 AI 스튜디오에서 "휴대폰 연결" 창을 열고 QR을 찍어 주세요. QR이 안 되면 창에 보이는 짝짓기 번호를 넣어도 돼요.' }),
      input,
      h('div', { class: 'btns' }, h('button', { class: 'btn primary', type: 'button', text: '연결하기', onclick: () => pair(input.value) })));
  }

  // ---------------------------------------------------------------- 화면
  function chip(t) { return h('span', { class: `chip ${t.status}`, text: t.status_label }); }

  function taskCard(t, extra) {
    return h('button', { class: 'card tap', type: 'button', onclick: () => open(t.id) },
      h('span', { class: 'title' }, chip(t), t.title),
      h('span', { class: 'meta', text: `${t.kind_label} · ${t.who}${t.waiting ? ` · ${t.waiting}` : ''}` }),
      t.blocked_reason ? h('span', { class: 'why', text: t.blocked_reason }) : null,
      extra || null);
  }

  function inboxTab() {
    const list = state.inbox;
    return [h('h2', { text: `결재함 ${list.length}건` }),
      list.length ? list.map((t) => taskCard(t)) : h('p', { class: 'empty', text: '결재할 일이 없어요.' })];
  }

  // 진행판 (PC 진행판과 같은 다섯 칸, 옆으로 밀어 넘김). 위에는 발표 캐릭터와 한 줄 요약
  const KB = [['wait', '대기', ['queued', 'ready']], ['work', '작업 중', ['blocked', 'running']], ['check', '검사·리뷰', ['checking']],
    ['approve', '결재 대기', ['awaiting_approval']], ['done', '완료', ['done']]];

  function workTab() {
    const cur = state.current;
    const all = [...state.active, ...state.inbox, ...state.done];
    const blocked = state.active.filter((t) => t.status === 'blocked').length;
    const mood = blocked ? 'worried' : state.inbox.length ? 'happy' : 'normal';
    const say = blocked ? `막힌 일이 ${blocked}개 있어요. 눌러서 도와주세요!`
      : state.inbox.length ? `결재를 기다리는 일이 ${state.inbox.length}개예요.`
        : cur ? `지금 ${cur.who} · '${cur.title}' 하는 중이에요.` : '지금은 조용해요.';
    return [
      // 하나는 손바닥을 왼쪽으로 내밀고 있다 (PC 진행판에서 왼쪽의 판을 가리키는 자세) → 말풍선을 그 쪽에 기둥 달린 판으로 세우고 하나는 오른쪽에
      h('div', { class: `host ${mood}` },
        h('div', { class: 'host-board' },
          h('div', { class: 'host-bubble' }, h('b', { text: '진행 발표' }), h('span', { text: say })),
          h('span', { class: 'host-pole', 'aria-hidden': 'true' })),
        h('img', { class: 'host-img', src: `/assets/mascot/${mood}.png`, alt: '' })),
      h('div', { class: 'kb', 'aria-label': '진행판' }, KB.map(([key, label, sts]) => {
        const list = all.filter((t) => sts.includes(t.status)).sort((a, b) => sts.indexOf(a.status) - sts.indexOf(b.status));
        return h('section', { class: `kb-col k-${key}`, 'aria-label': `${label} ${list.length}개` },
          h('h3', {}, h('span', { text: label }), h('b', { text: String(list.length) })),
          list.length ? list.map((t) => taskCard(t)) : h('p', { class: 'empty', text: '비어 있어요' }));
      })),
      h('p', { class: 'kb-hint', text: '← 옆으로 밀면 다음 칸 →' }),
    ];
  }

  function orderTab() {
    const text = h('textarea', { maxlength: '4000', placeholder: '무엇을 시킬까요? 예: 저장 기능에 자동 저장을 더해 줘', 'aria-label': '지시' });
    const project = h('select', { 'aria-label': '프로젝트' }, state.projects.map((p) => h('option', { value: p.key, text: p.title })));
    return [h('h2', { text: '지시 보내기' }),
      h('p', { class: 'meta', text: '기획 담당이 퀘스트로 나눠 오면 결재함에서 골라 주세요.' }),
      h('label', { class: 'field' }, h('span', { text: '프로젝트' }), project),
      h('label', { class: 'field' }, h('span', { text: '지시' }), text),
      h('div', { class: 'btns' }, h('button', { class: 'btn primary', type: 'button', text: '보내기', onclick: (e) => {
        if (!text.value.trim()) { text.focus(); return; }
        act(e.currentTarget, api('/m/api/directive', { text: text.value.trim(), project: project.value }), '지시를 보냈어요!', () => { text.value = ''; });
      } }))];
  }

  function alertsTab() {
    return [h('h2', { text: '알림' }),
      state.alerts.length ? state.alerts.map((a) => h('div', { class: 'alert' }, h('time', { text: a.time || '' }), h('b', { text: a.name || '' }), h('span', { text: a.text || '' })))
        : h('p', { class: 'empty', text: '알림이 없어요.' }),
      h('div', { class: 'btns' }, h('button', { class: 'btn', type: 'button', text: '이 휴대폰 연결 끊기', onclick: () => {
        if (window.confirm('이 휴대폰의 연결을 끊을까요? 다시 쓰려면 PC에서 QR을 새로 찍어야 해요.')) api('/m/api/forget', {}).catch(() => {}).finally(forget);
      } }))];
  }

  async function open(id) {
    view = { id, data: null };
    render();
    try {
      view.data = await api(`/m/api/task/${encodeURIComponent(id)}`);
    } catch (e) {
      view.error = e.message;
    }
    render();
  }

  function detail() {
    const d = view.data;
    const back = h('button', { class: 'back', type: 'button', text: '← 목록', onclick: () => { view = null; render(); } });
    if (view.error) return [back, h('p', { class: 'empty', text: view.error })];
    if (!d) return [back, h('p', { class: 'empty', text: '불러오는 중…' })];
    const picks = new Set((d.quests || []).map((_, i) => i));
    const note = h('textarea', { maxlength: '2000', placeholder: '무엇을 고쳐 달라고 할까요?', 'aria-label': '수정 요청' });
    const buttons = [];
    const doAct = (btn, action, body, done) => act(btn, api('/m/api/act', { task: d.id, action, ...body }), done, () => open(d.id));
    if (d.status === 'awaiting_approval') {
      buttons.push(h('button', { class: 'btn primary', type: 'button', text: d.kind === 'plan' ? '고른 퀘스트로 승인' : '승인',
        onclick: (e) => doAct(e.currentTarget, 'approve', d.kind === 'plan' ? { selected: [...picks] } : {}, '승인했어요!') }));
      buttons.push(h('button', { class: 'btn', type: 'button', text: '수정 요청', onclick: (e) => {
        if (!note.value.trim()) { note.hidden = false; note.focus(); return; }
        doAct(e.currentTarget, 'request-changes', { note: note.value.trim() }, '수정을 요청했어요');
      } }));
    }
    if (d.status === 'blocked') buttons.push(h('button', { class: 'btn primary', type: 'button', text: '재시도', onclick: (e) => doAct(e.currentTarget, 'retry', {}, '다시 해 볼게요!') }));
    if (d.status === 'ready' || (d.status === 'queued' && (d.created_by || '').startsWith('supervisor:'))) buttons.push(h('button', { class: 'btn primary', type: 'button', text: '실행', onclick: (e) => doAct(e.currentTarget, 'run', {}, '시작할게요!') }));
    if (!['done', 'cancelled', 'awaiting_approval'].includes(d.status)) {
      buttons.push(h('button', { class: 'btn danger', type: 'button', text: '취소', onclick: (e) => {
        if (window.confirm(`'${d.title}' 작업을 취소할까요?`)) doAct(e.currentTarget, 'cancel', {}, '취소했어요');
      } }));
    }
    note.hidden = true;
    return [back, h('section', { class: 'card detail' },
      h('h2', {}, h('span', { class: `chip ${d.status}`, text: d.status_label }), d.title),
      d.blocked_reason ? h('p', { class: 'bad', text: d.blocked_reason }) : null,
      d.summary ? h('p', { text: d.summary }) : null,
      d.brief ? [h('h3', { text: '목표' }), h('p', { text: d.brief })] : null,
      (d.acceptance || []).length ? [h('h3', { text: '수용 기준' }), h('ul', {}, d.acceptance.map((a) => h('li', { text: a })))] : null,
      (d.quests || []).length ? [h('h3', { text: d.status === 'awaiting_approval' ? '퀘스트 (승인할 것만 남겨 두세요)' : '퀘스트' }), d.quests.map((q, i) => h('label', { class: 'quest' },
        d.status === 'awaiting_approval'
          ? h('input', { type: 'checkbox', checked: true, onchange: (e) => { if (e.target.checked) picks.add(i); else picks.delete(i); } }) : null,
        h('span', {}, h('b', { text: q.title }), h('span', { class: 'meta', text: q.brief || '' }))))] : null,
      d.qa ? h('p', { class: d.qa.verdict === 'pass' ? 'ok' : 'bad', text: `품질 검사: ${d.qa.verdict === 'pass' ? '합격' : d.qa.verdict || '없음'}${d.qa.total ? ` (${d.qa.passed}/${d.qa.total})` : ''}` }) : null,
      d.review ? [h('h3', { text: `리뷰: ${d.review.verdict === 'approve' ? '통과' : d.review.verdict || ''}` }), h('p', { text: d.review.summary || '' }),
        (d.review.findings || []).length ? h('ul', {}, d.review.findings.map((f) => h('li', { text: `${f.file || ''} ${f.issue || ''}` }))) : null] : null,
      d.report ? [h('h3', { text: '보고' }), h('p', { text: d.report })] : null,
      d.body ? [h('h3', { text: d.kind === 'build' ? '바뀐 코드' : d.kind === 'research' ? '보고서' : '내용' }), h('pre', { text: d.body })] : null,
      note,
      buttons.length ? h('div', { class: 'btns' }, buttons) : null)];
  }

  async function act(btn, promise, done, after) {
    if (btn) btn.disabled = true;
    try {
      await promise;
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); // 다 쓴 입력칸은 놓아 줘야 새로 그린다
      banner(done, true);
      setTimeout(() => banner(''), 2500);
      if (after) after();
      await refresh();
    } catch (e) {
      banner(e.message);
      if (btn) btn.disabled = false;
    }
  }

  function render() {
    const paired = Boolean(token);
    $('#tabs').hidden = !paired || !state;
    $('#stop').hidden = !paired || !state;
    if (!paired) { app.replaceChildren(pairScreen()); return; }
    if (!state) {
      app.replaceChildren(loadError
        ? h('section', { class: 'pair' },
          h('h2', { text: 'PC에 연결하지 못했어요' }),
          h('p', { text: loadError }),
          h('div', { class: 'btns' }, h('button', { class: 'btn primary', type: 'button', text: '다시 시도', onclick: () => { loadError = ''; render(); refresh(); } })))
        : h('p', { class: 'empty', text: '불러오는 중…' }));
      return;
    }
    $('#name').textContent = state.studio.name + (state.studio.fake ? ' (연습용)' : '');
    $('#energy').textContent = `에너지 ${state.energy.left}/${state.energy.max}`;
    const stop = $('#stop');
    stop.textContent = state.stopped ? '다시 일하기' : '긴급 정지';
    stop.classList.toggle('on', state.stopped);
    const badge = $('#badge');
    badge.hidden = !state.inbox.length;
    badge.textContent = String(state.inbox.length);
    for (const b of document.querySelectorAll('#tabs button')) b.setAttribute('aria-current', b.dataset.tab === tab && !view ? 'page' : 'false');
    const body = view ? detail() : tab === 'work' ? workTab() : tab === 'order' ? orderTab() : tab === 'alerts' ? alertsTab() : inboxTab();
    if (state.stopped && !view) {
      body.unshift(h('div', { class: 'banner', text: state.needs_login
        ? 'AI 사용 한도가 다 되어 멈췄어요. PC에서 다른 아이디로 로그인한 뒤 다시 시작해 주세요.'
        : '긴급 정지 중이에요. 모든 일이 멈춰 있어요.' }));
    }
    app.replaceChildren(...[body].flat(Infinity).filter(Boolean));
  }

  let lastVersion = '';
  async function refresh() {
    if (!token) return render();
    try {
      const s = await api('/m/api/state');
      const changed = s.version !== lastVersion;
      lastVersion = s.version;
      state = s;
      loadError = '';
      // 글을 쓰는 중(지시·수정 요청)에는 다시 그리지 않는다 (입력이 지워지지 않게)
      const typing = document.activeElement && ['TEXTAREA', 'INPUT', 'SELECT'].includes(document.activeElement.tagName);
      if (changed && !typing) render();
      else if (!changed) { /* 그대로 */ }
      if ($('#banner').textContent.startsWith('PC와 연결')) banner('');
    } catch (e) {
      if (token) {
        banner(`PC와 연결이 안 돼요: ${e.message}`);
        if (!state) { loadError = e.message; render(); }
      } else render();
    }
  }

  document.querySelectorAll('#tabs button').forEach((b) => b.addEventListener('click', () => { tab = b.dataset.tab; view = null; render(); }));
  $('#stop').addEventListener('click', () => {
    if (!state) return;
    const stopping = !state.stopped;
    if (stopping && !window.confirm('모든 직원의 일을 멈출까요?')) return;
    act($('#stop'), api('/m/api/stop', { stopped: stopping }), stopping ? '모두 멈췄어요' : '다시 일할게요!');
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

  const m = /[#&]pair=([A-Za-z0-9-]{8,9})/.exec(location.hash);
  if (m) {
    history.replaceState(null, '', location.pathname);
    pair(m[1]);
  } else {
    refresh().then(render);
  }
  timer = setInterval(() => { if (!document.hidden) refresh(); }, 5000);
  window.addEventListener('pagehide', () => clearInterval(timer));
})();
