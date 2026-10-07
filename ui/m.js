// 휴대폰 리모컨 (/m): 결재·지시·긴급 정지. 서버 글은 모두 textContent로 넣는다 (innerHTML은 고정 선 아이콘 글자열에만).
// 짝짓기: PC 화면 QR의 주소 끝 #pair=번호 → /m/api/pair → 기기 토큰을 이 휴대폰에만 저장 (localStorage).
// 개발용 확인 화면: 주소 끝 #demo=states (가짜 작업으로 앱 그리기) · #demo=pair (짝짓기 화면). 이때는 서버·토큰·저장소를 전혀 건드리지 않는다.
(() => {
  'use strict';

  // ---------------------------------------------------------------- 순수 계산 (화면 없이 node로 점검: tools/dev/m_sim.js)
  // 진행판 다섯 칸: [키, 칸 이름, 들어가는 상태들] — PC 진행판과 같은 순서
  const KB = [['wait', '대기', ['queued', 'ready']], ['work', '작업 중', ['blocked', 'running']], ['check', '검사·리뷰', ['checking']],
    ['approve', '결재 대기', ['awaiting_approval']], ['done', '완료', ['done']]];

  const logic = {
    KB,
    // 숫자는 서버(/m/api/state)가 준 작업 목록으로만 센다. 지어낸 값 없음.
    counts(state) {
      const active = (state && state.active) || [];
      return {
        approvals: ((state && state.inbox) || []).length,
        blocked: active.filter((t) => t.status === 'blocked').length,
        working: active.filter((t) => t.status === 'running' || t.status === 'checking').length,
      };
    },
    // 결재함 맨 위 한 줄. 0건인 것은 말하지 않는다.
    summaryText(c) {
      const parts = [];
      if (c.approvals) parts.push(`정할 일 ${c.approvals}건`);
      if (c.blocked) parts.push(`막힌 일 ${c.blocked}건`);
      if (parts.length) return parts.join(' · ');
      return c.working ? `정할 일은 없고, ${c.working}건이 일하는 중이에요.` : '정할 일이 없어요. 지금은 조용해요.';
    },
    // 진행판 맨 위 한 줄: 막힘 > 결재 > 일하는 중 > 조용함
    nowLine(state) {
      const c = logic.counts(state);
      const cur = state && state.current;
      if (c.blocked) return { tone: 'blocked', icon: 'alert', text: `막힌 일이 ${c.blocked}개 있어요. 눌러서 도와주세요!` };
      if (c.approvals) return { tone: 'awaiting', icon: 'inbox', text: `결재를 기다리는 일이 ${c.approvals}개예요.` };
      if (cur) return { tone: 'running', icon: 'bolt', text: `지금 ${cur.who} · '${cur.title}' 하는 중이에요.` };
      return { tone: 'idle', icon: 'check', text: '지금은 조용해요.' };
    },
    // 진행판 칸별 작업 (칸 안에서는 상태 순서대로)
    columns(state) {
      const all = [...(state.active || []), ...(state.inbox || []), ...(state.done || [])];
      return KB.map(([key, label, sts]) => ({
        key, label,
        tasks: all.filter((t) => sts.includes(t.status)).sort((a, b) => sts.indexOf(a.status) - sts.indexOf(b.status)),
      }));
    },
    // '18분 전' 같은 말 (시각을 못 읽으면 빈 글)
    ago(iso, now) {
      const t = Date.parse(iso || '');
      if (!Number.isFinite(t)) return '';
      const s = Math.max(0, Math.round((now - t) / 1000));
      if (s < 60) return '방금';
      const m = Math.floor(s / 60);
      if (m < 60) return `${m}분 전`;
      const hh = Math.floor(m / 60);
      if (hh < 24) return `${hh}시간 전`;
      return `${Math.floor(hh / 24)}일 전`;
    },
    // 작업 종류 이름 (서버 model.KIND_LABELS와 같은 말). 모르는 종류는 영어를 그대로 보이지 않고 비운다
    KIND_LABELS: { plan: '기획', build: '개발', research: '리서치·문서', skill: '스킬 공부', look: '의상 제작', hire: '새 직원', tool: 'MCP 만들기' },
    initial(name) { return Array.from(String(name || ''))[0] || ''; },
    // 에너지가 거의 바닥이면 칩을 노란 톤으로
    energyLow(e) { return Boolean(e && e.max > 0 && e.left / e.max <= 0.15); },
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = { logic };
  if (typeof document === 'undefined') return; // node 점검에서는 여기까지

  // ---------------------------------------------------------------- 준비
  const KEY = 'ais.device';
  const $ = (s) => document.querySelector(s);
  const app = $('#app');
  const hashParam = (k) => (new RegExp(`[#&]${k}=([A-Za-z0-9_-]+)`).exec(location.hash) || [])[1] || '';
  const DEMO = ['states', 'pair'].includes(hashParam('demo')) ? hashParam('demo') : ''; // 개발용: 서버에 아무것도 보내지 않는다
  let token = '';
  let state = null;
  let tab = 'inbox';
  let view = null; // { id } 작업 자세히 보기
  let timer = null;
  let loadError = ''; // 처음 불러오다 실패한 이유 (있으면 '불러오는 중…' 대신 다시 시도 단추)
  const draft = { text: '', project: '' }; // 지시 글 초안 (이 창이 열려 있는 동안만, 저장소에는 안 넣는다)

  if (!DEMO) { try { token = localStorage.getItem(KEY) || ''; } catch (_) { token = ''; } }

  // 선 아이콘 (고정 글자열만 innerHTML로 넣는다. 서버 글은 절대 넣지 않는다)
  const ICONS = {
    bolt: '<svg viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
    inbox: '<svg viewBox="0 0 24 24"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
    board: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="5" height="16" rx="1.5"/><rect x="9.5" y="4" width="5" height="10" rx="1.5"/><rect x="16" y="4" width="5" height="13" rx="1.5"/></svg>',
    send: '<svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>',
    bell: '<svg viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
    bellOff: '<svg viewBox="0 0 24 24"><path d="M13.73 21a2 2 0 0 1-3.46 0"/><path d="M18.63 13A17.9 17.9 0 0 1 18 8"/><path d="M6.26 6.26A5.86 5.86 0 0 0 6 8c0 7-3 9-3 9h14"/><path d="M18 8a6 6 0 0 0-9.33-5"/><line x1="1" y1="1" x2="23" y2="23"/></svg>',
    check: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><polyline points="8 12.5 11 15.5 16 9.5"/></svg>',
    alert: '<svg viewBox="0 0 24 24"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    next: '<svg viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg>',
    back: '<svg viewBox="0 0 24 24"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>',
    phone: '<svg viewBox="0 0 24 24"><rect x="7" y="2" width="10" height="20" rx="2.5"/><line x1="11" y1="18" x2="13" y2="18"/></svg>',
    cloudOff: '<svg viewBox="0 0 24 24"><path d="M22.61 16.95A5 5 0 0 0 18 10h-1.26a8 8 0 0 0-7.05-6M5 5a8 8 0 0 0 4 15h9a5 5 0 0 0 1.7-.3"/><line x1="1" y1="1" x2="23" y2="23"/></svg>',
    columns: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><line x1="9" y1="4" x2="9" y2="20"/><line x1="15" y1="4" x2="15" y2="20"/></svg>',
  };
  function icon(name, cls = 'ic') {
    const s = document.createElement('span');
    s.className = cls;
    s.setAttribute('aria-hidden', 'true');
    s.innerHTML = ICONS[name] || ''; // 고정 아이콘만
    return s;
  }
  document.querySelectorAll('[data-icon]').forEach((el) => { el.innerHTML = ICONS[el.dataset.icon] || ''; });

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
    if (DEMO) throw new Error('연습 화면이에요. 서버에 아무것도 보내지 않아요.');
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
    if (DEMO) { banner('연습 화면이에요. 실제로는 아무것도 바뀌지 않아요.'); return; }
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
    const input = h('input', { type: 'text', maxlength: '9', placeholder: 'ABCD-EFGH', autocomplete: 'off', autocapitalize: 'characters', 'aria-label': '짝짓기 번호' });
    return h('section', { class: 'pair' },
      icon('phone', 'big'),
      h('h2', { text: '휴대폰 연결' }),
      h('p', { text: 'PC의 AI 스튜디오에서 "휴대폰 연결" 창을 열고 QR을 찍어 주세요.' }),
      h('p', { text: 'QR이 안 되면 창에 보이는 짝짓기 번호를 아래에 넣어도 돼요.' }),
      input,
      h('div', { class: 'btns' }, h('button', { class: 'btn primary', type: 'button', text: '연결하기', onclick: () => pair(input.value) })));
  }

  // ---------------------------------------------------------------- 화면
  const chip = (t) => h('span', { class: `chip s-${t.status}`, text: t.status_label });
  const emptyState = (ic, text, mini = false) => h('div', { class: `empty${mini ? ' mini' : ''}` }, icon(ic), h('p', { text }));
  const section = (label, n, tone) => h('h3', { class: 'sec' }, h('span', { text: label }), h('span', { class: `count ${tone || ''}`, text: String(n) }));

  // cta: 카드 맨 아래 알약 안내 { text, red } — 카드 전체가 눌리는 단추이므로 안내 글자일 뿐이다
  function taskCard(t, cta) {
    const when = logic.ago(t.updated_at, Date.now());
    return h('button', { class: `card tap${t.status === 'blocked' ? ' is-blocked' : ''}`, type: 'button', onclick: () => open(t.id) },
      h('span', { class: 'chips' }, h('span', { class: 'chip', text: t.kind_label }), chip(t), when ? h('span', { class: 'when', text: when }) : null),
      h('span', { class: 'title', text: t.title }),
      t.who ? h('span', { class: 'meta' }, h('span', { class: 'av', 'aria-hidden': 'true', text: logic.initial(t.who) }),
        h('span', { text: `${t.who}${t.waiting ? ` · ${t.waiting}` : ''}` })) : null,
      t.blocked_reason ? h('span', { class: 'why', text: t.blocked_reason }) : null,
      cta ? h('span', { class: `go${cta.red ? ' red' : ''}` }, cta.text, icon('next', 'ic')) : null);
  }

  function inboxTab() {
    const c = logic.counts(state);
    const blocked = state.active.filter((t) => t.status === 'blocked');
    const stat = (n, label, tone) => h('div', { class: `stat${n ? ` ${tone}` : ''}` }, h('b', { text: String(n) }), h('span', { text: label }));
    const out = [
      h('h2', { text: '결재함' }),
      h('section', { class: 'sum', 'aria-label': '요약' },
        h('p', { class: 'sum-line', text: logic.summaryText(c) }),
        h('div', { class: 'stats' }, stat(c.approvals, '결재 기다림', 'awaiting'), stat(c.blocked, '막힘', 'blocked'), stat(c.working, '일하는 중', 'running')))];
    if (blocked.length) out.push(section('막힌 일', blocked.length, 'blocked'), blocked.map((t) => taskCard(t, { text: '살펴보고 도와주기', red: true })));
    if (state.inbox.length) out.push(section('결재 기다림', state.inbox.length, 'awaiting'), state.inbox.map((t) => taskCard(t, { text: t.kind === 'plan' ? '퀘스트 고르기' : '내용 보고 결재하기' })));
    if (!blocked.length && !state.inbox.length) out.push(emptyState('inbox', '결재함이 비어 있어요.'));
    return out;
  }

  // 진행판 (PC 진행판과 같은 다섯 칸, 옆으로 밀어 넘김). 위에는 한 줄 요약 (발표 캐릭터는 쓰지 않는다)
  function workTab() {
    const line = logic.nowLine(state);
    return [
      h('h2', { text: '진행판' }),
      h('div', { class: `now t-${line.tone}` }, icon(line.icon), h('span', { text: line.text })),
      h('div', { class: 'kb', 'aria-label': '진행판' }, logic.columns(state).map((col) =>
        h('section', { class: `kb-col k-${col.key}${col.tasks.length ? ' has' : ''}`, 'aria-label': `${col.label} ${col.tasks.length}개` },
          h('h3', {}, h('i', { 'aria-hidden': 'true' }), h('span', { text: col.label }), h('b', { text: String(col.tasks.length) })),
          col.tasks.length ? col.tasks.map((t) => taskCard(t)) : emptyState('columns', '비어 있어요', true)))),
      h('p', { class: 'kb-hint', text: '← 옆으로 밀면 다음 칸 →' }),
    ];
  }

  function orderTab() {
    const text = h('textarea', { maxlength: '4000', placeholder: '무엇을 시킬까요? 예: 저장 기능에 자동 저장을 더해 줘', 'aria-label': '지시', oninput: (e) => { draft.text = e.target.value; } });
    text.value = draft.text;
    const project = h('select', { 'aria-label': '프로젝트', onchange: (e) => { draft.project = e.target.value; } }, state.projects.map((p) => h('option', { value: p.key, text: p.title })));
    if (draft.project && state.projects.some((p) => p.key === draft.project)) project.value = draft.project;
    return [h('h2', { text: '지시 보내기' }),
      h('p', { class: 'sub', text: '기획 담당이 퀘스트로 나눠 오면 결재함에서 골라 주세요.' }),
      h('section', { class: 'card form' },
        h('label', { class: 'field' }, h('span', { text: '프로젝트' }), project),
        h('label', { class: 'field' }, h('span', { text: '지시' }), text),
        h('div', { class: 'btns' }, h('button', { class: 'btn primary', type: 'button', onclick: (e) => {
          if (!text.value.trim()) { text.focus(); return; }
          act(e.currentTarget, api('/m/api/directive', { text: text.value.trim(), project: project.value }), '지시를 보냈어요!', () => { text.value = ''; draft.text = ''; });
        } }, icon('send'), '보내기')))];
  }

  function alertsTab() {
    return [h('h2', { text: '알림' }),
      state.alerts.length
        ? h('ul', { class: 'alerts' }, state.alerts.map((a) => h('li', { class: 'alert' },
          h('span', { class: 'av', 'aria-hidden': 'true', text: logic.initial(a.name) || '•' }),
          h('div', { class: 'body' }, h('div', { class: 'head' }, h('b', { text: a.name || '' }), h('time', { text: a.time || '' })), h('p', { text: a.text || '' })))))
        : emptyState('bellOff', '알림이 없어요.'),
      h('div', { class: 'btns' }, h('button', { class: 'btn', type: 'button', text: '이 휴대폰 연결 끊기', onclick: () => {
        if (DEMO) { banner('연습 화면이에요. 실제로는 아무것도 끊지 않아요.'); return; }
        if (window.confirm('이 휴대폰의 연결을 끊을까요? 다시 쓰려면 PC에서 QR을 새로 찍어야 해요.')) api('/m/api/forget', {}).catch(() => {}).finally(forget);
      } }))];
  }

  async function open(id) {
    view = { id, data: null };
    render();
    try {
      view.data = DEMO ? demoTask(id) : await api(`/m/api/task/${encodeURIComponent(id)}`);
      if (!view.data) view.error = '작업을 찾을 수 없어요.';
    } catch (e) {
      view.error = e.message;
    }
    render();
  }

  // 작업 상세 응답에는 종류 이름이 없어서 목록에서 찾거나 같은 이름표로 바꾼다
  function kindLabel(d) {
    const t = [...state.inbox, ...state.active, ...state.done].find((x) => x.id === d.id);
    return (t && t.kind_label) || d.kind_label || logic.KIND_LABELS[d.kind] || '';
  }

  function detail() {
    const d = view.data;
    const back = h('button', { class: 'back', type: 'button', onclick: () => { view = null; render(); } }, icon('back'), '목록');
    if (view.error) return [back, emptyState('alert', view.error)];
    if (!d) return [back, emptyState('inbox', '불러오는 중…')];
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
    if (!['done', 'cancelled'].includes(d.status)) {
      // 결재 대기도 취소할 수 있다 (한 건씩만 — 묶음 취소는 PC 화면에만 있다). 되돌릴 수 없다는 안내가 든 확인 창
      const waiting = d.status === 'awaiting_approval';
      buttons.push(h('button', { class: 'btn danger', type: 'button', text: '취소', onclick: (e) => {
        const ask = waiting ? `'${d.title}' 결재 대기 작업을 취소할까요? 취소하면 작업이 끝나고 되돌릴 수 없어요. 만들어진 결과 파일은 지우지 않아요.` : `'${d.title}' 작업을 취소할까요?`;
        if (window.confirm(ask)) doAct(e.currentTarget, 'cancel', {}, '취소했어요');
      } }));
    }
    note.hidden = true;
    const qaOk = d.qa && d.qa.verdict === 'pass';
    return [back, h('section', { class: 'card detail' },
      h('div', { class: 'chips' }, kindLabel(d) ? h('span', { class: 'chip', text: kindLabel(d) }) : null, h('span', { class: `chip s-${d.status}`, text: d.status_label })),
      h('h2', { text: d.title }),
      d.blocked_reason ? h('p', { class: 'why', text: d.blocked_reason }) : null,
      d.summary ? h('p', { text: d.summary }) : null,
      d.brief ? [h('h3', { text: '목표' }), h('p', { text: d.brief })] : null,
      (d.acceptance || []).length ? [h('h3', { text: '수용 기준' }), h('ul', {}, d.acceptance.map((a) => h('li', { text: a })))] : null,
      (d.quests || []).length ? [h('h3', { text: d.status === 'awaiting_approval' ? '퀘스트 (승인할 것만 남겨 두세요)' : '퀘스트' }), d.quests.map((q, i) => h('label', { class: 'quest' },
        d.status === 'awaiting_approval'
          ? h('input', { type: 'checkbox', checked: true, onchange: (e) => { if (e.target.checked) picks.add(i); else picks.delete(i); } }) : null,
        h('span', {}, h('b', { text: q.title }), h('span', { class: 'meta', text: q.brief || '' }))))] : null,
      d.qa ? h('div', { class: 'verdicts' }, h('span', { class: `chip ${qaOk ? 'ok' : d.qa.verdict ? 'bad' : ''}`,
        text: `품질 검사: ${qaOk ? '합격' : d.qa.verdict || '없음'}${d.qa.total ? ` (${d.qa.passed}/${d.qa.total})` : ''}` })) : null,
      d.review ? [h('h3', { text: `리뷰: ${d.review.verdict === 'approve' ? '통과' : d.review.verdict || ''}` }), h('p', { text: d.review.summary || '' }),
        (d.review.findings || []).length ? h('ul', {}, d.review.findings.map((f) => h('li', { text: `${f.file || ''} ${f.issue || ''}` }))) : null] : null,
      d.report ? [h('h3', { text: '보고' }), h('p', { text: d.report })] : null,
      d.body ? [h('h3', { text: d.kind === 'build' ? '바뀐 코드' : d.kind === 'research' ? '보고서' : '내용' }), h('pre', { text: d.body })] : null,
      note),
    buttons.length ? h('div', { class: 'actbar' }, buttons) : null];
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
    } finally {
      // 위쪽 바의 정지 단추처럼 다시 그려도 그대로 남는 단추는 여기서 풀어 줘야 다시 누를 수 있다
      if (btn) btn.disabled = false;
    }
  }

  // 스크롤 자리 기억: 같은 화면을 새 데이터로 다시 그릴 때는 그 자리(세로·진행판 가로)에 그대로 두고,
  // 다른 화면으로 가면 맨 위에서 시작하되 목록으로 돌아오면 있던 자리로 돌려놓는다.
  let lastKey = '';
  const memo = {};
  function render() {
    const paired = Boolean(token);
    $('#tabs').hidden = !paired || !state;
    $('#stop').hidden = !paired || !state;
    $('#energy').hidden = !paired || !state;
    if (!paired) { app.replaceChildren(pairScreen()); lastKey = 'pair'; return; }
    if (!state) {
      app.replaceChildren(loadError
        ? h('section', { class: 'pair' },
          icon('cloudOff', 'big red'),
          h('h2', { text: 'PC에 연결하지 못했어요' }),
          h('p', { text: loadError }),
          h('div', { class: 'btns' }, h('button', { class: 'btn primary', type: 'button', text: '다시 시도', onclick: () => { loadError = ''; render(); refresh(); } })))
        : emptyState('inbox', '불러오는 중…'));
      lastKey = 'loading';
      return;
    }
    $('#name').textContent = state.studio.name + (state.studio.fake ? ' (연습용)' : '');
    $('#energy-text').textContent = `${state.energy.left}/${state.energy.max}`;
    $('#energy').classList.toggle('low', logic.energyLow(state.energy));
    const stop = $('#stop');
    stop.textContent = state.stopped ? '다시 시작' : '긴급 정지';
    stop.classList.toggle('on', state.stopped);
    const badge = $('#badge');
    badge.hidden = !state.inbox.length;
    badge.textContent = String(state.inbox.length);
    for (const b of document.querySelectorAll('#tabs button')) b.setAttribute('aria-current', b.dataset.tab === tab && !view ? 'page' : 'false');
    const body = view ? detail() : tab === 'work' ? workTab() : tab === 'order' ? orderTab() : tab === 'alerts' ? alertsTab() : inboxTab();
    if (state.stopped && !view) {
      body.unshift(h('div', { class: 'notice', role: 'status' }, icon('alert'), h('span', { text: state.needs_login
        ? 'AI 사용 한도가 다 되어 멈췄어요. PC에서 다른 아이디로 로그인한 뒤 다시 시작해 주세요.'
        : '긴급 정지 중이에요. 모든 일이 멈춰 있어요.' })));
    }
    const key = view ? `v:${view.id}` : `t:${tab}`;
    const kb = app.querySelector('.kb');
    const here = { y: window.scrollY, kb: kb ? kb.scrollLeft : 0 };
    if (lastKey.startsWith('t:') && key !== lastKey) memo[lastKey] = here; // 떠나는 목록의 자리 기억
    const want = key === lastKey ? here : (memo[key] || { y: 0, kb: 0 });
    app.replaceChildren(...[body].flat(Infinity).filter(Boolean));
    const nkb = app.querySelector('.kb');
    if (nkb && want.kb) nkb.scrollLeft = want.kb;
    window.scrollTo(0, want.y);
    lastKey = key;
  }

  let lastVersion = '';
  async function refresh() {
    if (DEMO) return;
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

  // ---------------------------------------------------------------- 개발용 가짜 화면 (#demo=states · #demo=pair). 서버·토큰·저장소를 건드리지 않는다.
  function demoTasks() {
    const now = Date.now();
    const at = (min) => new Date(now - min * 60000).toISOString();
    const T = (id, kind, kind_label, status, status_label, title, who, min, extra = {}) =>
      ({ id, kind, kind_label, status, status_label, title, who, project: 'core', updated_at: at(min), blocked_reason: '', waiting: null, run_requested: false, ...extra });
    return {
      inbox: [
        T('D101', 'plan', '기획', 'awaiting_approval', '결재 대기', '코어 쿠리어 시작 화면에 제목과 시작 단추를 넣어 줘', '하나', 18),
        T('D102', 'build', '개발', 'awaiting_approval', '결재 대기', '결과 화면에 다시 하기 단추 넣기', '솔', 125),
      ],
      active: [
        T('D103', 'build', '개발', 'blocked', '막힘', '게임 아이콘과 실행 파일 이름 정하기', '솔', 42, { blocked_reason: '내보내기 도구를 찾지 못했어요. 도구를 깔아도 되는지 알려 주세요.' }),
        T('D104', 'build', '개발', 'running', '작업 중', '스크린샷을 저장하는 단추와 저장 폴더 안내를 화면에 넣고, 저장이 끝나면 알려 주는 말풍선도 같이 만들기', '솔', 3),
        T('D105', 'research', '리서치·문서', 'checking', '검증 중', 'Steam 스토어 페이지에 필요한 그림 크기 정리', '루나', 9),
        T('D106', 'build', '개발', 'ready', '준비', '타이틀 화면 만들기', '솔', 55, { waiting: '선행 작업 D104 완료 대기' }),
        T('D107', 'plan', '기획', 'queued', '기획 대기', '다음 단계를 기획해 줘', '하나', 70),
      ],
      done: [
        T('D108', 'research', '리서치·문서', 'done', '완료', 'Godot 4에서 윈도우 내보내기 조사', '루나', 60 * 26),
        T('D109', 'build', '개발', 'done', '완료', '승패 결과와 재시작 흐름 연결', '솔', 60 * 50),
        T('D110', 'research', '리서치·문서', 'done', '완료', '회고: 플레이어 이동 씬 정리', '루나', 60 * 74),
      ],
    };
  }
  function demoState() {
    // 덧붙이는 확인용 주소 값: &stopped=1 긴급 정지 중 · &fake=1 연습용 이름표 · &empty=1 작업·알림 없음 · &low=1 에너지 거의 없음
    const t = hashParam('empty') === '1' ? { inbox: [], active: [], done: [] } : demoTasks();
    return {
      studio: { name: 'AI 스튜디오', fake: hashParam('fake') === '1' }, version: 'demo', stopped: hashParam('stopped') === '1', needs_login: false,
      energy: hashParam('low') === '1' ? { max: 40, left: 3 } : { max: 40, left: 39 },
      current: t.active.length ? { title: '스크린샷을 저장하는 단추와 저장 폴더 안내…', who: '솔' } : null,
      projects: [{ key: 'core', title: 'Core Courier' }, { key: 'docs', title: 'Studio Docs' }],
      inbox: t.inbox, active: t.active, done: t.done,
      alerts: hashParam('empty') === '1' ? [] : [
        { time: '23:19', name: '하나', text: '기획안 나왔어요! 골라 주세요', task: 'D101' },
        { time: '22:42', name: '솔', text: '게임 아이콘과 실행 파일 이름 정하기 막혔어요, 도와주세요', task: 'D103' },
        { time: '21:05', name: '루나', text: '회고: 플레이어 이동 씬 정리 완료!', task: 'D110' },
      ],
    };
  }
  function demoTask(id) {
    const s = state;
    const t = [...s.inbox, ...s.active, ...s.done].find((x) => x.id === id);
    if (!t) return null;
    const d = { ...t, brief: '', acceptance: [], report: '', qa: null, review: null };
    if (id === 'D101') {
      d.summary = '시작 화면을 만들고, 제목과 시작 단추를 넣고, 시작하면 첫 장면으로 가게 해요.';
      d.quests = [
        { title: '시작 화면 만들기', brief: '배경과 제목 글자를 넣어요.' },
        { title: '시작 단추 넣기', brief: '누르면 첫 장면으로 가요. 키보드와 터치 모두 돼요.' },
        { title: '시작 효과음 붙이기', brief: '단추를 누를 때 짧은 소리가 나요.' },
      ];
    } else if (id === 'D102') {
      d.brief = '결과 화면에 "다시 하기" 단추를 넣고, 누르면 같은 판을 다시 시작하게 해 주세요.';
      d.acceptance = ['결과 화면에 다시 하기 단추가 보인다', '누르면 점수가 0으로 돌아가고 새 판이 시작된다'];
      d.qa = { verdict: 'pass', passed: 8, total: 8 };
      d.review = { verdict: 'approve', summary: '요청한 단추가 들어갔고 시험도 모두 통과했어요.', findings: [] };
      d.body = 'diff --git a/ui/result.gd b/ui/result.gd\n+func _on_retry_pressed():\n+    get_tree().reload_current_scene()';
    } else if (t.status === 'blocked') {
      d.brief = '게임 아이콘과 실행 파일 이름을 정해서 내보내기 설정에 넣어 주세요.';
    }
    return d;
  }

  if (DEMO) {
    if (DEMO === 'states') {
      token = 'demo'; // 이 창의 메모리에만 있는 자리표시 글자. 서버에 보내거나 저장하지 않는다 (api()는 연습 화면에서 항상 거절).
      state = demoState();
      if (['inbox', 'work', 'order', 'alerts'].includes(hashParam('tab'))) tab = hashParam('tab');
      const id = hashParam('open');
      if (id) view = { id, data: demoTask(id) };
    }
    render();
  } else {
    const m = /[#&]pair=([A-Za-z0-9-]{8,9})/.exec(location.hash);
    if (m) {
      history.replaceState(null, '', location.pathname);
      pair(m[1]);
    } else {
      refresh().then(render);
    }
    timer = setInterval(() => { if (!document.hidden) refresh(); }, 5000);
    window.addEventListener('pagehide', () => clearInterval(timer));
  }
})();
