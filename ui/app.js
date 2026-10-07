/* AI 스튜디오 — 화면 (모던 화면: 홈 · 진행판 · 이미지·영상 작업대 · 소설 집필실 · 디자인 작업실)
 *
 * 상단 바, 명령창, 알림 말풍선, 긴급 정지 화면을 그리고 버튼을 팝업(popups.js)과 화면 전환(board.js)에 잇는다.
 * 데이터는 data.js(감독 프로그램 API)에서만 읽는다. 직원 정지 그림(얼굴·꾸미기 미리보기)은 stills.js·looks.js.
 * 옛 도트 사무실(직원이 걷는 본사 화면)은 CEO 결정 2026-10-06으로 완전히 없앴다: 어떤 주소·기억값으로 열어도 나오지 않는다.
 * CSP 때문에 style 속성과 인라인 이벤트는 쓰지 않는다 (CSSOM, addEventListener만).
 */
'use strict';

const CANVAS_W = 1536;
const CANVAS_H = 1024;
const NOTICE_MS = 5000;

const $ = (sel, root = document) => root.querySelector(sel);
const stage = $('#stage');
const hash = new URLSearchParams(location.hash.slice(1));
const demo = hash.get('demo'); // 개발용: #demo=boardflip(진행판 보드를 뒤집은 채로) · #demo=rig(인형 뼈대 맞추기)
const BOARD_DEMOS = ['boardflip', 'rig'];

// ---------------------------------------------------------------- 캔버스 확대
function fit() {
  const scale = Math.min(window.innerWidth / CANVAS_W, window.innerHeight / CANVAS_H);
  stage.style.setProperty('--s', String(scale));
}

