/* AI 스튜디오 — 홈(오늘): 사장님이 제일 먼저 보는 화면.
 *
 * 인사말 + 한 줄 요약("결정이 필요한 일 1건, 나머지는 순조로워요") → 핵심 숫자 → 결정이 필요한 일(바로 결재·도와주기 단추) →
 * 전체 진행과 직원별 진행 → 다가오는 자동 업무(없으면 최근 끝난 일). 숫자는 모두 실제 작업·실행 기록으로만 센다 (지어낸 것 없음).
 * 글자는 모두 textContent로 넣는다 (작업 제목은 에이전트가 만든 글). 주간 요약 창(digest)도 여기서 연다.
 * 순수 계산(greeting·summaryText·weekStats·progressSplit·peopleRows·attentionItems·recentDone)은 DOM 없이 돈다 — tools/dev/home_sim.js가 확인한다.
 * board.js가 껍데기(왼쪽 메뉴)와 이 구역을 만들어 주고, 필요한 도구는 init(el, helpers)로 받는다.
 */
'use strict';

const Home = (() => {
  const DAY = 86400000;
  const WEEK = 7 * DAY;

  // ---------------------------------------------------------------- 순수 계산
  const live = (tasks) => tasks.filter((t) => t.status !== 'cancelled' && !t.archived);
  const at = (iso) => Date.parse(iso || '');

  // 시각에 맞는 인사
  function greeting(hour) {
    if (hour < 5) return '늦은 시간이에요';
    if (hour < 11) return '좋은 아침이에요';
    if (hour < 14) return '안녕하세요';
    if (hour < 18) return '좋은 오후예요';
    if (hour < 22) return '좋은 저녁이에요';
    return '늦은 시간이에요';
  }

  // 한 줄 요약 (att = Board.logic.attention 결과, total = 맡긴 일 수)
  function summaryText(att, total) {
    if (!total) return '아직 맡긴 일이 없어요. 아래 명령창에 첫 지시를 적어 보세요.';
    const need = [];
    if (att.approvals) need.push(`결재 ${att.approvals}건`);
    if (att.blocked) need.push(`막힌 일 ${att.blocked}건`);
    if (need.length) return `사장님이 정할 일이 ${need.join(' · ')} 있어요. 나머지는 순조로워요.`;
    if (att.working) return '지금 직원들이 일하는 중이에요. 사장님이 할 일은 없어요.';
    return '지금은 사장님이 할 일이 없어요. 모든 일이 순조로워요.';
  }

  // 이번 주(최근 7일) 숫자: 끝낸 일 · 검사 통과율 · 일한 직원 수. 기획 카드는 퀘스트로 나뉜 뒤라 세지 않는다
  function weekStats(tasks, now = Date.now(), ownerOf = null) {
    const l = live(tasks);
    const recent = (t) => now - at(t.updated_at) <= WEEK && now - at(t.updated_at) >= -DAY;
    const done = l.filter((t) => t.status === 'done' && t.kind !== 'plan' && recent(t));
    const checked = l.filter((t) => t.kind !== 'plan' && t.qa && (t.qa.verdict === 'pass' || t.qa.verdict === 'fail') && recent(t));
    const pass = checked.filter((t) => t.qa.verdict === 'pass').length;
    const workers = new Set(done.map((t) => (ownerOf ? ownerOf(t) : t.role)).filter(Boolean));
    return {
      done: done.length,
      doneTasks: done.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || ''))),
      checked: checked.length,
      passPct: checked.length ? Math.round((pass / checked.length) * 100) : null,
      workers: workers.size,
      open: l.filter((t) => t.status !== 'done' && t.kind !== 'plan').length,
    };
  }

  // 전체 진행: 끝남 · 일하는 중(작업+검사) · 기다림(대기+결재) · 막힘. 기획 카드는 빼고 센다
  function progressSplit(tasks) {
    const l = live(tasks).filter((t) => t.kind !== 'plan');
    const count = (f) => l.filter(f).length;
    const done = count((t) => t.status === 'done');
    const working = count((t) => t.status === 'running' || t.status === 'checking');
    const blocked = count((t) => t.status === 'blocked');
    const waiting = l.length - done - working - blocked;
    return { total: l.length, done, working, waiting, blocked };
  }

  // 직원별: 끝낸 일 · 열린 일 · 끝낸 비율 (ownerOf(t) = 담당 직원 id)
  function peopleRows(tasks, team, ownerOf) {
    const l = live(tasks).filter((t) => t.kind !== 'plan');
    return team.map((p) => {
      const mine = l.filter((t) => ownerOf(t) === p.id);
      const done = mine.filter((t) => t.status === 'done').length;
      const open = mine.length - done;
      return {
        id: p.id, name: p.name, title: p.title || '', state: p.state || 'rest', done, open, total: mine.length,
        pct: mine.length ? Math.round((done / mine.length) * 100) : 0,
      };
    });
  }

  // 결정이 필요한 일: 막힘 먼저, 그다음 결재 기다림. 같은 종류는 오래된 것 먼저
  function attentionItems(tasks) {
    const l = live(tasks).filter((t) => t.status === 'blocked' || t.status === 'awaiting_approval');
    const rank = (t) => (t.status === 'blocked' ? 0 : 1);
    return l.sort((a, b) => rank(a) - rank(b) || String(a.created_at || '').localeCompare(String(b.created_at || '')) || String(a.id).localeCompare(String(b.id)));
  }

  // 최근 끝난 일 (기획 카드 제외)
  function recentDone(tasks, n = 5) {
    return live(tasks).filter((t) => t.status === 'done' && t.kind !== 'plan')
      .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || ''))).slice(0, n);
  }

  const logic = { greeting, summaryText, weekStats, progressSplit, peopleRows, attentionItems, recentDone };

  // ---------------------------------------------------------------- 화면 (init 뒤에만 DOM을 만진다)
  let root = null;
  let H = null; // board.js가 준 도구
  const h = (...a) => Popups.h(...a);

  const ICON = {
    approve: '<svg viewBox="0 0 24 24"><path d="M6 3.5h8l4 4V20.5H6Z"/><path d="M9 13.5l2.2 2.2L15.5 11"/></svg>',
    blocked: '<svg viewBox="0 0 24 24"><path d="M12 4.5l8.5 15h-17Z"/><path d="M12 10v4.5M12 17.3v.2"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="M5.5 12.5l4.2 4.2L18.5 8"/></svg>',
    clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
    chevron: '<svg viewBox="0 0 24 24"><path d="M9.5 6l6 6-6 6"/></svg>',
  };
  const svgEl = (name, cls = 'hm-ico') => { const el = h('span', { class: cls, 'aria-hidden': 'true' }); el.innerHTML = ICON[name] || ''; return el; };

  function init(el, helpers) {
    root = el;
    H = helpers;
  }

  const ownerId = (t) => (Data.owner(t) || {}).id;
  const ownerName = (t) => (Data.owner(t) || {}).name || '';

  // 검사·리뷰 결과를 한 줄 설명으로
  function checkText(t) {
    const out = [];
    if (t.qa && t.qa.verdict === 'pass') out.push(`검사${t.qa.total ? ` ${t.qa.passed}/${t.qa.total}` : ''} 통과`);
    else if (t.qa && t.qa.verdict === 'fail') out.push('검사 탈락');
    if (t.review && t.review.verdict === 'approve') out.push('리뷰 통과');
    else if (t.review && (t.review.verdict === 'changes_requested' || t.review.verdict === 'request_changes')) out.push('리뷰 수정 요청');
    return out;
  }

  function whenShort(iso) {
    const d = iso ? new Date(iso) : null;
    if (!d || Number.isNaN(d.getTime())) return '';
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }

  function newButton() {
    const el = h('button', { type: 'button', class: 'bd-new', 'data-fk': 'home-new', onclick: H.focusCommand });
    el.append(svgEl('plus', 'bd-new-ico'), h('span', { text: '새 지시' }));
    return el;
  }

  function stat(value, unit, label, hint) {
    return h('div', { class: 'hm-stat' }, h('b', {}, value, unit ? h('small', { text: unit }) : null), h('span', { class: 'hm-stat-label', text: label }), hint ? h('small', { class: 'hm-stat-hint', text: hint }) : null);
  }

  function card(title, count, sub, ...body) {
    return h('section', { class: 'hm-card' },
      h('header', { class: 'hm-card-head' }, h('div', {}, h('h3', {}, h('span', { text: title }), count != null ? h('b', { class: 'hm-count', text: String(count) }) : null), sub ? h('p', { text: sub }) : null)),
      ...body);
  }

  // ---- 결정이 필요한 일
  function attnRow(t, now) {
    const blocked = t.status === 'blocked';
    const a = H.actionOf(t);
    const open = () => (t.status === 'awaiting_approval' ? Popups.openTask(t) : Popups.taskCard(t.id));
    const desc = blocked ? (t.blocked_reason || '막혀서 멈췄어요. 사장님이 도와 주세요.')
      : [ownerName(t), Data.kindLabel(t), ...checkText(t)].filter(Boolean).join(' · ');
    const stopped = Data.get().stopped;
    return h('article', {
      class: `hm-row ${blocked ? 'red' : 'amber'}`, tabindex: '0', role: 'button', 'data-id': t.id, 'data-fk': `hm:${t.id}`,
      'aria-label': `${t.title}, ${Data.statusLabel(t)}, ${ownerName(t)}`, onclick: open,
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } },
    },
    h('span', { class: 'hm-row-ico' }, svgEl(blocked ? 'blocked' : 'approve')),
    h('div', { class: 'hm-row-main' }, h('b', { text: t.title, title: t.title }), h('p', { text: desc, title: desc })),
    h('span', { class: 'hm-row-chip', text: blocked ? (t.needs_plan_input ? '답변 필요' : '막힘') : H.ago(t.updated_at, now) || '결재' }),
    a ? h('button', {
      type: 'button', class: `hm-act ${a.cls}`, disabled: a.needsRun && stopped,
      onclick: (e) => { e.stopPropagation(); a.run(); },
    }, a.label) : null);
  }

  function attnCard(view, att, now) {
    const items = attentionItems(view.tasks);
    const shown = items.slice(0, 4);
    const rest = items.length - shown.length;
    const total = live(view.tasks).filter((t) => t.kind !== 'plan').length;
    const body = shown.length ? h('div', { class: 'hm-list' }, shown.map((t) => attnRow(t, now)))
      : h('div', { class: 'hm-clear' }, svgEl('check', 'hm-clear-ico'), h('b', { text: '지금은 결정할 일이 없어요' }),
        h('p', { text: total ? '직원들이 맡은 일을 하고 있어요. 새 일이 올라오면 여기에 먼저 보여 드려요.' : '새 지시를 적으면 직원들이 일을 시작하고, 사장님이 정할 일은 여기에 모여요.' }),
        total ? null : newButton());
    const foot = rest > 0 || shown.length
      ? h('footer', { class: 'hm-card-foot' }, h('button', {
        type: 'button', class: 'hm-link', onclick: () => (att.approvals ? Popups.inbox() : H.goBoard('blocked')),
      }, h('span', { text: rest > 0 ? `${rest}건 더 보기` : att.approvals ? '결재함 열기' : '진행판에서 보기' }), svgEl('chevron', 'hm-link-ico')))
      : null;
    return h('section', { class: 'hm-card hm-attn' },
      h('header', { class: 'hm-card-head' }, h('div', {}, h('h3', {}, h('span', { text: '결정이 필요해요' }), items.length ? h('b', { class: 'hm-count amber', text: String(items.length) }) : null),
        h('p', { text: items.length ? '막힌 일을 먼저, 그다음 결재 기다리는 일을 보여 드려요' : '사장님이 정해 줄 일이 모이는 곳이에요' }))),
      body, foot);
  }

  // ---- 전체 진행 + 직원별
  function progressCard(view) {
    const sp = progressSplit(view.tasks);
    const seg = (n, cls, label) => (n ? h('i', { class: `seg ${cls}`, title: `${label} ${n}`, vars: { '--n': String(n) } }) : null);
    const bar = h('div', { class: 'hm-seg', role: 'img', 'aria-label': `끝남 ${sp.done}, 일하는 중 ${sp.working}, 기다림 ${sp.waiting}, 막힘 ${sp.blocked}` },
      seg(sp.done, 'done', '끝남'), seg(sp.working, 'work', '일하는 중'), seg(sp.waiting, 'wait', '기다림'), seg(sp.blocked, 'bad', '막힘'));
    const legend = h('div', { class: 'hm-legend' },
      [['done', '끝남', sp.done], ['work', '일하는 중', sp.working], ['wait', '기다림', sp.waiting], ['bad', '막힘', sp.blocked]].map(([k, l, n]) => h('span', {}, h('i', { class: `dot ${k}`, 'aria-hidden': 'true' }), `${l} `, h('b', { text: String(n) }))));
    const rows = peopleRows(view.tasks, Data.TEAM || [], ownerId);
    const person = (r) => {
      const p = (Data.TEAM || []).find((x) => x.id === r.id) || {};
      const state = r.state === 'work' ? ['일하는 중', 'on'] : r.state === 'blocked' ? ['막힘', 'bad'] : ['쉬는 중', ''];
      const fill = h('i', {});
      fill.style.setProperty('--pct', `${r.pct}%`);
      return h('li', { class: 'hm-person' },
        h('span', { class: 'hm-person-face' }, Popups.face(r.id, r.state === 'blocked' ? 'worried' : 'normal')),
        h('div', { class: 'hm-person-main' }, h('b', { text: r.name }), h('span', { text: `${r.title ? `${r.title} · ` : ''}${r.done}개 끝냄${r.open ? ` · ${r.open}개 열림` : ''}` })),
        h('span', { class: 'hm-person-bar', role: 'img', 'aria-label': `${r.name} 끝낸 비율 ${r.pct}%`, title: `끝낸 일 ${r.done} / 맡은 일 ${r.total}` }, fill),
        h('span', { class: `hm-person-state ${state[1]}`, text: state[0] }));
    };
    return h('section', { class: 'hm-card hm-prog' },
      h('header', { class: 'hm-card-head' }, h('div', {}, h('h3', {}, h('span', { text: '전체 진행' })), h('p', { text: sp.total ? '맡긴 일 가운데 어디까지 왔는지' : '아직 맡긴 일이 없어요' }))),
      h('div', { class: 'hm-big' }, h('b', { text: String(sp.done) }), h('span', { text: ` / ${sp.total}개 끝남` })),
      bar, legend,
      h('ul', { class: 'hm-people', 'aria-label': '직원별 진행' }, rows.map(person)));
  }

  // ---- 다가오는 자동 업무 (없으면 최근 끝난 일)
  function nextCard(view, now) {
    const sch = (view.schedules || []).filter((x) => x.enabled && x.next).sort((a, b) => String(a.next).localeCompare(String(b.next))).slice(0, 4);
    if (sch.length) {
      const cells = sch.map((x) => h('li', { class: 'hm-next' },
        h('span', { class: 'hm-next-when' }, h('i', { class: 'dot', 'aria-hidden': 'true' }), h('b', { text: whenShort(x.next) })),
        h('b', { class: 'hm-next-title', text: x.title, title: x.title }),
        h('span', { class: 'hm-next-sub', text: x.when || '' }),
        h('span', { class: 'hm-next-sub', text: Data.projectTitle(x.project) || '' })));
      return h('section', { class: 'hm-card hm-nextcard' },
        h('header', { class: 'hm-card-head' }, h('div', {}, h('h3', {}, h('span', { text: '다가오는 자동 업무' })), h('p', { text: `정해 둔 때가 되면 직원이 스스로 시작해요 · ${sch.length}개` })),
          h('button', { type: 'button', class: 'hm-link', onclick: () => Popups.schedules() }, h('span', { text: '자동 업무 열기' }), svgEl('chevron', 'hm-link-ico'))),
        h('ul', { class: 'hm-nexts' }, cells));
    }
    const done = recentDone(view.tasks, 5);
    const cells = done.map((t) => h('li', { class: 'hm-next done', tabindex: '0', role: 'button', 'data-fk': `hmd:${t.id}`, onclick: () => Popups.taskCard(t.id),
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); Popups.taskCard(t.id); } } },
    h('span', { class: 'hm-next-when' }, h('i', { class: 'dot', 'aria-hidden': 'true' }), h('b', { text: H.ago(t.updated_at, now) || '끝남' })),
    h('b', { class: 'hm-next-title', text: t.title, title: t.title }),
    h('span', { class: 'hm-next-sub', text: `${Data.kindLabel(t)} · ${Data.projectTitle(t.project) || ''}` }),
    h('span', { class: 'hm-next-who' }, Popups.face(ownerId(t), 'normal'), h('span', { text: ownerName(t) }))));
    return h('section', { class: 'hm-card hm-nextcard' },
      h('header', { class: 'hm-card-head' }, h('div', {}, h('h3', {}, h('span', { text: '최근 끝난 일' })), h('p', { text: done.length ? '자동 업무가 없어서 최근에 끝난 일을 보여 드려요' : '아직 끝난 일이 없어요' })),
        h('button', { type: 'button', class: 'hm-link', 'data-action': 'diary' }, h('span', { text: '업무 일지 열기' }), svgEl('chevron', 'hm-link-ico'))),
      done.length ? h('ul', { class: 'hm-nexts' }, cells) : null);
  }

  function render(view, att) {
    if (!root || !H) return;
    const now = Date.now();
    const total = live(view.tasks).filter((t) => t.kind !== 'plan').length;
    const ws = weekStats(view.tasks, now, ownerId);
    const energy = view.energy || { max: 0, runsToday: 0 };
    const left = Math.max(0, (energy.max || 0) - (energy.runsToday || 0));
    const focusKey = document.activeElement && root.contains(document.activeElement) ? document.activeElement.getAttribute('data-fk') : null;
    root.replaceChildren(
      h('header', { class: 'hm-head' },
        h('nav', { class: 'bd-crumb', 'aria-label': '위치' }, h('span', { text: '홈' }), h('i', { 'aria-hidden': 'true', text: '›' }), h('span', { class: 'cur', text: '오늘' })),
        h('div', { class: 'hm-titlebar' },
          h('div', { class: 'hm-hello' }, h('h2', { text: `${greeting(new Date(now).getHours())}, 사장님` }), h('p', { class: 'hm-sub', text: summaryText(att, total) })),
          h('div', { class: 'hm-stats' },
            stat(String(ws.done), '개', '이번 주 끝낸 일', ws.workers ? `${ws.workers}명이 일했어요` : '아직 없어요'),
            stat(ws.passPct == null ? '–' : String(ws.passPct), ws.passPct == null ? '' : '%', '검사 통과율', ws.checked ? `이번 주 검사 ${ws.checked}건 중` : '이번 주 검사한 일 없음'),
            stat(String(energy.runsToday || 0), '회', '오늘 실행', energy.max ? `에너지 ${left}/${energy.max} 남음` : '')),
          newButton())),
      h('div', { class: 'hm-grid' }, attnCard(view, att, now), progressCard(view), nextCard(view, now)));
    if (focusKey) {
      const again = root.querySelector(`[data-fk="${CSS.escape(focusKey)}"]`);
      if (again) again.focus({ preventScroll: true });
    }
  }

  // ---------------------------------------------------------------- 주간 요약 창 (최근 7일)
  function digest() {
    if (!H) return;
    Popups.open(() => {
      const now = Date.now();
      const view = H.viewNow();
      const ws = weekStats(view.tasks, now, ownerId);
      const day = (ms) => { const d = new Date(ms); return `${d.getMonth() + 1}월 ${d.getDate()}일`; };
      const skills = (Data.get().skills || []).filter((s) => now - Date.parse(s.created || '') <= WEEK && now - Date.parse(s.created || '') >= -DAY);
      const open = live(view.tasks).filter((t) => t.status !== 'done' && t.kind !== 'plan').slice(0, 5);
      const row = (t, tone) => h('li', { class: 'dg-row' },
        h('span', { class: `dg-dot ${tone}`, 'aria-hidden': 'true' }),
        h('b', { text: t.title, title: t.title }),
        h('span', { class: 'dg-meta', text: `${ownerName(t)} · ${Data.kindLabel(t)}` }),
        h('span', { class: 'dg-at', text: tone === 'done' ? H.ago(t.updated_at, now) : Data.statusLabel(t) }));
      const closeBtn = h('button', { type: 'button', class: 'x-btn', 'aria-label': '닫기', onclick: () => Popups.close() }, Popups.icon('x'));
      return h('div', { class: 'pop dg paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': '주간 요약' },
        closeBtn,
        h('h2', { text: '주간 요약' }),
        h('p', { class: 'dg-range', text: `최근 7일 · ${day(now - WEEK)} ~ ${day(now)}` }),
        h('div', { class: 'dg-stats' },
          stat(String(ws.done), '개', '끝낸 일', ws.workers ? `${ws.workers}명이 일했어요` : ''),
          stat(ws.passPct == null ? '–' : String(ws.passPct), ws.passPct == null ? '' : '%', '검사 통과율', ws.checked ? `검사 ${ws.checked}건 중` : '검사한 일 없음'),
          stat(String(skills.length), '개', '새로 배운 스킬', skills.length ? skills.slice(0, 2).map((s) => s.title).join(' · ') : ''),
          stat(String(ws.open), '개', '아직 열린 일', '')),
        h('h3', { text: '이번 주에 끝낸 일' }),
        ws.doneTasks.length ? h('ul', { class: 'dg-list' }, ws.doneTasks.slice(0, 8).map((t) => row(t, 'done'))) : h('p', { class: 'dg-none', text: '이번 주에 끝낸 일이 아직 없어요.' }),
        h('h3', { text: '아직 열려 있는 일' }),
        open.length ? h('ul', { class: 'dg-list' }, open.map((t) => row(t, t.status === 'blocked' ? 'bad' : t.status === 'awaiting_approval' ? 'amber' : 'work'))) : h('p', { class: 'dg-none', text: '열려 있는 일이 없어요.' }));
    });
  }

  return { init, render, digest, logic };
})();

if (typeof module !== 'undefined') module.exports = Home; // tools/dev/home_sim.js (node)
