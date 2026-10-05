/* AI 스튜디오 — 팝업 화면 (SPEC 3단계, 6장)
 *
 * 퀘스트 보드, 작업 카드, 결재함, 결재 창, 보고서, 회의실, 업무 일지, 직원 목록·상태창, 완성작, 알림 목록.
 * 팝업은 겹겹이 쌓인다 (결재함 → 결재 창). Esc나 바깥을 누르면 맨 위 한 겹만 닫힌다.
 * 글자는 모두 textContent로 넣는다 (작업 제목은 에이전트가 만든 글이라 HTML로 해석하지 않는다).
 * CSP 때문에 style 속성 대신 클래스와 CSS 변수(style.setProperty)만 쓴다.
 */
'use strict';

const Popups = (() => {
  const layer = document.getElementById('layer-popup');
  const host = document.getElementById('popup-host');
  const stack = [];
  let lastFocus = null;
  let hooks = { notify: () => {}, onOpen: () => {}, onClose: () => {} };

  // ---------------------------------------------------------------- 작은 도구
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'vars') for (const [n, val] of Object.entries(v)) el.style.setProperty(n, val);
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
    return el;
  }

  // 고정된 SVG만 넣는다 (데이터는 절대 여기로 오지 않는다).
  const ICONS = {
    chip: '<svg viewBox="0 0 24 24"><path d="M8 2.5V5.5M12 2.5V5.5M16 2.5V5.5M8 18.5V21.5M12 18.5V21.5M16 18.5V21.5M2.5 8H5.5M2.5 12H5.5M2.5 16H5.5M18.5 8H21.5M18.5 12H21.5M18.5 16H21.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><rect x="5" y="5" width="14" height="14" rx="2.5" fill="currentColor"/><rect x="9" y="9" width="6" height="6" rx="1" fill="#fff" opacity="0.85"/></svg>',
    x: '<svg viewBox="0 0 24 24"><path d="M5 5L19 19M19 5L5 19" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="M5 12.5L10 17L19 7" stroke="currentColor" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    doc: '<svg viewBox="0 0 24 24"><path d="M6 2H14L19 7V22H6Z" fill="#fff" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M9 11H16M9 15H16M9 19H13" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    shield: '<svg viewBox="0 0 24 24"><path d="M12 2L20 5V11C20 16 16.5 20 12 22C7.5 20 4 16 4 11V5Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M8 12L11 15L16 9" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>',
    folder: '<svg viewBox="0 0 24 24"><path d="M3 6H10L12 8H21V19H3Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
    link: '<svg viewBox="0 0 24 24"><path d="M10 14L14 10M8 12L6 14C4.5 15.5 4.5 18 6 19.5C7.5 21 10 21 11.5 19.5L13.5 17.5M16 12L18 10C19.5 8.5 19.5 6 18 4.5C16.5 3 14 3 12.5 4.5L10.5 6.5" stroke="currentColor" stroke-width="2.4" fill="none" stroke-linecap="round"/></svg>',
    warn: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#f5a742"/><path d="M12 6V13" stroke="#fff" stroke-width="3.2" stroke-linecap="round"/><circle cx="12" cy="17.5" r="1.8" fill="#fff"/></svg>',
    star: '<svg viewBox="0 0 24 24"><path d="M12 2.5L14.9 8.6L21.5 9.4L16.6 13.9L17.9 20.5L12 17.2L6.1 20.5L7.4 13.9L2.5 9.4L9.1 8.6Z" fill="currentColor" stroke="#7a5a1c" stroke-width="1.4" stroke-linejoin="round"/></svg>',
    archive: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="5" rx="1" fill="currentColor"/><path d="M5 9V20H19V9" fill="none" stroke="currentColor" stroke-width="2.4"/><path d="M9.5 13H14.5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>',
    play: '<svg viewBox="0 0 24 24"><path d="M7 4L20 12L7 20Z" fill="currentColor"/></svg>',
    left: '<svg viewBox="0 0 24 24"><path d="M15 4L7 12L15 20" stroke="currentColor" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    right: '<svg viewBox="0 0 24 24"><path d="M9 4L17 12L9 20" stroke="currentColor" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    bolt: '<svg viewBox="0 0 24 24"><path d="M14 1L4 14H11L9 23L20 9H13L15 1Z" fill="#f7c53c" stroke="#8a5a14" stroke-width="1.2" stroke-linejoin="round"/></svg>',
    gear: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2.4"/><path d="M12 2V5M12 19V22M2 12H5M19 12H22M4.9 4.9L7 7M17 17L19.1 19.1M4.9 19.1L7 17M17 7L19.1 4.9" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg>',
    crown: '<svg viewBox="0 0 32 24"><path d="M3 20L5 6L11 12L16 3L21 12L27 6L29 20Z" fill="#f7c53c" stroke="#8a5a14" stroke-width="1.8" stroke-linejoin="round"/></svg>',
    trophy: '<svg viewBox="0 0 48 56"><path d="M12 4H36V18C36 26 31 32 24 32C17 32 12 26 12 18Z" fill="#f2c94c" stroke="#8a5a14" stroke-width="2"/><path d="M12 8H5C5 16 8 20 13 21M36 8H43C43 16 40 20 35 21" fill="none" stroke="#8a5a14" stroke-width="3"/><rect x="20" y="32" width="8" height="10" fill="#d9a830"/><rect x="12" y="42" width="24" height="10" rx="2" fill="#8a5a32" stroke="#5a3a1e" stroke-width="2"/><path d="M18 12L22 16M26 12L22 16" stroke="#fff6" stroke-width="3" stroke-linecap="round"/></svg>',
    frame: '<svg viewBox="0 0 48 56"><rect x="4" y="4" width="40" height="48" rx="2" fill="#8a5a32" stroke="#5a3a1e" stroke-width="2"/><rect x="9" y="9" width="30" height="38" fill="#fffbf3"/><path d="M13 16H35M13 22H35M13 28H30M13 34H33" stroke="#9aa6ba" stroke-width="2.4"/></svg>',
    pad: '<svg viewBox="0 0 48 32"><rect x="3" y="5" width="42" height="22" rx="11" fill="currentColor"/><path d="M13 12V20M9 16H17" stroke="#fff" stroke-width="3" stroke-linecap="round"/><circle cx="31" cy="14" r="2.6" fill="#fff"/><circle cx="36" cy="19" r="2.6" fill="#fff"/></svg>',
    smile: '<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="21" fill="#f7c53c" stroke="#8a5a14" stroke-width="2.4"/><path d="M14 20Q17 16 20 20M28 20Q31 16 34 20" stroke="#5a3a1e" stroke-width="2.6" fill="none" stroke-linecap="round"/><path d="M14 28Q24 38 34 28" stroke="#5a3a1e" stroke-width="2.8" fill="#fff" stroke-linejoin="round"/></svg>',
    worried: '<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="21" fill="#f7c53c" stroke="#8a5a14" stroke-width="2.4"/><path d="M13 17L20 20M35 17L28 20" stroke="#5a3a1e" stroke-width="2.6" stroke-linecap="round"/><circle cx="18" cy="24" r="2.4" fill="#5a3a1e"/><circle cx="30" cy="24" r="2.4" fill="#5a3a1e"/><path d="M16 35Q24 29 32 35" stroke="#5a3a1e" stroke-width="2.8" fill="none" stroke-linecap="round"/><path d="M38 9Q41 14 38 16Q35 14 38 9Z" fill="#6cc3f0"/></svg>',
    home: '<svg viewBox="0 0 24 24"><path d="M3 11L12 3L21 11" stroke="currentColor" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M5.5 9.5V20.5H18.5V9.5" fill="#fff" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/><rect x="10" y="13.5" width="4" height="7" fill="currentColor"/></svg>',
    paw: '<svg viewBox="0 0 32 32"><circle cx="9" cy="11" r="3.4" fill="currentColor"/><circle cx="16" cy="8" r="3.4" fill="currentColor"/><circle cx="23" cy="11" r="3.4" fill="currentColor"/><path d="M8 22C8 17 12 15 16 15C20 15 24 17 24 22C24 26 20 26 16 25C12 26 8 26 8 22Z" fill="currentColor"/></svg>',
  };

  // 도트 그림 아이콘·소품 (assets/ui, tools/sprites/make_ui_assets.gd로 자른 C1·C2). 없는 것은 위의 SVG.
  const PIXEL = {
    check: 'icon-check', warn: 'icon-warn', doc: 'icon-doc', shield: 'icon-shield', folder: 'icon-folder', link: 'icon-link',
    archive: 'icon-archive', bolt: 'icon-bolt', book: 'icon-book', scroll: 'icon-scroll', team: 'icon-team',
    trophy: 'trophy', frame: 'frame',
  };

  function icon(name, cls = '') {
    const el = document.createElement('span');
    el.className = `icon i-${name} ${PIXEL[name] ? 'pixel' : ''} ${cls}`.replace(/\s+/g, ' ').trim();
    if (PIXEL[name]) {
      const img = document.createElement('img');
      img.src = `/assets/ui/${PIXEL[name]}.png`;
      img.alt = '';
      img.draggable = false;
      el.append(img);
    } else {
      el.innerHTML = ICONS[name]; // 고정 SVG만 (데이터 아님)
    }
    el.setAttribute('aria-hidden', 'true');
    return el;
  }

  // 얼굴 칸 위치(--fx)는 요소에 넣지 않는다: looks.js가 .face.<직원> 규칙(CSSOM)으로 주고, 새 직원이 들어와 그림의 열 구성이 바뀌면 그 규칙만 고친다
  function face(id, mood = 'normal', cls = '') {
    return h('span', { class: `face ${id} ${mood} ${cls}`.trim(), role: 'img', 'aria-label': Data.BY_ID[id] ? Data.BY_ID[id].name : '' });
  }

  function stars(n) {
    return h('span', { class: 'stars', 'aria-label': `난이도 ${n}` },
      [1, 2, 3].map((i) => icon('star', i <= n ? 'on' : 'off')));
  }

  function stopped() { return Data.get().stopped; }

  // 행동 버튼: 정지 중이면 잠근다 (SPEC 6.8).
  function btn(label, kind, run, { needsRun = false, cls = '', iconName = null, aria = null, disabled = false } = {}) {
    const locked = needsRun && stopped();
    return h('button', {
      type: 'button', class: `btn ${kind || ''} ${cls}`.trim(), disabled: locked || disabled,
      title: locked ? '정지 중이에요' : null, 'aria-label': aria,
      onclick: (e) => { e.stopPropagation(); run(e); },
    }, iconName ? icon(iconName) : null, label);
  }

  const pause = (ms) => new Promise((r) => setTimeout(r, Math.max(0, ms)));

  function closeBtn() {
    return h('button', { type: 'button', class: 'x-btn', 'aria-label': '닫기', onclick: () => close() }, icon('x'));
  }

  function fail(err) { hooks.notify('하나', err.message || String(err)); }

  // ---------------------------------------------------------------- 쌓기
  function open(render, opts = {}) {
    if (!stack.length) lastFocus = document.activeElement;
    stack.push({ render, st: {}, keep: Boolean(opts.keep), taskId: opts.taskId || null });
    hooks.onOpen();
    draw(true);
  }

  function draw(focus = false) {
    const current = stack[stack.length - 1];
    const scrolls = new Map();
    let focusKey = null;
    if (current && current.el && host.contains(current.el)) {
      for (const el of current.el.querySelectorAll('[data-scroll-key]')) scrolls.set(el.getAttribute('data-scroll-key'), el.scrollTop);
      if (current.el.contains(document.activeElement)) focusKey = document.activeElement.getAttribute('data-focus-key');
    }
    host.replaceChildren();
    if (!stack.length) {
      const wasOpen = !layer.hidden;
      layer.hidden = true;
      if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
      if (wasOpen) hooks.onClose();
      return;
    }
    const top = stack[stack.length - 1];
    top.el = top.render(top.st);
    top.el.tabIndex = -1;
    if (top.st.busy) top.el.classList.add('busy'); // 효과 도중 새로 그려도 (종이 뒤집기·책장) 누르지 않게
    host.append(top.el);
    if (top.taskId) top.taskKey = taskRenderKey(top.taskId);
    layer.hidden = false;
    for (const el of top.el.querySelectorAll('[data-scroll-key]')) el.scrollTop = scrolls.get(el.getAttribute('data-scroll-key')) || 0;
    // 창 자체에 초점을 둔다 (Tab을 누르면 안의 버튼으로). 글을 쓰는 창은 입력칸에.
    if (focus) (top.el.querySelector('[autofocus]') || top.el).focus();
    else if (focusKey) {
      const target = [...top.el.querySelectorAll('[data-focus-key]')].find((el) => el.getAttribute('data-focus-key') === focusKey);
      if (target) target.focus({ preventScroll: true });
    }
  }

  function close() { stack.pop(); draw(true); }
  function closeAll() { stack.length = 0; draw(); }
  function isOpen() { return stack.length > 0; }

  // 데이터가 바뀌면 맨 위 화면을 다시 그린다. 글을 쓰는 중인 창(keep)은 건드리지 않는다.
  // 효과가 도는 창(hold)은 그리지 않고 표시만 해 두었다가, 잠금을 풀 때 한 번 그린다.
  function refresh() {
    const top = stack[stack.length - 1];
    if (!top || (top.keep && !top.st.loadingAIOptions)) return;
    if (top.hold) { top.dirty = true; return; }
    if (top.taskId && top.taskKey === taskRenderKey(top.taskId)) return;
    draw();
  }

  function taskRenderKey(id) {
    return JSON.stringify([Data.task(id), Data.detail(id), Data.TEAM, Data.get().skills,
      Data.get().trophies, Data.get().stopped]);
  }

  // ---------------------------------------------------------------- 효과 잠금 (5단계)
  // 창마다 st가 하나씩 있으므로 st로 그 창을 찾는다. 효과를 기다리는 사이 CEO가 창을 닫았을 수 있다.
  const entryOf = (st) => stack.find((e) => e.st === st) || null;
  const isTop = (st) => stack.length > 0 && stack[stack.length - 1].st === st;

  function hold(st) {
    const e = entryOf(st);
    if (e) e.hold = true;
  }

  // 잠금을 푼다. 그사이 데이터가 바뀌었거나(redraw) 되돌려야 하면 다시 그린다.
  function release(st, redraw = false) {
    const e = entryOf(st);
    if (!e) return;
    const dirty = e.dirty;
    e.hold = false;
    e.dirty = false;
    if ((dirty || redraw) && isTop(st)) draw();
  }

  // 이 창이 아직 맨 위일 때만 닫는다 (먼저 닫혔으면 밑의 창을 잘못 닫지 않게).
  function closeOwn(st) { if (isTop(st)) close(); }

  // 효과를 시작해도 되는지: 이미 도는 중이면 두 번 누른 것으로 보고 무시한다.
  // 도는 동안 그 창의 버튼(닫기 빼고)은 누를 수 없다 (.pop.busy).
  function begin(st) {
    if (st.busy) return false;
    st.busy = true;
    hold(st);
    const e = entryOf(st);
    if (e && e.el) e.el.classList.add('busy');
    return true;
  }

  function end(st, redraw = false) {
    st.busy = false;
    const e = entryOf(st);
    if (e && e.el) e.el.classList.remove('busy');
    release(st, redraw);
  }

  // 도장 찍고 승인 (결재 창·보고서). 승인 요청은 도장과 같이 보내고, 누른 뒤 0.9초 이상 보여 주고 닫는다.
  // 실패하면 잉크 자국을 지우고 원래 모습으로 다시 그린다.
  async function stampApprove(st, id, tool, { paper, text, x, y, color = 'red', tilt = -10, onStamp = () => {}, done = () => {} }) {
    if (stopped() || !begin(st)) return;
    const started = performance.now();
    const sent = Data.act(id, 'approve').then(() => null, (err) => err);
    const ink = await Fx.stamp(tool, paper, { text, x, y, color, tilt });
    st.stamped = true;
    onStamp();
    const err = await sent;
    if (err) {
      ink.remove();
      st.stamped = false;
      end(st, true);
      fail(err);
      return;
    }
    await pause(900 - (performance.now() - started));
    closeOwn(st);
    end(st);
    done();
  }

  // 결재 종이 뒤집기: 바뀐 파일 보기 ↔ 돌아가기
  function flipPaper(st, value) {
    if (!begin(st)) return;
    const paper = () => host.querySelector('.ap > .ap-paper:not(.back)');
    Fx.flip(paper(), () => { st.flip = value; if (isTop(st)) draw(true); }, paper).finally(() => end(st));
  }

  // ---------------------------------------------------------------- 공용 창
  function dialog(title, body, actions) {
    open(() => h('div', { class: 'pop dialog paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
      h('h2', { text: title }),
      body ? h('p', { text: body }) : null,
      h('div', { class: 'row-btns' }, actions.map((a) => btn(a.label, a.kind, () => { close(); if (a.run) a.run(); }, a)))));
  }

  function soon(title, step) { dialog(title, `${step}단계에서 연결돼요.`, [{ label: '닫기', kind: 'primary' }]); }

  function memo(title, placeholder, sendLabel, onSend) {
    open((st) => {
      const area = h('textarea', { class: 'memo-input', maxlength: '2000', placeholder, text: st.text || '', 'aria-label': title, 'data-focus-key': 'memo-text', autofocus: true, oninput: (e) => { st.text = e.target.value; } });
      const box = h('div', { class: 'pop dialog paper memo', role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
        h('h2', { text: title }), area,
        h('div', { class: 'row-btns' },
          btn('취소', '', () => close()),
          btn(sendLabel, 'primary', () => {
            const text = area.value.trim();
            if (!text) { shake(box); area.focus(); return; }
            close();
            onSend(text);
          }, { needsRun: true })));
      return box;
    }, { keep: true });
  }

  function shake(el) {
    el.classList.remove('shake');
    void el.offsetWidth;
    el.classList.add('shake');
  }

  // ---------------------------------------------------------------- 퀘스트 보드 (02)
  const NOTE_COLOR = { build: 'yellow', plan: 'pink', research: 'purple', skill: 'green', look: 'pink', hire: 'pink' };

  function questBoard() {
    open(() => {
      const s = Data.get();
      return h('div', { class: 'pop qb', role: 'dialog', 'aria-modal': 'true', 'aria-label': '퀘스트 보드' },
        closeBtn(),
        h('button', { type: 'button', class: 'qb-goal', title: '눌러서 고치기',
          onclick: () => memo('이번 주 목표', s.goals.week, '정하기', (text) => Data.setGoal(text.slice(0, 40))) },
        h('span', { class: 'pin l' }), h('span', { class: 'pin r' }), `이번 주 목표: ${s.goals.week}`),
        h('h2', { class: 'qb-title', text: '퀘스트 보드' }),
        h('div', { class: 'qb-cols' }, Data.columns().map((col) =>
          h('section', { class: `qb-col ${col.key}`, 'aria-label': col.label },
            h('h3', { text: col.label }),
            h('div', { class: 'qb-notes' },
              col.tasks.length ? col.tasks.map((t, i) => note(t, i)) : h('p', { class: 'qb-empty', text: '비어 있어요' }))))));
    });
  }

  function note(t, i) {
    const p = Data.owner(t);
    const blocked = t.status === 'blocked';
    return h('button', { type: 'button', class: `note ${NOTE_COLOR[t.kind] || 'yellow'} ${i % 2 ? 'tilt-r' : 'tilt-l'}`,
      'aria-label': `${t.title}, ${Data.statusLabel(t)}`, onclick: () => taskCard(t.id) },
    h('span', { class: 'pin' }),
    h('span', { class: 'note-title', text: t.title }),
    Data.projectTitle(t.project) ? h('span', { class: 'note-proj', text: Data.projectTitle(t.project) }) : null,
    face(p.id, blocked ? 'worried' : 'normal', 'note-face'),
    stars(t.difficulty || 1),
    t.status === 'done' ? h('span', { class: 'gold-stamp' }, icon('crown')) : null,
    blocked ? h('span', { class: 'ribbon', text: t.needs_plan_input ? '답변 필요' : '막힘' }) : null);
  }

  function chooseProject() {
    open(() => h('div', { class: 'pop dialog paper project-picker', role: 'dialog', 'aria-modal': 'true', 'aria-label': '작업 대상 선택' },
      closeBtn(), h('h2', { text: '어느 프로젝트에서 일할까요?' }),
      h('p', { text: '선택한 프로젝트의 허용된 파일에서만 일해요. 목록에 없는 프로젝트는 아직 작업 대상으로 등록되지 않았어요.' }),
      h('div', { class: 'project-options' }, Data.get().projects.map((p) => h('button', {
        type: 'button', class: 'project-option', 'aria-pressed': String(p.key === Data.currentProject()?.key),
        onclick: () => { close(); Data.setProject(p.key); },
      }, h('b', { text: p.title }), h('span', { text: p.description || (p.kind === 'godot' ? '게임 프로젝트' : '등록된 제품 프로젝트') }),
      h('small', { text: `작업 파일: ${(p.default_allowed_paths || []).join(', ') || '프로젝트의 허용 범위'}` })))),
      btn('프로젝트 등록', 'primary', () => registerProject())));
  }

  function projectField(st, key, label, multiline = false) {
    const props = { 'aria-label': label, 'data-focus-key': key, maxlength: multiline ? 7000 : 1000,
      oninput: (e) => { st[key] = e.target.value; } };
    if (multiline) props.text = st[key] || '';
    else { props.type = 'text'; props.value = st[key] || ''; }
    return h('label', { class: 'project-field' }, h('span', { text: label }), h(multiline ? 'textarea' : 'input', props));
  }

  function registerProject() {
    open((st) => {
      const applyPreset = () => Data.projectDefaults().then((d) => {
        Object.assign(st, { key: 'ai-studio', title: 'AI Studio', repo: d.repo, main_branch: d.main_branch,
          description: 'AI Studio 감독 프로그램의 화면과 디자인 개선', paths: d.allowed_paths.join('\n') });
        if (isTop(st)) draw();
      }).catch(fail);
      const submit = async () => {
        if (st.busy) return;
        st.busy = true; st.error = ''; hold(st);
        try {
          const result = await Data.registerProject({ key: st.key, title: st.title, repo: st.repo,
            main_branch: st.main_branch, description: st.description || '',
            allowed_paths: (st.paths || '').split('\n').map(x => x.trim()).filter(Boolean), confirm_scope: Boolean(st.confirmed) });
          Data.setProject(result.project); closeOwn(st);
          hooks.notify('하나', '프로젝트를 등록했어요. 작업은 아직 실행하지 않았어요.');
        } catch (e) { st.error = e.message; }
        finally { st.busy = false; release(st, true); }
      };
      return h('div', { class: 'pop dialog paper project-form', role: 'dialog', 'aria-modal': 'true', 'aria-label': '프로젝트 등록' },
        closeBtn(), h('h2', { text: '프로젝트 등록' }),
        h('div', { class: 'project-form-body', 'data-scroll-key': 'register-body', tabindex: '0' },
          btn('AI Studio 자체 입력', '', applyPreset),
          projectField(st, 'title', '프로젝트 이름'), projectField(st, 'key', '프로젝트 ID (영문 소문자)'),
          projectField(st, 'repo', 'Git 폴더 전체 경로'), projectField(st, 'main_branch', '기준 브랜치'),
          projectField(st, 'description', '설명'), projectField(st, 'paths', '수정 허용 경로 (한 줄에 하나)', true),
          h('p', { text: '기존 로컬 Git 저장소만 등록합니다. 작업 사본은 커밋 기준으로 만들므로 아직 커밋하지 않은 변경은 포함되지 않습니다.' }),
          h('label', { class: 'project-confirm' }, h('input', { type: 'checkbox', checked: st.confirmed,
            'data-focus-key': 'register-confirm', onchange: e => { st.confirmed = e.target.checked; } }),
            '폴더·브랜치·수정 범위를 확인했습니다. 자동 검증은 아직 없으며 리뷰와 CEO 확인이 필요합니다.'),
          st.error ? h('p', { class: 'tc-blocked', role: 'alert', text: st.error }) : null),
        h('div', { class: 'row-btns' }, btn('취소', '', () => close()), btn('확인하고 등록', 'primary', submit)));
    }, { keep: true });
  }

  function retargetTask(t) {
    open((st) => {
      const targets = Data.get().projects.filter(p => p.key !== t.project);
      if (!st.project && targets.length) {
        st.project = targets[0].key;
        st.paths = (t.allowed_paths || []).join('\n');
      }
      const target = targets.find(p => p.key === st.project);
      const submit = async () => {
        if (st.busy) return;
        st.busy = true; st.error = ''; hold(st);
        try {
          const result = await Data.retarget(t.id, { project: st.project, revision: t.retarget_revision,
            allowed_paths: (st.paths || '').split('\n').map(x => x.trim()).filter(Boolean) });
          closeOwn(st); close(); taskCard(result.task);
          hooks.notify('하나', '새 대상의 카드를 만들었어요. 내용을 확인한 뒤 재시도하세요.');
        } catch (e) { st.error = e.message; }
        finally { st.busy = false; release(st, true); }
      };
      return h('div', { class: 'pop dialog paper project-form', role: 'dialog', 'aria-modal': 'true', 'aria-label': '작업 대상 변경' },
        closeBtn(), h('h2', { text: '작업 대상 변경' }),
        h('div', { class: 'project-form-body', 'data-scroll-key': 'retarget-body', tabindex: '0' },
          h('p', { text: `${t.id} · ${t.title}` }),
          h('p', { text: '이전 카드는 실행을 중단한 상태로 기록·작업 폴더를 보존합니다. 새 카드에는 목표와 수용 기준만 가져오며, 실행 기록과 검증 결과를 재사용하지 않습니다.' }),
          h('label', { class: 'project-field' }, h('span', { text: '새 작업 대상' }),
            h('select', { 'aria-label': '새 작업 대상', 'data-focus-key': 'retarget-project', onchange: e => {
              st.project = e.target.value; st.paths = (targets.find(p => p.key === st.project)?.default_allowed_paths || []).join('\n'); draw();
            } }, targets.map(p => h('option', { value: p.key, selected: p.key === st.project, text: p.title })))),
          target ? h('p', { text: `${target.repo || ''}\n기준 브랜치: ${target.main_branch || ''}\n등록 범위: ${(target.default_allowed_paths || []).join(', ')}` }) : h('p', { text: '새 대상을 먼저 등록하세요.' }),
          btn('프로젝트 등록', '', () => registerProject()),
          t.kind !== 'plan' ? projectField(st, 'paths', '새 대상에서 수정할 경로 (한 줄에 하나)', true) : null,
          !target?.has_qa ? h('p', { text: '선택한 프로젝트에는 자동 검증이 없습니다. 리뷰와 CEO 확인이 필요합니다.' }) : null,
          st.error ? h('p', { class: 'tc-blocked', role: 'alert', text: st.error }) : null),
        h('div', { class: 'row-btns' }, btn('취소', '', () => close()),
          btn('대상 변경 · 실행 대기', 'primary', submit, { disabled: !target })));
    }, { keep: true });
  }

  // ---------------------------------------------------------------- 작업 카드
  function taskCard(id) {
    open((st) => {
      const summary = Data.task(id);
      if (!summary) return missing();
      const detail = Data.detail(id);
      const t = detail && !detail.error ? { ...summary, ...detail } : summary;
      const p = Data.owner(t);
      const needsInput = t.needs_plan_input;
      const actions = [];
      if (t.retarget_revision && ['queued', 'ready', 'blocked'].includes(t.status) && ['plan', 'build', 'research'].includes(t.kind)
          && !(t.created_by || '').startsWith('supervisor:')) {
        actions.push(btn('작업 대상 변경', '', () => retargetTask(t)));
      }
      const act = (action, label) => Data.act(id, action).then(() => hooks.notify(p.name, label)).catch(fail);
      if ((t.status === 'ready' || (t.status === 'queued' && (t.created_by || '').startsWith('supervisor:')))) {
        actions.push(btn('실행', 'primary', () => act('run', `${t.title} 시작할게요!`), { needsRun: true }));
      }
      const onShelf = Data.get().trophies.some((x) => x.task === t.id);
      if (t.status === 'done' && t.kind === 'build' && !onShelf) {
        actions.push(btn('완성작에 올리기', 'lav-btn', () => Data.addTrophy(t.id)
          .then(() => { close(); hooks.notify(p.name, '완성작 선반에 올렸어요!'); }).catch(fail), { iconName: 'star' }));
      }
      if (t.status === 'blocked') {
        if (t.kind === 'plan' && t.has_proposal) actions.push(btn('설명·질문 보기', needsInput ? 'primary' : '', () => { close(); openTask(t); }));
        if (!needsInput) actions.push(btn('재시도', 'primary', () => act('retry', '다시 해 볼게요!'), { needsRun: true }));
        if (['look', 'hire'].includes(t.kind) && (t.extra || {}).draw === 'grok') {
          actions.push(btn('Codex로 다시 그리기', 'lav-btn', () => Data.act(id, 'retry', { draw: 'codex' })
            .then(() => hooks.notify(p.name, 'Codex로 다시 그려 올게요!')).catch(fail), { needsRun: true }));
        }
      }
      if (t.status === 'awaiting_approval') actions.push(btn('열기', 'primary', () => { close(); openTask(t); }));
      if (!['done', 'cancelled', 'awaiting_approval'].includes(t.status)) {
        actions.push(btn('취소', 'danger', () => dialog('작업을 취소할까요?', t.title, [
          { label: '아니요' },
          { label: '취소하기', kind: 'danger', needsRun: true, run: () => Data.act(id, 'cancel').then(close).catch(fail) },
        ]), { needsRun: true }));
      }
      return h('div', { class: 'pop tc paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': t.title },
        closeBtn(),
        h('div', { class: 'tc-head' },
          face(p.id, t.status === 'blocked' ? 'worried' : 'normal', 'tc-face'),
          h('div', { class: 'tc-heading' },
            h('h2', { text: t.title, title: t.title }),
            h('p', { class: 'tc-meta' }, h('span', { class: `chip st-${needsInput ? 'input' : t.status}`, text: Data.statusLabel(t) }),
              `${p.title} · ${p.name}`, stars(t.difficulty || 1),
              Data.projectTitle(t.project) ? h('span', { class: 'chip proj', text: Data.projectTitle(t.project) }) : null))),
        h('div', { class: 'tc-body', tabindex: '0', role: 'region', 'aria-label': '작업 내용', 'data-scroll-key': 'task-body', 'data-focus-key': 'task-body' },
        needsInput ? h('p', { class: 'tc-input-note', text: '기획 결과를 저장했어요. 설명·질문을 확인하고 답변하면 다시 기획할 수 있어요.' }) : null,
        t.blocked_reason ? h('p', { class: `tc-blocked ${needsInput ? 'tc-clarification' : ''}` }, icon('warn'), h('span', { text: t.blocked_reason })) : null,
        t.waiting ? h('p', { class: 'tc-waiting', text: t.waiting }) : null,
        t.progress && t.progress.last.stage ? h('p', { class: 'tc-waiting', text: `저장 단계: ${t.progress.last.label} · ${t.progress.last.status_label}${t.progress.last.reason ? ' · ' + t.progress.last.reason : ''}` }) : null,
        executionInfo(t.execution, st),
        t.progress && t.progress.steps.length ? h('ul', {}, ...t.progress.steps.map(step => h('li', { text: `${step.label}: ${step.status_label}${step.reason ? ' (' + step.reason + ')' : ''}` }))) : null,
        t.progress && t.progress.last.next_action ? h('p', { class: 'tc-blocked', text: t.progress.last.next_action }) : null,
        t.evidence ? h('div', {}, h('h3', { text: '수용 기준별 근거' }), ...(t.evidence.items || []).map(r => h('p', { text: `${r.id}: ${r.text} — ${r.status === 'verified' ? '근거 확인' : '근거 누락 또는 미확인'}` }))) : null,
        usageLine(t.usage),
        skillUseRow(t),
        assignRow(t),
        h('h3', { text: '목표' }), h('p', { class: 'tc-brief', text: t.brief || '—' }),
        t.acceptance && t.acceptance.length ? [h('h3', { text: '수용 기준' }),
          h('ul', { class: 'tc-acc' }, t.acceptance.map((a, i) => h('li', {}, icon(t.evidence?.items?.[i]?.status === 'verified' ? 'check' : 'doc'), a)))] : null,
        ),
        actions.length ? h('div', { class: 'row-btns tc-actions' }, actions) : null);
    }, { taskId: id });
  }

  function executionInfo(e, st) {
    if (!e || !(e.requested_provider || e.actual_runtime || e.runtime_version)) return null;
    const providers = { codex: 'Codex', grok: 'Grok', grok_text: 'Grok', claude: 'Claude', fake: '가짜 실행기' };
    const provider = providers[e.requested_provider] || e.requested_provider || '기록 없음';
    const program = e.actual_runtime === 'fake' ? '가짜 실행기 (시험용)' :
      e.runtime_version || providers[e.actual_runtime] || e.actual_runtime || '실행 프로그램 기록 없음';
    const fake = e.actual_runtime === 'fake' || e.model_identity_reason === 'fake_runtime';
    const failed = e.ok === false || e.model_identity_reason === 'execution_failed_without_model_id';
    const identity = fake ? '실제 모델 호출 없음' : e.provider_model ||
      (failed ? '실행 오류 · 모델 ID 기록 없음' : '로그에 모델 ID가 제공되지 않음');
    const explanation = fake ? '가짜 실행기로 확인한 결과입니다.' : e.provider_model ?
      (e.provider_model_source ? '응답 메타데이터에서 확인한 모델입니다.' : '기록에 모델 이름이 있지만 확인 경로는 기록되지 않았습니다.') :
      failed ? '실행 오류를 먼저 확인해 주세요. 선택한 모델 이름으로 응답 모델을 추정하지 않습니다.' :
      '선택한 모델로 실행을 요청했습니다. 응답 로그에 모델 ID가 없으며, 이 표시 자체는 연결 오류를 뜻하지 않습니다.';
    const row = (label, value) => [h('dt', { text: label }), h('dd', { text: value })];
    return h('section', { class: 'tc-execution', 'aria-label': 'AI 실행 정보' },
      h('dl', {}, row('선택한 AI', `${provider} · ${e.requested_model || '계정 기본 모델'}`),
        row('실행 프로그램', program), row('응답 모델', identity)),
      h('p', { class: 'tc-model-note', text: explanation }),
      e.provider_model_source ? h('details', { open: Boolean(st.modelProofOpen) }, h('summary', {
        text: '모델 확인 근거', 'data-focus-key': 'model-proof', onclick: event => {
          event.preventDefault(); st.modelProofOpen = !st.modelProofOpen; draw();
        } }),
        h('p', { text: `응답 필드: ${e.provider_model_source}` })) : null,
      e.fallback ? h('p', { class: 'tc-model-note', text: `대체 실행${e.fallback_reason ? ': ' + e.fallback_reason : ''}` }) : null);
  }

  // 작업별 사용량 (실행 기록으로 센 실제 숫자): 실행 횟수 · 걸린 분 · 토큰(입력+출력)
  function tokenText(n) {
    return n >= 10000 ? `${(n / 10000).toFixed(1).replace(/\.0$/, '')}만` : n.toLocaleString('ko-KR');
  }
  function usageLine(u) {
    if (!u || !u.runs) return null;
    return h('p', { class: 'tc-usage', text: `사용량: 실행 ${u.runs}번 · ${u.minutes}분${u.tokens == null ? ' · 토큰 확인 불가' : ` · 토큰 ${tokenText(u.tokens)}`}` });
  }

  // 이 일에 붙은 배운 스킬과 직원이 따랐다고 알린 것 (실행 기록으로 센 것, server.task_usage)
  const SKILL_STATE = { yes: '따랐어요', no: '안 따랐대요', unknown: '알리지 않았어요' };
  function skillUse(t) {
    const u = t.usage || {};
    const all = Data.get().skills;
    return (u.skills || []).map((slug) => {
      const sk = all.find((s) => s.slug === slug);
      const state = (u.applied || []).includes(slug) ? 'yes' : u.told ? 'no' : 'unknown';
      return { slug, title: sk ? sk.title : slug, state, exists: Boolean(sk) };
    });
  }

  // 결재 창 한 줄: "배운 스킬 3개 · 모두 따랐어요" (이름이 길어도 칸을 넘지 않게. 자세한 것은 skillUsePop)
  function skillSummary(list) {
    const yes = list.filter((s) => s.state === 'yes').length;
    const said = yes === list.length ? '모두 따랐어요' : yes ? `${yes}개 따랐어요` : list.some((s) => s.state === 'no') ? '안 따랐대요' : '알리지 않았어요';
    return `배운 스킬 ${list.length}개 · ${said}`;
  }

  function skillUsePop(t) {
    open(() => h('div', { class: 'pop dialog paper list-pop', role: 'dialog', 'aria-modal': 'true', 'aria-label': '이 일에 붙은 배운 스킬' },
      closeBtn(), h('h2', { text: '이 일에 붙은 배운 스킬' }),
      h('ul', {}, skillUse(t).map((s) => h('li', {}, icon('star'),
        h('button', { type: 'button', class: `tc-skill ${s.state}`, disabled: !s.exists, onclick: () => skillDetail(s.slug) },
          h('b', { text: s.title }), h('small', { text: ` · ${SKILL_STATE[s.state]}` })))))));
  }

  function skillUseRow(t) {
    const list = skillUse(t);
    if (!list.length) return null;
    return h('div', { class: 'tc-skills' }, icon('star'), h('span', { class: 'tc-skills-label', text: '배운 스킬' }),
      list.map((s) => h('button', { type: 'button', class: `tc-skill ${s.state}`, disabled: !s.exists, title: s.exists ? '스킬 보기' : '지운 스킬',
        onclick: () => skillDetail(s.slug) }, h('b', { text: s.title }), h('small', { text: ` · ${SKILL_STATE[s.state]}` }))));
  }

  // 담당 바꾸기: 시작 전이거나 막힌 기획·개발·리서치 작업, 같은 일을 하는 직원이 둘 이상일 때
  function assignRow(t) {
    if (!['queued', 'ready', 'blocked'].includes(t.status) || !['plan', 'build', 'research'].includes(t.kind)) return null;
    const owner = Data.owner(t);
    const mates = Data.TEAM.filter((m) => m.job === owner.job);
    if (mates.length < 2) return null;
    return h('div', { class: 'tc-assign' }, h('span', { text: '담당' }),
      whoPick(mates, t.role, (role) => Data.assign(t.id, role)
        .then(() => { const m = Data.BY_ROLE[role]; hooks.notify(m ? m.name : '하나', '제가 맡을게요!'); }).catch(fail)));
  }

  function whoPick(people, selected, onPick) {
    return h('div', { class: 'sk-who', role: 'radiogroup', 'aria-label': '직원' }, people.map((m) => h('button', {
      type: 'button', class: 'sk-who-btn', role: 'radio', 'aria-label': m.name, 'aria-checked': String(m.role === selected),
      onclick: () => { if (m.role !== selected) onPick(m.role); } }, face(m.id, 'normal', 'sk-who-face'), h('span', { text: m.name }))));
  }

  // 결재 대기 작업을 종류에 맞는 창으로 연다.
  function openTask(t) {
    if (t.kind === 'plan') meeting(t.id);
    else if (t.kind === 'research') report(t.id);
    else if (t.kind === 'skill') skillReview(t.id);
    else if (t.kind === 'look') lookReview(t.id);
    else if (t.kind === 'hire') hireReview(t.id);
    else if (t.kind === 'tool') toolReview(t.id);
    else approval(t.id);
  }

  // ---------------------------------------------------------------- 결재함 (08)
  const WAX = { plan: 'gold', build: 'red', research: 'purple', skill: 'gold', look: 'purple', hire: 'gold', tool: 'gold' };

  function tagOf(t) {
    if (t.kind === 'plan') return ['기획 회의', 'amber'];
    if (t.kind === 'research') return ['보고서', 'lavender'];
    if (t.kind === 'skill') return [t.origin ? '스스로 배움' : t.target ? '스킬 고치기' : '스킬 공부', 'teal'];
    if (t.kind === 'look') return ['새 옷', 'lavender'];
    if (t.kind === 'hire') return ['새 직원', 'amber'];
    if (t.kind === 'tool') return ['MCP 만들기', 'teal'];
    return t.qa && t.qa.verdict === 'pass' ? ['품질 합격', 'teal'] : ['검사 없음', 'gray'];
  }

  function inbox() {
    open((st) => {
      const list = Data.inbox(Boolean(st.archived));
      const later = Data.inbox(true).length;
      return h('div', { class: 'pop ib', role: 'dialog', 'aria-modal': 'true', 'aria-label': '결재함' },
        closeBtn(),
        h('h2', { class: 'ib-sign', text: st.archived ? `나중에 보기 ${list.length}` : `결재함 ${list.length}` }),
        h('div', { class: 'ib-tray' },
          list.length ? list.slice(0, 4).map((t, i) => letter(t, i === 0 && !st.archived))
            : h('p', { class: 'ib-empty', text: st.archived ? '미뤄 둔 편지가 없어요' : '결재할 게 없어요. 다들 잘하고 있어요!' }),
          list.length > 4 ? h('p', { class: 'ib-more', text: `그 밖에 ${list.length - 4}통` }) : null),
        later || st.archived ? h('button', { type: 'button', class: 'ib-later',
          onclick: () => { st.archived = !st.archived; draw(); } }, icon('archive'), st.archived ? '결재함으로' : `나중에 보기 ${later}`) : null);
    });
  }

  function letter(t, glow) {
    const p = Data.owner(t);
    const [tag, tone] = tagOf(t);
    return h('div', { class: `letter ${glow ? 'glow' : ''}` },
      h('span', { class: `wax ${WAX[t.kind]}` }),
      h('span', { class: 'letter-face' }, face(p.id), h('span', { text: p.name })),
      h('div', { class: 'letter-body' }, h('span', { class: 'letter-title', text: t.title, title: t.title }),
        h('span', { class: 'letter-tags' }, h('span', { class: `tag ${tone}`, text: tag }),
          Data.projectTitle(t.project) ? h('span', { class: 'letter-proj', text: Data.projectTitle(t.project) }) : null)),
      btn('열기', 'wood', () => openTask(t)));
  }

  // ---------------------------------------------------------------- 결재 창 (03)
  function approval(id) {
    open((st) => {
      const t = Data.task(id);
      if (!t) return missing();
      const p = Data.owner(t);
      const done = t.status !== 'awaiting_approval';
      const approvalBlocked = t.approval?.allowed === false;
      const passed = t.qa && t.qa.verdict === 'pass' && t.qa.total;
      const qa = passed ? `품질 검사 ${t.qa.passed}/${t.qa.total} 합격` : '자동 검사 없음 · 직접 확인';
      // 리뷰: 다른 회사 모델(클로 = Claude)이 봤으면 교차 검증, Codex가 대신 봤으면 대리 검토 (SPEC 6.5)
      const rv = t.review || {};
      const reviewer = Data.BY_ROLE.reviewer || { id: 'clo', name: '클로' };
      const cross = rv.cross_model === true;
      const reviewText = rv.actual_runtime === 'fake' ? '리뷰: 가짜 실행기 검증' : cross ? `리뷰: ${reviewer.name} 승인` : rv.runtime ? '리뷰: 대리 검토 (교차 검증 아님)' : '리뷰 없음 · 직접 확인';
      const files = t.files ?? '?';
      const sheet = h('div', { class: `pop ap ${st.flip ? 'flipped' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': `결재 · ${t.title}` },
        h('span', { class: 'ap-peek' }, face(p.id, st.stamped ? 'happy' : 'worried')),
        h('div', { class: 'ap-paper' }, // 클립보드 그림 (집게까지 그림에 있다)
          closeBtn(),
          h('h2', { text: `결재 · ${t.title}`, title: t.title }),
          st.flip ? diffView(t, st) : [
            h('div', { class: 'ap-row' }, passed ? h('span', { class: 'ok-badge' }, icon('check')) : icon('warn', 'big'), h('span', { text: qa })),
            h('div', { class: 'ap-row' }, cross ? face(reviewer.id, 'normal', 'row-face') : icon('shield', 'big'), h('span', { text: reviewText })),
            skillUse(t).length ? h('button', { type: 'button', class: 'ap-row link ap-skills', onclick: () => skillUsePop(t),
              title: skillUse(t).map((s) => `${s.title} (${SKILL_STATE[s.state]})`).join('\n') },
            icon('star', 'big'), h('span', { text: skillSummary(skillUse(t)) }), h('span', { class: 'more', text: '보기' })) : null,
            h('button', { type: 'button', class: 'ap-row link', onclick: () => flipPaper(st, true) },
              icon('doc', 'big'), h('span', { text: `바뀐 파일 ${files}개` }), h('span', { class: 'more', text: '보기' })),
            btn('진행 단계·완료 근거', 'paper-btn', () => taskCard(id)),
            h('div', { class: 'ap-actions' },
              approvalBlocked && !done ? h('p', { class: 'ap-proof-note', role: 'status', text: '승인 불가: ' + t.approval.reasons.join(' / ') }) : null,
              h('button', { type: 'button', class: `stamp-btn ${st.stamped ? 'stamped' : ''}`, disabled: stopped() || done || st.stamped || approvalBlocked,
                title: stopped() ? '정지 중에는 승인할 수 없어요' : approvalBlocked ? t.approval.reasons.join('\n') : null,
                onclick: (e) => {
                  const tool = e.currentTarget;
                  const peek = tool.closest('.ap').querySelector('.ap-peek .face');
                  stampApprove(st, id, tool, {
                    paper: tool.closest('.ap-paper'), text: '승인', x: 350, y: 420,
                    onStamp: () => {
                      tool.classList.add('stamped');
                      tool.disabled = true;
                      tool.firstChild.textContent = '승인!';
                      peek.classList.replace('worried', 'happy');
                    },
                    done: () => hooks.notify(p.name, '승인됐어요! 고마워요'),
                  });
                } }, h('span', { text: st.stamped ? '승인!' : '승인' })),
              btn('수정 요청', 'paper-btn', () => memo('수정 요청', `${p.name}에게 무엇을 고쳐 달라고 할까요?`, '보내기',
                (note) => Data.act(id, 'request-changes', { note }).then(() => { close(); hooks.notify(p.name, '고쳐서 다시 올릴게요!'); }).catch(fail)),
              { needsRun: true }))]));
      return sheet;
    });
  }

  function diffView(t, st) {
    const d = Data.diff(t.id);
    const back = btn('돌아가기', 'paper-btn', () => flipPaper(st, false), { iconName: 'left' });
    if (!d) return h('div', { class: 'ap-diff' }, h('p', { class: 'loading', text: '변경 내용을 불러오는 중…' }), back);
    if (d.error) return h('div', { class: 'ap-diff' }, h('p', { class: 'loading', text: d.error }), back);
    const lines = (d.diff || '변경 내용이 없어요').split('\n').slice(0, 3000);
    return h('div', { class: 'ap-diff' },
      h('ul', { class: 'ap-files' }, (d.stats || []).map((f) => h('li', {}, h('span', { class: 'path', text: f.path }),
        h('span', { class: 'plus', text: `+${f.added ?? '?'}` }), h('span', { class: 'minus', text: `−${f.deleted ?? '?'}` })))),
      h('pre', { class: 'diff', tabindex: '0' }, lines.map((line) =>
        h('span', { class: line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : line.startsWith('@@') ? 'hunk' : '', text: `${line}\n` }))),
      d.truncated ? h('p', { class: 'loading', text: '길어서 앞부분만 보여요' }) : null,
      back);
  }

  function missing() {
    return h('div', { class: 'pop dialog paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': '없음' },
      h('h2', { text: '작업을 찾을 수 없어요' }), h('p', { text: '이미 정리됐을 수 있어요.' }),
      h('div', { class: 'row-btns' }, btn('닫기', 'primary', () => close())));
  }

  function loadingPop(label) {
    return h('div', { class: 'pop dialog paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': label },
      closeBtn(), h('h2', { text: label }), h('p', { text: '불러오는 중…' }));
  }

  // 불러오기 실패 (연결이 끊겼을 때 등): 이유와 '다시 불러오기'. 다시 연결되면 저절로도 다시 불러온다 (data.js)
  function failPop(label, message) {
    return h('div', { class: 'pop dialog paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': label },
      closeBtn(), h('h2', { text: label }), h('p', { text: `불러오지 못했어요.\n${message}` }),
      h('div', { class: 'row-btns' }, btn('닫기', '', () => close()), btn('다시 불러오기', 'primary', () => Data.retry())));
  }

  // ---------------------------------------------------------------- 보고서 (06)
  const CLAIM_ICONS = ['doc', 'shield', 'folder'];

  function report(id) {
    open((st) => {
      const t = Data.task(id);
      if (!t) return missing();
      const p = Data.owner(t);
      const providerDetail = Data.detail(id);
      const loaded = Data.report(id);
      if (!loaded) return loadingPop('보고서');
      if (loaded.error) return failPop('보고서', loaded.error);
      const empty = { title: t.title, conclusion: '', claims: [], sources: [], unverified: [], body: '' };
      const r = { ...empty, ...loaded, title: loaded.title || t.title };
      const pending = t.status === 'awaiting_approval';
      return h('div', { class: 'pop rp', role: 'dialog', 'aria-modal': 'true', 'aria-label': r.title },
        h('span', { class: 'rp-clip' }),
        h('div', { class: 'rp-paper' },
          closeBtn(),
          h('div', { class: 'rp-head' }, h('span', { class: 'rp-photo' }, face(p.id)), h('span', { text: `리서치 보고서 · ${p.name}` }),
            h('button', { type: 'button', class: 'rp-full', onclick: () => reader(r) }, '전체 보기')),
          h('h2', { class: 'rp-title', text: r.title }),
          // 결론·핵심 주장은 길 수 있다 (진짜 보고서는 주장 하나가 두세 줄): 이 칸만 스크롤, 출처·단추는 늘 아래에 보인다
          h('div', { class: 'rp-body', tabindex: '0', 'aria-label': '결론과 핵심 주장' },
            r.conclusion ? h('p', { class: 'rp-conclusion', text: `한 줄 결론: ${r.conclusion}` }) : null,
            r.claims.length ? h('ol', { class: 'rp-claims' }, r.claims.slice(0, 8).map((c, i) => h('li', {}, icon(CLAIM_ICONS[i] || 'doc'),
              h('span', { class: 'rp-claim-text', text: `${i + 1}. ${c}` })))) : null),
          h('div', { class: 'rp-chips' },
            h('button', { type: 'button', class: 'rp-chip teal', onclick: () => sources(r) }, icon('link'), `출처 ${r.sources.length}개`,
              h('span', { class: 'links' }, r.sources.slice(0, 3).map(() => icon('link')))),
            h('button', { type: 'button', class: 'rp-chip amber', onclick: () => unverified(r) }, icon('warn'), `확인 필요 ${r.unverified.length}`)),
          pending ? h('div', { class: 'rp-actions' },
            btn('확인 완료', 'primary', (e) => {
              const tool = e.currentTarget;
              stampApprove(st, id, tool, {
                paper: tool.closest('.rp-paper'), text: '확인', x: 470, y: 330, color: 'lavender', tilt: 0,
                onStamp: () => { tool.disabled = true; },
                done: () => hooks.notify(p.name, '보고서를 완성작에 올렸어요!'),
              });
            }, { needsRun: true }),
            btn('질문하기', 'paper-btn', () => memo('질문하기', `${p.name}에게 무엇을 물어볼까요?`, '보내기',
              (note) => Data.act(id, 'request-changes', { note }).then(() => { close(); hooks.notify(p.name, '찾아보고 다시 올릴게요!'); }).catch(fail)),
            { needsRun: true }),
            btn('', 'paper-btn square', () => Data.act(id, 'archive').then(() => { close(); hooks.notify(p.name, '나중에 보기로 옮겼어요'); }).catch(fail),
              { iconName: 'archive', aria: t.archived ? '결재함으로 되돌리기' : '나중에 보기로 보관' })) : null));
    });
  }

  function sources(r) {
    open(() => h('div', { class: 'pop dialog paper list-pop', role: 'dialog', 'aria-modal': 'true', 'aria-label': '출처' },
      closeBtn(), h('h2', { text: `출처 ${r.sources.length}개` }),
      h('ul', {}, r.sources.map((s) => h('li', {}, icon('link'),
        /^https?:\/\//.test(s.url) ? h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer', text: s.title || s.url }) : h('span', { text: s.title || s.url }))))));
  }

  function unverified(r) {
    open(() => h('div', { class: 'pop dialog paper list-pop', role: 'dialog', 'aria-modal': 'true', 'aria-label': '확인 필요' },
      closeBtn(), h('h2', { text: `확인 필요 ${r.unverified.length}` }),
      r.unverified.length ? h('ul', {}, r.unverified.map((u) => h('li', {}, icon('warn'), u))) : h('p', { text: '없어요' })));
  }

  function reader(r) {
    open(() => h('div', { class: 'pop reader paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': r.title },
      closeBtn(), h('h2', { text: r.title }), h('pre', { class: 'reader-body', tabindex: '0', text: r.body || '본문이 없어요' })));
  }

  // ---------------------------------------------------------------- 회의실 (05)
  function meetingRoom() {
    const plan = Data.get().tasks.find((t) => t.kind === 'plan' && t.status === 'awaiting_approval');
    if (plan) meeting(plan.id);
    else dialog('회의실', '지금은 회의가 없어요.', [{ label: '닫기', kind: 'primary' }]);
  }

  // 퀘스트로 붙이기: 고른 카드는 본사 퀘스트 보드 쪽으로 날아가고, 안 고른 카드는 흐려진다.
  // 승인과 날아가기가 둘 다 끝나면 닫는다 (닫히면 본사 벽에 새 쪽지가 떨어진다, app.js).
  const BOARD = [902, 200]; // 본사 퀘스트 보드 가운데 (캔버스 좌표)

  function attachQuests(st, id, picked, producer) {
    if (stopped() || !begin(st)) return;
    const cards = [...host.querySelectorAll('.mt-card')];
    const chosen = cards.filter((c) => c.classList.contains('on'));
    const rest = cards.filter((c) => !c.classList.contains('on'));
    const sent = Data.act(id, 'approve').then(() => null, (err) => err);
    const fly = Fx.flyCards(document.getElementById('stage'), chosen, rest, BOARD[0], BOARD[1]);
    Promise.all([sent, fly]).then(([err]) => {
      if (err) {
        end(st, true);
        fail(err);
        return;
      }
      closeOwn(st);
      end(st);
      hooks.notify(producer.name, `퀘스트 ${picked}개 붙였어요!`);
    });
  }

  function replyToPlan(id) {
    const t = Data.task(id);
    const d = Data.detail(id);
    const questions = (d?.proposal?.questions || []).join('\n');
    memo('기획 질문에 답변', `현재 대상: ${Data.projectTitle(t.project) || t.project}\n${questions}\n답변을 보내면 이 프로젝트에서 다시 기획해요.`, '답변하고 다시 기획',
      (note) => Data.act(id, 'request-changes', { note }).then(() => { close(); hooks.notify(Data.owner(t).name, '답변을 반영해서 다시 기획할게요.'); }).catch(fail));
  }

  function meeting(id) {
    open((st) => {
      const t = Data.task(id);
      if (!t) return missing();
      const d = Data.detail(id);
      if (!d) return loadingPop('회의실');
      if (d.error) return failPop('회의실', d.error);
      const cards = Data.planCards(id) || [];
      if (d.proposal?.workbench_plan) {
        return h('div', { class: 'pop mt', role: 'dialog', 'aria-modal': 'true', 'aria-label': '목표 기획 결재' },
          h('header', {}, h('h2', { text: d.proposal.simulation ? 'MOCK / 모의 목표 기획' : 'AI 목표 기획 · CEO 결재' })),
          h('div', { class: 'mt-content' }, h('pre', { text: JSON.stringify(d.proposal.review, null, 2) }),
            h('p', { text: '검증된 기술 버전·연결·검증 조건을 확인하세요. 외부 실행은 별도 요청별 승인과 비용 미상 동의가 필요합니다.' })),
          h('footer', {}, btn('작업대에서 검토', 'primary', () => { close(); document.dispatchEvent(new CustomEvent('studio:planner-review', { detail: d.proposal.workbench_plan })); })), closeBtn());
      }
      const questions = (d.proposal && d.proposal.questions) || [];
      const picked = cards.filter((c) => c.checked).length;
      const pending = t.status === 'awaiting_approval';
      const waiting = t.status === 'blocked';
      const needsInput = t.needs_plan_input;
      // 기획안에 작업이 없으면 붙일 것이 없다: 다시 기획만 할 수 있다
      const say = waiting ? '현재 작업 대상과 질문을 확인해 주세요. 답변을 보내면 기획을 다시 실행해요.' : !pending ? '이 기획안은 이미 정리됐어요.'
        : cards.length ? `${cards.length}단계로 나눴어요. 골라 주세요!` : '나눌 작업이 없어요. 다시 기획해 주세요';
      const producer = Data.BY_ROLE.producer || Data.TEAM[0];
      const directive = String(t.brief || t.title);
      return h('div', { class: 'pop mt', role: 'dialog', 'aria-modal': 'true', 'aria-label': '회의실' },
        h('img', { class: 'mt-bg', src: '/assets/bg/meeting.png', alt: '', draggable: 'false' }),
        sprite('producer', 'call', 'mt-hana', 200),
        h('section', { class: 'mt-panel' },
          h('header', { class: 'mt-header' }, h('div', {}, h('p', { class: 'panel-kicker', text: '회의실 · 기획안 검토' }),
            h('h2', { text: t.title })), h('span', { class: 'panel-status', text: pending ? '결재 대기' : Data.statusLabel(t) })),
          h('div', { class: 'mt-context', tabindex: '0', 'data-scroll-key': 'meeting-context', 'data-focus-key': 'meeting-context' },
            h('h3', { text: `작업 대상: ${Data.projectTitle(t.project) || t.project}` }), h('p', { text: directive }),
            d.proposal && d.proposal.summary ? h('p', { class: 'mt-summary', text: `기획 요약: ${d.proposal.summary}` }) : null),
          h('div', { class: `mt-content ${needsInput ? 'mt-input-content' : ''}` },
            h('section', { class: 'mt-candidates', hidden: needsInput }, h('h3', { text: `작업 후보 ${cards.length}개` }),
              h('div', { class: 'mt-cards', tabindex: '0', role: 'region', 'aria-label': '작업 후보 목록', 'data-scroll-key': 'meeting-cards', 'data-focus-key': 'meeting-cards' },
                cards.length ? cards.map((c, i) => card(t, c, i, pending)) : h('p', { class: 'panel-empty', text: '작업 후보가 없어요. 다시 기획할 수 있어요.' }))),
            h('section', { class: 'mt-notes', tabindex: '0', 'data-scroll-key': 'meeting-notes', 'data-focus-key': 'meeting-notes', 'aria-label': '확인할 질문과 주의할 점' },
              h('h3', { text: `확인할 질문 ${questions.length}개` }),
              questions.length ? h('ol', {}, questions.map((q) => h('li', { text: q }))) : h('p', { text: '기획안에 질문이 없어요.' }),
              d.proposal && d.proposal.risks && d.proposal.risks.length ? [h('h3', { text: '주의할 점' }), h('ul', {}, d.proposal.risks.map((r) => h('li', { text: r })))] : null)),
          h('footer', { class: 'mt-footer' },
            h('div', {}, h('b', { class: 'mt-picked', 'aria-live': 'polite', text: needsInput ? '답변 기다림' : `선택 ${picked} / ${cards.length}` }), h('p', { text: say })),
            pending ? h('div', { class: 'mt-actions' },
              btn('다시 기획', '', () => memo('다시 기획', '어떻게 바꿔 볼까요?', '보내기',
                (note) => Data.act(id, 'request-changes', { note }).then(() => { close(); hooks.notify(producer.name, '다시 나눠 볼게요!'); }).catch(fail)), { needsRun: true }),
              cards.length ? btn('퀘스트로 붙이기', 'primary', () => {
                if (!picked) { hooks.notify(producer.name, '카드를 하나 이상 골라 주세요'); return; }
                attachQuests(st, id, picked, producer);
              }, { needsRun: true }) : null) : needsInput ? h('div', { class: 'mt-actions' }, btn('답변하고 다시 기획', 'primary', () => replyToPlan(id), { needsRun: true })) : h('p', { class: 'panel-status', text: waiting ? '확인이 필요한 기획안 · 승인할 작업 없음' : '정리된 기획안 · 선택 변경 불가' }))),
        closeBtn());
    });
  }

  // 회의실 직원: 꾸미기가 적용된 정지 그림 (역할로 찾는다)
  function sprite(role, action, cls, height) {
    const p = Data.BY_ROLE[role];
    const c = Scene.still(p ? p.id : 'sol', action, p ? p.look : null, height);
    c.classList.add('mt-sprite', cls);
    return c;
  }

  function card(t, c, i, pending) {
    const p = Data.BY_ROLE[c.role] || Data.BY_ROLE.builder;
    return h('div', { class: `mt-card ${c.checked ? 'on' : ''}` },
      h('button', { type: 'button', class: 'mt-card-open', 'data-focus-key': `meeting-card-${i}`, 'aria-label': `${c.title} 자세히`, onclick: () => cardDetail(t.id, i) },
        h('span', { class: 'mt-card-number', text: `후보 ${i + 1} · ${p.title}` }),
        h('span', { class: 'mt-card-title', text: c.title }), h('span', { class: 'mt-card-brief', text: c.brief || '목표를 자세히 확인해 주세요.' }),
        h('span', { class: 'mt-card-owner' }, face(p.id, 'normal', 'mt-card-face'), p.name, stars(c.difficulty || 1))),
      h('button', { type: 'button', class: 'mt-check', role: 'checkbox', 'aria-checked': String(Boolean(c.checked)),
        'data-focus-key': `meeting-check-${i}`, 'aria-label': `${c.title} 고르기`, disabled: !pending, onclick: () => Data.editCard(t.id, i, { checked: !c.checked }) },
      c.checked ? icon('check') : null));
  }

  function cardDetail(id, i) {
    open(() => {
      const c = (Data.planCards(id) || [])[i];
      if (!c) return missing();
      const p = Data.BY_ROLE[c.role] || Data.BY_ROLE.builder;
      const input = h('input', { class: 'title-input', type: 'text', maxlength: '60', value: c.title, 'aria-label': '카드 제목' });
      return h('div', { class: 'pop tc paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': c.title },
        closeBtn(),
        h('div', { class: 'tc-head' }, face(p.id, 'normal', 'tc-face'),
          h('div', {}, input, h('p', { class: 'tc-meta' }, `${p.title} · ${p.name}`, stars(c.difficulty || 1)))),
        h('div', { class: 'tc-body', tabindex: '0', 'data-scroll-key': 'candidate-body', 'data-focus-key': 'candidate-body' },
        h('h3', { text: '목표' }), h('p', { class: 'tc-brief', text: c.brief || '—' }),
        c.acceptance && c.acceptance.length ? [h('h3', { text: '수용 기준' }), h('ul', { class: 'tc-acc' }, c.acceptance.map((a) => h('li', {}, icon('doc'), a)))] : null,
        ),
        h('div', { class: 'row-btns tc-actions' },
          btn('닫기', '', () => close()),
          btn('제목 고치기', 'primary', () => {
            const title = input.value.trim();
            if (title) Data.editCard(id, i, { title: title.slice(0, 60) });
            close();
          }, { needsRun: true })));
    }, { keep: true });
  }

  // ---------------------------------------------------------------- 업무 일지 (07)
  const ROLE_LINE = { hana: 'lav', sol: 'blue', clo: 'coral', luna: 'amber' };

  // 날짜 넘기기: 그날 일지를 먼저 불러 두고 책장을 넘긴다 (넘기는 동안 빈 쪽이 보이지 않게).
  function turnTo(st, n) {
    if (n < 1 || n > Data.get().day || n === st.day || !begin(st)) return;
    const forward = n > st.day;
    const swap = () => { st.day = n; if (isTop(st)) draw(true); };
    Data.loadDiary(n)
      .then(() => (isTop(st)
        ? Fx.pageTurn(() => host.querySelector('.dy-book'), '.dy-page.left', '.dy-page.right', forward, swap)
        : swap()))
      .finally(() => end(st));
  }

  function diary(day) {
    open((st) => {
      const s = Data.get();
      if (st.day == null) st.day = day || s.day;
      const loaded = Data.diary(st.day);
      const d = loaded && !loaded.error ? loaded : { events: [], summary: null };
      const sum = d.summary;
      // 탭은 최근 7일 (1일차부터 오늘까지 중), 나머지는 넘김 화살표로
      const first = Math.max(1, Math.min(st.day, s.day) - 6);
      const tabs = Array.from({ length: Math.min(7, s.day - first + 1) }, (_, i) => first + i);
      const exists = (n) => n >= 1 && n <= s.day;
      const go = (n) => turnTo(st, n);
      return h('div', { class: 'pop dy', role: 'dialog', 'aria-modal': 'true', 'aria-label': `${st.day}일차 업무 일지` },
        closeBtn(),
        h('div', { class: 'dy-book' },
          h('section', { class: 'dy-page left' },
            h('h2', {}, icon('paw'), `${st.day}일차 업무 일지`),
            h('p', { class: 'dy-count', text: loaded && !loaded.error ? `기록 ${d.events.length}개 · 시간순` : '기록 확인 중' }),
            d.events.length ? h('ol', { class: 'dy-timeline', tabindex: '0', 'aria-label': '업무 기록', 'data-scroll-key': 'diary-events', 'data-focus-key': 'diary-events' }, d.events.map((e) => h('li', {},
              h('span', { class: 'time', text: e.time }), face(e.who, 'normal', 'dy-face'),
              h('span', { class: `line ${ROLE_LINE[e.who] || 'lav'}` }, h('b', { text: e.name }), h('span', { text: e.text })))))
              : h('p', { class: 'dy-empty', text: loaded ? (loaded.error || '기록이 없어요') : '불러오는 중…' }),
            h('button', { type: 'button', class: 'dy-arrow prev', 'aria-label': '전날', disabled: !exists(st.day - 1), onclick: () => go(st.day - 1) }, icon('left'))),
          h('section', { class: 'dy-page right' },
            h('h2', { text: st.day === s.day ? '오늘의 요약' : '그날의 요약' }),
            sum ? [
              h('div', { class: 'dy-stickies' },
                h('div', { class: 'sticky teal' }, h('span', { class: 'ok-badge' }, icon('check')), h('span', { text: '완료' }), h('b', { text: String(sum.done) })),
                h('div', { class: 'sticky lav' }, icon('doc', 'big'), h('span', { text: '결재' }), h('b', { text: String(sum.approvals) })),
                h('div', { class: 'sticky yellow' }, icon('bolt', 'big'), h('span', { text: '실행' }), h('b', { text: String(sum.runs) }))),
              h('div', { class: 'dy-first' }, icon('crown'), h('span', { text: '첫 시도 합격' }), h('b', { text: `${sum.firstPass[0]}/${sum.firstPass[1]}` })),
              sum.tomorrow ? h('p', { class: 'dy-tomorrow', text: `내일: ${sum.tomorrow}` }) : null,
            ] : h('p', { class: 'dy-empty', text: loaded ? '요약이 없어요' : '불러오는 중…' }),
            h('button', { type: 'button', class: 'dy-arrow next', 'aria-label': '다음 날', disabled: !exists(st.day + 1), onclick: () => go(st.day + 1) }, icon('right'))),
          h('nav', { class: 'dy-tabs', 'aria-label': '날짜' }, tabs.map((n, i) => h('button', { type: 'button',
            class: `dy-tab t${i % 4} ${n === st.day ? 'on' : ''}`, 'aria-current': n === st.day ? 'page' : null, onclick: () => go(n) }, `${n}일차`)))));
    });
  }

  // ---------------------------------------------------------------- 직원 목록·상태창 (04)
  function team() {
    open(() => h('div', { class: 'pop tm paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': '직원' },
      closeBtn(), h('h2', { text: '직원' }),
      h('div', { class: 'tm-list' }, Data.TEAM.map((p) => {
        const s = Data.sheet(p.id);
        return h('button', { type: 'button', class: 'tm-card', onclick: () => employee(p.id) },
          face(p.id, 'normal', 'tm-face'), h('b', { text: `${p.title} · ${p.name}` }), h('span', { text: `Lv.${s.level}` }));
      }), hireCard())));
  }

  function employee(id) {
    open(() => {
      const s = Data.sheet(id);
      const p = s.person;
      // 기록이 없으면 빈 막대 (숫자를 꾸며내지 않는다)
      const bar = (cls, value) => h('span', { class: `meter ${cls} ${value == null ? 'none' : ''}`, title: value == null ? '아직 기록이 없어요' : null,
        vars: { '--v': `${Math.round((value || 0) * 100)}%` } }, h('i'));
      // 막힌 일이 있으면 위쪽에 빨간 꼬리표: 누르면 막힌 이유와 재시도·취소
      const who = Data.BY_ID[id] || {};
      const stuck = who.state === 'blocked' && who.task ? Data.task(who.task) : null;
      return h('div', { class: 'pop sh', role: 'dialog', 'aria-modal': 'true', 'aria-label': `${p.title} 담당 ${p.name}` },
        closeBtn(),
        stuck ? h('button', { type: 'button', class: 'sh-blocked', onclick: () => taskCard(stuck.id) },
          icon('warn'), h('span', { text: `막힌 일: ${stuck.title}` }), h('b', { text: '도와주기' })) : null,
        h('button', { type: 'button', class: 'sh-jobtab', onclick: () => jobCard(id) }, icon('doc'), '업무 카드'),
        h('div', { class: 'sh-left' },
          h('div', { class: 'polaroid' }, h('span', { class: 'tape' }), h('span', { class: 'photo' }, face(p.id, s.mood === 'happy' ? 'happy' : s.mood, 'sh-face'))),
          p.memo ? h('p', { class: 'sh-memo', text: p.memo }) : null,
          h('button', { type: 'button', class: 'sh-dress', onclick: () => customize(p.id) }, icon('star'), '꾸미기'),
          h('button', { type: 'button', class: `sh-ai ${p.aiCustom ? 'custom' : ''}`, title: `탑재된 AI: ${aiText(p.ai)}`,
            'aria-label': `탑재된 AI ${aiText(p.ai)} · 바꾸기`, onclick: () => aiLoad(p.id) }, icon('chip'), aiShort(p.ai))),
        h('div', { class: 'sh-right' },
          h('h2', { text: `${p.title} 담당 · ${p.name}` }),
          h('div', { class: 'sh-level' }, h('b', { text: `Lv.${s.level}` }), bar('lav', s.xp / s.xpMax), h('span', { text: `${s.xp} / ${s.xpMax}` })),
          h('ul', { class: 'sh-stats' },
            h('li', {}, icon('bolt'), h('span', { text: '속도' }), bar('lav', s.speed)),
            h('li', {}, icon('gear'), h('span', { text: '정확도' }), bar('teal', s.accuracy)),
            h('li', {}, icon('doc'), h('span', { text: '꼼꼼함' }), bar('yellow', s.thorough))),
          // 보유 스킬: 스킬 학습에서 배운 스킬(별, 누르면 스킬 보기)을 먼저, 그다음 설정의 특기(글자만)
          h('fieldset', { class: 'sh-skills' }, h('legend', { text: '보유 스킬' }),
            Data.get().skills.filter((sk) => sk.learned_by.includes(p.role)).map((sk) => h('button', { type: 'button', class: 'sh-skill learned',
              title: sk.description, onclick: () => skillDetail(sk.slug) }, icon('star'), sk.title)),
            p.skills.map((k) => h('span', { class: 'sh-skill', text: k }))),
          h('div', { class: 'sh-today' }, h('span', { text: `오늘 완료 ${s.todayDone} · 수정 ${s.todayFix}` }),
            who.job && who.job !== who.role ? btn('내보내기', 'paper-btn small sh-dismiss', () => dismissStaff(who)) : null,
            icon(s.mood === 'happy' ? 'smile' : 'worried', 'mood'))));
    });
  }

  // 직원 내보내기 (새 직원만): 열린 일은 같은 일을 하는 직원에게 넘어가고, 옷·스킬 공부는 취소, 그림은 휴지통 폴더로
  function dismissStaff(p) {
    const mate = Data.BY_ROLE[p.job];
    dialog(`${p.name}${subj(p.name)} 회사를 떠날까요?`, `맡은 일은 ${mate ? mate.name : '같은 일을 하는 직원'}에게 넘어가요.
만들던 옷·스킬 공부는 취소되고, 그림은 휴지통 폴더(data/trash/staff)에 남아요.
뒤 직원들은 책상을 한 칸씩 당겨 앉아요.`, [
      { label: '아니요' },
      { label: '내보내기', kind: 'danger', needsRun: true, run: () => Data.dismiss(p.role)
        .then(() => Data.refresh())
        .then(() => { closeAll(); hooks.notify(mate ? mate.name : '하나', `${p.name}${subj(p.name)} 떠났어요. 그동안 고마웠어요!`); })
        .catch(fail) },
    ]);
  }

  // ---------------------------------------------------------------- 업무 카드 (CEO 요청 B)
  // 이 직원이 어떤 일을 하는 에이전트인지: 임무(회사 규칙 company/roles/<일>.md), 할 수 있는 것(실제 설정: 파일 고치기·인터넷 검색),
  // 하지 않는 것, 만드는 것, 끼운 AI, 배운 스킬. 숫자는 실제 기록만 (완료 수).
  function jobCard(id) {
    open(() => {
      const p = Data.BY_ID[id] || Data.TEAM[0];
      const c = p.card || { mission: '', can: [], cannot: [], outputs: [] };
      const s = Data.sheet(id);
      const learned = Data.get().skills.filter((sk) => sk.learned_by.includes(p.role));
      const list = (cls, items, iconName) => h('ul', { class: `jc-list ${cls}` }, items.map((x) => h('li', {}, icon(iconName), x)));
      return h('div', { class: 'pop jc paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': `${p.name} 업무 카드` },
        closeBtn(),
        h('div', { class: 'jc-head' },
          face(p.id, 'normal', 'jc-face'),
          h('div', {}, h('span', { class: 'jc-kicker', text: '업무 카드' }), h('h2', { text: `${p.fullTitle || p.title} · ${p.name}` }),
            h('p', { class: 'jc-mission', text: c.mission || '—' }))),
        h('div', { class: 'jc-cols' },
          h('section', {}, h('h3', { text: '할 수 있어요' }), list('can', c.can, 'check'),
            h('h3', { text: '하지 않아요' }), list('cannot', c.cannot, 'warn')),
          h('section', {}, h('h3', { text: '만드는 것' }), list('out', c.outputs, 'doc'),
            h('h3', { text: '끼운 AI' }),
            h('button', { type: 'button', class: `sh-ai jc-ai ${p.aiCustom ? 'custom' : ''}`, onclick: () => aiLoad(p.id) }, icon('chip'), aiText(p.ai)),
            h('h3', { text: `배운 스킬 ${learned.length}개` }),
            learned.length ? h('div', { class: 'jc-skills' }, learned.map((sk) => h('button', { type: 'button', class: 'sh-skill learned',
              title: sk.description, onclick: () => skillDetail(sk.slug) }, icon('star'), sk.title)))
              : h('p', { class: 'jc-none', text: '아직 없어요 · 스킬 학습 게시판에서 가르칠 수 있어요' }))),
        h('p', { class: 'jc-foot', text: `지금까지 끝낸 일 ${s.done}건 · 오늘 ${s.todayDone}건` }));
    });
  }

  // ---------------------------------------------------------------- AI 탑재
  // 직원마다 어떤 AI(Codex·Claude, 모델, 생각 깊이)를 끼울지. 목록은 서버가 설치된 CLI에서 읽어 온다 (지어내지 않음).
  // 파일을 고치는 일에는 Codex만 (Claude는 읽기 전용). 권한은 일이 정하고 AI를 바꿔도 그대로다.
  const RUNTIME_LABEL = { codex: 'Codex', claude: 'Claude', grok_text: 'Grok 텍스트' };

  function modelName(ai) {
    const opts = Data.aiOptions();
    const list = opts && !opts.error ? opts[ai.runtime] || [] : [];
    const m = list.find((x) => x.slug === (ai.model || ''));
    if (m) return m.name;
    return ai.model || '기본';
  }
  function aiShort(ai) {
    if (ai.runtime === 'claude' && Data.aiOptions()?.unavailable?.claude) return 'Claude 사용 불가 · Codex 대체';
    if (ai.runtime === 'claude') return `Claude ${ai.model ? modelName(ai) : ''}`.trim();
    return ai.model ? modelName(ai) : 'Codex 기본';
  }
  function aiText(ai) {
    const opts = Data.aiOptions();
    const labels = opts && !opts.error ? opts.effort_labels || {} : {};
    return `${RUNTIME_LABEL[ai.runtime] || ai.runtime} · ${modelName(ai)} · 생각 ${ai.effort ? labels[ai.effort] || ai.effort : '기본'}`;
  }

  function aiLoad(id) {
    open((st) => {
      const p = Data.BY_ID[id];
      const opts = Data.aiOptions();
      st.loadingAIOptions = !opts;
      if (!opts) return loadingPop('AI 탑재');
      if (opts.error) return failPop('AI 탑재', opts.error);
      if (!st.sel) st.sel = { ...p.ai };
      const writes = Boolean((opts.writes || {})[p.role]);
      const labels = opts.effort_labels || {};
      const pick = (patch) => { st.sel = { ...st.sel, ...patch }; draw(); };
      const chosen = (opts[st.sel.runtime] || []).find((m) => m.slug === (st.sel.model || ''));
      const efforts = chosen ? chosen.efforts || [] : Object.keys(labels);
      if (st.sel.effort && !efforts.includes(st.sel.effort)) st.sel.effort = '';
      const card = (runtime, m) => {
        const locked = ['claude','grok_text'].includes(runtime) && writes;
        const on = st.sel.runtime === runtime && (st.sel.model || '') === m.slug;
        return h('button', { type: 'button', class: `ai-card ${runtime}`, role: 'radio', 'aria-checked': String(on), disabled: locked,
          title: locked ? '파일을 고치는 일에는 Codex만 끼울 수 있어요' : null,
          onclick: () => pick({ runtime, model: m.slug, effort: (m.efforts || []).includes(st.sel.effort) ? st.sel.effort : '' }) },
          h('span', { class: 'ai-chip' }, icon('chip')),
          h('b', { text: m.name }),
          h('span', { class: 'ai-desc', text: m.desc || '' }));
      };
      const same = st.sel.runtime === p.ai.runtime && (st.sel.model || '') === (p.ai.model || '') && (st.sel.effort || '') === (p.ai.effort || '');
      return h('div', { class: 'pop aiw paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': `${p.name} AI 탑재` },
        closeBtn(),
        h('div', { class: 'aiw-head' }, face(p.id, 'normal', 'aiw-face'),
          h('div', {}, h('h2', { text: `${p.name} AI 탑재` }),
            h('p', { class: 'aiw-now', text: `지금: ${aiText(p.ai)}` }))),
        h('h3', { text: 'Codex (ChatGPT 구독)' }),
        h('div', { class: 'ai-grid', role: 'radiogroup', 'aria-label': 'Codex 모델' },
          [{ slug: '', name: '기본', desc: 'Codex가 정한 기본 모델' }, ...(opts.codex || [])].map((m) => card('codex', m))),
        h('h3', { text: 'Grok 텍스트 (기존 Grok 로그인)' }),
        h('p', { class: 'aiw-note', text: writes ? 'Grok 텍스트는 파일을 고치는 직원에게 장착할 수 없어요.' : '기획·읽기 전용 리뷰만 가능하며 매 호출 전 도구 차단을 확인해요.' }),
        h('div', { class: 'ai-grid', role: 'radiogroup', 'aria-label': 'Grok 텍스트 모델' }, (opts.grok_text || []).map((m) => card('grok_text', m))),
        h('h3', { text: 'Claude (Claude 구독)' }),
        opts.unavailable?.claude ? h('p', { class: 'aiw-note', text: opts.unavailable.claude }) : null,
        writes ? h('p', { class: 'aiw-note', text: `${p.name}의 일은 파일을 고쳐야 해서 Codex만 끼울 수 있어요. Claude는 읽기만 하는 일(기획·리뷰)에 끼울 수 있어요.` }) : null,
        h('div', { class: 'ai-grid', role: 'radiogroup', 'aria-label': 'Claude 모델' }, (opts.claude || []).map((m) => card('claude', m))),
        h('h3', { text: '생각 깊이' }),
        h('div', { class: 'cz-chips', role: 'radiogroup', 'aria-label': '생각 깊이' },
          ['', ...efforts].map((e) => h('button', { type: 'button', class: 'cz-chip', role: 'radio', 'aria-checked': String((st.sel.effort || '') === e),
            onclick: () => pick({ effort: e }) }, e ? labels[e] || e : '기본'))),
        h('p', { class: 'aiw-note', text: '깊게 생각할수록 똑똑하지만 느리고 구독 사용량을 더 써요. 파일을 고칠 수 있는지 같은 권한은 AI를 바꿔도 그대로예요. 바꾼 AI는 다음 일부터 써요.' }),
        h('div', { class: 'row-btns' },
          p.aiCustom ? btn('처음대로', '', () => Data.resetAI(p.role).then(() => { close(); hooks.notify(p.name, '원래 AI로 돌아왔어요'); }).catch(fail)) : null,
          btn('취소', '', () => close()),
          btn('끼우기', 'primary', (e) => {
            if (same) { close(); return; }
            const paper = e.currentTarget.closest('.aiw');
            Data.setAI(p.role, st.sel).then(() => {
              Sfx.play('cheer');
              Fx.sparkle(paper, paper.offsetWidth / 2, 90, { count: 14, spread: 150 });
              return pause(500);
            }).then(() => { close(); hooks.notify(p.name, `새 AI를 끼웠어요! ${aiShort(st.sel)}`); }).catch(fail);
          })));
    }, { keep: true });
  }

  // ---------------------------------------------------------------- 완성작 (10)
  function trophies() {
    open(() => {
      const s = Data.get();
      const slots = s.trophies;
      return h('div', { class: 'pop tr', role: 'dialog', 'aria-modal': 'true', 'aria-label': '완성작' },
        closeBtn(),
        h('h2', { class: 'tr-sign', text: '완성작' }),
        h('p', { class: 'tr-intro', text: '완료한 작품을 모아 뒀어요. 아래 목록에서 결과를 확인하세요.' }),
        h('div', { class: 'tr-shelves', tabindex: '0', role: 'region', 'aria-label': '완성작 목록', 'data-scroll-key': 'trophies', 'data-focus-key': 'trophies' }, slots.length ? slots.map((item) => h('article', { class: `tr-slot ${item.kind}` },
          h('div', { class: 'tr-info' }, h('span', { class: 'panel-kicker', text: item.kind === 'game' ? '게임' : '보고서' }),
            h('h3', { text: item.title }), h('p', { class: 'tr-meta', text: (Data.task(item.task) || {}).project || item.task })),
          item.kind === 'game' ? [
              h('span', { class: 'tr-item' }, h('span', { class: 'cart' }, h('span', { class: 'cart-label', text: item.title })), icon('trophy', 'tr-cup')),
              btn('플레이', 'lav-btn', () => Data.play(item.task)
                .then(() => hooks.notify((Data.BY_ROLE.builder || {}).name || '솔', 'Godot로 게임을 켰어요!')).catch(fail), { iconName: 'play' })]
              : [
                h('span', { class: 'frame' }, h('span', { class: 'frame-title', text: item.title }),
                  face((Data.BY_ROLE.analyst || { id: 'luna' }).id, 'normal', 'frame-face'), h('span', { class: 'frame-lines' })),
                btn('열기', 'lav-btn', () => report(item.task), { iconName: 'doc' })])) : h('p', { class: 'panel-empty', text: '아직 완성작이 없어요. 작업을 끝내고 결재하면 여기에 모여요.' })),
        h('p', { class: 'tr-plate', text: `완성 ${s.trophies.length} · 이번 달 목표 ${s.goals.month}` }));
    });
  }

  // ---------------------------------------------------------------- 스킬 학습 (Claude 스킬 방식)
  // 스킬 = 직원이 다음 작업부터 따르는 짧은 지침서 (skills/<이름>/SKILL.md). CEO가 직접 가르치거나,
  // 직원에게 공부를 맡기고 정리해 온 것을 CEO가 승인하면 배운다. 배운 스킬은 그 직원의 프롬프트에 붙는다.
  // 스스로 배우기: 한 번에 안 풀린 일을 끝낸 직원이 돌아보고(회고) 스킬을 새로 만들거나 고쳐 온다 (판이 오른다).
  const STUDY_STATE = { queued: '공부 준비', running: '공부 중…', awaiting_approval: '다 했어요! 확인해 주세요', blocked: '막혔어요' };
  const REFLECT_STATE = { ...STUDY_STATE, queued: '돌아볼 차례', running: '돌아보는 중…' };
  const HOW_LABEL = { ceo: 'CEO가 가르침', study: '공부해 옴', reflect: '스스로 돌아보고 만듦' };

  // 직원 얼굴 토글 (배운 직원 고르기). 다시 그리지 않고 그 자리에서 바꾼다 (글을 쓰는 창의 입력이 지워지지 않게).
  function whoToggles(selected, onToggle, { single = false, people = null } = {}) {
    const box = h('div', { class: 'sk-who', role: single ? 'radiogroup' : 'group', 'aria-label': '직원' });
    for (const m of people || Data.TEAM) {
      const on = selected.includes(m.role);
      box.append(h('button', { type: 'button', class: 'sk-who-btn', role: single ? 'radio' : null, 'aria-label': m.name,
        'aria-checked': single ? String(on) : null, 'aria-pressed': single ? null : String(on),
        onclick: (e) => {
          const b = e.currentTarget;
          if (single) {
            box.querySelectorAll('.sk-who-btn').forEach((x) => x.setAttribute('aria-checked', String(x === b)));
            onToggle(m.role, true);
          } else {
            const next = b.getAttribute('aria-pressed') !== 'true';
            b.setAttribute('aria-pressed', String(next));
            onToggle(m.role, next);
          }
        } }, face(m.id, 'normal', 'sk-who-face'), h('span', { text: m.name })));
    }
    return box;
  }

  // 스킬을 쓰는 곳: 프로젝트·일 종류. 비어 있으면 모든 곳 (studio/skills.py in_scope)
  // 셋째는 칩에 다는 도움말. '디자인 일'은 종류가 아니라 조건 (다른 종류와 함께 고르면 그 종류의 디자인 일만)
  const SCOPE_KINDS = [['plan', '기획'], ['build', '개발'], ['research', '리서치'], ['review', '리뷰'], ['study', '스킬 공부'], ['tool', 'MCP 만들기'],
    ['design', '디자인 일', '화면·그림·글자 모양을 다루는 일일 때만 붙어요']];
  const kindLabel = (k) => (SCOPE_KINDS.find(([x]) => x === k) || [k, k])[1];
  function kindsText(kinds) {
    const work = kinds.filter((k) => k !== 'design').map(kindLabel).join('·');
    return kinds.includes('design') ? (work ? `${work} 중 디자인 일` : '디자인 일') : work;
  }
  function projectName(key) {
    const p = Data.get().projects.find((x) => x.key === key);
    return p ? p.title : key;
  }
  function scopeText({ projects = [], kinds = [] } = {}) {
    const where = projects.length ? projects.map(projectName).join('·') : '모든 프로젝트';
    const what = kinds.length ? kindsText(kinds) : '모든 일';
    return `${where} · ${what}`;
  }
  // 게시판 카드 꼬리표 (쓰는 곳을 좁힌 스킬만)
  function scopeTag(sk) {
    if (!(sk.projects || []).length && !(sk.kinds || []).length) return null;
    const parts = [...(sk.projects || []).map(projectName), ...((sk.kinds || []).length ? [kindsText(sk.kinds)] : [])];
    return h('span', { class: 'sk-tag scope', title: `쓰는 곳: ${scopeText(sk)}`, text: parts.join('·') });
  }

  // 쓰는 곳 고르기: '모두' 칩 + 프로젝트·일 종류 칩. 다시 그리지 않고 그 자리에서 바꾼다 (글을 쓰는 창의 입력이 지워지지 않게).
  // 다 고르면 '모두'와 같으니 비운다. 프로젝트 줄은 프로젝트가 둘 이상이거나 이미 좁혀 둔 경우만 보인다.
  function scopeToggles(sel, onChange) {
    const cur = { projects: [...(sel.projects || [])], kinds: [...(sel.kinds || [])] };
    const box = h('div', { class: 'sk-scope' });
    const row = (label, key, items) => {
      const chips = h('div', { class: 'sk-chips', role: 'group', 'aria-label': label });
      const paint = () => chips.querySelectorAll('.sk-chip').forEach((b) => {
        const v = b.dataset.value;
        b.setAttribute('aria-pressed', String(v ? cur[key].includes(v) : !cur[key].length));
      });
      const chip = (value, text, help) => h('button', { type: 'button', class: `sk-chip${value ? '' : ' all'}`, 'data-value': value, text, title: help || null,
        onclick: () => {
          if (!value) cur[key] = [];
          else cur[key] = cur[key].includes(value) ? cur[key].filter((x) => x !== value) : [...cur[key], value];
          if (cur[key].length === items.length) cur[key] = [];
          cur[key] = items.map(([k]) => k).filter((k) => cur[key].includes(k)); // 순서는 목록 순
          paint();
          onChange({ projects: [...cur.projects], kinds: [...cur.kinds] });
        } });
      chips.append(chip('', label === '프로젝트' ? '모든 프로젝트' : '모든 일'), ...items.map(([k, text, help]) => chip(k, text, help)));
      paint();
      return h('div', { class: 'sk-scope-row' }, h('span', { class: 'sk-scope-label', text: label }), chips);
    };
    const projects = Data.get().projects.map((p) => [p.key, p.title]);
    if (projects.length > 1 || cur.projects.length) box.append(row('프로젝트', 'projects', projects));
    box.append(row('일 종류', 'kinds', SCOPE_KINDS));
    return box;
  }

  // 이름 뒤 조사 '이/가' (솔이, 클로가). 한글이 아니면 '가'
  function subj(name) {
    const c = String(name).charCodeAt(String(name).length - 1) - 0xac00;
    return c >= 0 && c < 11172 && c % 28 ? '이' : '가';
  }

  function learnerFaces(roles) {
    return h('span', { class: 'sk-learners' }, roles.map((r) => Data.BY_ROLE[r]).filter(Boolean).map((m) => face(m.id, 'happy', 'sk-mini')));
  }

  function skillBoard() {
    open(() => {
      const s = Data.get();
      const studying = s.tasks.filter((t) => t.kind === 'skill' && !['done', 'cancelled'].includes(t.status));
      return h('div', { class: 'pop sk', role: 'dialog', 'aria-modal': 'true', 'aria-label': '스킬 학습' },
        closeBtn(),
        h('h2', { class: 'sk-sign', text: '스킬 학습' }),
        h('p', { class: 'sk-lead', text: '직원에게 일하는 요령을 가르쳐요. 배운 스킬은 다음 작업부터 지침으로 따르고, 쓰면서 고쳐 가요.' }),
        h('div', { class: 'sk-actions' },
          btn('직접 가르치기', 'primary', () => teachSkill(), { iconName: 'doc', needsRun: true }),
          btn('공부 맡기기', 'lav-btn', () => studySkill(), { iconName: 'book', needsRun: true }),
          s.skills.length ? btn('성적표', 'paper-btn', () => skillGrades(), { iconName: 'trophy' }) : null),
        selfLearningBar(s.selfLearning),
        studying.length ? h('section', { class: 'sk-study', 'aria-label': '공부 중' }, studying.map((t) => {
          const p = Data.owner(t);
          return h('div', { class: `sk-row st-${t.status}` },
            face(p.id, t.status === 'blocked' ? 'worried' : 'normal', 'sk-row-face'),
            h('span', { class: 'sk-row-title', text: `${p.name} · ${t.title}` }),
            h('span', { class: 'sk-row-state', text: (t.origin ? REFLECT_STATE : STUDY_STATE)[t.status] || Data.STATUS_LABELS[t.status] }),
            t.status === 'awaiting_approval' ? btn('확인하기', 'primary', () => skillReview(t.id)) : null,
            t.status === 'blocked' ? btn('재시도', '', () => Data.act(t.id, 'retry').catch(fail), { needsRun: true }) : null,
            t.status === 'blocked' ? btn('', 'paper-btn square', () => taskCard(t.id), { iconName: 'warn', aria: '막힌 이유 보기' }) : null);
        })) : null,
        h('div', { class: 'sk-grid' }, s.skills.length
          ? s.skills.map((sk) => h('button', { type: 'button', class: 'sk-card', onclick: () => skillDetail(sk.slug) },
            h('span', { class: 'sk-card-pin' }),
            h('b', { class: 'sk-card-title', text: sk.title }),
            h('span', { class: 'sk-card-when', text: sk.description }),
            h('span', { class: 'sk-card-foot' },
              sk.learned_by.length ? learnerFaces(sk.learned_by) : h('span', { class: 'sk-card-none', text: '아직 아무도 안 배웠어요' }),
              h('span', { class: 'sk-card-tags' },
                scopeTag(sk),
                sk.version > 1 ? h('span', { class: 'sk-tag ver', title: `${sk.version - 1}번 고쳤어요`, text: `v${sk.version}` }) : null,
                sk.how === 'reflect' ? h('span', { class: 'sk-tag self', text: '스스로' }) : null))))
          : h('p', { class: 'sk-empty', text: '아직 배운 스킬이 없어요. 직접 가르치거나 공부를 맡겨 보세요.' })));
    });
  }

  // 스스로 배우기 스위치 줄 (끄면 회고를 하지 않는다. 켜져 있어도 배우는 것은 CEO 확인 뒤)
  function selfLearningBar(sl) {
    const on = sl.on !== false;
    const who = (Data.BY_ROLE.producer || Data.TEAM[0]).name;
    return h('div', { class: `sk-auto ${on ? 'on' : 'off'}` },
      h('button', { type: 'button', class: 'sk-switch', role: 'switch', 'aria-checked': String(on), 'aria-label': '스스로 배우기',
        onclick: () => Data.setSelfLearning(!on)
          .then(() => hooks.notify(who, on ? '스스로 배우기를 껐어요' : '이제 스스로 돌아보고 배울게요!')).catch(fail) }, h('i')),
      h('div', { class: 'sk-auto-text' },
        h('b', { text: `스스로 배우기 ${on ? '켜짐' : '꺼짐'}` }),
        h('span', { text: on
          ? `한 번에 안 풀린 일은 끝난 뒤 스스로 돌아보고 스킬을 새로 만들거나 고쳐 와요. 하루 ${sl.limit}번까지 (오늘 ${sl.today}번). 배우기 전에 CEO가 확인해요.`
          : '켜면 한 번에 안 풀린 일을 끝낸 직원이 스스로 돌아보고 스킬을 만들거나 고쳐 와요.' })));
  }

  // 사용 기록 한 줄 (실행 기록으로 센 실제 숫자). 따름 = 직원이 끝낼 때 '이 스킬을 따랐다'고 알린 횟수
  function usageText(u) {
    if (!u || (!u.runs && !u.told)) return '아직 쓴 적 없어요';
    const told = u.told ? ` · 따랐다고 알린 것 ${u.applied}번 (알린 ${u.told}번 중)` : '';
    const tail = u.tasks ? ` · 이 스킬을 쓴 일 ${u.tasks}개 중 ${u.smooth}개가 한 번에 풀렸어요` : ' · 아직 끝난 일은 없어요';
    return `${u.runs}번 붙었어요${told}${tail}`;
  }

  // ---------------------------------------------------------------- 스킬 성적표 (CEO 요청 B: 스킬이 얼마나 효과 있나)
  // 스킬마다 실제 기록으로만: 쓴 횟수, 쓴 일 중 한 번에 풀린 수, 배운 직원마다 배우기 전·후 '한 번에 끝낸 일' 비율.
  // 한 번에 = 막힘·다시 하기·CEO 수정 요청 없이 끝남 (리뷰 담당은 CEO 수정 요청 없음). 기록이 적으면 비교하지 않는다.
  const GRADE_MIN = 2; // 전·후 모두 이만큼 끝낸 일이 있어야 비교한다
  function rate(x) { return x.tasks ? Math.round((x.smooth / x.tasks) * 100) : null; }

  function skillGrades() {
    open(() => {
      const r = Data.skillGrades();
      if (!r) return loadingPop('스킬 성적표');
      if (r.error) return failPop('스킬 성적표', r.error);
      const row = (g) => {
        const u = g.usage || {};
        const learners = g.learners.map((l) => {
          const m = Data.BY_ROLE[l.role];
          const b = rate(l.before);
          const a = rate(l.after);
          const enough = l.before.tasks >= GRADE_MIN && l.after.tasks >= GRADE_MIN;
          const trend = !enough ? 'wait' : a > b ? 'up' : a < b ? 'down' : 'same';
          return h('li', { class: `sg-who ${trend}` },
            m ? face(m.id, 'normal', 'sg-face') : null,
            h('b', { text: l.name }),
            enough
              ? h('span', { class: 'sg-text', text: `한 번에 ${b}% (${l.before.smooth}/${l.before.tasks}) → ${a}% (${l.after.smooth}/${l.after.tasks})` })
              : h('span', { class: 'sg-text sg-wait', text: `기록이 더 필요해요 · 배우기 전 ${l.before.tasks}건 · 후 ${l.after.tasks}건` }),
            enough ? h('i', { class: 'sg-arrow', 'aria-label': trend === 'up' ? '좋아짐' : trend === 'down' ? '나빠짐' : '같음' }) : null);
        });
        return h('div', { class: 'sg-row' },
          h('button', { type: 'button', class: 'sg-title', onclick: () => skillDetail(g.slug) }, h('b', { text: g.title }), h('span', { class: 'skd-ver', text: `v${g.version}` })),
          h('div', { class: 'sg-usage' },
            h('span', {}, h('b', { text: String(u.runs || 0) }), '번 씀'),
            h('span', { title: '직원이 끝낼 때 이 스킬을 따랐다고 알린 횟수 / 따른 스킬을 알린 횟수' }, '따름 ', h('b', { text: String(u.applied || 0) }), `/${u.told || 0}`),
            h('span', {}, '쓴 일 ', h('b', { text: String(u.tasks || 0) }), '개 중 한 번에 ', h('b', { text: String(u.smooth || 0) }), '개')),
          learners.length ? h('ul', { class: 'sg-learners' }, learners) : h('p', { class: 'jc-none', text: '배운 직원이 없어요' }));
      };
      return h('div', { class: 'pop sg paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': '스킬 성적표' },
        closeBtn(),
        h('h2', { text: '스킬 성적표' }),
        h('p', { class: 'sg-lead', text: `숫자는 실제 기록으로만 셉니다. '한 번에'는 막힘·다시 하기·CEO 수정 요청 없이 끝난 일이에요. 배우기 전·후는 그 직원이 끝낸 일로 비교하고, 양쪽 모두 ${GRADE_MIN}건 이상일 때만 보여 줘요.` }),
        h('div', { class: 'sg-list' }, r.skills.length ? r.skills.map(row) : h('p', { class: 'jc-none', text: '아직 배운 스킬이 없어요' })));
    });
  }

  function skillDetail(slug) {
    open(() => {
      const sk = Data.get().skills.find((x) => x.slug === slug);
      if (!sk) {
        return h('div', { class: 'pop dialog paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': '스킬' },
          h('h2', { text: '스킬을 찾을 수 없어요' }), h('p', { text: '이미 지웠을 수 있어요.' }),
          h('div', { class: 'row-btns' }, btn('닫기', 'primary', () => close())));
      }
      const full = Data.skill(slug);
      const from = `${HOW_LABEL[sk.how] || HOW_LABEL.study}${sk.source === 'ceo' ? '' : ` (${sk.source})`}`;
      const hist = full && !full.error ? full.history || [] : [];
      return h('div', { class: 'pop skd paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': sk.title },
        closeBtn(),
        h('h2', {}, sk.title, h('span', { class: 'skd-ver', text: `v${sk.version}` })),
        h('p', { class: 'skd-when', text: `언제 쓰나: ${sk.description}` }),
        h('pre', { class: 'skd-body', tabindex: '0', text: full ? (full.error || full.body) : '불러오는 중…' }),
        full && !full.error ? h('p', { class: 'skd-usage', text: usageText(full.usage) }) : null,
        hist.length > 1 ? h('ul', { class: 'skd-hist', 'aria-label': '진화 기록' }, hist.slice().reverse().map((v) => h('li', {
          text: `v${v.version} · ${v.date} · ${HOW_LABEL[v.how] || ''}${v.change ? ` · ${v.change}` : ' · 처음'}` }))) : null,
        h('div', { class: 'skd-learn' }, h('span', { class: 'skd-label', text: '배운 직원' }),
          whoToggles(sk.learned_by, (role, on) => Data.learnSkill(slug, role, on)
            .then(() => { const m = Data.BY_ROLE[role]; hooks.notify(m ? m.name : '하나', on ? `'${sk.title}' 배웠어요!` : `'${sk.title}' 잊었어요`); })
            .catch(fail))),
        h('div', { class: 'skd-learn skd-scope' }, h('span', { class: 'skd-label', text: '쓰는 곳' }),
          scopeToggles(sk, (next) => Data.setSkillScope(slug, next.projects, next.kinds)
            .then(() => hooks.notify('하나', `'${sk.title}' 쓰는 곳: ${scopeText(next)}`)).catch(fail))),
        h('p', { class: 'skd-meta', text: `${from} · 처음 ${sk.created} · 파일 skills/${sk.slug}/SKILL.md` }),
        h('div', { class: 'row-btns' },
          btn('더 좋게 고쳐 오기', 'lav-btn', () => studySkill({ target: sk.slug, title: sk.title, role: sk.learned_by[0] }),
            { iconName: 'book', needsRun: true }),
          btn('지우기', 'danger', () => dialog('스킬을 지울까요?', `${sk.title}\n지운 스킬은 data/skills-trash에 남아요.`, [
            { label: '아니요' },
            { label: '지우기', kind: 'danger', run: () => Data.removeSkill(slug).then(() => close()).catch(fail) },
          ])),
          btn('닫기', 'primary', () => close())));
    });
  }

  function teachSkill() {
    open((st) => {
      if (!st.who) st.who = [];
      if (!st.scope) st.scope = { projects: [], kinds: [] };
      const title = h('input', { class: 'title-input', type: 'text', maxlength: '30', placeholder: '예: 시그널 연결', 'aria-label': '스킬 제목', autofocus: true });
      const when = h('input', { class: 'title-input sm', type: 'text', maxlength: '300', placeholder: '언제 쓰나요? 예: 씬 사이 이벤트를 만들 때', 'aria-label': '언제 쓰는 스킬인지' });
      const body = h('textarea', { class: 'memo-input tall', maxlength: '4000', placeholder: '지침: 순서, 실제 파일·함수 이름, 흔한 실수와 확인 방법', 'aria-label': '지침' });
      const box = h('div', { class: 'pop dialog paper sk-form', role: 'dialog', 'aria-modal': 'true', 'aria-label': '직접 가르치기' },
        h('h2', { text: '직접 가르치기' }),
        h('label', { class: 'sk-field' }, h('span', { text: '제목' }), title),
        h('label', { class: 'sk-field' }, h('span', { text: '언제 쓰나' }), when),
        h('label', { class: 'sk-field' }, h('span', { text: '지침' }), body),
        h('div', { class: 'sk-field' }, h('span', { text: '배울 직원' }),
          whoToggles(st.who, (role, on) => { st.who = on ? [...new Set([...st.who, role])] : st.who.filter((r) => r !== role); })),
        h('div', { class: 'sk-field' }, h('span', { text: '쓰는 곳 (고르지 않으면 모든 곳)' }),
          scopeToggles(st.scope, (next) => { st.scope = next; })),
        h('div', { class: 'row-btns' },
          btn('취소', '', () => close()),
          btn('가르치기', 'primary', () => {
            const data = { title: title.value.trim(), description: when.value.trim(), body: body.value.trim(), learned_by: st.who,
              projects: st.scope.projects, kinds: st.scope.kinds };
            const empty = [[title, data.title], [when, data.description], [body, data.body]].find(([, v]) => !v);
            if (empty) { shake(box); empty[0].focus(); return; }
            Data.teachSkill(data).then(() => { close(); hooks.notify('하나', `'${data.title}' 스킬을 게시판에 붙였어요`); }).catch(fail);
          }, { needsRun: true })));
      return box;
    }, { keep: true });
  }

  // target이 있으면 '더 좋게 고쳐 오기': 그 스킬을 고쳐 온다 (무엇을 고칠지는 비워도 된다)
  function studySkill({ target = null, title = '', role = null } = {}) {
    open((st) => {
      if (!st.role) st.role = role && Data.BY_ROLE[role] ? role : (Data.BY_ROLE.reviewer ? 'reviewer' : Data.TEAM[0].role); // 기본: 클로 (Claude)
      const topic = h('textarea', { class: 'memo-input', maxlength: '2000', autofocus: true, 'aria-label': target ? '고칠 점' : '공부할 주제',
        placeholder: target ? '무엇을 고칠까요? 비워 두면 알아서 더 좋게 고쳐 와요' : '무엇을 공부해 올까요? 예: 우리 게임 코드에서 씬 전환하는 법을 정리해 줘' });
      const project = Data.currentProject();
      const head = target ? `'${title}' 고쳐 오기` : '공부 맡기기';
      const box = h('div', { class: 'pop dialog paper sk-form', role: 'dialog', 'aria-modal': 'true', 'aria-label': head },
        h('h2', { text: head }),
        h('div', { class: 'sk-field' }, h('span', { text: '누가' }), whoToggles([st.role], (role) => { st.role = role; }, { single: true })),
        h('label', { class: 'sk-field' }, h('span', { text: target ? '고칠 점 (비워도 돼요)' : '무엇을' }), topic),
        h('p', { class: 'sk-note', text: `${project ? project.title : '프로젝트 없음'} 코드를 읽기만 하며 ${target ? '고쳐' : '공부해'}요 (파일은 고치지 않아요). ${target ? '고쳐 오면 판이 하나 오르고, 옛 판은 기록에 남아요. ' : ''}정리해 오면 CEO가 확인한 뒤에 배워요. 에너지 1을 써요.` }),
        h('div', { class: 'row-btns' },
          btn('취소', '', () => close()),
          btn(target ? '고쳐 오기' : '공부 맡기기', 'primary', () => {
            const text = topic.value.trim();
            if (!text && !target) { shake(box); topic.focus(); return; }
            const m = Data.BY_ROLE[st.role];
            Data.studySkill(st.role, text, target)
              .then(() => { close(); hooks.notify(m ? m.name : '하나', target ? '더 좋게 고쳐 올게요!' : '공부해 올게요!'); }).catch(fail);
          }, { needsRun: true })));
      return box;
    }, { keep: true });
  }

  // 공부·회고해 온 스킬 확인: 읽어 보고 함께 배울 직원을 골라 승인하거나, 다시 공부를 맡긴다.
  // 고친 스킬이면 바뀐 점과 전 판을 함께 본다 (승인하면 판이 오르고 옛 판은 기록에 남는다).
  function skillReview(id) {
    open((st) => {
      const t = Data.task(id);
      if (!t) return missing();
      const d = Data.detail(id);
      if (!d) return loadingPop('스킬 확인');
      if (d.error) return failPop('스킬 확인', d.error);
      const prop = d.proposal || {};
      const sk = prop.skill;
      const p = Data.owner(t);
      const pending = t.status === 'awaiting_approval';
      const updating = prop.action === 'update' && prop.target;
      const old = updating ? Data.get().skills.find((x) => x.slug === prop.target) : null;
      if (!sk) return h('div', { class: 'pop dialog paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': '스킬 확인' },
        closeBtn(), h('h2', { text: t.title }), h('p', { text: pending ? '정리한 내용이 없어요.' : `${Data.STATUS_LABELS[t.status]} 상태예요.` }));
      if (!st.who) st.who = old ? [...new Set([...old.learned_by, t.role])] : [t.role];
      // 쓰는 곳: 제안대로 (scope project = 이 작업의 프로젝트에서만). CEO가 바꿀 수 있다
      if (!st.scope) st.scope = { projects: sk.scope === 'project' && t.project ? [t.project] : [], kinds: sk.kinds || [] };
      const how = t.origin ? `스스로 돌아보고 ${updating ? '고친' : '만든'}` : updating ? '고쳐 온' : '공부해 온';
      // 본문 칸에 보는 것: 제안(기본) · 전 판(고친 스킬) · 비슷한 스킬
      const peek = st.showOld && updating ? prop.target : st.peek || null;
      const peekFull = peek ? Data.skill(peek) : null;
      const bodyText = !peek ? sk.body : peekFull ? (peekFull.error || peekFull.body) : '불러오는 중…';
      const shown = peek ? Data.get().skills.find((s) => s.slug === peek) || sk : sk;
      const similar = pending && !updating ? (prop.similar || []).filter((x) => Data.get().skills.some((s) => s.slug === x.slug)) : [];
      return h('div', { class: 'pop skd paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': `스킬 확인 · ${sk.title}` },
        closeBtn(),
        h('div', { class: 'skr-head' }, face(p.id, 'happy', 'skr-face'),
          h('div', {}, h('p', { class: 'skr-kicker', text: `${p.name}${subj(p.name)} ${how} 스킬 · ${t.title}` }), h('h2', { text: sk.title }))),
        prop.reason ? h('p', { class: 'skr-why', text: `왜: ${prop.reason}` }) : null,
        updating ? h('div', { class: 'skr-change' },
          h('span', { text: old ? `v${old.version} → v${old.version + 1}${prop.change ? ` · ${prop.change}` : ''}` : '고칠 스킬이 지워져서 새 스킬로 배워요' }),
          old ? btn(st.showOld ? '새 판 보기' : '전 판 보기', 'paper-btn', () => { st.showOld = !st.showOld; st.peek = null; draw(); }) : null) : null,
        // 새 스킬인데 비슷한 스킬이 이미 있으면: 따로 두기보다 그 스킬에 합쳐 고쳐 오게 할 수 있다 (스킬이 겹겹이 쌓이지 않게)
        similar.length ? h('div', { class: 'skr-similar' },
          h('p', { class: 'skr-sim-head' }, h('b', { text: '비슷한 스킬이 이미 있어요' }),
            h('span', { text: ' 따로 두면 비슷한 지침이 겹쳐요. 합치면 그 스킬의 판이 하나 올라요.' })),
          similar.map((x) => h('div', { class: 'skr-sim-row' },
            h('b', { class: 'skr-sim-title', text: x.title }),
            h('span', { class: 'skr-sim-score', text: `겹침 ${Math.round(x.score * 100)}%` }),
            btn(st.peek === x.slug ? '제안 보기' : '보기', 'paper-btn', () => { st.peek = st.peek === x.slug ? null : x.slug; st.showOld = false; draw(); }),
            btn('여기에 합쳐 고쳐 오기', 'lav-btn', () => Data.act(id, 'merge-skill', { into: x.slug })
              .then(() => { close(); hooks.notify(p.name, `'${x.title}'에 합쳐서 고쳐 올게요!`); }).catch(fail), { needsRun: true })))) : null,
        peek && peek !== prop.target ? h('p', { class: 'skr-peek', text: `지금 보는 것: 이미 있는 스킬 '${shown.title}'` }) : null,
        h('p', { class: 'skd-when', text: `언제 쓰나: ${shown.description}` }),
        h('pre', { class: `skd-body ${peek ? 'old' : ''}`, tabindex: '0', text: bodyText }),
        pending ? [
          h('div', { class: 'skd-learn' }, h('span', { class: 'skd-label', text: '함께 배울 직원' }),
            whoToggles(st.who, (role, on) => { st.who = on ? [...new Set([...st.who, role])] : st.who.filter((r) => r !== role); })),
          h('div', { class: 'skd-learn skd-scope' }, h('span', { class: 'skd-label', text: '쓰는 곳' }),
            scopeToggles(st.scope, (next) => { st.scope = next; })),
          h('div', { class: 'row-btns' },
            btn('다시 공부', 'paper-btn', () => memo('다시 공부', `${p.name}에게 무엇을 더 공부해 오라고 할까요?`, '보내기',
              (note) => Data.act(id, 'request-changes', { note }).then(() => { close(); hooks.notify(p.name, '더 공부해 올게요!'); }).catch(fail)),
            { needsRun: true }),
            btn(updating && old ? '고친 판 승인' : '배우기 승인', 'primary', (e) => {
              if (!st.who.length) { hooks.notify(p.name, '배울 직원을 한 명 이상 골라 주세요'); return; }
              if (!begin(st)) return;
              const paper = e.currentTarget.closest('.skd');
              Sfx.play('cheer');
              Fx.sparkle(paper, paper.offsetWidth / 2, 120, { count: 16, spread: 160 });
              Data.act(id, 'approve', { learned_by: st.who, projects: st.scope.projects, kinds: st.scope.kinds }).then(() => pause(700)).then(() => {
                closeOwn(st);
                end(st);
                hooks.notify(p.name, updating && old ? `'${sk.title}' 고쳐서 다시 배웠어요!` : `'${sk.title}' 배웠어요!`);
              }).catch((err) => { end(st, true); fail(err); });
            }, { needsRun: true }))]
          : h('p', { class: 'skd-meta', text: '이미 정리된 공부예요.' }));
    });
  }

  // ---------------------------------------------------------------- MCP 보관소 (왼쪽 서재)
  // 직원에게 쥐여 줄 도구(MCP 서버). 내장(AI 스튜디오 안에 들어 있음) · 바깥(CEO가 등록) · 직원이 만듦.
  // 장착한 직원은 일할 때 그 도구를 쓴다. 리뷰 담당은 읽기만 해서 장착하지 않는다 (studio/mcp.py).
  const MCP_SOURCE = { builtin: '내장', custom: '바깥', staff: '직원이 만듦' };
  const mcpPeople = () => Data.TEAM.filter((m) => m.job !== 'reviewer');

  function mcpState(s) {
    if (!s.enabled) return ['off', '꺼 둠'];
    if (!s.check) return ['wait', '연결 확인 전'];
    return s.check.ok ? ['ok', `도구 ${s.check.tools.length}개`] : ['bad', '연결 안 됨'];
  }

  const TOOL_STATE = { queued: '만들 준비', running: '만드는 중…', awaiting_approval: '다 만들었어요! 확인해 주세요', blocked: '막혔어요' };

  function mcpShelf() {
    open(() => {
      const list = Data.get().mcp;
      const making = Data.get().tasks.filter((t) => t.kind === 'tool' && !['done', 'cancelled'].includes(t.status));
      return h('div', { class: 'pop mc', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'MCP 보관소' },
        closeBtn(),
        h('h2', { class: 'sk-sign mc-sign', text: 'MCP 보관소' }),
        h('p', { class: 'sk-lead', text: '직원에게 도구(MCP)를 쥐여 줘요. 장착한 직원은 일할 때 그 도구를 스스로 써요. 리뷰 담당은 읽기만 해서 장착하지 않아요.' }),
        h('div', { class: 'sk-actions' },
          btn('만들기 맡기기', 'lav-btn', () => mcpOrder(), { iconName: 'gear', needsRun: true }),
          btn('바깥 MCP 등록', 'primary', () => mcpAdd(), { iconName: 'link' })),
        making.length ? h('section', { class: 'sk-study', 'aria-label': '만드는 중' }, making.map((t) => {
          const p = Data.owner(t);
          return h('div', { class: `sk-row st-${t.status}` },
            face(p.id, t.status === 'blocked' ? 'worried' : 'normal', 'sk-row-face'),
            h('span', { class: 'sk-row-title', text: `${p.name} · ${t.title}` }),
            h('span', { class: 'sk-row-state', text: TOOL_STATE[t.status] || Data.STATUS_LABELS[t.status] }),
            t.status === 'awaiting_approval' ? btn('확인하기', 'primary', () => toolReview(t.id)) : null,
            t.status === 'blocked' ? btn('재시도', '', () => Data.act(t.id, 'retry').catch(fail), { needsRun: true }) : null,
            t.status === 'blocked' ? btn('', 'paper-btn square', () => taskCard(t.id), { iconName: 'warn', aria: '막힌 이유 보기' }) : null);
        })) : null,
        h('div', { class: 'mc-grid' }, list.map((s) => {
          const [state, label] = mcpState(s);
          return h('button', { type: 'button', class: `mc-book src-${s.source}${s.enabled ? '' : ' off'}`, onclick: () => mcpDetail(s.name) },
            h('span', { class: 'mc-spine' }),
            h('b', { class: 'mc-title', text: s.title }),
            h('span', { class: 'mc-name', text: s.name }),
            h('span', { class: 'mc-desc', text: s.description }),
            h('span', { class: 'mc-foot' },
              s.equipped.length ? learnerFaces(s.equipped) : h('span', { class: 'sk-card-none', text: '아무도 장착 안 함' }),
              h('span', { class: 'sk-card-tags' },
                h('span', { class: `sk-tag mc-src ${s.source}`, text: MCP_SOURCE[s.source] || s.source }),
                h('span', { class: `sk-tag mc-state ${state}`, text: label }))));
        })));
    });
  }

  function mcpDetail(name) {
    open((st) => {
      const s = Data.get().mcp.find((x) => x.name === name);
      if (!s) return missing();
      const [state, label] = mcpState(s);
      const act = (action, body, done) => Data.mcpAction(name, action, body).then(done).catch(fail);
      const check = () => {
        st.checking = true;
        draw();
        act('check', {}, (r) => {
          st.checking = false;
          const c = r.server.check || {};
          hooks.notify('하나', c.ok ? `'${s.title}' 연결됐어요! 도구 ${c.tools.length}개` : `'${s.title}' 연결이 안 돼요`);
        }).finally(() => { st.checking = false; draw(); });
      };
      const tools = (s.check && s.check.tools) || [];
      return h('div', { class: 'pop skd paper mcd', role: 'dialog', 'aria-modal': 'true', 'aria-label': s.title },
        closeBtn(),
        h('h2', {}, s.title, h('span', { class: `skd-ver mc-src ${s.source}`, text: MCP_SOURCE[s.source] || s.source })),
        h('p', { class: 'skd-when', text: s.description || '설명이 없어요' }),
        s.source === 'custom' ? h('p', { class: 'mcd-run', text: s.transport === 'http' ? `주소: ${s.url}` : `실행: ${[s.command, ...s.args].join(' ')}` }) : null,
        h('div', { class: `mcd-check ${state}` },
          h('span', { text: st.checking ? '연결 확인 중… (처음이면 1분쯤 걸릴 수 있어요)'
            : s.check && !s.check.ok ? `연결 안 됨: ${s.check.error}` : `${label}${s.check ? ` · ${String(s.check.at).slice(0, 16).replace('T', ' ')}` : ''}` }),
          btn('연결 확인', 'paper-btn', check, { iconName: 'check' })),
        tools.length ? h('ul', { class: 'mcd-tools', 'aria-label': '도구' }, tools.map((t) => h('li', {},
          h('b', { text: t.name }), t.description ? h('span', { text: ` — ${t.description}` }) : null))) : null,
        (s.env_keys || []).length ? h('div', { class: 'mcd-secrets' }, h('span', { class: 'skd-label', text: '토큰' }),
          s.env_keys.map((k) => {
            const input = h('input', { class: 'title-input sm', type: 'password', autocomplete: 'off', spellcheck: 'false',
              placeholder: s.env_set[k] ? '넣었어요 · 바꾸려면 새 값' : '토큰 값을 넣어 주세요', 'aria-label': `${k} 토큰` });
            return h('div', { class: 'mcd-secret' }, h('code', { text: k }),
              h('span', { class: `mcd-set ${s.env_set[k] ? 'yes' : 'no'}`, text: s.env_set[k] ? '넣음' : '없음' }), input,
              btn('저장', 'paper-btn', () => act('secrets', { values: { [k]: input.value } },
                () => hooks.notify('하나', input.value ? '토큰을 넣었어요' : '토큰을 지웠어요'))));
          }),
          h('p', { class: 'sk-note', text: '토큰은 이 PC의 data/mcp-secrets.json에만 두고, 화면·기록·직원 프롬프트에는 보이지 않아요. 비우고 저장하면 지워요.' })) : null,
        h('div', { class: 'skd-learn' }, h('span', { class: 'skd-label', text: '장착한 직원' }),
          whoToggles(s.equipped, (role, on) => act('equip', { role, on },
            () => { const m = Data.BY_ROLE[role]; hooks.notify(m ? m.name : '하나', on ? `'${s.title}' 장착했어요!` : `'${s.title}' 뺐어요`); }),
          { people: mcpPeople() })),
        h('div', { class: 'row-btns' },
          s.source === 'staff' ? btn('고쳐 오기', 'lav-btn', () => mcpOrder({ target: s.name, title: s.title }), { iconName: 'gear', needsRun: true }) : null,
          btn(s.enabled ? '끄기' : '켜기', 'paper-btn', () => act('enable', { on: !s.enabled }, () => {})),
          s.source !== 'builtin' ? btn('지우기', 'danger', () => dialog('MCP를 지울까요?', `${s.title}\n장착과 토큰도 함께 지워요.`, [
            { label: '아니요' },
            { label: '지우기', kind: 'danger', run: () => act('remove', {}, () => close()) },
          ])) : null,
          btn('닫기', 'primary', () => close())));
    });
  }

  // MCP 만들기 맡기기: 고른 직원이 표준 라이브러리 한 파일짜리 도구를 만들어 오면 리뷰 담당이 읽고, CEO가 승인하면 보관소에 꽂는다.
  // target이 있으면 직원이 만든 도구 '고쳐 오기'. 리뷰 담당은 만들지 않는다 (만든 것을 읽는다).
  function mcpOrder({ target = null, title = '' } = {}) {
    open((st) => {
      const people = mcpPeople();
      if (!st.role) st.role = (people.find((m) => m.job === 'builder') || people[0]).role; // 기본: 솔 (개발)
      const ask = h('textarea', { class: 'memo-input', maxlength: '2000', autofocus: true, 'aria-label': target ? '고칠 점' : '만들 도구',
        placeholder: target ? '무엇을 고칠까요? 비워 두면 알아서 더 좋게 고쳐 와요' : '어떤 도구가 필요해요? 예: 게임 저장 파일(JSON)을 읽어서 요약해 주는 도구' });
      const head = target ? `'${title}' 고쳐 오기` : 'MCP 만들기 맡기기';
      const box = h('div', { class: 'pop dialog paper sk-form', role: 'dialog', 'aria-modal': 'true', 'aria-label': head },
        h('h2', { text: head }),
        h('div', { class: 'sk-field' }, h('span', { text: '누가' }), whoToggles([st.role], (role) => { st.role = role; }, { single: true, people })),
        h('label', { class: 'sk-field' }, h('span', { text: target ? '고칠 점 (비워도 돼요)' : '무엇을' }), ask),
        h('p', { class: 'sk-note', text: '직원이 파이썬 한 파일로 도구를 만들어 오면, 리뷰 담당이 코드를 읽고 안전한지 봐요. 승인하기 전에는 이 PC에서 실행하지 않아요. 에너지를 2~4 써요.' }),
        h('div', { class: 'row-btns' },
          btn('취소', '', () => close()),
          btn(target ? '고쳐 오기' : '맡기기', 'primary', () => {
            const text = ask.value.trim();
            if (!text && !target) { shake(box); ask.focus(); return; }
            const m = Data.BY_ROLE[st.role];
            Data.mcpOrder(st.role, text, target)
              .then(() => { close(); hooks.notify(m ? m.name : '하나', target ? '더 좋게 고쳐 올게요!' : '도구를 만들어 올게요!'); }).catch(fail);
          }, { needsRun: true })));
      return box;
    }, { keep: true });
  }

  // 만들어 온 도구 확인: 코드·도구 목록·자동 검사 표시·리뷰 판정을 보고, 장착할 직원을 골라 승인(설치)하거나 다시 만들게 한다.
  function toolReview(id) {
    open((st) => {
      const t = Data.task(id);
      if (!t) return missing();
      const d = Data.detail(id);
      if (!d) return loadingPop('도구 확인');
      if (d.error) return failPop('도구 확인', d.error);
      const prop = d.proposal || {};
      const review = d.review || {};
      const p = Data.owner(t);
      const pending = t.status === 'awaiting_approval';
      if (!prop.code) return h('div', { class: 'pop dialog paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': '도구 확인' },
        closeBtn(), h('h2', { text: t.title }), h('p', { text: pending ? '만든 코드가 없어요.' : `${Data.STATUS_LABELS[t.status]} 상태예요.` }));
      if (!st.equip) st.equip = mcpPeople().some((m) => m.role === t.role) ? [t.role] : [];
      const flags = prop.flags || [];
      return h('div', { class: 'pop skd paper tlr', role: 'dialog', 'aria-modal': 'true', 'aria-label': `도구 확인 · ${prop.title}` },
        closeBtn(),
        h('div', { class: 'skr-head' }, face(p.id, 'happy', 'skr-face'),
          h('div', {}, h('p', { class: 'skr-kicker', text: `${p.name}${subj(p.name)} 만든 도구 · ${prop.name}${t.target ? ' (고친 판)' : ''}` }), h('h2', { text: prop.title }))),
        prop.reason ? h('p', { class: 'skr-why', text: `왜: ${prop.reason}${prop.change ? ` · 바뀐 점: ${prop.change}` : ''}` }) : null,
        h('p', { class: 'skd-when', text: prop.description || '' }),
        h('p', { class: `tlr-review ${review.verdict === 'approve' ? 'ok' : 'bad'}`,
          text: `리뷰 (${(Data.BY_ROLE[review.by] || { name: '리뷰' }).name}): ${review.verdict === 'approve' ? '통과' : '반려'} · ${review.summary || ''}` }),
        (prop.tools || []).length ? h('p', { class: 'tlr-tools', text: `도구: ${prop.tools.map((x) => x.name).join(', ')}` }) : null,
        flags.length ? h('details', { class: 'tlr-flags' }, h('summary', { text: `눈여겨볼 곳 ${flags.length}군데 (자동 검사 — 문제라는 뜻은 아니에요)` }),
          h('ul', {}, flags.map((f) => h('li', { text: f })))) : null,
        h('pre', { class: 'skd-body tlr-code', tabindex: '0', text: prop.code }),
        pending ? [
          h('div', { class: 'skd-learn' }, h('span', { class: 'skd-label', text: '장착할 직원' }),
            whoToggles(st.equip, (role, on) => { st.equip = on ? [...new Set([...st.equip, role])] : st.equip.filter((r) => r !== role); }, { people: mcpPeople() })),
          h('div', { class: 'row-btns' },
            btn('다시 만들기', 'paper-btn', () => memo('다시 만들기', `${p.name}에게 무엇을 고쳐 오라고 할까요?`, '보내기',
              (note) => Data.act(id, 'request-changes', { note }).then(() => { close(); hooks.notify(p.name, '고쳐 올게요!'); }).catch(fail)),
            { needsRun: true }),
            btn('승인하고 꽂기', 'primary', (e) => {
              if (!begin(st)) return;
              const paper = e.currentTarget.closest('.skd');
              Sfx.play('cheer');
              Fx.sparkle(paper, paper.offsetWidth / 2, 120, { count: 16, spread: 160 });
              Data.act(id, 'approve', { equip: st.equip }).then(() => pause(700)).then(() => {
                closeOwn(st);
                end(st);
                hooks.notify(p.name, `'${prop.title}'를 MCP 보관소에 꽂았어요!`);
              }).catch((err) => { end(st, true); fail(err); });
            }, { needsRun: true }))]
          : h('p', { class: 'skd-meta', text: `${Data.STATUS_LABELS[t.status]} 상태예요.` }));
    });
  }

  // 바깥 MCP 등록: 명령으로 띄우기(stdio) 또는 주소로 잇기(http). 토큰은 하나까지 여기서, 더 있으면 등록 뒤 자세히 보기에서.
  function mcpAdd() {
    open((st) => {
      if (!st.mode) st.mode = 'stdio';
      const field = (label, input) => h('label', { class: 'sk-field' }, h('span', { text: label }), input);
      const name = h('input', { class: 'title-input sm', type: 'text', maxlength: '32', placeholder: '영어 이름 (예: github)', 'aria-label': 'MCP 이름', autofocus: true });
      const title = h('input', { class: 'title-input sm', type: 'text', maxlength: '30', placeholder: '보관소에 보일 이름 (예: 깃허브)', 'aria-label': '보일 이름' });
      const desc = h('input', { class: 'title-input sm', type: 'text', maxlength: '300', placeholder: '무엇을 하는 도구인지 (직원이 읽어요)', 'aria-label': '설명' });
      const command = h('input', { class: 'title-input sm', type: 'text', maxlength: '300', placeholder: '예: npx', 'aria-label': '실행할 명령' });
      const args = h('input', { class: 'title-input sm', type: 'text', maxlength: '1000', placeholder: '예: -y @modelcontextprotocol/server-github', 'aria-label': '인자' });
      const url = h('input', { class: 'title-input sm', type: 'text', maxlength: '500', placeholder: '예: https://example.com/mcp', 'aria-label': 'MCP 주소' });
      const key = h('input', { class: 'title-input sm', type: 'text', maxlength: '64', placeholder: '예: GITHUB_PERSONAL_ACCESS_TOKEN', 'aria-label': '토큰 이름' });
      const value = h('input', { class: 'title-input sm', type: 'password', autocomplete: 'off', placeholder: '토큰 값', 'aria-label': '토큰 값' });
      const box = h('div', { class: 'pop dialog paper sk-form mc-form', role: 'dialog', 'aria-modal': 'true', 'aria-label': '바깥 MCP 등록' },
        h('h2', { text: '바깥 MCP 등록' }),
        h('div', { class: 'sk-field' }, h('span', { text: '연결 방식' }),
          h('div', { class: 'sk-chips', role: 'radiogroup', 'aria-label': '연결 방식' }, [['stdio', '명령으로 띄우기'], ['http', '주소로 잇기']].map(([v, t]) =>
            h('button', { type: 'button', class: 'sk-chip', role: 'radio', 'aria-checked': String(st.mode === v), 'aria-pressed': String(st.mode === v), text: t,
              onclick: () => { st.mode = v; box.querySelectorAll('.mc-mode').forEach((x) => { x.hidden = x.dataset.mode !== v; });
                box.querySelectorAll('[role=radio]').forEach((x) => { const on = x.textContent === t; x.setAttribute('aria-checked', String(on)); x.setAttribute('aria-pressed', String(on)); }); } })))),
        h('div', { class: 'mc-row' }, field('이름', name), field('보일 이름', title)), field('설명', desc),
        h('div', { class: 'mc-mode mc-row', 'data-mode': 'stdio', hidden: st.mode !== 'stdio' }, field('실행할 명령', command), field('인자 (띄어쓰기로 나눠요)', args)),
        h('div', { class: 'mc-mode', 'data-mode': 'http', hidden: st.mode !== 'http' }, field('MCP 주소', url)),
        h('div', { class: 'mc-row' }, field('토큰 이름 (없으면 비움)', key), field('토큰 값', value)),
        h('p', { class: 'sk-note mc-warn', text: '명령으로 띄우는 MCP는 이 PC에서 프로그램을 실행해요. 믿을 수 있는 것만 등록하세요. npx·uvx는 처음 연결할 때 인터넷에서 내려받아요. 등록한 뒤 "연결 확인"을 눌러 보세요.' }),
        h('div', { class: 'row-btns' },
          btn('취소', '', () => close()),
          btn('등록', 'primary', () => {
            const k = key.value.trim().toUpperCase();
            const data = { name: name.value.trim().toLowerCase(), title: title.value.trim(), description: desc.value.trim(), transport: st.mode,
              command: command.value.trim(), args: args.value.trim() ? args.value.trim().split(/\s+/) : [], url: url.value.trim(),
              env_keys: k ? [k] : [], env: k && value.value ? { [k]: value.value } : {}, bearer_key: st.mode === 'http' && k ? k : '' };
            const empty = [[name, data.name], [title, data.title], ...(st.mode === 'http' ? [[url, data.url]] : [[command, data.command]])].find(([, v]) => !v);
            if (empty) { shake(box); empty[0].focus(); return; }
            Data.mcpAdd(data).then((r) => { close(); hooks.notify('하나', `'${data.title}'를 보관소에 꽂았어요`); mcpDetail(r.server.name); }).catch(fail);
          })));
      return box;
    }, { keep: true });
  }

  // ---------------------------------------------------------------- 자동 업무 (벽시계)
  // 정해 둔 때가 되면 직원이 스스로 일을 시작한다 (studio/schedules.py). 결재는 그대로 CEO.
  const SC_KIND = { directive: '지시 (기획부터)', research: '리서치 보고서' };
  const SC_EVERY = [['daily', '매일'], ['weekdays', '평일'], ['weekly', '매주'], ['hours', '몇 시간마다']];
  const SC_DAYS = ['월', '화', '수', '목', '금', '토', '일'];
  function whenShort(iso) {
    const d = iso ? new Date(iso) : null;
    if (!d || Number.isNaN(d.getTime())) return '';
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }

  function schedules() {
    open((st) => {
      if (!st.f) st.f = { kind: 'directive', title: '', text: '', every: 'daily', at: '09:00', weekday: 0, hours: 3 };
      const f = st.f;
      const list = Data.get().schedules;
      const redraw = () => draw();
      const chips = (items, key, label) => h('div', { class: 'sk-chips', role: 'radiogroup', 'aria-label': label }, items.map(([v, t]) =>
        h('button', { type: 'button', class: 'sk-chip', role: 'radio', 'aria-checked': String(f[key] === v), 'aria-pressed': String(f[key] === v), text: t,
          onclick: () => { f[key] = v; redraw(); } })));
      const input = (key, attrs) => h('input', { ...attrs, value: String(f[key] ?? ''), oninput: (e) => { f[key] = e.target.value; } });
      const project = Data.currentProject();
      const row = (x) => h('div', { class: `sc-row${x.enabled ? '' : ' off'}` },
        h('button', { type: 'button', class: 'sk-switch', role: 'switch', 'aria-checked': String(x.enabled), 'aria-label': `${x.title} 켜기`,
          onclick: () => Data.scheduleAction(x.id, 'enable', { on: !x.enabled }).then(redraw).catch(fail) }, h('i')),
        h('div', { class: 'sc-main' },
          h('b', { text: x.title }),
          h('span', { class: 'sc-meta', text: `${SC_KIND[x.kind] || x.kind} · ${x.when} · ${projectName(x.project)}` }),
          h('span', { class: 'sc-meta', text: [x.enabled && x.next ? `다음 ${whenShort(x.next)}` : '꺼 둠',
            x.last_run ? `지난 ${whenShort(x.last_run)}${x.last_task ? ` (${x.last_task})` : ''}` : ''].filter(Boolean).join(' · ') })),
        btn('지금 하기', 'paper-btn', () => Data.scheduleAction(x.id, 'run').then(() => {
          redraw(); hooks.notify((Data.BY_ROLE[x.kind === 'research' ? 'analyst' : 'producer'] || Data.TEAM[0]).name, `'${x.title}' 시작할게요!`);
        }).catch(fail), { needsRun: true }),
        btn('', 'paper-btn square', () => dialog('자동 업무를 지울까요?', x.title, [
          { label: '아니요' },
          { label: '지우기', kind: 'danger', run: () => Data.scheduleAction(x.id, 'remove').then(redraw).catch(fail) },
        ]), { iconName: 'x', aria: '지우기' }));
      return h('div', { class: 'pop sc paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': '자동 업무' },
        closeBtn(),
        h('h2', { text: '자동 업무' }),
        h('p', { class: 'sc-lead', text: '정해 둔 때가 되면 직원이 스스로 일을 시작해요. 결재는 지금처럼 CEO가 해요. 긴급 정지 중이거나 에너지가 없으면 기다렸다가 한 번만 하고, 지난 일이 안 끝났으면 그때는 건너뛰어요.' }),
        h('div', { class: 'sc-list' }, list.length ? list.map(row) : h('p', { class: 'jc-none', text: '아직 자동 업무가 없어요. 아래에서 만들어 보세요.' })),
        h('div', { class: 'sc-form' },
          h('h3', { text: `새 자동 업무 · ${project ? project.title : '프로젝트 없음'}` }),
          h('div', { class: 'sc-line' }, h('span', { text: '무엇을' }), chips([['directive', '지시'], ['research', '리서치']], 'kind', '무엇을')),
          h('div', { class: 'sc-line' }, h('span', { text: '제목' }), input('title', { class: 'title-input sm', type: 'text', maxlength: '40', placeholder: '예: 아침 점검', 'aria-label': '제목' })),
          h('div', { class: 'sc-line' }, h('span', { text: '내용' }), input('text', { class: 'title-input sm', type: 'text', maxlength: '2000',
            placeholder: f.kind === 'research' ? '예: 이번 주 Godot 새 소식을 정리해 줘' : '예: 어제 바뀐 코드를 점검하고 고칠 곳을 퀘스트로 만들어 줘', 'aria-label': '내용' })),
          h('div', { class: 'sc-line' }, h('span', { text: '언제' }), chips(SC_EVERY, 'every', '언제'),
            f.every === 'hours'
              ? input('hours', { class: 'title-input sm sc-num', type: 'number', min: '1', max: '168', 'aria-label': '몇 시간마다' })
              : input('at', { class: 'title-input sm sc-time', type: 'time', 'aria-label': '시각' }),
            f.every === 'weekly' ? h('select', { class: 'sc-day', 'aria-label': '요일', onchange: (e) => { f.weekday = Number(e.target.value); } },
              SC_DAYS.map((d, i) => h('option', { value: String(i), selected: f.weekday === i, text: `${d}요일` }))) : null),
          h('div', { class: 'row-btns' }, btn('만들기', 'primary', () => {
            Data.addSchedule({ kind: f.kind, title: f.title.trim(), text: f.text.trim(), every: f.every, at: f.at, weekday: f.weekday, hours: Number(f.hours) })
              .then((r) => { st.f = null; redraw(); hooks.notify('하나', `'${r.schedule.title}' 자동 업무를 걸어 뒀어요 (${r.schedule.every === 'hours' ? `${r.schedule.hours}시간마다` : r.schedule.at})`); })
              .catch(fail);
          }))));
    }, { keep: true });
  }

  // 휴대폰 연결 창: 윈도우 방화벽 점검 결과를 쉬운 말로 (고치는 명령은 CEO가 관리자 권한으로 직접 실행)
  function firewallNote(check, checking, copy) {
    if (checking || !check) return h('p', { class: 'rm-text', text: '윈도우 방화벽을 살펴보는 중…' });
    if (!check.checked) {
      return h('p', { class: 'rm-text', text: '방화벽은 살펴보지 못했어요. 휴대폰이 이 PC와 같은 와이파이에 있는지(모바일 데이터가 아닌지) 확인해 주세요.' });
    }
    if (!check.blocked && check.category !== 'Public') {
      return h('p', { class: 'rm-ok', text: '방화벽 점검: 막는 곳이 없어 보여요. 휴대폰이 이 PC와 같은 와이파이인지(모바일 데이터가 아닌지)만 확인해 주세요.' });
    }
    const netName = check.category === 'Public' ? '공용' : check.category === 'Private' ? '개인' : check.category;
    return h('div', { class: 'rm-bad' },
      h('b', { text: check.blocked ? '윈도우 방화벽이 휴대폰의 접속을 막고 있어요' : '이 PC의 네트워크가 "공용"이라 막힐 수 있어요' }),
      h('p', { text: check.blocked
        ? `그래서 휴대폰에서 주소를 열면 화면이 안 나오고 계속 로딩만 돌아요. (지금 네트워크: ${netName}) 예전에 방화벽 창이 떴을 때 취소를 눌렀거나 "공용"만 골라서 그래요.`
        : '집 와이파이라면 "개인 네트워크"로 바꾸는 것이 안전하고 잘 돼요.' }),
      h('p', { text: '고치는 법: 시작 버튼 → "PowerShell"을 찾아 마우스 오른쪽 → "관리자 권한으로 실행" → 아래 글을 붙여 넣고 엔터. 끝나면 휴대폰에서 주소를 다시 열어 보세요. (집처럼 믿을 수 있는 와이파이에서만 하세요. AI 스튜디오가 대신 바꾸지는 않아요.)' }),
      check.fix ? h('div', { class: 'rm-cmd rm-fix' }, h('code', { text: check.fix }), btn('복사', 'paper-btn', () => copy(check.fix))) : null);
  }

  // ---------------------------------------------------------------- 휴대폰 연결 (리모컨)
  // 같은 와이파이(QR) 또는 Tailscale로 휴대폰에서 결재·지시·긴급 정지 (studio/remote.py). 설정은 이 PC에서만 바꾼다.
  function remote() {
    open((st) => {
      if (!st.loading && !st.info) {
        st.loading = true;
        Data.remoteInfo().then((r) => { st.info = r; }).catch((e) => { st.error = e.message; }).finally(() => { st.loading = false; draw(); });
      }
      // 같은 와이파이가 켜져 있으면 윈도우 방화벽이 휴대폰을 막는지 본다 (읽기만, 2~3초)
      if (st.info && st.info.lan_running && !st.check && !st.checking) {
        st.checking = true;
        Data.remoteCheck().then((c) => { st.check = c; }).catch(() => { st.check = { checked: false }; }).finally(() => { st.checking = false; draw(); });
      }
      if (st.info && !st.info.lan_running && st.check) st.check = null;
      const box = h('div', { class: 'pop dialog paper rm', role: 'dialog', 'aria-modal': 'true', 'aria-label': '휴대폰 연결' }, closeBtn(), h('h2', { text: '휴대폰 연결' }));
      if (st.error) { box.append(h('p', { text: st.error })); return box; }
      const r = st.info;
      if (!r) { box.append(h('p', { text: '불러오는 중…' })); return box; }
      const update = (p, msg) => p.then((x) => { st.info = x; if (msg) hooks.notify('하나', msg); draw(); }).catch(fail);
      const copy = (text) => (navigator.clipboard ? navigator.clipboard.writeText(text).then(() => hooks.notify('하나', '복사했어요')) : Promise.resolve()).catch(() => {});
      const pairing = st.pair && st.pair.until > Date.now();
      const left = pairing ? Math.ceil((st.pair.until - Date.now()) / 1000) : 0;
      if (pairing && !st.tick) st.tick = setTimeout(() => { st.tick = null; draw(); }, 1000);
      box.append(
        h('p', { class: 'rm-lead', text: '휴대폰에서 결재·지시·긴급 정지를 할 수 있어요. 휴대폰 화면(/m)만 열리고, 직원·MCP·설정은 이 PC에서만 바꿔요.' }),
        h('section', { class: 'rm-sec' },
          h('div', { class: 'rm-head' },
            h('button', { type: 'button', class: 'sk-switch', role: 'switch', 'aria-checked': String(r.lan_running), 'aria-label': '같은 와이파이',
              onclick: () => update(Data.remoteLan(!r.lan_running), r.lan_running ? '같은 와이파이 연결을 껐어요' : '같은 와이파이로 열었어요') }, h('i')),
            h('b', { text: '같은 와이파이 (집·회사)' })),
          h('p', { class: 'rm-text', text: r.lan_running ? `주소: ${r.lan_url}` : r.lan_ip ? `꺼져 있어요 · 켜면 ${r.lan_ip}에 열려요` : '이 PC의 집 안 주소를 찾지 못했어요 (와이파이에 연결돼 있나요?)' }),
          h('p', { class: 'rm-warn', text: '암호화가 없는 연결이라 믿을 수 있는 와이파이에서만 켜세요. 처음 켤 때 윈도우 방화벽이 물어보면 "개인 네트워크"만 허용해 주세요. (취소를 누르면 윈도우가 막아 버려서 휴대폰 화면이 계속 로딩만 돌아요.)' }),
          r.lan_running ? firewallNote(st.check, st.checking, copy) : null),
        h('section', { class: 'rm-sec' },
          h('div', { class: 'rm-head' }, h('b', { text: 'Tailscale (밖에서도, 암호화)' })),
          r.ts_hosts.length
            ? h('ul', { class: 'rm-list' }, r.ts_hosts.map((host) => h('li', {}, h('span', { text: `https://${host}/m` }),
              btn('빼기', 'paper-btn', () => update(Data.remoteTailscale({ remove: host }), 'Tailscale 주소를 뺐어요')))))
            : h('p', { class: 'rm-text', text: r.ts_installed ? 'Tailscale이 깔려 있어요. 아래 명령을 이 PC에서 한 번 실행한 뒤 "주소 찾기"를 눌러 주세요.' : 'PC와 휴대폰에 Tailscale 앱을 깔고 같은 계정으로 로그인해 주세요 (내 기기끼리만 이어져요).' }),
          h('div', { class: 'rm-cmd' }, h('code', { text: r.ts_command }), btn('복사', 'paper-btn', () => copy(r.ts_command))),
          h('div', { class: 'row-btns rm-row' }, btn('주소 찾기', 'paper-btn', () => update(Data.remoteTailscale({ detect: true }), 'Tailscale 주소를 허용했어요')))),
        h('section', { class: 'rm-sec' },
          h('div', { class: 'rm-head' }, h('b', { text: '휴대폰 짝짓기' })),
          pairing
            ? h('div', { class: 'rm-pair' },
              st.pair.urls.length ? st.pair.urls.map((u) => h('figure', { class: 'rm-qr' },
                h('img', { src: `/api/remote/qr.svg?u=${encodeURIComponent(u)}`, alt: '짝짓기 QR', width: '220', height: '220' }),
                h('figcaption', { text: u.startsWith('https://') ? 'Tailscale' : '같은 와이파이' })))
                : h('p', { class: 'rm-warn', text: '먼저 같은 와이파이를 켜거나 Tailscale 주소를 찾아 주세요.' }),
              h('p', { class: 'rm-code' }, '번호 ', h('b', { text: st.pair.code }), ` · ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')} 남음 · 한 번만 쓸 수 있어요`))
            : h('div', { class: 'row-btns rm-row' }, btn('QR 만들기', 'primary', () => Data.remotePair().then((p) => {
              st.pair = { ...p, until: Date.now() + p.expires_in * 1000 };
              draw();
            }).catch(fail), { disabled: !r.lan_running && !r.ts_hosts.length }))),
        h('section', { class: 'rm-sec' },
          h('div', { class: 'rm-head' }, h('b', { text: `연결된 기기 ${r.devices.length}대` })),
          r.devices.length ? h('ul', { class: 'rm-list' }, r.devices.map((d) => h('li', {},
            h('span', { text: `${d.name} · 마지막 ${String(d.last_seen || '').slice(5, 16).replace('T', ' ')}` }),
            btn('끊기', 'danger', () => update(Data.remoteForget(d.id), `${d.name} 연결을 끊었어요`)))))
            : h('p', { class: 'rm-text', text: '아직 없어요.' })));
      return box;
    });
  }

  // ---------------------------------------------------------------- 다른 아이디로 로그인 (한도·로그인 만료)
  // 멈추면 엔진이 새 명령 창에서 로그아웃 → 로그인을 띄운다 (studio/login.py). 로그인은 CEO가 브라우저에서 직접 한다.
  function needLogin() {
    open(() => {
      const need = Data.get().needsLogin;
      if (!need) {
        return h('div', { class: 'pop dialog paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': '로그인' },
          h('h2', { text: '지금은 로그인할 일이 없어요' }), h('div', { class: 'row-btns' }, btn('닫기', 'primary', () => close())));
      }
      const name = need.runtime === 'claude' ? 'Claude Code' : 'Codex';
      const quota = need.reason === 'quota';
      return h('div', { class: 'pop dialog paper lg', role: 'dialog', 'aria-modal': 'true', 'aria-label': '다른 아이디로 로그인' },
        h('h2', { text: quota ? `${name} 사용 한도가 다 됐어요` : `${name} 로그인이 필요해요` }),
        h('p', { class: 'lg-text', text: `회사를 잠깐 멈췄어요. ${need.opened ? '로그인 창(검은 명령 창)을 띄웠어요.' : '아래 단추로 로그인 창을 열어 주세요.'} 브라우저가 열리면 다른 아이디로 로그인하세요.` }),
        h('ol', { class: 'lg-steps' },
          h('li', { text: '로그인 창이 지금 아이디에서 로그아웃하고, 브라우저로 로그인 화면을 열어요.' }),
          h('li', { text: '브라우저에서 다른 아이디로 로그인해요. (AI 스튜디오는 아이디·비밀번호를 보지 않아요)' }),
          h('li', { text: "끝나면 아래 '로그인했어요 · 다시 시작'을 눌러요. 멈춘 일을 다시 해요." })),
        need.error ? h('p', { class: 'lg-error', text: `로그인 창을 못 열었어요: ${need.error}` }) : null,
        h('div', { class: 'row-btns' },
          btn(need.opened ? '로그인 창 다시 열기' : '로그인 창 열기', 'paper-btn', () => Data.loginOpen(need.runtime)
            .then(() => hooks.notify('하나', '로그인 창을 열었어요. 작업 표시줄의 검은 창을 봐 주세요')).catch(fail)),
          btn('로그인했어요 · 다시 시작', 'primary', () => Data.loginDone().then((r) => {
            close();
            hooks.notify('하나', r.retried.length ? `다시 일할게요! 멈춘 일 ${r.retried.length}개를 다시 해요` : '다시 일할게요!');
          }).catch(fail)),
          btn('나중에', '', () => close())));
    });
  }

  // ---------------------------------------------------------------- 알림 목록 (종)
  function alerts() {
    Data.markAlertsRead();
    open(() => {
      const list = Data.get().events.slice(0, 8);
      return h('div', { class: 'pop al paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': '알림' },
        closeBtn(), h('h2', { text: '알림' }),
        list.length ? h('ul', {}, list.map((e) => h('li', {},
          h('button', { type: 'button', class: 'al-item', disabled: !e.target, onclick: () => { close(); openTarget(e.target); } },
            face(e.who, 'normal', 'al-face'), h('span', { class: 'al-text', text: `${e.name}: ${e.text}` }), h('span', { class: 'al-time', text: e.time })))))
          : h('p', { text: '새 소식이 없어요' }));
    });
  }

  // ---------------------------------------------------------------- 꾸미기 (모습 세트·머리색·옷 색)
  // 키·체격 늘리기는 없앴다 (CEO 결정 2026-09-29). 옷·체형·머리 모양·안경·소품·표정은 꾸미기 공방에서 새로 그린다.
  function customize(id) {
    open((st) => {
      const p = Data.BY_ID[id];
      const opts = Looks.getOptions();
      if (!st.look) st.look = Looks.norm(p.look);
      const pick = (key, value) => { st.look = { ...st.look, [key]: value }; draw(); };
      // 모습 칩: '기본'을 뺀 칩마다 옆에 작은 ✕ (공방에서 만든 옷은 지우기, 배포 옷은 목록에서 빼기)
      const chips = (key, items, withX = false) => h('div', { class: 'cz-chips', role: 'radiogroup', 'aria-label': key },
        items.map(([value, label]) => h('span', { class: 'cz-chip-wrap' },
          h('button', { type: 'button', class: 'cz-chip', role: 'radio', 'aria-checked': String(st.look[key] === value),
            onclick: () => pick(key, value) }, label),
          withX && value !== 'base' ? h('button', { type: 'button', class: 'cz-chip-x', 'aria-label': `${label} 지우기`,
            title: (opts.made || []).includes(value) ? '이 옷 지우기' : '목록에서 빼기', onclick: () => removeLook(value, label) }, icon('x')) : null)));
      const removeLook = (set, label) => {
        const made = (opts.made || []).includes(set);
        dialog(made ? '이 옷을 지울까요?' : '목록에서 뺄까요?',
          made ? `'${label}'
지운 옷은 휴지통 폴더에 남아요.` : `'${label}'
'숨긴 옷 다시 보기'로 되살릴 수 있어요.`,
          [{ label: '아니요' }, { label: made ? '지우기' : '빼기', kind: 'danger', run: () => Data.removeLook(p.role, set).then(() => {
            if (st.look.style === set) st.look = { ...st.look, style: 'base' }; // 입고 있던 옷이면 기본으로 (서버도 저장한 모습을 기본으로 돌린다)
            hooks.notify(p.name, made ? `'${label}' 옷을 지웠어요` : `'${label}' 옷을 목록에서 뺐어요`);
            draw();
          }).catch(fail) }]);
      };
      const hiddenCount = Object.keys((opts.hidden || {})[id] || {}).length;
      const swatches = (key, items) => h('div', { class: 'cz-swatches', role: 'radiogroup', 'aria-label': key },
        items.map((o) => h('button', { type: 'button', class: `cz-swatch ${o.color ? '' : 'base'}`, role: 'radio', title: o.label,
          'aria-label': o.label, 'aria-checked': String(st.look[key] === o.key), vars: o.color ? { '--c': o.color } : null,
          onclick: () => pick(key, o.key) }, o.color ? null : '원래')));
      // 미리보기: 서 있는 모습 + 얼굴 (얼굴은 칠한 아틀라스를 이 요소에만 적용)
      const faceEl = face(id, 'happy', 'cz-face');
      const looks = Object.fromEntries(Data.TEAM.map((m) => [m.id, m.look]));
      looks[id] = st.look;
      // 이 미리보기만 따로 칠한 그림을 쓰므로, 그 그림의 열 구성(--face-cols·--fx)도 이 요소에 함께 넣는다
      Looks.portraits(looks).then((res) => {
        if (res) for (const [name, value] of Object.entries(Looks.faceStyle(res, id))) faceEl.style.setProperty(name, value);
      });
      const styles = Object.entries((opts.styles || {})[id] || { base: '기본' });
      const canColor = Looks.colorable(id);
      // 미리보기 (몸 막대를 끄는 동안에는 이 그림만 바꾼다)
      const preview = h('div', { class: 'cz-preview' }, h('span', { class: 'cz-floor' }), Scene.still(id, 'step', st.look, 300), faceEl);
      const refreshPreview = () => {
        const old = preview.querySelector('.sprite-still');
        const next = Scene.still(id, 'step', st.look, 300);
        if (old) old.replaceWith(next);
        else preview.prepend(next);
      };
      // 몸 조절 막대 (CEO 요청: 여성형·남성형이 구분되게). 정의·범위는 서버(company.BODY_SLIDERS), 그리기는 looks.js 몸 조절.
      // 끄는 동안 창 전체를 다시 그리면 손잡이가 끊기므로 단계 이름과 미리보기만 바꾼다. 빠른 선택은 창을 다시 그린다.
      const sliders = (opts.body || []).map((d) => {
        const off = d.key === 'hair_volume' && !canColor; // 머리 표시(마스크)가 없는 새 직원은 머리 숱을 못 바꾼다
        const now = off ? 0 : Number(st.look[d.key]) || 0;
        const shown = h('span', { class: 'cz-slider-value', text: d.steps[now - d.min] || '' });
        return h('label', { class: `cz-slider ${off ? 'off' : ''}` }, h('span', { class: 'cz-slider-name', text: d.label }),
          h('input', { type: 'range', min: String(d.min), max: String(d.max), step: '1', value: String(now), disabled: off,
            'aria-label': d.label, 'aria-valuetext': d.steps[now - d.min] || '',
            oninput: (e) => {
              const v = Number(e.currentTarget.value);
              st.look = { ...st.look, [d.key]: v };
              shown.textContent = d.steps[v - d.min] || '';
              e.currentTarget.setAttribute('aria-valuetext', shown.textContent);
              refreshPreview();
            } }), shown);
      });
      const presets = h('div', { class: 'cz-presets' }, (opts.presets || []).map((pr) => btn(pr.label, 'paper-btn small', () => {
        st.look = { ...st.look, ...pr.values };
        draw();
      })), btn('무작위', 'paper-btn small', () => { st.look = randomLook(id, opts, canColor); draw(); }));
      return h('div', { class: 'pop cz paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': `${p.name} 꾸미기` },
        closeBtn(),
        preview,
        h('div', { class: 'cz-options' },
          h('h2', { text: `${p.name} 꾸미기` }),
          h('div', { class: 'cz-scroll' },
            h('div', { class: 'cz-head' }, h('h3', { text: '모습' }),
              btn('꾸미기 공방', 'lav-btn small', () => wardrobeOrder(id), { iconName: 'star', needsRun: true })),
            chips('style', styles, true),
            hiddenCount ? h('div', { class: 'cz-hidden-row' }, btn(`숨긴 옷 다시 보기 (${hiddenCount})`, 'paper-btn small', () => hiddenLooks(id))) : null,
            liveMaking(p.role),
            sliders.length ? [h('div', { class: 'cz-head' }, h('h3', { text: '몸' }), presets), h('div', { class: 'cz-sliders' }, sliders)] : null,
            canColor ? [h('h3', { text: '머리색' }), swatches('hair', opts.hair || []),
              h('h3', { text: '옷 색' }), swatches('outfit', opts.outfit || [])]
              : h('p', { class: 'cz-note', text: '새 직원은 머리 숱·머리색·옷 색을 바꿀 수 없어요 (색 표시가 없어요). 몸 막대는 돼요.' }),
            h('p', { class: 'cz-note', text: '머리 모양·안경·새 옷은 꾸미기 공방에서 지금 모습을 바탕으로 그려요.' })),
          h('div', { class: 'row-btns' },
            btn('처음대로', '', () => { st.look = Looks.norm(null); draw(); }),
            btn('저장', 'primary', () => Data.saveLook(p.role, st.look)
              .then(() => { close(); hooks.notify(p.name, '어때요? 마음에 들어요!'); }).catch(fail)))));
    }, { keep: true });
  }

  // 무작위 꾸미기: 모습 세트·머리색·옷 색·몸 막대를 범위 안에서 섞는다 (색 표시가 없는 새 직원은 색·머리 숱 그대로)
  function randomLook(id, opts, canColor) {
    const pick = (list) => list[Math.floor(Math.random() * list.length)];
    const look = { ...Looks.norm(null), style: pick(Object.keys((opts.styles || {})[id] || { base: '기본' })) };
    if (canColor) {
      look.hair = pick((opts.hair || [{ key: 'base' }]).map((o) => o.key));
      look.outfit = pick((opts.outfit || [{ key: 'base' }]).map((o) => o.key));
    }
    for (const d of opts.body || []) {
      if (d.key === 'hair_volume' && !canColor) continue;
      look[d.key] = d.min + Math.floor(Math.random() * (d.max - d.min + 1));
    }
    return look;
  }

  // 숨긴 옷 다시 보기: 꾸미기 목록에서 뺀 배포 옷(여름 옷 등)을 되살린다
  function hiddenLooks(id) {
    open(() => {
      const p = Data.BY_ID[id];
      const list = Object.entries((Looks.getOptions().hidden || {})[id] || {});
      return h('div', { class: 'pop dialog paper cz-hidden', role: 'dialog', 'aria-modal': 'true', 'aria-label': `${p.name}의 숨긴 옷` },
        h('h2', { text: `${p.name}의 숨긴 옷` }),
        list.length ? h('ul', { class: 'cz-hidden-list' }, list.map(([set, label]) => h('li', {},
          h('span', { text: label }),
          btn('되살리기', 'primary small', () => Data.restoreLook(p.role, set)
            .then(() => hooks.notify(p.name, `'${label}' 옷을 되살렸어요`)).catch(fail)))))
          : h('p', { text: '숨긴 옷이 없어요' }),
        h('div', { class: 'row-btns' }, btn('닫기', '', () => close())));
    });
  }

  // 연습용 회사(serve --fake)에서는 그림을 진짜로 그리지 않는다: 주문·확인 창마다 눈에 띄게 한 줄로 알린다 (studio/runtimes.py 가짜 실행기)
  function fakeNote(withAi = false) {
    if (!(Data.get().studio || {}).fake) return null;
    return h('p', { class: 'wd-fake', role: 'note' },
      h('b', { text: '연습용 회사예요. ' }),
      '그림을 진짜로 그리지 않고, 지금 모습의 옷 색만 바꿔 보여 줘요. 진짜 그림은 실제 회사에서 주문하세요.',
      withAi ? ' 그리는 AI를 Grok으로 골라도 연습용에서는 Grok을 쓰지 않아요.' : '');
  }

  // ---------------------------------------------------------------- 꾸미기 공방 (예전 의상 제조실)
  // 지금 모습에서 한 가지(옷·체형·머리 모양·안경·소품·표정)만 바꾼 새 모습: Codex가 그림 3장(동작·걷기·얼굴)을 그리고,
  // 감독 프로그램이 잘라 미리보기를 만든다. CEO가 '입혀 보기'로 승인하면 꾸미기에 새 모습이 생기고 바로 입는다.
  // 그래서 여름 옷 + 안경처럼 겹쳐 쌓인다.
  const LOOK_STATE = { queued: '공방 차례 기다리는 중', running: '그리는 중…', checking: '그림 자르는 중…',
    awaiting_approval: '다 됐어요! 볼까요?', blocked: '막혔어요' };
  // 종류마다 예시 (누르면 이름과 설명을 채운다) — 설명은 한국어 그대로 Codex에 간다
  const LOOK_KINDS = {
    outfit: { label: '옷', icon: 'star', hint: '예: 남색 겨울 코트와 회색 목도리, 검은 바지, 갈색 부츠',
      examples: [['겨울 코트', '남색 겨울 코트와 회색 목도리'], ['정장', '단정한 회색 정장과 흰 셔츠'], ['운동복', '편한 트레이닝복 상하의'],
        ['비키니', '파란색 비키니 수영복']] },
    body: { label: '체형', icon: 'team', hint: '예: 지금보다 키가 조금 크고 마른 체형',
      examples: [['마른 체형', '지금보다 조금 마른 체형'], ['통통한 체형', '지금보다 조금 통통하고 둥근 체형'], ['키 큰 체형', '지금보다 키가 조금 큰 체형'],
        ['키 작은 체형', '지금보다 키가 조금 작은 체형'], ['근육질', '어깨가 넓고 팔이 튼튼한 근육질 체형']] },
    hair: { label: '머리 모양', icon: 'star', hint: '예: 어깨까지 오는 웨이브 단발, 색은 그대로',
      examples: [['단발', '턱선까지 오는 단발, 색은 그대로'], ['긴 생머리', '허리까지 오는 긴 생머리, 색은 그대로'], ['묶은 머리', '뒤로 높게 묶은 포니테일'],
        ['곱슬머리', '부드러운 곱슬머리'], ['짧은 머리', '짧게 자른 머리']] },
    accessory: { label: '안경·소품', icon: 'star', hint: '예: 동그란 금테 안경',
      examples: [['동그란 안경', '동그란 금테 안경'], ['뿔테 안경', '검은 뿔테 안경'], ['비니', '회색 니트 비니'], ['헤드폰', '목에 건 하얀 헤드폰'], ['목도리', '빨간 체크 목도리']] },
    face: { label: '표정', icon: 'smile', hint: '예: 늘 졸린 듯한 반쯤 감긴 눈',
      examples: [['졸린 눈', '늘 졸린 듯한 반쯤 감긴 눈'], ['초롱초롱', '크고 반짝이는 동그란 눈'], ['시크', '차분하고 시크한 눈매'], ['늘 웃는 얼굴', '늘 웃는 초승달 눈']] },
  };

  // 꾸미기 창은 글을 쓰는 창이라 데이터가 바뀌어도 다시 그리지 않는다: 이 줄만 1.5초마다 제자리에서 맞춘다 (창이 닫히면 멈춤)
  function liveMaking(role) {
    const box = h('div', { class: 'cz-making-live' });
    let last = null;
    const tick = (first) => {
      if (!first && !box.isConnected) return;
      const key = Data.get().tasks.filter((t) => t.kind === 'look' && t.role === role).map((t) => `${t.id}:${t.status}`).join('|');
      if (key !== last) {
        last = key;
        box.replaceChildren(...[makingLooks(role)].filter(Boolean));
      }
      setTimeout(() => tick(false), 1500);
    };
    tick(true);
    return box;
  }

  function makingLooks(role) {
    const mine = Data.get().tasks.filter((t) => t.kind === 'look' && t.role === role && !['done', 'cancelled'].includes(t.status));
    if (!mine.length) return null;
    return h('div', { class: 'cz-making' }, mine.map((t) => h('div', { class: `cz-make st-${t.status}` },
      h('span', { text: `${(t.extra || {}).label || t.title} · ${LOOK_STATE[t.status] || Data.STATUS_LABELS[t.status]}` }),
      t.status === 'awaiting_approval' ? btn('보기', 'primary small', () => lookReview(t.id)) : null,
      t.status === 'blocked' ? btn('이유', 'paper-btn small', () => taskCard(t.id)) : null)));
  }

  // 그리는 AI 고르기 (꾸미기 공방·캐릭터 제조실): Codex(기본) · Grok(본인 grok.com 로그인, 정사각형 그림, 시험 단계).
  // 목록과 쓸 수 있는지는 서버가 알려 준다 (ai.draw_options: Grok은 설치·로그인됐을 때만).
  // 글을 쓰는 창이라 다시 그리지 않으므로, 목록이 아직이면 불러오는 대로 이 줄만 바꾼다.
  function drawPick(st) {
    if (!st.draw) st.draw = 'codex';
    const row = h('div', { class: 'wd-draw' });
    const fill = () => {
      const opts = Data.aiOptions();
      const list = opts && !opts.error && opts.draw ? opts.draw : [{ key: 'codex', label: 'Codex', ok: true, note: '기본' }];
      const grok = list.find((d) => d.key === 'grok');
      row.replaceChildren(h('span', { text: '그리는 AI' }),
        h('div', { class: 'cz-chips', role: 'radiogroup', 'aria-label': '그리는 AI' }, list.map((d) => h('button', {
          type: 'button', class: 'cz-chip', role: 'radio', disabled: !d.ok, title: d.note, 'aria-checked': String(st.draw === d.key),
          onclick: (e) => {
            st.draw = d.key;
            e.currentTarget.parentNode.querySelectorAll('.cz-chip').forEach((b) => b.setAttribute('aria-checked', String(b === e.currentTarget)));
          } }, d.label))),
        h('span', { class: 'wd-draw-note', text: grok ? `Grok: ${grok.note}` : opts ? '' : 'Grok 확인 중…' }));
      return Boolean(opts);
    };
    if (!fill()) {
      let tries = 0;
      const again = () => { if (row.isConnected || tries < 3) { tries += 1; if (!fill() && tries < 40) setTimeout(again, 500); } };
      setTimeout(again, 500);
    }
    return row;
  }

  function wardrobeOrder(id) {
    open((st) => {
      const p = Data.BY_ID[id];
      if (!st.kind) st.kind = 'outfit';
      const k = LOOK_KINDS[st.kind];
      const styles = (Looks.getOptions().styles || {})[id] || {};
      const worn = Looks.norm(p.look).style;
      const label = h('input', { class: 'title-input', type: 'text', maxlength: '16', placeholder: `예: ${k.examples[0][0]}`, 'aria-label': '이름', autofocus: true });
      const desc = h('textarea', { class: 'memo-input', maxlength: '200', 'aria-label': '어떻게 바꿀지', placeholder: k.hint });
      if (st.label) label.value = st.label;
      if (st.desc) desc.value = st.desc;
      const keep = () => { st.label = label.value; st.desc = desc.value; };
      const box = h('div', { class: 'pop dialog paper sk-form wd-order', role: 'dialog', 'aria-modal': 'true', 'aria-label': `${p.name} 꾸미기 공방` },
        h('div', { class: 'wd-head' }, face(p.id, 'happy', 'wd-face'), h('h2', { text: `${p.name} 꾸미기 공방` })),
        fakeNote(true),
        h('p', { class: 'wd-base', text: `지금 모습 '${styles[worn] || '기본'}'에서 고른 것만 바꿔 새로 그려요.` }),
        h('div', { class: 'cz-chips wd-kinds', role: 'radiogroup', 'aria-label': '바꿀 것' },
          Object.entries(LOOK_KINDS).map(([key, v]) => h('button', { type: 'button', class: 'cz-chip', role: 'radio',
            'aria-checked': String(st.kind === key), onclick: () => { keep(); st.kind = key; draw(); } }, v.label))),
        h('div', { class: 'wd-examples' }, h('span', { text: '예시' }), k.examples.map(([name, text]) => h('button', { type: 'button', class: 'sh-skill',
          onclick: () => { label.value = name; desc.value = text; keep(); } }, name))),
        h('label', { class: 'sk-field' }, h('span', { text: '이름' }), label),
        h('label', { class: 'sk-field' }, h('span', { text: '어떻게' }), desc),
        drawPick(st),
        h('p', { class: 'sk-note', text: `AI가 새 ${k.label} 그림 3장(동작·걷기·얼굴)을 그려요. 3~5분쯤 걸리고 에너지 3(구독 사용량)을 써요. 다 되면 결재함에서 보고 입힐지 정해요.` }),
        h('div', { class: 'row-btns' },
          btn('취소', '', () => close()),
          btn('주문하기', 'primary', () => {
            const data = { label: label.value.trim(), desc: desc.value.trim() };
            const empty = [[label, data.label], [desc, data.desc]].find(([, v]) => !v);
            if (empty) { shake(box); empty[0].focus(); return; }
            Data.orderOutfit(p.role, data.label, data.desc, st.kind, st.draw).then(() => { close(); hooks.notify(p.name, `새 ${k.label} 기대돼요!`); }).catch(fail);
          }, { needsRun: true })));
      return box;
    }, { keep: true });
  }

  // 새 옷 확인: 미리보기(서 있기·만세·걷기·얼굴)를 보고 입혀 보기(승인)·다시 만들기·버리기
  function lookReview(id) {
    open((st) => {
      const t = Data.task(id);
      if (!t) return missing();
      const d = Data.detail(id);
      if (!d) return loadingPop('새 옷');
      if (d.error) return failPop('새 옷', d.error);
      const prop = d.proposal || {};
      const pv = prop.preview || {};
      const p = Data.owner(t);
      const pending = t.status === 'awaiting_approval';
      const what = (LOOK_KINDS[prop.kind || (t.extra || {}).look_kind] || LOOK_KINDS.outfit).label;
      const shot = (name, cls, caption) => h('figure', { class: `wd-shot ${cls}` },
        name ? h('img', { src: Data.lookPreview(id, name), alt: caption, draggable: 'false' }) : null,
        h('figcaption', { text: caption }));
      return h('div', { class: 'pop wd paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': `새 ${what} · ${prop.label || t.title}` },
        closeBtn(),
        h('div', { class: 'skr-head' }, face(p.id, 'happy', 'skr-face'),
          h('div', {}, h('p', { class: 'skr-kicker', text: `${p.name}의 새 ${what}` }), h('h2', { text: prop.label || t.title }))),
        h('p', { class: 'skd-when', text: `주문: ${t.brief}` }),
        fakeNote(),
        pv.step ? h('div', { class: 'wd-shots' },
          shot(pv.step, 'one', '서 있기'), shot(pv.celebrate, 'one', '만세'), shot(pv.walk, 'walk', '걷기'), shot(pv.face, 'faces', '얼굴'))
          : h('p', { text: '미리보기가 아직 없어요.' }),
        pending ? h('div', { class: 'row-btns' },
          btn('버리기', 'danger', () => dialog(`새 ${what}을(를) 버릴까요?`, `${prop.label || t.title}
그림은 꾸미기에 넣지 않아요.`, [
            { label: '아니요' },
            { label: '버리기', kind: 'danger', run: () => Data.act(id, 'cancel').then(() => close()).catch(fail) },
          ])),
          btn('다시 만들기', 'paper-btn', () => memo('다시 만들기', `${p.name}의 ${what}을(를) 어떻게 바꿀까요?`, '보내기',
            (note) => Data.act(id, 'request-changes', { note }).then(() => { close(); hooks.notify(p.name, '다시 그려 올게요!'); }).catch(fail)),
          { needsRun: true }),
          btn('입혀 보기', 'primary', (e) => {
            if (!begin(st)) return;
            const paper = e.currentTarget.closest('.wd');
            Sfx.play('cheer');
            Fx.sparkle(paper, paper.offsetWidth / 2, 110, { count: 16, spread: 170 });
            Data.act(id, 'approve', { wear: true }).then(() => pause(700)).then(() => {
              closeOwn(st);
              end(st);
              hooks.notify(p.name, `'${prop.label}' 어때요? 잘 어울려요?`);
            }).catch((err) => { end(st, true); fail(err); });
          }, { needsRun: true }))
          : h('p', { class: 'skd-meta', text: `${Data.STATUS_LABELS[t.status]} 상태예요.` }));
    });
  }

  // ---------------------------------------------------------------- 캐릭터 제조실 (새 직원)
  // CEO가 이름·맡을 일·겉모습을 정하면 Codex가 그림 3장을 그린다 (같은 일을 하는 기본 직원 그림이 틀).
  // 채용하면 회사에 들어와 같은 일을 하는 직원과 일을 나눠 받고, 빈 책상(1층 앞자리부터, 층을 늘리면 위층)에 앉는다.
  // 뽑을 수 있는 수는 책상 수로 정해진다 (studio/floors.py capacity). 책상이 모자라면 층 늘리기를 권한다.
  const JOB_NAMES = { producer: '기획', builder: '개발', reviewer: '리뷰', analyst: '리서치' };

  function hireCard() {
    const s = Data.get();
    const max = s.floors.staff_max;
    const made = Data.TEAM.filter((m) => m.job !== m.role).length;
    const waiting = s.tasks.filter((t) => t.kind === 'hire' && !['done', 'cancelled'].includes(t.status));
    if (made + waiting.length >= max) {
      if (waiting.length) {
        return h('button', { type: 'button', class: 'tm-card new', onclick: () => openTask(waiting[0]) },
          h('span', { class: 'tm-plus', text: '…' }), h('b', { text: '새 직원 만드는 중' }), h('span', { text: `책상 ${max}자리` }));
      }
      if (s.floors.count < s.floors.max) {
        return h('button', { type: 'button', class: 'tm-card new', onclick: () => addFloor() },
          h('span', { class: 'tm-plus', text: '+' }), h('b', { text: '빈 책상이 없어요' }), h('span', { text: `${s.floors.count + 1}층 열기` }));
      }
      return null;
    }
    return h('button', { type: 'button', class: 'tm-card new', onclick: () => hireForm() },
      h('span', { class: 'tm-plus', text: '+' }), h('b', { text: '새 직원 만들기' }),
      h('span', { text: waiting.length ? `만드는 중 ${waiting.length}명` : `빈 책상 ${max - made}자리` }));
  }

  // 층 늘리기 (studio/floors.py): 책상과 휴식터가 있는 층이 하나 생긴다. 열면 그 층을 보여 준다.
  function addFloor() {
    const f = Data.get().floors;
    const n = f.count + 1;
    dialog(`${n}층을 열까요?`, `책상 ${f.next_desks}개와 휴식터가 생겨요. 새 직원을 ${f.next_desks}명 더 뽑을 수 있어요.`, [
      { label: '아니요' },
      { label: `${n}층 열기`, kind: 'primary', needsRun: true, run: () => Data.addFloor()
        .then(() => Data.refresh())
        .then(() => { closeAll(); Scene.showFloor(n); Sfx.play('cheer'); hooks.notify('하나', `${n}층을 열었어요!`); })
        .catch(fail) },
    ]);
  }

  function hireForm() {
    open((st) => {
      if (!st.job) st.job = 'builder';
      const base = Data.BY_ROLE[st.job] || Data.TEAM[0];
      const name = h('input', { class: 'title-input', type: 'text', maxlength: '8', placeholder: '예: 미나', 'aria-label': '이름', autofocus: true });
      const looks = h('textarea', { class: 'memo-input', maxlength: '200', 'aria-label': '겉모습',
        placeholder: '예: 짧은 분홍 머리, 동그란 눈, 초록 후드티와 청바지' });
      const memo = h('input', { class: 'title-input sm', type: 'text', maxlength: '40', placeholder: '한마디 (예: 잘 부탁해요!)', 'aria-label': '한마디' });
      const tags = h('input', { class: 'title-input sm', type: 'text', maxlength: '60', placeholder: '특기 (쉼표로, 예: Godot, 셰이더)', 'aria-label': '특기' });
      if (st.draft) { name.value = st.draft.name; looks.value = st.draft.looks; memo.value = st.draft.memo; tags.value = st.draft.tags; }
      const keep = () => { st.draft = { name: name.value, looks: looks.value, memo: memo.value, tags: tags.value }; };
      const box = h('div', { class: 'pop dialog paper sk-form hr-form', role: 'dialog', 'aria-modal': 'true', 'aria-label': '새 직원 만들기' },
        h('h2', { text: '캐릭터 제조실' }),
        fakeNote(true),
        h('label', { class: 'sk-field' }, h('span', { text: '이름' }), name),
        h('div', { class: 'sk-field' }, h('span', { text: '맡을 일' }),
          h('div', { class: 'hr-jobs', role: 'radiogroup', 'aria-label': '맡을 일' }, Object.entries(JOB_NAMES).map(([job, label]) => {
            const m = Data.BY_ROLE[job];
            return h('button', { type: 'button', class: 'hr-job', role: 'radio', 'aria-checked': String(st.job === job),
              onclick: () => { keep(); st.job = job; draw(); } },
            m ? face(m.id, 'normal') : null, label, h('small', { text: m ? `${m.name} 책상` : '' }));
          }))),
        h('label', { class: 'sk-field' }, h('span', { text: '겉모습' }), looks),
        h('label', { class: 'sk-field' }, h('span', { text: '한마디 · 특기' }), memo, tags),
        drawPick(st),
        h('p', { class: 'sk-note', text: `빈 책상(1층 앞자리부터, 모자라면 층을 늘려요)에 앉고 그 층 휴식터에서 쉬어요. AI가 그림 3장(동작·걷기·얼굴)을 그려요: 3~5분, 에너지 3. 다 되면 결재함에서 보고 채용할지 정해요.` }),
        h('div', { class: 'row-btns' },
          btn('취소', '', () => close()),
          btn('그려 주세요', 'primary', () => {
            const data = { name: name.value.trim(), job: st.job, looks: looks.value.trim(), memo: memo.value.trim(), skills: tags.value, draw: st.draw || 'codex' };
            const empty = [[name, data.name], [looks, data.looks]].find(([, v]) => !v);
            if (empty) { shake(box); empty[0].focus(); return; }
            const who = (Data.BY_ROLE.producer || Data.TEAM[0]).name;
            Data.hire(data).then(() => { close(); hooks.notify(who, `${data.name}${subj(data.name)} 어떤 모습일지 그려 올게요!`); }).catch(fail);
          }, { needsRun: true })));
      return box;
    }, { keep: true });
  }

  function hireReview(id) {
    open((st) => {
      const t = Data.task(id);
      if (!t) return missing();
      const d = Data.detail(id);
      if (!d) return loadingPop('새 직원');
      if (d.error) return failPop('새 직원', d.error);
      const ex = t.extra || {};
      const pv = (d.proposal || {}).preview || {};
      const pending = t.status === 'awaiting_approval';
      const shot = (file, cls, caption) => h('figure', { class: `wd-shot ${cls}` },
        file ? h('img', { src: Data.lookPreview(id, file), alt: caption, draggable: 'false' }) : null,
        h('figcaption', { text: caption }));
      const job = JOB_NAMES[ex.job] || '';
      // 같은 일을 하는 직원이 배운 스킬을 신입도 배울지 (기본 배운다, 서버 Engine._inherit_skills)
      const mates = Data.get().skills.filter((sk) => sk.learned_by.some((r) => (Data.BY_ROLE[r] || {}).job === ex.job));
      if (st.inherit === undefined) st.inherit = true;
      const inheritRow = pending && mates.length ? h('label', { class: 'hr-inherit' },
        h('input', { type: 'checkbox', checked: st.inherit, 'aria-label': `스킬 ${mates.length}개 물려받기`,
          onchange: (e) => { st.inherit = e.currentTarget.checked; } }),
        h('span', {}, h('b', { text: `같은 일을 하는 직원이 배운 스킬 ${mates.length}개 물려받기` }),
          h('small', { text: mates.map((sk) => sk.title).join(' · ') }))) : null;
      return h('div', { class: 'pop wd paper', role: 'dialog', 'aria-modal': 'true', 'aria-label': `새 직원 · ${ex.name || ''}` },
        closeBtn(),
        h('div', {}, h('p', { class: 'skr-kicker', text: `새 직원 · ${job} 담당` }), h('h2', { text: ex.name || t.title })),
        h('p', { class: 'skd-when', text: `겉모습: ${t.brief}${ex.memo ? ` · "${ex.memo}"` : ''}` }),
        fakeNote(),
        pv.step ? h('div', { class: 'wd-shots' },
          shot(pv.step, 'one', '서 있기'), shot(pv.celebrate, 'one', '만세'), shot(pv.walk, 'walk', '걷기'), shot(pv.face, 'faces', '얼굴'))
          : h('p', { text: '미리보기가 아직 없어요.' }),
        inheritRow,
        pending ? h('div', { class: 'row-btns' },
          btn('버리기', 'danger', () => dialog('이 그림을 버릴까요?', `${ex.name || ''}
채용하지 않아요.`, [
            { label: '아니요' },
            { label: '버리기', kind: 'danger', run: () => Data.act(id, 'cancel').then(() => close()).catch(fail) },
          ])),
          btn('다시 그리기', 'paper-btn', () => memo('다시 그리기', '어떻게 바꿀까요?', '보내기',
            (note) => Data.act(id, 'request-changes', { note }).then(() => { close(); hooks.notify((Data.BY_ROLE.producer || Data.TEAM[0]).name, '다시 그려 올게요!'); }).catch(fail)),
          { needsRun: true }),
          btn('채용하기', 'primary', (e) => {
            if (!begin(st)) return;
            const paper = e.currentTarget.closest('.wd');
            Sfx.play('cheer');
            Fx.sparkle(paper, paper.offsetWidth / 2, 110, { count: 18, spread: 180 });
            Data.act(id, 'approve', { inherit_skills: st.inherit !== false }).then(() => pause(700)).then(() => {
              closeOwn(st);
              end(st);
              const m = Data.TEAM.find((x) => x.name === ex.name);
              hooks.notify(ex.name, '잘 부탁드려요!');
              if (m) Scene.setState(m.id, 'celebrate', { text: '안녕하세요!' });
            }).catch((err) => { end(st, true); fail(err); });
          }, { needsRun: true }))
          : h('p', { class: 'skd-meta', text: `${Data.STATUS_LABELS[t.status]} 상태예요.` }));
    });
  }

  function openTarget(target) {
    if (!target) return;
    if (target.screen === 'mcp') {
      const done = target.task ? Data.task(target.task) : null;
      if (done && Data.get().mcp.some((x) => x.name === done.report)) mcpDetail(done.report);
      else mcpShelf();
      return;
    }
    if (target.screen === 'skills') {
      if (Data.get().skills.some((x) => x.slug === target.skill)) skillDetail(target.skill);
      else skillBoard();
      return;
    }
    const t = target.task ? Data.task(target.task) : null;
    if (!t) return;
    if (target.screen === 'task' || t.status !== 'awaiting_approval') taskCard(t.id);
    else openTask(t);
  }

  // ---------------------------------------------------------------- 시작
  function init(options) {
    hooks = { ...hooks, ...options };
    layer.querySelector('.scrim').addEventListener('click', close);
    Data.on('change', refresh);
  }

  return {
    init, h, open, close, closeAll, isOpen, refresh, dialog, soon, memo, face, icon, addFloor, jobCard, skillGrades,
    chooseProject, questBoard, taskCard, inbox, approval, report, meeting, meetingRoom, diary, team, employee, customize, trophies, alerts, openTask, openTarget,
    skillBoard, skillDetail, skillReview, skillUse, mcpShelf, mcpDetail, schedules, remote, needLogin, aiLoad, wardrobeOrder, lookReview, hireForm, hireReview,
  };
})();
