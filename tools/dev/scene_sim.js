// 본사 소환 시뮬레이션 (브라우저 없이 Node로 ui/scene.js를 돌린다).
//
//   node tools/dev/scene_sim.js
//
// 직원은 걷지 않고 '뾰로롱' 소환된다 (CEO 요청 2026-09-29). 60fps로 흘려서 확인한다:
// - 소환: 책상 → 휴식터에서 빙글 돌며 작아져 사라졌다가(크기 0) 새 자리에서 커지며 나타나는지,
//   걸린 시간, 도착 자리, 소리 1번·반짝임 2번
// - 가까운 자리(의자 → 옆에 선 자리)는 소환하지 않고 일어서서 폴짝 옮기는지
// - 도중에 목적지가 바뀌면 새 목적지로 가는지, 긴급 정지 때 바로 도착하는지, 효과를 끄면 바로 가는지
// - 그림자: 서 있을 때만 보이고 앉으면 숨는지
// - 눌렀다 펴기·소환 크기: 발끝이 캔버스 바닥에 붙어 있고 머리가 캔버스 위로 잘리지 않는지
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ui = path.resolve(__dirname, '..', '..', 'ui');
const index = JSON.parse(fs.readFileSync(path.join(ui, 'assets/sprites/index.json'), 'utf8'));
const floors = JSON.parse(fs.readFileSync(path.join(ui, 'assets/bg/floors.json'), 'utf8'));
let now = 0;
let rafQueue = [];
let timers = [];
const draws = [];
const sounds = [];
const sparkles = [];
let reduced = false;

// 아주 작은 가짜 DOM: scene.js가 쓰는 것만
function node(tag) {
  return {
    tag, children: [], className: '', hidden: false, textContent: '', tabIndex: 0, width: 0, height: 0, dataset: {},
    style: { setProperty(k, v) { this[k] = v; } },
    classList: { toggle() {}, add() {}, remove() {} },
    setAttribute() {}, addEventListener() {}, remove() {},
    appendChild(c) { this.children.push(c); return c; },
    append(...items) { for (const c of items) this.children.push(c); },
    replaceChildren() { this.children = []; },
    getContext() {
      const el = this;
      let sx = 1;
      return {
        setTransform(a) { sx = a; },
        clearRect() {},
        drawImage(img, fx, fy, fw, fh, dx, dy, dw, dh) { draws.push({ el, dy, dh, ch: el.height, sx, t: now }); },
      };
    },
  };
}

const sandbox = {
  console, Math, JSON, Object, Array, Set, Map, Promise, String, Number,
  document: { createElement: node },
  performance: { now: () => now },
  requestAnimationFrame: (f) => rafQueue.push(f),
  setTimeout: (f, ms) => { timers.push({ f, at: now + ms }); return timers.length; },
  clearTimeout: () => {},
  fetch: async (url) => ({ json: async () => (String(url).includes('floors.json') ? floors : index) }),
  Looks: {
    init: async () => {},
    loadIndex: async () => index, // 배포 + 설치한 그림 목록 (여기서는 배포 것만)
    norm: (l) => ({ style: 'base', ...(l || {}) }),
    strip: (id, action) => ({ meta: index[`${id}.${action}`], image: index[`${id}.${action}`] ? {} : null }),
  },
  Fx: { sparkle: (parent, x, y) => sparkles.push({ x, y, t: now }), reduced: () => reduced },
  Sfx: { play: (name) => sounds.push(name) },
};
vm.createContext(sandbox);
vm.runInContext(`${fs.readFileSync(path.join(ui, 'scene.js'), 'utf8')}\nthis.Scene = Scene;`, sandbox);
const { Scene } = sandbox;

function frame() {
  now += 1000 / 60;
  const due = timers.filter((t) => t.at <= now);
  timers = timers.filter((t) => t.at > now);
  for (const t of due) t.f();
  const q = rafQueue;
  rafQueue = [];
  for (const f of q) f(now);
}
const run = (sec) => { for (let i = 0; i < Math.round(sec * 60); i++) frame(); };

const problems = [];
const check = (ok, text) => { if (!ok) problems.push(text); };

