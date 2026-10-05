/* AI 스튜디오 — 게임 화면 (SPEC 1~4단계)
 *
 * 상단 바, 명령창, 알림 말풍선, 본사 소품(벽 쪽지·완성작 선반), 긴급 정지 화면을 그리고
 * 버튼을 팝업(popups.js)과 장면(scene.js)에 잇는다. 데이터는 data.js(감독 프로그램 API)에서만 읽는다.
 * 직원의 모습(일·휴식·막힘)은 서버가 정하고, 새 알림(결재 올림·합격)은 잠깐 동작으로 보여 준다.
 * CSP 때문에 style 속성과 인라인 이벤트는 쓰지 않는다 (CSSOM, addEventListener만).
 */
'use strict';

const CANVAS_W = 1536;
const CANVAS_H = 1024;
const NOTICE_MS = 5000;

const $ = (sel, root = document) => root.querySelector(sel);
const stage = $('#stage');
const hash = new URLSearchParams(location.hash.slice(1));
const demo = hash.get('demo'); // 개발용: 장면 자세를 고정해 캡처할 때 (서버 상태로 덮지 않는다)
// 사무실(도트 본사) 화면은 쓰지 않는다 (CEO 결정 2026-09-30): 진행판(칸반)만. 개발·캡처용 주소(#view=office, #floor, 진행판이 아닌 #demo)일 때만 다시 켠다.
const BOARD_DEMOS = ['boardflip', 'rig'];
const OFFICE = hash.get('view') === 'office' || Boolean(hash.get('floor')) || Boolean(demo && !BOARD_DEMOS.includes(demo));
stage.classList.toggle('office-off', !OFFICE);
// #demo=bodies·bodieswork: 기본 4명에게 서로 다른 몸 막대를 입혀 본다 (저장하지 않는다)
const DEMO_BODIES = demo && demo.startsWith('bodies') ? {
  hana: { shoulders: -1, chest: 1, waist: -1, hips: 1, height: -1 }, // 여성형 + 키 작게
  sol: { shoulders: 1, hips: -1, build: 1 },                          // 남성형 + 체격 듬직하게
  clo: { shoulders: -1, chest: 1, waist: -1, hips: 1, head: 1 },      // 여성형 + 머리 크게
  luna: { height: 2 },                                                // 중간 + 키 아주 크게
} : null;

// ---------------------------------------------------------------- 캔버스 확대
function fit() {
  const scale = Math.min(window.innerWidth / CANVAS_W, window.innerHeight / CANVAS_H);
  stage.style.setProperty('--s', String(scale));
}

