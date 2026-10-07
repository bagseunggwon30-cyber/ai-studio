/* AI 스튜디오 — 빠른 찾기 (Ctrl K)
 *
 * 위쪽 바의 검색칸. 일 · 직원 · 스킬 · 화면을 글자로 찾아 바로 간다.
 * 비어 있을 때는 '지금 챙길 일'(결재 기다림·막힘)과 화면 바로가기를 보여 준다.
 * 위·아래 화살표로 고르고 Enter로 열고 Esc로 닫는다. 글자는 모두 textContent로 넣는다 (작업 제목은 에이전트가 만든 글).
 * 순수 계산(words·score·highlightParts·search)은 DOM 없이 돈다 — tools/dev/finder_sim.js가 확인한다.
 */
'use strict';

const Finder = (() => {
  // 화면 바로가기: [동작 이름(app.js ACTIONS), 보이는 이름, 같이 찾아지는 말]
  const SCREENS = [
    ['home', '홈', '오늘 처음 화면 요약'],
    ['board', '진행판', '칸반 보드 일 목록'],
    ['media', '이미지·영상 작업대', '그림 영상 만들기 제작 그록 이미지 비디오'],
    ['novel', '소설 집필실', '소설 글쓰기 작품 원고 설정집 집필 이야기 장'],
    ['design', '디자인 작업실', '디자인 시안 화면 그림 기획서 규칙 점검'],
    ['workbench', '노드 편집기 (고급)', '기능 작업대 노드 서랍 흐름'],
    ['inbox', '결재함', '결재 승인 기다림'],
    ['meeting', '회의실', '기획 회의'],
    ['team', '직원', '하나 솔 클로 루나 사람'],
    ['skills', '스킬 학습', '스킬 배우기'],
    ['mcp', 'MCP 보관소', '도구 서재'],
    ['schedules', '자동 업무', '일정 반복 시계'],
    ['gateway', '외부 연결', 'MCP 연결 문 챗지피티 ChatGPT Dots 바깥 앱 OAuth 터널 연결 번호 권한'],
    ['diary', '업무 일지', '기록 지난 일'],
    ['trophies', '완성작', '완성 결과물 진열장'],
    ['digest', '주간 요약', '이번 주 정리 보고'],
  ];
  const SHOW = { task: 6, person: 4, skill: 4 };
  const NAV_SVG = {
    screen: '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="14" rx="3"/><path d="M4 9.5h16"/></svg>',
    skill: '<svg viewBox="0 0 24 24"><path d="M12 3.5l2.4 5 5.4.7-4 3.8 1 5.4-4.8-2.6-4.8 2.6 1-5.4-4-3.8 5.4-.7Z"/></svg>',
    task: '<svg viewBox="0 0 24 24"><rect x="5" y="4" width="14" height="16" rx="3"/><path d="M9 9h6M9 13h6M9 17h3"/></svg>',
    board: '<svg viewBox="0 0 24 24"><rect x="3.5" y="4" width="4.5" height="16" rx="1.5"/><rect x="9.75" y="4" width="4.5" height="10" rx="1.5"/><rect x="16" y="4" width="4.5" height="13" rx="1.5"/></svg>',
  };

  // ---------------------------------------------------------------- 순수 계산
  // 찾는 글 → 소문자 낱말 목록 (띄어쓰기로 나눔)
  function words(query) {
    return String(query || '').toLowerCase().split(' ').filter(Boolean);
  }

  // 글에 낱말이 모두 들어 있으면 점수(앞에서 시작할수록 높음), 하나라도 없으면 -1
  function score(text, ws) {
    const t = String(text || '').toLowerCase();
    let s = 0;
    for (const w of ws) {
      const i = t.indexOf(w);
      if (i < 0) return -1;
      s += i === 0 ? 3 : 1;
    }
    return s;
  }

  // 첫 낱말이 처음 나오는 곳을 [앞, 맞은 곳, 뒤]로 자른다 (강조용). 없으면 [글, '', '']
  function highlightParts(text, ws) {
    const t = String(text || '');
    const w = ws[0];
    const i = w ? t.toLowerCase().indexOf(w) : -1;
    return i < 0 ? [t, '', ''] : [t.slice(0, i), t.slice(i, i + w.length), t.slice(i + w.length)];
  }

  // 모든 갈래에서 찾는다. 갈래마다 점수 높은 것부터 SHOW 개까지.
  // data = { tasks, team, skills, statusLabel, ownerName, kindLabel, projectTitle }
  function search(query, data) {
    const ws = words(query);
    const rank = (list, textOf, limit) => list
      .map((x) => ({ x, s: score(textOf(x), ws) }))
      .filter((r) => r.s >= 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, limit)
      .map((r) => r.x);
    const live = (data.tasks || []).filter((t) => t.status !== 'cancelled' && !t.archived);
    return {
      screens: rank(SCREENS, (x) => `${x[1]} ${x[2]}`, 12),
      tasks: rank(live, (t) => `${t.id} ${t.title} ${data.ownerName(t)} ${data.kindLabel(t)} ${data.projectTitle(t.project)}`, SHOW.task),
      people: rank(data.team || [], (p) => `${p.name} ${p.title || ''} ${p.job || ''}`, SHOW.person),
      skills: rank(data.skills || [], (s) => `${s.title || ''} ${s.slug || ''} ${s.description || ''}`, SHOW.skill),
    };
  }

  // ---------------------------------------------------------------- 화면
  let hooks = { actions: {}, setView: () => {} };
  let input = null;
  let box = null;
  let rows = []; // 지금 보이는 항목들 { el, go }
  let cur = -1;
  let opened = false;

  const h = (...a) => Popups.h(...a);

  function icon(name) {
    const el = h('span', { class: 'fi-ico', 'aria-hidden': 'true' });
    el.innerHTML = NAV_SVG[name] || '';
    return el;
  }

  function label(text, ws) {
    const [a, m, z] = highlightParts(text, ws);
    return h('span', { class: 'fi-main' }, a, m ? h('mark', { text: m }) : null, z);
  }

  function dataNow() {
    const v = typeof Board !== 'undefined' && Board.view ? Board.view() : Data.get();
    return {
      tasks: v.tasks || [],
      team: Data.TEAM || [],
      skills: Data.get().skills || [],
      statusLabel: (t) => Data.statusLabel(t),
      ownerName: (t) => (Data.owner(t) || {}).name || '',
      kindLabel: (t) => Data.kindLabel(t),
      projectTitle: (key) => Data.projectTitle(key) || '',
    };
  }

  function openTask(t) {
    if (t.status === 'awaiting_approval') Popups.openTask(t);
    else Popups.taskCard(t.id);
  }

  function item(iconEl, mainEl, sub, go) {
    const el = h('button', { type: 'button', class: 'finder-item', role: 'option', tabindex: '-1', 'aria-selected': 'false', onclick: () => choose({ go }) },
      iconEl, mainEl, sub ? h('span', { class: 'fi-sub', text: sub }) : null);
    return { el, go };
  }

  function build(query) {
    const d = dataNow();
    const ws = words(query);
    const out = [];
    const parts = [];
    const group = (title, list) => {
      if (!list.length) return;
      parts.push(h('p', { class: 'finder-group', role: 'presentation', text: title }));
      for (const r of list) { out.push(r); parts.push(r.el); }
    };
    const taskRow = (t) => item(icon('task'), label(`${t.id} · ${t.title}`, ws), `${d.statusLabel(t)} · ${d.ownerName(t)}`, () => openTask(t));
    if (!ws.length) {
      // 비어 있을 때: 지금 챙길 일 → 화면 바로가기
      const need = d.tasks.filter((t) => t.status === 'awaiting_approval' || t.status === 'blocked').slice(0, 3);
      group('지금 챙길 일', need.map(taskRow));
      group('화면 바로가기', SCREENS.map(([action, name]) => item(icon('screen'), label(name, ws), '', () => (hooks.actions[action] || (() => {}))())));
    } else {
      const r = search(query, d);
      group('일', r.tasks.map(taskRow));
      group('직원', r.people.map((p) => item(h('span', { class: 'fi-ico', 'aria-hidden': 'true' }, Popups.face(p.id, 'normal')), label(p.name, ws), `${p.title || ''} 담당`, () => Popups.employee(p.id))));
      group('스킬', r.skills.map((s) => item(icon('skill'), label(s.title || s.slug, ws), '배운 스킬', () => Popups.skillDetail(s.slug))));
      group('화면', r.screens.map(([action, name]) => item(icon('screen'), label(name, ws), '', () => (hooks.actions[action] || (() => {}))())));
      if (r.tasks.length && typeof Board !== 'undefined') {
        // 일이 여럿이면 진행판에서 모아 보기
        parts.splice(0, 0, h('p', { class: 'finder-group', role: 'presentation', text: '진행판' }));
        const more = item(icon('board'), h('span', { class: 'fi-main', text: `‘${query.trim()}’로 진행판 걸러 보기` }), `${r.tasks.length}개`, () => { hooks.setView('board'); Board.setQuery(query.trim()); });
        out.unshift(more);
        parts.splice(1, 0, more.el);
      }
      if (!out.length) parts.push(h('p', { class: 'finder-empty', text: '찾는 것이 없어요. 다른 낱말로 찾아 보세요.' }));
    }
    parts.push(h('p', { class: 'finder-foot', 'aria-hidden': 'true', text: '↑↓ 고르기 · Enter 열기 · Esc 닫기' }));
    return { out, parts };
  }

  function show() {
    if (!input || !box) return;
    const { out, parts } = build(input.value);
    rows = out;
    cur = rows.length ? 0 : -1;
    box.replaceChildren(...parts);
    box.hidden = false;
    opened = true;
    input.setAttribute('aria-expanded', 'true');
    mark();
  }

  function hide() {
    if (!box) return;
    box.hidden = true;
    opened = false;
    cur = -1;
    if (input) input.setAttribute('aria-expanded', 'false');
  }

  function mark() {
    rows.forEach((r, i) => {
      r.el.classList.toggle('on', i === cur);
      r.el.setAttribute('aria-selected', String(i === cur));
    });
    if (rows[cur]) rows[cur].el.scrollIntoView({ block: 'nearest' });
  }

  function choose(row) {
    hide();
    if (input) { input.value = ''; input.blur(); }
    if (row && row.go) row.go();
  }

  function focus() {
    if (!input) return;
    input.focus();
    input.select();
    show();
  }

  function init(options = {}) {
    hooks = { ...hooks, ...options };
    input = document.getElementById('board-search');
    box = document.getElementById('finder-list');
    if (!input || !box) return;
    input.addEventListener('focus', show);
    input.addEventListener('input', show);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (!opened) { show(); return; }
        if (rows.length) cur = (cur + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length;
        mark();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (rows[cur]) choose(rows[cur]);
      } else if (e.key === 'Escape') {
        e.stopPropagation();
        input.value = '';
        hide();
        input.blur();
      }
    });
    // 목록을 눌러도 입력칸이 초점을 잃지 않게 (그래야 blur로 닫히기 전에 눌림이 간다)
    box.addEventListener('mousedown', (e) => e.preventDefault());
    document.addEventListener('mousedown', (e) => { if (opened && !e.target.closest('#finder')) hide(); });
    input.addEventListener('blur', () => setTimeout(() => { if (document.activeElement !== input) hide(); }, 120));
    // 비어 있을 때의 '지금 챙길 일'은 데이터가 바뀌면 새로 (결재가 들어오는 순간 등)
    if (typeof Data !== 'undefined') Data.on('change', () => { if (opened && !input.value) show(); }); // 글을 쓰는 중에는 결과가 제멋대로 바뀌지 않게
  }

  return { init, focus, hide, logic: { words, score, highlightParts, search, SCREENS } };
})();

if (typeof module !== 'undefined') module.exports = Finder; // tools/dev/finder_sim.js (node)