(async () => {
  const layer = node('div');
  await Scene.init(layer, () => {});
  await new Promise((r) => setImmediate(r));
  const ids = Object.keys(Scene.people);
  const shadows = layer.children.filter((c) => c.className === 'shadow');
  const canvases = layer.children.filter((c) => c.tag === 'canvas');
  const at = (k) => { const w = Scene.where(ids[k]); return [w.x, w.y]; };
  const canvasOf = (id) => canvases[ids.indexOf(id)];
  for (const id of ids) Scene.setState(id, 'work', { instant: true });
  run(0.2);

  // 1) 책상 → 휴식터 소환
  draws.length = 0;
  sounds.length = 0;
  sparkles.length = 0;
  const t0 = now;
  for (const id of ids) Scene.setState(id, 'rest');
  run(1.5);
  ids.forEach((id, k) => {
    const mine = draws.filter((d) => d.el === canvases[k] && d.t > t0);
    const sizes = mine.map((d) => d.dh / (d.ch / 1.05));
    const small = mine.findIndex((d) => d.dh < 0.5 || Math.abs(d.sx) < 0.05);
    const grown = mine.findIndex((d, i) => i > small && d.sx === 1); // 소환 중에는 가로 크기가 정확히 1이 되지 않는다
    const ms = grown > 0 ? Math.round(mine[grown].t - t0) : -1;
    const flips = mine.filter((d, i) => i > 0 && Math.sign(d.sx) !== Math.sign(mine[i - 1].sx)).length;
    const feet = mine.every((d) => Math.abs(d.dy + d.dh - d.ch) < 0.01);
    const head = mine.every((d) => d.dy >= -0.01);
    const [x, y] = at(k);
    const { rest } = Scene.people[id];
    console.log(`${id}: 사라짐 ${small >= 0 ? '예' : '아니오'} → 나타남 ${ms}ms, 도는 중 뒤집힘 ${flips}번, 크기 ${Math.min(...sizes).toFixed(2)}~${Math.max(...sizes).toFixed(2)}배, 도착 (${x},${y}), 그림자 ${shadows[k].hidden ? '숨김' : '보임'}`);
    check(small >= 0, `${id} 사라지지 않음`);
    check(ms > 800 && ms < 1100, `${id} 소환 시간 ${ms}ms`);
    check(flips >= 4, `${id} 빙글 돌지 않음 (${flips})`);
    check(x === rest[0] && y === rest[1], `${id} 휴식터 자리가 아님 (${x},${y})`);
    check(shadows[k].hidden, `${id} 앉았는데 그림자가 보임`);
    check(feet, `${id} 발끝이 떨어짐`);
    check(head, `${id} 머리가 캔버스 위로 잘림`);
  });
  check(sounds.filter((s) => s === 'warp').length === ids.length, `소환 소리 ${sounds.length}번`);
  check(sparkles.length === ids.length * 2, `반짝임 ${sparkles.length}번 (사람마다 2번이어야)`);

  // 2) 가까운 자리: 휴식터 → 책상(소환) 뒤 의자 → 선 자리(결재)는 일어나기만
  for (const id of ids) Scene.setState(id, 'work');
  run(1.5);
  draws.length = 0;
  sounds.length = 0;
  Scene.setState('hana', 'call');
  run(0.3);
  const [hx, hy] = at(ids.indexOf('hana'));
  check(hx === Scene.people.hana.stand[0] && hy === Scene.people.hana.stand[1], `하나 결재 자리로 바로 가지 않음 (${hx},${hy})`);
  check(!sounds.includes('warp'), '가까운 자리인데 소환함');
  run(0.1);
  const hop = draws.filter((d) => d.el === canvasOf('hana')).map((d) => d.dh / (d.ch / 1.05));
  console.log(`하나 결재: 소환 없이 폴짝, 눌렀다 펴기 ${Math.min(...hop).toFixed(2)}~${Math.max(...hop).toFixed(2)}배`);
  check(Math.min(...hop) > 0.9, '일어날 때 크기가 너무 작아짐');
  run(3);

  // 3) 도중에 목적지 바꾸기: 휴식터로 가다가(사라지는 중) 다시 일하러
  Scene.setState('sol', 'rest');
  run(0.2);
  Scene.setState('sol', 'work');
  run(1.5);
  let [sx, sy] = at(ids.indexOf('sol'));
  console.log(`솔 사라지는 중 목적지 바꿈 → (${sx},${sy})`);
  // 나타나는 중에 바꾸기
  Scene.setState('sol', 'rest');
  run(0.6);
  Scene.setState('sol', 'work');
  run(1.8);
  [sx, sy] = at(ids.indexOf('sol'));
  console.log(`솔 나타나는 중 목적지 바꿈 → (${sx},${sy})`);
  check(sx === Scene.people.sol.seat[0] && sy === Scene.people.sol.seat[1], `솔이 책상으로 돌아오지 않음 (${sx},${sy})`);

  // 4) 긴급 정지: 소환 도중이면 바로 도착
  Scene.setState('clo', 'rest');
  run(0.2);
  Scene.setStopped(true);
  run(0.2);
  const [cx, cy] = at(ids.indexOf('clo'));
  const frozen = draws.filter((d) => d.el === canvasOf('clo')).slice(-1)[0];
  console.log(`클로 소환 중 긴급 정지 → (${cx},${cy}), 크기 ${(frozen.dh / (frozen.ch / 1.05)).toFixed(2)}배`);
  check(cx === Scene.people.clo.rest[0] && cy === Scene.people.clo.rest[1], '긴급 정지 때 도착하지 않음');
  check(frozen.sx === 1 && frozen.dh / (frozen.ch / 1.05) > 0.9, '긴급 정지 때 작아진 채 멈춤');
  Scene.setStopped(false);

  // 5) 효과 끄기: 바로 간다
  reduced = true;
  sounds.length = 0;
  Scene.setState('luna', 'rest');
  const [lx, ly] = at(ids.indexOf('luna'));
  check(lx === Scene.people.luna.rest[0] && ly === Scene.people.luna.rest[1], '효과를 껐는데 바로 가지 않음');
  check(!sounds.includes('warp'), '효과를 껐는데 소환 소리');
  console.log(`루나 효과 끔 → 바로 (${lx},${ly})`);

  console.log(problems.length ? `문제: ${problems.join(' / ')}` : '소환 점검 통과');
  process.exitCode = problems.length ? 1 : 0;
})();