// ---------------------------------------------------------------- 상단 바·명령창·본사 소품 그리기
function clockText(day, now = new Date()) {
  const h = now.getHours();
  const m = String(now.getMinutes()).padStart(2, '0');
  const half = h < 12 ? '오전' : '오후';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${day}일차 · ${half} ${h12}:${m}`;
}

const NOTE_ICON = { build: 'pad', plan: 'doc', research: 'link', skill: 'star', look: 'star', hire: 'team', tool: 'link' };
const NOTE_COLOR = { build: 'yellow', plan: 'pink', research: 'purple', skill: 'green', look: 'pink', hire: 'pink', tool: 'green' };

let loginShownAt = null; // 한도 알림 창을 이미 연 멈춤 (같은 멈춤에는 한 번만)

function render() {
  const s = Data.get();
  $('#hud-company').textContent = s.studio.name;
  $('#hud-clock').textContent = clockText(s.day);

  const { max, runsToday, minutesToday } = s.energy;
  const left = Math.max(0, max - runsToday);
  $('#hud-energy-text').textContent = `에너지 ${left}/${max}`;
  $('#hud-energy-fill').style.setProperty('--energy', `${Math.round((left / max) * 100)}%`);
  $('#energy-tip').textContent = `오늘 실행 ${runsToday}회 · ${minutesToday}분`;

  const waiting = Data.inbox().length;
  const inbox = $('#hud-inbox');
  inbox.textContent = String(waiting);
  inbox.hidden = waiting === 0;
  if (Data.loaded && lastInbox !== null && waiting > lastInbox) Fx.pop(inbox); // 새 결재가 오면 숫자가 튄다
  if (Data.loaded) lastInbox = waiting;
  $('[data-action="inbox"]').setAttribute('aria-label', `결재함, 대기 ${waiting}건`);
  $('#hud-alerts').hidden = Data.unreadAlerts() === 0;

  // 새 버전 알림 (연결이 끊겼을 때는 끊김 알림만)
  $('#restart-note').hidden = !s.studio.restart || !Data.isOnline();
  // 한도·로그인 만료로 멈춤: 위쪽 알림 + 처음 한 번은 로그인 창을 바로 연다
  const need = s.needsLogin;
  $('#login-note').hidden = !need || !Data.isOnline();
  if (need) {
    const name = need.runtime === 'claude' ? 'Claude' : 'Codex';
    $('#login-note-text').textContent = `${name} ${need.reason === 'quota' ? '사용 한도가 다 됐어요' : '로그인이 필요해요'} · 눌러서 다른 아이디로 로그인`;
    if (Data.loaded && need.at !== loginShownAt) { loginShownAt = need.at; Popups.needLogin(); }
  }

  renderMotion();
  renderSound();
  if (OFFICE) {
    renderFloors();
    renderWallClock();
  }

  const stop = $('.stop-btn');
  stop.setAttribute('aria-pressed', String(s.stopped));
  stop.setAttribute('aria-label', s.stopped ? '긴급 정지 중 · 누르면 재개' : '긴급 정지');
  $('#layer-alarm').hidden = !s.stopped;
  $('#alarm-reason').textContent = s.stopReason && s.stopReason !== 'CEO 긴급 정지' ? s.stopReason : '';

  const command = $('#command');
  const input = $('#command-input');
  command.classList.toggle('locked', s.stopped);
  input.disabled = s.stopped;
  input.placeholder = s.stopped ? '정지 중이에요' : '무엇을 시킬까요?';
  const project = Data.currentProject();
  const chip = $('#project-chip');
  chip.textContent = project ? `대상: ${project.title}` : '프로젝트 없음';
  chip.hidden = !s.projects.length;
  chip.title = project ? `작업 대상: ${project.title} · 눌러서 선택` : '프로젝트 없음';
  chip.setAttribute('aria-label', `지시할 프로젝트: ${project ? project.title : '없음'} (누르면 바꾸기)`);

  // 벽 쪽지·선반은 팝업이 모두 닫혔을 때만 바꾼다 (새로 생긴 것이 떨어지는 모습을 CEO가 보도록).
  // 팝업이 닫히면 Popups가 onClose로 render()를 다시 부른다.
  if (OFFICE && !Popups.isOpen()) {
    // 벽의 퀘스트 보드: 대기·진행 중·결재 대기 작업 수만큼 쪽지 (최대 4장, SPEC 6.1)
    const open = Data.columns().slice(0, 3).flatMap((c) => c.tasks).slice(0, 4);
    const notes = renderItems('wall', $('#wall-notes'), open, (t) => `${t.id}:${t.kind}`, (t) => {
      const n = document.createElement('span');
      n.className = `wall-note ${NOTE_COLOR[t.kind] || 'yellow'}`;
      n.append(Popups.icon(NOTE_ICON[t.kind] || 'doc'));
      return n;
    });
    if (notes.length) {
      Sfx.play('drop');
      Fx.sparkle($('#layer-bg'), 902, 200, { count: 14, spread: 120 });
    }
    // 스킬 학습 게시판: 배운 스킬 수만큼 초록 쪽지 (최대 6장, 새 스킬은 떨어진다)
    const learned = renderItems('skills', $('#skill-notes'), s.skills.slice(-6), (sk) => sk.slug, () => {
      const n = document.createElement('span');
      n.className = 'skill-note';
      n.append(Popups.icon('star'));
      return n;
    });
    if (learned.length) Fx.sparkle($('#layer-bg'), 190, 440, { count: 12, spread: 90 });
    // 완성작 선반: 완성작 수만큼 트로피·액자, 나머지는 배경의 점선 칸
    const items = renderItems('shelf', $('#shelf-items'), s.trophies.slice(0, 5), (item) => `${item.task}:${item.kind}`, (item) => {
      const n = document.createElement('span');
      n.className = 'shelf-item';
      n.append(Popups.icon(item.kind === 'game' ? 'trophy' : 'frame'));
      return n;
    });
    for (const i of items) Fx.sparkle($('#layer-bg'), SHELF_X[i], 512, { count: 12, spread: 80 });
  }

  if (OFFICE) Scene.setStopped(s.stopped);
}

// 효과 스위치 (상단 바의 별): 켜짐 = 도장·책장·카드·반짝임이 움직인다 (effects.js)
function renderMotion() {
  const on = !Fx.reduced();
  const btn = $('.fx-btn');
  btn.setAttribute('aria-pressed', String(on));
  btn.setAttribute('aria-label', on ? '효과 켜짐 · 누르면 끄기' : '효과 꺼짐 · 누르면 켜기');
  btn.title = on ? '효과 켜짐' : '효과 꺼짐';
}

// 소리 스위치 (상단 바의 스피커): 기본 꺼짐 (sound.js)
function renderSound() {
  const on = Sfx.enabled();
  const btn = $('.snd-btn');
  btn.setAttribute('aria-pressed', String(on));
  btn.setAttribute('aria-label', on ? '소리 켜짐 · 누르면 끄기' : '소리 꺼짐 · 누르면 켜기');
  btn.title = on ? '소리 켜짐' : '소리 꺼짐';
}

// 벽 쪽지·선반 물건: 목록이 그대로면 건드리지 않는다 (도는 애니메이션이 끊기지 않게).
// 새로 생긴 것에만 .drop을 준다. 처음 그릴 때(서버를 읽기 전후)는 떨어뜨리지 않는다. 새 것의 자리 번호를 돌려준다.
let lastInbox = null;
const drawn = {};
const SHELF_X = [1100, 1183, 1265, 1354, 1435]; // 완성작 선반 칸 가운데 (popups.css .shelf-items)

function renderItems(which, box, list, keyOf, make) {
  const keys = list.map(keyOf);
  const prev = drawn[which];
  if (prev && prev.join('|') === keys.join('|')) return [];
  const fresh = [];
  box.replaceChildren(...list.map((item, i) => {
    const n = make(item);
    if (prev && !prev.includes(keys[i])) {
      n.classList.add('drop');
      n.style.setProperty('--delay', `${fresh.length * 140}ms`);
      n.addEventListener('animationend', () => n.classList.remove('drop'), { once: true });
      fresh.push(i);
    }
    return n;
  }));
  if (Data.loaded) drawn[which] = keys;
  return fresh;
}

// ---------------------------------------------------------------- 직원 모습 (서버 상태 → 장면)
const applied = {};
let facesKey = '';
let facesSeq = 0;

let spriteVersion = null; // 그림 목록(index.json) 버전: 바뀌면 새 옷이 설치된 것

function applyTeam() {
  const opts = Data.get().lookOptions || {};
  Looks.setOptions(opts);
  if (opts.version && spriteVersion && opts.version !== spriteVersion) Scene.reloadStrips().then(() => applyTeam());
  if (opts.version) spriteVersion = opts.version;
  // 새 직원: 서버가 준 책상(층)에 앉히고, 앞으로 만들 얼굴 그림의 열 구성을 직원 수에 맞춘다.
  // 화면에 걸린 그림은 그대로라(합친 그림이 준비되기 전에는 기본 4열) 새 직원 얼굴은 준비될 때까지 비워 둔다 (Looks.syncFaces)
  for (const p of Data.TEAM) if (!Scene.people[p.id]) Scene.addPerson(p.id, { job: p.job, desk: p.desk, name: p.name, title: p.title });
  // 내보낸 직원은 장면에서 빼고(연습용 #demo 직원은 두고), 명부가 당겨져 책상이 바뀐 직원은 새 책상으로 옮긴다
  if (Data.loaded) {
    const ids = new Set(Data.TEAM.map((p) => p.id));
    for (const [id, def] of Object.entries(Scene.people)) if (def.guest && !ids.has(id) && !id.startsWith('demo')) Scene.removePerson(id);
    for (const p of Data.TEAM) Scene.moveDesk(p.id, p.desk);
  }
  Looks.setFaceCols(Data.TEAM.map((p) => p.id));
  Looks.syncFaces(Data.TEAM.map((p) => p.id));
  const looks = {};
  for (const p of Data.TEAM) {
    Scene.setPerson(p.id, { name: p.name, title: p.title });
    Scene.setLook(p.id, DEMO_BODIES && DEMO_BODIES[p.id] ? { ...p.look, ...DEMO_BODIES[p.id] } : p.look);
    looks[p.id] = p.look;
    if (demo) continue;
    const key = `${p.state}|${p.phase || ''}`;
    if (applied[p.id] !== key) {
      Scene.setState(p.id, p.state || 'rest', { text: p.phase, instant: applied[p.id] === undefined });
      applied[p.id] = key;
    }
  }
  // 얼굴: 꾸미기가 바뀌었을 때만 다시 칠한다
  const key = JSON.stringify(looks);
  if (key !== facesKey) {
    facesKey = key;
    const seq = ++facesSeq; // 늦게 끝난 옛 아틀라스가 새 것을 덮지 않게 (옛 blob 주소는 이미 정리됐을 수도 있다)
    Looks.portraits(looks, true).then((res) => {
      if (seq !== facesSeq) return;
      if (!res) { facesKey = ''; return; } // 그림을 못 불렀다: 다음에 다시 만든다
      // 합친 그림이 걸리는 순간 그림·열 수(--face-cols)·모든 얼굴의 위치(--fx 규칙)가 한꺼번에 바뀐다
      if (res.url) stage.style.setProperty('--portraits', `url("${res.url}")`);
      else stage.style.removeProperty('--portraits');
      stage.style.setProperty('--face-cols', String(res.ids.length));
      Looks.commitFaces(res.ids);
    });
  }
}

// ---------------------------------------------------------------- 층 (studio/floors.py, scene.js showFloor)
// 왼쪽 엘리베이터 판: 위층이 위. 연 층만 버튼이 있고, 결재를 기다리거나 막힌 직원이 있는 층에는 빨간 점. 맨 위 +는 층 늘리기.
let floorsKey = '';

function renderFloors() {
  const f = Data.get().floors;
  const needs = new Set();
  for (const p of Data.TEAM) if (p.state === 'blocked') needs.add(p.floor);
  for (const t of Data.inbox()) { const o = Data.owner(t); if (o) needs.add(o.floor || 1); }
  const key = `${f.count}|${f.max}|${Scene.floor}|${[...needs].sort().join(',')}`;
  if (key === floorsKey) return;
  floorsKey = key;
  const nav = $('#floors');
  const buttons = [];
  if (f.count < f.max) {
    const add = document.createElement('button');
    add.type = 'button';
    add.className = 'floor-btn add';
    add.textContent = '+';
    add.title = '층 늘리기';
    add.setAttribute('aria-label', `층 늘리기 (${f.count + 1}층, 책상 ${f.next_desks}개)`);
    add.addEventListener('click', () => Popups.addFloor());
    buttons.push(add);
  }
  for (let n = f.count; n >= 1; n--) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'floor-btn';
    b.textContent = `${n}층`;
    b.setAttribute('aria-pressed', String(Scene.floor === n));
    b.setAttribute('aria-label', `${n}층${n === 1 ? ' 본사' : ''}${needs.has(n) ? ' · 도움이 필요한 직원 있음' : ''}`);
    if (needs.has(n)) b.append(Object.assign(document.createElement('span'), { className: 'dot' }));
    b.addEventListener('click', () => Scene.showFloor(n));
    buttons.push(b);
  }
  nav.replaceChildren(...buttons);
  nav.hidden = f.max <= 1;
}

// 층이 바뀌면: 본사 전용 표시(hq) 숨기기, 휴식터 간판 옮기기, 층 버튼 다시 그리기
function onFloorChanged(n, f) {
  stage.dataset.floor = String(n);
  const sign = $('#lounge-sign');
  sign.textContent = n === 1 ? '휴식터' : `${f.name} 휴식터`;
  if (f.lounge) {
    sign.style.left = `${f.lounge[0]}px`;
    sign.style.top = `${f.lounge[1]}px`;
  }
  floorsKey = '';
  renderFloors();
}

// 본사 벽시계 바늘 (지금 시각)
function renderWallClock(now = new Date()) {
  const m = now.getMinutes();
  const h = (now.getHours() % 12) + m / 60;
  $('#wall-clock .hour').style.setProperty('--a', `${h * 30}deg`);
  $('#wall-clock .minute').style.setProperty('--a', `${m * 6}deg`);
}

// ---------------------------------------------------------------- 알림 말풍선
let noticeTimer = 0;
let noticeTarget = null;

function notify(name, text, target = null) {
  const person = Data.TEAM.find((p) => p.name === name) || Data.TEAM[0];
  const el = $('#notice');
  $('#notice-face').className = `face ${person.id} ${target ? 'normal' : 'happy'}`;
  $('#notice-text').textContent = `${name}: ${text}`;
  noticeTarget = target;
  el.classList.remove('hidden');
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => el.classList.add('hidden'), NOTICE_MS);
}

function fail(err) { notify((Data.BY_ROLE.producer || Data.TEAM[0]).name, err.message || String(err)); }

// ---------------------------------------------------------------- 사무실 ↔ 진행판
// 진행판(board.js)은 사무실과 같은 데이터를 칸반으로 본다. 마지막으로 본 화면은 이 브라우저에만 기억한다.
function setView(name, remember = true) {
  const workbench = name === 'workbench';
  Workbench.setVisible(workbench);
  stage.hidden = workbench;
  const board = !OFFICE || name === 'board'; // 사무실을 안 쓰면 언제나 진행판
  stage.classList.toggle('view-board', board);
  Board.setVisible(board && !workbench);
  if (!remember) return;
  try { localStorage.setItem('studio.view', workbench ? 'workbench' : board ? 'board' : 'office'); } catch (_) { /* 기억 못 해도 된다 */ }
}

// 처음 화면: 주소의 #view=… → 개발용 주소(#demo·#open·#floor)면 사무실 → 이 브라우저가 기억한 것. 주소로 연 화면은 기억하지 않는다 (캡처가 서로 섞이지 않게).
function savedView() {
  if (hash.get('view') === 'workbench') return 'workbench';
  if (!OFFICE) return 'board';
  if (hash.get('view')) return hash.get('view');
  if (demo || hash.get('open') || hash.get('floor')) return 'office';
  try { return localStorage.getItem('studio.view') || 'office'; } catch (_) { return 'office'; }
}

// ---------------------------------------------------------------- 동작
function setStopped(value) {
  const producer = (Data.BY_ROLE.producer || Data.TEAM[0]).name;
  // 소리(경광등)는 곧 올 알림(company.stopped)에서 한 번만 낸다
  Data.setStopped(value).then(() => notify(producer, value ? '모두 멈췄어요' : '다시 일할게요!')).catch(fail);
}

const ACTIONS = {
  energy() {
    const tip = $('#energy-tip');
    tip.hidden = !tip.hidden;
  },
  inbox: () => Popups.inbox(),
  alerts: () => Popups.alerts(),
  motion(el) {
    const on = Fx.reduced(); // 지금 꺼져 있으면 켠다
    Fx.setMotion(on);
    renderMotion();
    if (on) Fx.pop(el);
    notify((Data.BY_ROLE.producer || Data.TEAM[0]).name, on ? '효과를 켰어요!' : '효과를 껐어요');
  },
  sound(el) {
    Sfx.set(!Sfx.enabled()); // 켜는 순간 버튼을 누른 것이라 브라우저가 소리를 허락한다
    renderSound();
    if (Sfx.enabled()) Fx.pop(el);
    notify((Data.BY_ROLE.producer || Data.TEAM[0]).name, Sfx.enabled() ? '소리를 켰어요!' : '소리를 껐어요');
  },
  stop() {
    if (Data.get().stopped) {
      Popups.dialog('다시 시작할까요?', '멈췄던 직원들이 일을 이어서 해요.', [
        { label: '취소' },
        { label: '재개', kind: 'primary', run: () => setStopped(false) },
      ]);
    } else {
      Popups.dialog('긴급 정지할까요?', '일하던 직원을 모두 멈추고, 새 일을 시작하지 않아요.', [
        { label: '취소' },
        { label: '정지', kind: 'danger', run: () => setStopped(true) },
      ]);
    }
  },
  resume: () => setStopped(false),
  notice(el) {
    el.classList.add('hidden');
    if (noticeTarget) Popups.openTarget(noticeTarget);
  },
  project: () => Popups.chooseProject(),
  quests: () => Popups.questBoard(),
  board: () => setView('board'),
  workbench: () => setView('workbench'),
  office: () => { if (OFFICE) setView('office'); },
  team: () => Popups.team(),
  diary: () => Popups.diary(),
  meeting: () => Popups.meetingRoom(),
  trophies: () => Popups.trophies(),
  skills: () => Popups.skillBoard(),
  mcp: () => Popups.mcpShelf(),
  schedules: () => Popups.schedules(),
  remote: () => Popups.remote(),
  login: () => Popups.needLogin(),
};

stage.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) {
    $('#energy-tip').hidden = true;
    return;
  }
  const fn = ACTIONS[el.dataset.action];
  if (fn) fn(el);
  if (el.dataset.action !== 'energy') $('#energy-tip').hidden = true;
});

$('#command').addEventListener('submit', (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const input = $('#command-input');
  const text = input.value.trim();
  if (Data.get().stopped || !text) {
    form.classList.remove('shake');
    void form.offsetWidth; // 애니메이션 다시 시작
    form.classList.add('shake');
    if (!Data.get().stopped) input.focus();
    return;
  }
  const producer = (Data.BY_ROLE.producer || Data.TEAM[0]).name;
  Data.directive(text).then(() => {
    input.value = '';
    notify(producer, '알겠어요! 회의실에서 나눠 볼게요');
  }).catch(fail);
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (Popups.isOpen()) Popups.close();
    $('#energy-tip').hidden = true;
  }
  if (e.key === 'F2') {
    e.preventDefault();
    const on = stage.classList.toggle('debug');
    const panel = $('#devpanel');
    if (on && OFFICE && !panel.childElementCount) Scene.buildDevPanel(panel);
    panel.hidden = !on;
  }
});

window.addEventListener('resize', fit);

// ---------------------------------------------------------------- 데이터 → 화면
Data.on('change', () => {
  render();
  applyTeam();
  Board.update(Data.get());
});

// 새 알림: 잠깐 동작(결재 올림·합격 도장·완료 반짝임)과 알림 말풍선
const EVENT_SOUND = { 'task.blocked': 'oops', 'company.stopped': 'alarm', 'skill.learned': 'cheer' };

Data.on('event', (ev) => {
  let sound = EVENT_SOUND[ev.type] || 'notify';
  if (OFFICE && !demo && ev.who) {
    if (ev.type === 'task.status' && ev.status === 'awaiting_approval') {
      Scene.setState(ev.who, 'call');
      sound = 'call';
    }
    if (ev.type === 'qa.finished' && ev.status === 'pass') {
      Scene.setState(ev.who, 'celebrate', { stamp: '합격', text: '합격!' });
      sound = 'cheer';
    }
    if (ev.type === 'task.status' && ev.status === 'done') {
      const t = ev.target ? Data.task(ev.target.task) : null;
      const plan = t ? t.kind === 'plan' : ev.role === 'producer';
      Scene.setState(ev.who, 'celebrate', { text: plan ? '고마워요!' : '완료!' });
    }
    if (ev.type === 'skill.learned') Scene.setState(ev.who, 'celebrate', { text: ev.text.includes('고쳤어요') ? '고쳤어요!' : '배웠어요!' });
  }
  Sfx.play(sound);
  notify(ev.name, ev.text, ev.target);
});

Data.on('connection', (ok) => {
  $('#offline').hidden = ok; // 끊긴 동안은 위쪽 가운데에 계속 보인다
  $('#restart-note').hidden = !ok || !Data.get().studio.restart;
  notify((Data.BY_ROLE.producer || Data.TEAM[0]).name, ok ? '다시 연결됐어요' : '감독 프로그램과 연결이 끊겼어요');
});

// 팝업을 열면 알림 말풍선은 접는다 (팝업의 닫기 버튼을 가리지 않게).
// 팝업이 모두 닫히면 본사를 다시 그린다 (그사이 생긴 벽 쪽지·완성작이 이때 떨어진다).
Popups.init({ notify, onOpen: () => $('#notice').classList.add('hidden'), onClose: render });
Board.init($('#layer-board'), { notify, fail, office: OFFICE });
Workbench.init($('#workbench-screen'), {
  back: () => setView('board'),
  task: (id) => { setView('board'); const t = Data.task(id); if (t) Popups.openTask(t); else Popups.taskCard(id); },
  inbox: () => { setView('board'); Popups.inbox(); },
  diary: () => { setView('board'); Popups.diary(); },
});
document.addEventListener('studio:planner-review', e => { setView('workbench'); Workbench.reviewPlanner(e.detail).catch(error => console.error(error.message)); });
setView(savedView(), false);

// ---------------------------------------------------------------- 시작
fit();
render();
setInterval(render, 20000);

// 개발용 (캡처 비교): #demo=rest (blocked, call, stop, warp, crowd, crowdrest, bodies, bodieswork)는 장면 자세 고정 (warp = 소환 중간 모습, crowd = 2층에 연습용 직원, bodies = 몸 막대 비교),
// #floor=2는 그 층으로 시작한다. #task=T0007은 그 작업의 결재 창으로. #view=board는 진행판으로 시작, #demo=boardflip은 진행판 보드를 뒤집은 채로 멈춘다.
// #demo=rig(진행판 인형 뼈대 맞추기)·#pose=…(멈춘 자세)는 board.js. #open=quests (inbox, diary, team, sheet, trophies, alerts, meeting, customize, skills, jobcard, grades)는 그 팝업으로 시작한다.
// 직원을 누르면 상태창. 막혀 있으면 막힌 일 카드(이유·재시도·취소)를 바로 연다 — 무엇을 해 줘야 하는지 바로 보이게.
function openPerson(id) {
  const p = Data.BY_ID[id];
  if (p && p.state === 'blocked' && p.task && Data.task(p.task)) Popups.taskCard(p.task);
  else Popups.employee(id);
}

Scene.init($('#layer-sprites'), openPerson, { background: $('#layer-bg .bg'), floorChanged: onFloorChanged, headless: !OFFICE }).then(() => {
  const startFloor = Number(hash.get('floor'));
  if (startFloor > 1) Scene.showFloor(startFloor);
  if (demo) {
    const first = ['rest', 'blocked'].includes(demo) ? demo : 'work';
    for (const id of Object.keys(Scene.people)) Scene.setState(id, first, { instant: true });
    if (demo === 'call') Object.keys(Scene.people).forEach((id) => Scene.setState(id, 'call'));
    // #demo=crowd / crowdrest: 2층 책상 8개에 연습용 직원(기본 직원 그림을 빌림)을 앉힌다 — 2층 자리 확인·캡처용
    // #demo=bodies: 선 자리에서 서 있는 자세로 멈춰 둔다 (몸 막대 비교용, 말풍선 없이)
    if (demo === 'bodies') Object.keys(Scene.people).forEach((id) => Scene.holdPose(id, 'stand', 'step'));
    if (demo.startsWith('crowd')) {
      const TPL = [['sol', 'builder', '개발'], ['luna', 'analyst', '리서치'], ['hana', 'producer', '기획'], ['clo', 'reviewer', '리뷰']];
      for (let i = 0; i < 8; i++) {
        const [sprite, job, title] = TPL[i % 4];
        Scene.addPerson(`demo${i}`, { job, desk: 6 + i, name: `연습${i + 1}`, title, sprite });
        Scene.setState(`demo${i}`, demo === 'crowdrest' ? 'rest' : 'work', { instant: true });
      }
    }
    if (demo === 'warp') {
      Scene.holdWarp('hana', 'rest', 'out', 0.45);
      Scene.holdWarp('sol', 'rest', 'in', 0.35);
      Scene.holdWarp('clo', 'rest', 'in', 0.7);
      Scene.holdWarp('luna', 'rest', 'out', 0.8);
    }
  }
  if (demo === 'boardflip') Board.demoFlip(); // 진행판 보드를 뒤집은 채로 (캡처용)
  // 개발용 (인형 엔진): #demo=rig는 큰 인형 + 영역 색 + 슬라이더 판, #pose=angleZ:1,hairSway:-1은 그 값으로 멈춘 자세 (서버에 아무것도 보내지 않는다)
  if (demo === 'rig') Board.demoRig(hash.get('pose'), hash.get('overlay'));
  else if (hash.get('pose')) Board.demoPose(hash.get('pose'));
  Data.start();
  const OPEN = {
    quests: () => Popups.questBoard(),
    inbox: () => Popups.inbox(),
    diary: () => Popups.diary(),
    team: () => Popups.team(),
    sheet: () => Popups.employee('sol'),
    customize: () => Popups.customize('sol'),
    trophies: () => Popups.trophies(),
    alerts: () => Popups.alerts(),
    meeting: () => Popups.meetingRoom(),
    skills: () => Popups.skillBoard(),
    mcp: () => Popups.mcpShelf(),
    schedules: () => Popups.schedules(),
    remote: () => Popups.remote(),
    jobcard: () => Popups.jobCard('luna'),
    grades: () => Popups.skillGrades(),
    workshop: () => Popups.wardrobeOrder('sol'),
  };
  const opener = OPEN[hash.get('open')];
  if (opener) setTimeout(opener, 400); // 첫 상태를 읽은 뒤
  // #task=T0007: 그 작업의 결재·보고서·회의 창으로 시작 (캡처로 긴 글이 칸에 맞는지 볼 때)
  const openTaskId = hash.get('task');
  if (openTaskId) {
    const tryOpen = (n) => {
      const t = Data.task(openTaskId);
      if (t) Popups.openTask(t);
      else if (n > 0) setTimeout(() => tryOpen(n - 1), 200);
    };
    setTimeout(() => tryOpen(20), 300);
  }
});
