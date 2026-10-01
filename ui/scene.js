/* AI 스튜디오 — 본사 장면 (SPEC 2단계)
 *
 * 배경 그림 위에 직원 스프라이트(캔버스), 켜진 모니터, 이름표, 말풍선을 올린다.
 * 스프라이트는 tools/sprites/make_strips.gd가 만든 가로 띠(<직원>.<동작>.strip.png)를 넘겨서 재생한다.
 * 좌표는 모두 1536×1024 캔버스 기준이다.
 */
'use strict';

const Scene = (() => {
  const BG = '/assets/bg/';

  // 층 (CEO 결정 2026-09-29: 본사 새로 그리기 + 층 늘리기). 좌표는 ui/assets/bg/floors.json 한 곳에 있다:
  // 층마다 배경·크기 배율(scale)·책상(앉는 자리 seat, 서는 자리 stand, 모니터 screen, 이름표 plate, 의자 상자 chair)·휴식 자리(rest).
  // 책상 번호는 1층 앞자리부터 이어진다 (studio/floors.py: 기본 직원 0~3, 새 직원은 명부 순서대로 4~). 휴식 자리는 그 층의 같은 번호.
  // 직원은 등을 보이며 의자에 앉는다. 의자 앞 그림(<배경>.front-<i>.png, tools/sprites/make_fronts.gd)을 몸 위에 한 겹 더 그려
  // 등받이가 허리 아래를 가린다. 자리를 옮길 때는 걷지 않고 '뾰로롱' 소환된다 (CEO 요청 2026-09-29, WARP_*).
  // 한 층만 보인다 (showFloor). 다른 층 직원·소품은 숨긴다 (.away).
  let FLOORS = [];
  let DESKS = [];             // 모든 층의 책상을 이은 목록: { floor, i, desk, rest }

  // 기본 직원 (서버가 이름·직함을 다시 준다). desk는 floors.py FOUNDERS 순서.
  const PEOPLE = {
    hana: { name: '하나', role: '기획', job: 'producer', desk: 0, work: '기획안 쓰는 중…' },
    sol: { name: '솔', role: '개발', job: 'builder', desk: 1, work: '코딩 중' },
    clo: { name: '클로', role: '리뷰', job: 'reviewer', desk: 2, work: '검토 중…' },
    luna: { name: '루나', role: '리서치', job: 'analyst', desk: 3, work: '자료 찾는 중…' },
  };
  const FOUNDER = { producer: 'hana', builder: 'sol', reviewer: 'clo', analyst: 'luna' }; // 새 직원 그림의 틀
  const SCREEN = { producer: 'doc', builder: 'code', reviewer: 'doc', analyst: 'chart' };
  // 뒤에서 본 앉은 그림은 사람마다 다리를 그린 정도가 달라(하나는 허리까지) 밑변을 맞추면 키가 달라 보인다.
  // 틀 직원마다 앉은 그림을 이만큼(1층 배율 기준 px) 올린다.
  const SEAT_LIFT = { hana: 22, sol: 0, clo: 4, luna: 0 };
  const SEATED = new Set(['work', 'frozen']);

  // 소환: 사라지기(빙글 돌며 작아짐) → 새 자리에서 나타나기(빙글 돌며 커짐, 살짝 넘쳤다가 제 크기)
  const WARP_OUT_MS = 420;
  const WARP_IN_MS = 520;
  const WARP_TURNS = 2;       // 사라질 때·나타날 때 각각 도는 바퀴 수
  const WARP_LIFT = 26;       // 사라지며 떠오르는 높이 (나타날 때는 그 높이에서 내려앉는다)
  const HOP = 140;            // 이보다 가까운 자리(의자↔옆에 선 자리)는 소환하지 않고 폴짝 뛰어 옮긴다
  const HOP_MS = 240;
  const HOP_ARC = 22;         // 폴짝 뛸 때 가장 높이 뜨는 px
  const WARP_COLORS = ['#ffd84a', '#ff9ecb', '#9fd8ff', '#ffffff'];

  // 서 있는 자세 (발밑 그림자, 앉기↔서기 눌렀다 펴기). 나머지(work·rest·frozen)는 앉은 자세.
  const STANDING = new Set(['walk', 'call', 'celebrate', 'worried', 'step']);
  const SQUASH_MS = 260;      // 앉기↔서기 눌렀다 펴기 (0.92 → 1.03 → 1배, 발끝 기준)
  const SQUASH_PAD = 0.05;    // 펴질 때·소환 끝에 살짝 커질 때 머리가 잘리지 않게 캔버스 위쪽 여유 (높이 비율)
  const STAMP_MS = 2200;      // 합격 도장이 머리 옆에 남아 있는 시간

  const actors = {};
  const floorNodes = [];      // [층 번호, 요소]: 그 층을 볼 때만 보인다
  let strips = {};
  let layer = null;
  let bgImg = null;
  let view = 1;               // 지금 보는 층
  let stopped = false;
  let quiet = false;          // 처음 놓을 때(instant)는 자세 바꾸기 효과를 건너뛴다
  let onClick = () => {};
  let onFloor = () => {};

  // ---------------------------------------------------------------- 불러오기
  // background: 배경 <img> (층을 바꾸면 그림을 간다), floorChanged(n, 층): 보는 층이 바뀌었을 때
  async function init(container, clickHandler, { background = null, floorChanged = null, headless = false } = {}) {
    layer = container;
    bgImg = background;
    onClick = clickHandler || onClick;
    onFloor = floorChanged || onFloor;
    // 그림 목록은 배포 것과 설치한 것(data/assets)을 합쳐 읽는다 (Looks.loadIndex)
    const [index, floors] = await Promise.all([Looks.loadIndex(), headless ? null : getJson(BG + 'floors.json')]);
    strips = index || {};
    // headless: 사무실은 안 그리고(직원·층·걷기 없음) 직원 그림 띠만 읽는다 — 상태창·꾸미기 미리보기(still)가 쓴다 (CEO 결정 2026-09-30: 진행판만 씀)
    if (headless) {
      await Looks.init(strips);
      return;
    }
    FLOORS = resolveFloors(floors);
    DESKS = FLOORS.flatMap((f) => f.desks.map((desk, i) => ({ floor: f, i, desk, rest: f.rest[i % f.rest.length] })));
    await Looks.init(strips);
    for (const f of FLOORS) buildFloor(f);
    for (const [id, p] of Object.entries(PEOPLE)) {
      if (DESKS[p.desk]) {
        const def = deskDef(DESKS[p.desk], p, id);
        PEOPLE[id] = def;
        actors[id] = makeActor(id, def);
      }
    }
    showFloor(1);
    requestAnimationFrame(frame);
  }

  async function getJson(url) {
    try {
      return await (await fetch(url, { cache: 'no-store' })).json();
    } catch (_) {
      return null;
    }
  }

  // "like": 2 인 층은 2층의 배경·자리를 그대로 쓴다 (3층)
  function resolveFloors(doc) {
    const list = doc && Array.isArray(doc.floors) ? doc.floors : [];
    const byN = {};
    return list.map((f) => {
      const full = f.like && byN[f.like] ? { ...byN[f.like], n: f.n, name: f.name, hq: false } : f;
      byN[f.n] = full;
      return full;
    });
  }

  // 층마다 한 번: 의자 앞 그림, 가림막, 방석, (본사) 고양이
  function buildFloor(f) {
    const stem = f.bg.replace(/\.png$/, '');
    (f.fronts || []).forEach((fr, i) => {
      const n = el('img', 'front');
      n.src = `${BG}${stem}.front-${i}.png`;
      n.alt = '';
      n.draggable = false;
      n.style.zIndex = String(fr.z);
      n.dataset.name = fr.name;
      floorNodes.push([f.n, n]);
    });
    for (const o of f.occluders || []) {
      const n = el('div', 'occluder');
      n.style.setProperty('background-image', `url("${BG}${f.bg}")`);
      n.style.setProperty('clip-path', `polygon(${o.points.map(([x, y]) => `${x}px ${y}px`).join(', ')})`);
      n.style.zIndex = String(o.z);
      n.dataset.name = o.name;
      floorNodes.push([f.n, n]);
    }
    for (const i of f.poufs || []) {
      const [x, y] = f.rest[i];
      const n = el('div', 'pouf');
      place(n, x, y + 9); // 앉은 사람 엉덩이 밑 (발끝보다 조금 아래가 방석 밑변)
      n.style.zIndex = String(y - 10);
      n.style.setProperty('--k', String(f.scale / 0.5));
      floorNodes.push([f.n, n]);
    }
    if (f.hq) floorNodes.push([f.n, cat(1400, 476)]);
  }

  // 완성작 선반 위에서 자는 고양이: 누르면 쓰다듬기 (야옹 소리, 몸을 움찔, 분홍 반짝임)
  function cat(x, y) {
    const n = el('img', 'cat');
    n.src = '/assets/ui/cat.png';
    n.alt = '';
    n.draggable = false;
    place(n, x, y);
    n.style.zIndex = String(y);
    n.setAttribute('role', 'button');
    n.setAttribute('aria-label', '고양이 쓰다듬기');
    n.tabIndex = 0;
    const pet = () => {
      Sfx.play('meow');
      n.classList.remove('pet');
      void n.offsetWidth;
      n.classList.add('pet');
      Fx.sparkle(layer, x, y - 60, { count: 8, spread: 50, colors: ['#ff8fb1', '#ffc2d4', '#ffffff'], shape: 'dot', size: 14 });
    };
    n.addEventListener('click', pet);
    n.addEventListener('keydown', (e) => { if (e.key === 'Enter') pet(); });
    return n;
  }

  // 책상 하나 → 그 자리에 앉는 사람의 자리 정보
  function deskDef(d, p, id) {
    const { floor: f, desk } = d;
    const tpl = FOUNDER[p.job] || id;
    const founder = PEOPLE[tpl];
    return {
      name: p.name, role: p.role, job: p.job, work: p.work || (founder && founder.work) || '일하는 중…', guest: Boolean(p.guest), sprite: id,
      floor: f.n, scale: f.scale, tpl, desk: DESKS.indexOf(d),
      seat: desk.seat, stand: desk.stand, rest: d.rest, plate: desk.plate,
      screen: [...desk.screen, SCREEN[p.job] || 'doc'],
    };
  }

  // 보는 층 바꾸기: 배경 그림을 갈고, 다른 층의 직원·소품을 숨긴다
  function showFloor(n) {
    const f = FLOORS.find((x) => x.n === n);
    if (!f) return;
    view = n;
    if (bgImg) bgImg.src = `${BG}${f.bg}`;
    for (const [fn, node] of floorNodes) node.classList.toggle('away', fn !== n);
    for (const a of Object.values(actors)) awayIf(a);
    onFloor(n, f);
  }

  function awayIf(a) {
    const away = a.def.floor !== view;
    for (const node of [a.canvas, a.shadow, a.bubble, a.mark, a.screen, a.plate, a.stamp]) {
      if (node) node.classList.toggle('away', away);
    }
  }

  function el(tag, cls, parent) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    (parent || layer).appendChild(node);
    return node;
  }

  function place(node, x, y) {
    node.style.left = `${x}px`;
    node.style.top = `${y}px`;
  }

  function makeActor(id, def) {
    const [sx, sy, sw, sh, kind] = def.screen;
    const screen = el('div', `screen ${kind}`);
    place(screen, sx, sy);
    screen.style.width = `${sw}px`;
    screen.style.height = `${sh}px`;
    screen.style.zIndex = String(sy + sh); // 모니터 밑변 기준 (앉은 사람 머리가 모니터 아래쪽을 가린다)

    const plate = el('div', 'plate');
    plate.textContent = `${def.role} · ${def.name}`;
    place(plate, def.plate[0], def.plate[1]);
    plate.style.setProperty('--k', String(def.scale / 0.5));
    plate.style.zIndex = String(def.stand[1] - 1); // 의자 앞 그림보다 앞, 이 책상 옆에 선 직원보다 한 칸 뒤 (선 직원이 이름표를 가린다)

    const shadow = el('div', 'shadow');
    shadow.hidden = true;

    const canvas = el('canvas', 'actor');
    canvas.setAttribute('role', 'button');
    canvas.setAttribute('aria-label', `${def.role} 담당 ${def.name}`);
    canvas.tabIndex = 0;
    canvas.addEventListener('click', () => onClick(id));
    canvas.addEventListener('keydown', (e) => { if (e.key === 'Enter') onClick(id); });

    const bubble = el('div', 'bubble');
    bubble.hidden = true;
    bubble.style.setProperty('--k', String(Math.min(1, def.scale / 0.5)));
    bubble.addEventListener('click', () => onClick(id)); // 막혔을 때만 눌린다 (style.css .bubble.alert)
    const mark = el('div', 'mark');
    mark.textContent = '!';
    mark.hidden = true;

    const a = {
      id, def, screen, plate, canvas, bubble, mark, shadow,
      ctx: canvas.getContext('2d'),
      warp: null, // 소환 중: { phase: 'out' | 'in', t: 지난 ms, to: 갈 자리, then }
      hop: null,  // 폴짝 옮기는 중: { x0, y0, x1, y1, t, then }
      x: def.seat[0], y: def.seat[1], at: 'seat', top: def.seat[1] - 170,
      pose: 'work', since: performance.now(), squash: 0,
      state: 'work', base: 'work', text: def.work, timer: 0,
      look: Looks.norm(null), stamp: null,
    };
    awayIf(a);
    return a;
  }

  // 새 직원 (캐릭터 제조실): 서버가 준 책상 번호(floors.py seats)에 앉는다. 휴식 자리는 그 층의 같은 번호.
  // sprite: 다른 직원 그림을 빌려 쓸 때 (개발용 #demo=crowd)
  function addPerson(id, { job, desk, name, title, sprite = null }) {
    if (actors[id] || !layer || !DESKS[desk]) return;
    const def = { ...deskDef(DESKS[desk], { name, role: title, job, guest: true }, id), sprite: sprite || id };
    PEOPLE[id] = def;
    actors[id] = makeActor(id, def);
    setState(id, 'rest', { instant: true });
  }

  // 내보낸 직원 (퇴사): 반짝임과 함께 사라지고 장면에서 빠진다
  function removePerson(id) {
    const a = actors[id];
    if (!a) return;
    clearTimeout(a.timer);
    if (a.def.floor === view && !Fx.reduced()) {
      Sfx.play('warp');
      poof(a, false);
    }
    for (const node of [a.canvas, a.shadow, a.bubble, a.mark, a.screen, a.plate, a.stamp]) if (node) node.remove();
    delete actors[id];
    delete PEOPLE[id];
  }

  // 책상이 바뀌었다 (앞 직원이 나가 명부가 당겨짐): 모니터·이름표를 새 책상으로 옮기고, 직원은 지금 하던 모습으로 소환된다
  function moveDesk(id, desk) {
    const a = actors[id];
    if (!a || !DESKS[desk] || a.def.desk === desk) return;
    const d = a.def;
    const next = { ...deskDef(DESKS[desk], { name: d.name, role: d.role, job: d.job, guest: d.guest }, id), sprite: d.sprite };
    PEOPLE[id] = next;
    a.def = next;
    const [sx, sy, sw, sh] = next.screen;
    place(a.screen, sx, sy);
    a.screen.style.width = `${sw}px`;
    a.screen.style.height = `${sh}px`;
    a.screen.style.zIndex = String(sy + sh);
    place(a.plate, next.plate[0], next.plate[1]);
    a.plate.style.setProperty('--k', String(next.scale / 0.5));
    a.plate.style.zIndex = String(next.stand[1] - 1);
    a.bubble.style.setProperty('--k', String(Math.min(1, next.scale / 0.5)));
    awayIf(a);
    setState(id, a.base, { text: a.text });
  }

  // 설정에서 온 이름·직함 (이름표와 읽어 주는 글)
  function setPerson(id, { name, title }) {
    const a = actors[id];
    if (!a) return;
    a.plate.textContent = `${title} · ${name}`;
    a.canvas.setAttribute('aria-label', `${title} 담당 ${name}`);
    if (a.def.name !== name) {
      a.def.name = name;
      if (a.state === 'work' && !a.bubble.hidden) say(a, a.text || a.def.work, 'working');
    }
    a.def.role = title;
  }

  // 꾸미기 (모습 세트·머리색·옷 색)
  function setLook(id, look) {
    const a = actors[id];
    if (a) a.look = Looks.norm(look);
  }

  function floorOf(id) { return actors[id] ? actors[id].def.floor : 1; }

  // ---------------------------------------------------------------- 상태
  // work: 책상에서 작업 / rest: 휴식터 / call: 결재 올림(잠깐) / celebrate: 합격·완료(잠깐) / blocked: 막힘
  // instant: 소환 연출 없이 바로 그 자리에 놓는다 (처음 불러올 때).
  // text: work·rest·blocked에서는 작업 중 말풍선 문구, celebrate에서는 그때 한마디 ('합격!', '완료!').
  // stamp: celebrate 때 머리 옆에 찍는 금색 도장 글자 ('합격'). celebrate는 늘 반짝임과 함께.
  // call·celebrate는 잠깐 보여 준 뒤 마지막 기본 상태(work·rest·blocked)로 돌아간다.
  function setState(id, state, { instant = false, text = null, stamp = null } = {}) {
    const a = actors[id];
    if (!a) return;
    clearTimeout(a.timer);
    a.state = state;
    if (['work', 'rest', 'blocked'].includes(state)) a.base = state;
    if (text && state !== 'celebrate') a.text = text;
    quiet = instant;
    if (state === 'work') {
      goTo(a, 'seat', () => show(a, 'work', a.text || a.def.work, 'working'), instant);
    } else if (state === 'rest') {
      show(a, null);
      goTo(a, 'rest', () => pose(a, 'rest'), instant);
    } else if (state === 'call') {
      goTo(a, 'stand', () => {
        show(a, 'call', '결재 부탁드려요!');
        a.timer = setTimeout(() => setState(id, a.base), 2400);
      }, instant);
    } else if (state === 'celebrate') {
      goTo(a, 'stand', () => {
        show(a, 'celebrate', text || '합격!', 'ok');
        cheer(a, stamp);
        a.timer = setTimeout(() => setState(id, a.base), 2400);
      }, instant);
    } else if (state === 'blocked') {
      goTo(a, 'stand', () => show(a, 'worried', '막혔어요 · 눌러 주세요', 'alert'), instant);
    }
    quiet = false;
    refreshScreen(a);
  }

  // 만세와 함께 머리 위 반짝임, stamp가 있으면 머리 옆에 금색 도장 (찍히는 모습은 style.css .pass-stamp)
  function cheer(a, stamp) {
    // 머리 높이는 만세 자세 그림으로 계산한다 (a.top은 다음 프레임에야 새 자세로 바뀐다)
    if (a.def.floor !== view) return; // 다른 층: 보이지 않는다
    const { meta } = Looks.strip(a.def.sprite, 'celebrate', a.look);
    const top = meta ? a.y - meta.anchor.y * a.def.scale : a.top;
    const headY = top + 40;
    Fx.sparkle(layer, a.x, headY, { count: 14, spread: 100, size: 24 });
    if (!stamp) return;
    if (a.stamp) a.stamp.remove();
    const s = el('div', 'pass-stamp');
    s.textContent = stamp;
    place(s, a.x + 78, headY + 30);
    a.stamp = s;
    setTimeout(() => { s.remove(); if (a.stamp === s) a.stamp = null; }, STAMP_MS);
  }

  function show(a, action, text, style) {
    if (action) pose(a, action);
    if (text) say(a, text, style);
    else a.bubble.hidden = true;
  }

  // 앉기↔서기가 바뀌면 그림을 살짝 눌렀다 편다 (draw의 squash). CSS 애니메이션 대신 캔버스에 직접 그린다
  // (캔버스에 transform 애니메이션을 걸면 헤드리스 캡처에서 그림이 사라진다).
  function pose(a, action) {
    if (a.pose !== action) {
      if (!quiet && !Fx.reduced() && STANDING.has(a.pose) !== STANDING.has(action)) a.squash = performance.now();
      a.pose = action;
      a.since = performance.now();
    }
  }

  function squash(a, now) {
    if (!a.squash) return 1;
    const t = (now - a.squash) / SQUASH_MS;
    if (t >= 1 || t < 0) {
      a.squash = 0;
      return 1;
    }
    return t < 0.55 ? 0.92 + 0.11 * (t / 0.55) : 1.03 - 0.03 * ((t - 0.55) / 0.45);
  }

  function say(a, text, style = '') {
    a.bubble.className = `bubble ${style}`.trim();
    a.bubble.replaceChildren();
    if (style === 'ok') el('span', 'check', a.bubble);
    if (style === 'alert') el('span', 'warn', a.bubble).textContent = '!';
    const t = el('span', 'bubble-text', a.bubble);
    if (style === 'working') el('b', 'who', t).textContent = a.def.name;
    t.append(text);
    if (style === 'working') el('span', 'flow', a.bubble).appendChild(document.createElement('i'));
    a.bubble.hidden = false;
  }

  // 켜진 모니터: 책상(의자·옆에 선 자리)에 있고 휴식터로 소환되는 중이 아닐 때
  // 앉아서 일하는 동안에는 이름을 말풍선에 넣고 책상 이름표를 숨긴다 (아랫줄 말풍선이 윗줄 이름표를 덮지 않게)
  function refreshScreen(a) {
    const atDesk = a.at !== 'rest' && !(a.warp && a.warp.to === 'rest');
    a.screen.classList.toggle('on', a.state !== 'rest' && atDesk);
    a.screen.classList.toggle('paused', stopped && atDesk);
    a.plate.classList.toggle('busy', a.state === 'work' && a.at === 'seat' && !a.warp);
  }

  // ---------------------------------------------------------------- 소환
  // 자리를 옮긴다. 멀면 소환(a.warp), 가깝거나 효과가 꺼져 있으면(instant 포함) 바로 그 자리에 놓는다.
  // 소환 도중에 목적지가 바뀌면: 사라지는 중이면 갈 곳만 바꾸고, 나타나는 중이면 그 크기에서 다시 사라진다.
  function goTo(a, where, then, instant = false) {
    const [x, y] = a.def[where];
    const arrive = () => { a.at = where; then(); refreshScreen(a); };
    finishHop(a);
    if (a.warp) {
      if (a.warp.phase === 'in') {
        a.warp.t = WARP_OUT_MS * (1 - Math.min(1, a.warp.t / WARP_IN_MS));
        a.warp.phase = 'out';
      }
      a.warp.to = where;
      a.warp.then = arrive;
      if (instant || Fx.reduced()) finishWarp(a);
      return;
    }
    if (a.at === where && a.x === x && a.y === y) return arrive();
    if (instant || Fx.reduced()) {
      [a.x, a.y] = [x, y];
      return arrive();
    }
    if (Math.hypot(x - a.x, y - a.y) < HOP) {
      // 가까우면 일어서서(눌렀다 펴기) 폴짝 옮긴다
      a.hop = { x0: a.x, y0: a.y, x1: x, y1: y, t: 0, then: arrive };
      a.bubble.hidden = true;
      pose(a, 'step');
      return;
    }
    a.warp = { phase: 'out', t: 0, to: where, then: arrive };
    a.bubble.hidden = true;
    a.pose = 'step'; // 일어선 모습으로 돈다 (앉기↔서기 눌렀다 펴기는 소환과 겹치지 않게 건너뛴다)
    a.squash = 0;
    a.since = performance.now();
    if (a.def.floor === view) Sfx.play('warp');
    poof(a, false);
    refreshScreen(a);
  }

  // 소환 반짝임: 몸 가운데에서 별이 튀고, 발밑에 빛 고리가 퍼진다
  function poof(a, sound) {
    if (a.def.floor !== view) return;
    const mid = Math.round((a.top + a.y) / 2);
    Fx.sparkle(layer, a.x, mid, { count: 12, spread: 80, colors: WARP_COLORS, size: 20, sound });
    const ring = el('div', 'warp-ring');
    place(ring, Math.round(a.x), Math.round(a.y));
    ring.style.zIndex = String(Math.round(a.y) - 2);
    ring.addEventListener('animationend', () => ring.remove());
    setTimeout(() => ring.remove(), 1200); // 효과를 끄면 animationend가 오지 않는다
  }

  function stepWarp(a, dt) {
    const w = a.warp;
    w.t += dt * 1000;
    if (w.phase === 'out' && w.t >= WARP_OUT_MS) {
      [a.x, a.y] = a.def[w.to];
      w.phase = 'in';
      w.t = 0;
      const { meta } = Looks.strip(a.def.sprite, 'step', a.look);
      if (meta) a.top = a.y - meta.anchor.y * a.def.scale;
      poof(a, true);
    } else if (w.phase === 'in' && w.t >= WARP_IN_MS) {
      finishWarp(a);
    }
  }

  function stepHop(a, dt) {
    const hop = a.hop;
    hop.t += dt * 1000;
    const p = Math.min(1, hop.t / HOP_MS);
    a.x = hop.x0 + (hop.x1 - hop.x0) * p;
    a.y = hop.y0 + (hop.y1 - hop.y0) * p;
    if (p >= 1) finishHop(a);
  }

  function finishHop(a) {
    const hop = a.hop;
    if (!hop) return;
    a.hop = null;
    [a.x, a.y] = [hop.x1, hop.y1];
    hop.then();
  }

  function hopLift(a) {
    if (!a.hop) return 0;
    const p = Math.min(1, a.hop.t / HOP_MS);
    return HOP_ARC * 4 * p * (1 - p);
  }

  // 소환을 바로 끝낸다 (도착했을 때, 긴급 정지, 효과를 껐을 때)
  function finishWarp(a) {
    const w = a.warp;
    if (!w) return;
    a.warp = null;
    [a.x, a.y] = a.def[w.to];
    w.then();
  }

  // 소환 중 모습: 가로 크기(음수면 뒤집힘 = 도는 중), 세로 크기, 떠오른 높이
  function warpShape(w) {
    if (!w) return { sx: 1, sy: 1, lift: 0 };
    if (w.phase === 'out') {
      const p = Math.min(1, w.t / WARP_OUT_MS);
      const s = 1 - p * p;                                   // 점점 빨리 작아진다
      const turn = p * p * WARP_TURNS;                         // 점점 빨리 돈다
      return { sx: s * Math.cos(turn * Math.PI * 2), sy: s, lift: WARP_LIFT * p };
    }
    const p = Math.min(1, w.t / WARP_IN_MS);
    const back = 1 + 2.2 * (p - 1) ** 3 + 1.2 * (p - 1) ** 2; // 0 → 1.04쯤 넘쳤다가 → 1
    const turn = (1 - (1 - p) ** 2) * WARP_TURNS;            // 점점 느리게 돈다
    return { sx: back * Math.cos(turn * Math.PI * 2), sy: Math.min(back, 1.04), lift: WARP_LIFT * (1 - p) ** 2 };
  }

  // 긴급 정지: 그 자리에서 멈추고 머리 위에 빨간 "!"를 띄운다. 말풍선은 CSS(.stopped)로 숨긴다.
  // 소환 중이던 직원은 도착한 것으로 친다 (반쯤 사라진 채 멈추지 않게).
  function setStopped(value) {
    stopped = value;
    if (layer) layer.classList.toggle('stopped', value);
    for (const a of Object.values(actors)) {
      if (value) { finishHop(a); finishWarp(a); }
      a.mark.hidden = !value;
      refreshScreen(a);
    }
  }

  // ---------------------------------------------------------------- 그리기
  let last = performance.now();
  function frame(now) {
    const dt = Math.min(0.25, (now - last) / 1000); // 탭이 가려졌다 돌아와도 순간이동하지 않게
    last = now;
    for (const a of Object.values(actors)) {
      if (!stopped && a.warp && !a.warp.hold) stepWarp(a, dt);
      if (!stopped && a.hop) stepHop(a, dt);
      draw(a, now);
    }
    requestAnimationFrame(frame);
  }

  function draw(a, now) {
    if (a.def.floor !== view) return; // 다른 층 사람은 그리지 않는다 (.away로 숨어 있다)
    const action = stopped ? 'frozen' : a.pose;
    const S = a.def.scale;
    let { meta, image } = Looks.strip(a.def.sprite, action, a.look);
    if (!image) ({ meta, image } = Looks.strip(a.def.sprite, 'step', a.look));
    if (!meta || !image) return;
    const w = Math.round(meta.frameWidth * S);
    const h = Math.round(meta.frameHeight * S);
    const pad = Math.ceil(h * SQUASH_PAD);
    if (a.canvas.width !== w || a.canvas.height !== h + pad) {
      a.canvas.width = w;
      a.canvas.height = h + pad;
    }
    const warp = warpShape(a.warp);
    // 앉은 그림은 틀 직원마다 조금 올려 머리 높이를 맞춘다 (SEAT_LIFT)
    const seatLift = SEATED.has(action) ? Math.round(((SEAT_LIFT[a.def.tpl] || 0) * S) / 0.5) : 0;
    const left = Math.round(a.x - meta.anchor.x * S);
    const top = Math.round(a.y - meta.anchor.y * S) - seatLift;
    a.top = top;
    place(a.canvas, left, Math.round(top - pad - warp.lift - hopLift(a)));
    a.canvas.style.zIndex = String(Math.round(a.y));
    // 발밑 그림자: 서 있을 때만 (앉은 자세는 의자·빈백이 받친다). 소환 중에는 몸 크기를 따라 줄었다 커진다.
    const standing = STANDING.has(action);
    if (a.shadow.hidden === standing) a.shadow.hidden = !standing;
    if (standing) {
      place(a.shadow, Math.round(a.x), Math.round(a.y));
      a.shadow.style.zIndex = String(Math.round(a.y) - 1);
      a.shadow.style.setProperty('--w', `${Math.round(((74 * S) / 0.5) * Math.min(1, warp.sy))}px`);
    }
    place(a.bubble, Math.round(a.x), top - 4);
    a.bubble.style.zIndex = '2000';
    place(a.mark, Math.round(a.x), top + 2);
    a.mark.style.zIndex = '2001';

    const n = meta.frames;
    const f = n > 1 && meta.loop && !stopped ? Math.floor(((now - a.since) / 1000) * meta.fps) % n : 0;
    const ctx = a.ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, w, h + pad);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    // 가로: 소환 중이면 가운데를 축으로 돈다 (크기가 음수면 뒤집혀 보인다)
    const { sx } = warp;
    if (sx !== 1) ctx.setTransform(sx, 0, 0, 1, (w * (1 - sx)) / 2, 0);
    const sh = h * squash(a, now) * warp.sy; // 발끝(아래)을 붙인 채 세로로 눌렀다 편다
    if (sh > 0.5) ctx.drawImage(image, f * meta.frameWidth, 0, meta.frameWidth, meta.frameHeight, 0, pad + h - sh, w, sh);
  }

  // 한 동작을 꾸미기대로 그린 정지 그림 (회의실·꾸미기 미리보기). 그림이 아직이면 준비되는 대로 다시 그린다.
  function still(id, action, look, height) {
    const c = document.createElement('canvas');
    c.className = 'sprite-still';
    const paint = () => {
      const { meta, image } = Looks.strip(id, action, look, paint);
      if (!meta || !image) return;
      // 배율은 몸 조절 전 높이로 정한다: 키·머리를 키운 만큼 미리보기도 커 보여야 한다 (meta.grown = 늘어난 높이)
      const s = height / (meta.frameHeight - (meta.grown || 0));
      c.width = Math.round(meta.frameWidth * s);
      c.height = Math.round(meta.frameHeight * s);
      const ctx = c.getContext('2d');
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(image, 0, 0, meta.frameWidth, meta.frameHeight, 0, 0, c.width, c.height);
    };
    paint();
    return c;
  }

  function look(id) { return actors[id] ? actors[id].look : Looks.norm(null); }

  // 캡처용 (#demo=warp): 소환 중간 모습(phase 'out' 사라지는 중 / 'in' 나타나는 중, p = 0~1)을 멈춰 둔다
  // (헤드리스 캡처는 '동작 줄이기'라 goTo를 거치지 않고 직접 만든다. 반짝임은 찍히지 않는다)
  // 캡처용 (#demo=bodies): 그 자리에 그 자세로 멈춰 둔다 (소환·말풍선 없이)
  function holdPose(id, where, action) {
    const a = actors[id];
    if (!a) return;
    clearTimeout(a.timer);
    a.warp = null;
    a.hop = null;
    [a.x, a.y] = a.def[where];
    a.at = where;
    a.bubble.hidden = true;
    a.pose = action;
    a.since = performance.now();
    refreshScreen(a);
  }

  function holdWarp(id, where, phase, p) {
    const a = actors[id];
    if (!a) return;
    if (phase === 'in') [a.x, a.y] = a.def[where];
    a.bubble.hidden = true;
    a.pose = 'step';
    a.warp = { phase, t: p * (phase === 'out' ? WARP_OUT_MS : WARP_IN_MS), to: where, then: () => { a.at = where; refreshScreen(a); }, hold: true };
    refreshScreen(a);
  }

  // 지금 서 있는 곳 (개발용 점검 tools/dev/scene_sim.js)
  function where(id) {
    const a = actors[id];
    return a ? { x: a.x, y: a.y, at: a.at, warping: Boolean(a.warp) } : null;
  }

  // ---------------------------------------------------------------- 개발용 패널 (F2)
  const DEV_STATES = [
    ['work', '작업'], ['rest', '휴식'], ['call', '결재'],
    ['celebrate', '합격', { stamp: '합격', text: '합격!' }], ['celebrate', '완료', { text: '완료!' }], ['blocked', '막힘'],
  ];

  function buildDevPanel(container) {
    container.replaceChildren();
    const title = el('div', 'dev-title', container);
    title.textContent = '개발용 · 직원 상태';
    for (const [id, def] of Object.entries(PEOPLE)) {
      const row = el('div', 'dev-row', container);
      el('span', 'dev-name', row).textContent = def.name;
      for (const [state, label, opts] of DEV_STATES) {
        const b = el('button', 'dev-btn', row);
        b.type = 'button';
        b.textContent = label;
        b.addEventListener('click', () => setState(id, state, opts));
      }
    }
    const all = el('div', 'dev-row', container);
    for (const [state, label] of [['work', '모두 작업'], ['rest', '모두 휴식']]) {
      const b = el('button', 'dev-btn', all);
      b.type = 'button';
      b.textContent = label;
      b.addEventListener('click', () => Object.keys(PEOPLE).forEach((id) => setState(id, state)));
    }
  }

  // 의상실에서 새 옷이 설치되면 그림 목록을 다시 읽는다 (app.js가 look_options.version이 바뀌면 부른다)
  async function reloadStrips() {
    const next = await Looks.loadIndex();
    if (!next) return; // 못 읽었으면 지금 목록을 그대로 둔다
    strips = next;
    await Looks.init(strips);
  }

  return {
    init, reloadStrips, addPerson, setState, setStopped, setPerson, setLook, look, where, holdWarp, holdPose, still, buildDevPanel, removePerson, moveDesk,
    showFloor, floorOf, people: PEOPLE,
    get floor() { return view; },
    get floors() { return FLOORS; },
  };
})();