// ---------------------------------------------------------------- 상단 바·명령창 그리기
function clockText(day, now = new Date()) {
  const h = now.getHours();
  const m = String(now.getMinutes()).padStart(2, '0');
  const half = h < 12 ? '오전' : '오후';
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${day}일차 · ${half} ${h12}:${m}`;
}

let loginShownAt = null; // 한도 알림 창을 이미 연 멈춤 (같은 멈춤에는 한 번만)
let lastInbox = null;

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

  const stop = $('.stop-btn');
  stop.setAttribute('aria-pressed', String(s.stopped));
  stop.setAttribute('aria-label', s.stopped ? '긴급 정지 중 · 누르면 재개' : '긴급 정지');
  const stopText = stop.querySelector('.stop-text');
  if (stopText) stopText.textContent = s.stopped ? '정지 중 · 재개' : '긴급 정지';
  $('#layer-alarm').hidden = !s.stopped;
  $('#alarm-reason').textContent = s.stopReason && s.stopReason !== 'CEO 긴급 정지' ? s.stopReason : '';

  const command = $('#command');
  const input = $('#command-input');
  command.classList.toggle('locked', s.stopped);
  input.disabled = s.stopped;
  input.placeholder = s.stopped ? '정지 중이에요' : '무엇을 시킬까요?';
  const project = Data.currentProject();
  const chip = $('#project-chip');
  const kindTag = project && (project.kind === 'novel' || project.kind === 'design') ? `${Data.projectKindLabel(project.kind)} · ` : ''; // 소설·디자인 프로젝트는 종류가 앞에 붙는다 (이름이 길어 잘려도 종류는 보이게)
  chip.textContent = project ? `대상: ${kindTag}${project.title}` : '프로젝트 없음';
  chip.hidden = !s.projects.length;
  chip.title = project ? `작업 대상: ${kindTag}${project.title} · 눌러서 선택` : '프로젝트 없음';
  chip.setAttribute('aria-label', `지시할 프로젝트: ${project ? `${kindTag}${project.title}` : '없음'} (누르면 바꾸기)`);
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

// ---------------------------------------------------------------- 직원 얼굴 (서버 상태 → 얼굴 그림)
let facesKey = '';
let facesSeq = 0;

let spriteVersion = null; // 그림 목록(index.json) 버전: 바뀌면 새 옷이 설치된 것

function applyTeam() {
  const opts = Data.get().lookOptions || {};
  Looks.setOptions(opts);
  if (opts.version && spriteVersion && opts.version !== spriteVersion) Stills.reload().then(() => applyTeam());
  if (opts.version) spriteVersion = opts.version;
  // 새 직원: 앞으로 만들 얼굴 그림의 열 구성을 직원 수에 맞춘다.
  // 화면에 걸린 그림은 그대로라(합친 그림이 준비되기 전에는 기본 4열) 새 직원 얼굴은 준비될 때까지 비워 둔다 (Looks.syncFaces)
  Looks.setFaceCols(Data.TEAM.map((p) => p.id));
  Looks.syncFaces(Data.TEAM.map((p) => p.id));
  const looks = {};
  for (const p of Data.TEAM) looks[p.id] = p.look;
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

// ---------------------------------------------------------------- 홈 · 진행판 · 이미지·영상 작업대 · 소설 집필실 · 디자인 작업실 · 노드 편집기
// 홈·진행판·이미지·영상 작업대·소설 집필실·디자인 작업실은 같은 껍데기(board.js) 안의 가운데 구역이고, 같은 Data(/api/state)를 본다. 마지막으로 본 화면은 이 브라우저에만 기억한다.
const SHELL_PAGES = ['home', 'media', 'novel', 'design']; // 진행판 말고 껍데기 안에서 따로 그리는 페이지
function setView(name, remember = true) {
  const workbench = name === 'workbench';
  Workbench.setVisible(workbench);
  stage.hidden = workbench;
  const inShell = SHELL_PAGES.includes(name) ? name : 'board';
  Board.setVisible(!workbench);
  Board.setPage(inShell);
  if (!remember) return;
  try { localStorage.setItem('studio.view', workbench ? 'workbench' : inShell); } catch (_) { /* 기억 못 해도 된다 */ }
}

// 처음 화면: 주소의 #view=… → 개발용 진행판 주소 → 이 브라우저가 기억한 화면 → 홈. 주소로 연 화면은 기억하지 않는다 (캡처가 서로 섞이지 않게).
// 옛 사무실 값(기억된 값이나 옛 주소)은 알 수 없는 화면이라 그냥 홈으로 간다.
const PAGES = ['home', 'board', 'media', 'novel', 'design', 'workbench'];
function savedView() {
  const asked = hash.get('view');
  if (PAGES.includes(asked)) return asked;
  if (hash.get('boarddemo') || BOARD_DEMOS.includes(demo)) return 'board';
  try {
    const mem = localStorage.getItem('studio.view');
    if (PAGES.includes(mem)) return mem;
  } catch (_) { /* 기억 못 해도 된다 */ }
  return 'home';
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
  home: () => setView('home'),
  board: () => setView('board'),
  digest: () => { if (typeof Home !== 'undefined') Home.digest(); },
  media: () => setView('media'),
  novel: () => setView('novel'),
  design: () => setView('design'),
  workbench: () => setView('workbench'), // 옛 노드 편집기 (이미지·영상 작업대의 '노드 편집기 (고급)'로만 열린다)
  team: () => Popups.team(),
  diary: () => Popups.diary(),
  meeting: () => Popups.meetingRoom(),
  trophies: () => Popups.trophies(),
  skills: () => Popups.skillBoard(),
  mcp: () => Popups.mcpShelf(),
  schedules: () => Popups.schedules(),
  gateway: () => { if (typeof Gateway !== 'undefined') Gateway.open(); }, // 외부 연결 (MCP 연결 문, ui/gateway.js)
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
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && String(e.key).toLowerCase() === 'k') {
    e.preventDefault();
    if (typeof Finder !== 'undefined') Finder.focus();
    return;
  }
  if (e.key === 'Escape') {
    if (Popups.isOpen()) Popups.close();
    $('#energy-tip').hidden = true;
  }
});

window.addEventListener('resize', fit);

// ---------------------------------------------------------------- 데이터 → 화면
Data.on('change', () => {
  render();
  applyTeam();
  Board.update(Data.get());
});

// 새 알림: 알림 말풍선과 소리
const EVENT_SOUND = { 'task.blocked': 'oops', 'company.stopped': 'alarm', 'skill.learned': 'cheer' };

Data.on('event', (ev) => {
  Sfx.play(EVENT_SOUND[ev.type] || 'notify');
  notify(ev.name, ev.text, ev.target);
});

Data.on('connection', (ok) => {
  $('#offline').hidden = ok; // 끊긴 동안은 위쪽 가운데에 계속 보인다
  $('#restart-note').hidden = !ok || !Data.get().studio.restart;
  notify((Data.BY_ROLE.producer || Data.TEAM[0]).name, ok ? '다시 연결됐어요' : '감독 프로그램과 연결이 끊겼어요');
});

// 팝업을 열면 알림 말풍선은 접는다 (팝업의 닫기 버튼을 가리지 않게).
Popups.init({ notify, onOpen: () => $('#notice').classList.add('hidden'), goRoom: (mode, key) => Board.openRoom(mode, key) });
Board.init($('#layer-board'), { notify, fail, setView });
// 빠른 찾기 (Ctrl K): 일·직원·스킬·화면. 화면 이동은 ACTIONS(왼쪽 메뉴와 같은 동작)를 그대로 쓴다
if (typeof Finder !== 'undefined') Finder.init({ actions: ACTIONS, setView });
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

// 개발용 (캡처 비교): #view=home|board|media|novel|design|workbench는 그 화면으로 시작, #boarddemo=states|calm|long|empty는 가짜 작업 목록 (board.js),
// #demo=boardflip은 진행판 보드를 뒤집은 채로 멈춘다. #task=T0007은 그 작업의 결재 창으로.
// #demo=rig(진행판 인형 뼈대 맞추기)·#pose=…(멈춘 자세)는 board.js. #open=quests (inbox, diary, team, sheet, trophies, alerts, meeting, customize, skills, jobcard, grades)는 그 팝업으로 시작한다.
// 직원 그림 띠 목록을 읽은 뒤에 시작한다: 직원 상태창·꾸미기·회의실의 정지 그림(Stills.still)이 쓴다.
Stills.init().then(() => {
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
    gateway: () => Gateway.open(),
    remote: () => Popups.remote(),
    jobcard: () => Popups.jobCard('luna'),
    grades: () => Popups.skillGrades(),
    workshop: () => Popups.wardrobeOrder('sol'),
    digest: () => Home.digest(),
    taskcard: () => { const t = Data.get().tasks.find((x) => x.status !== 'cancelled'); if (t) Popups.taskCard(t.id); },
    approval: () => { const all = Data.get().tasks; const t = all.find((x) => x.status === 'awaiting_approval') || all[0]; if (t) Popups.openTask(t); },
    skilldetail: () => { const k = Data.get().skills[0]; if (k) Popups.skillDetail(k.slug); },
    mcpdetail: () => { const m = Data.get().mcp[0]; if (m) Popups.mcpDetail(m.name); },
    hire: () => Popups.hireForm(),
    login: () => Popups.needLogin(),
    finder: () => { // 개발용: 빠른 찾기를 연다 (#open=finder&q=솔 이면 그 글로)
      Finder.focus();
      const box = document.getElementById('board-search');
      if (box && hash.get('q')) { box.value = hash.get('q'); box.dispatchEvent(new Event('input', { bubbles: true })); }
    },
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
