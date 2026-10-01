// 인형 엔진 계산 점검 (브라우저 없이): node tools/dev/puppet_sim.js
// ui/puppet.js의 순수 계산(뼈대 검사·영역 무게·그물 휘기·스프링 물리·움직임 조종)과, 가짜 DOM·가짜 GL로 그리기 켜고 끄기를 확인한다.
// 화면은 캡처로 본다 (#view=board&demo=rig, #pose=…).
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const root = path.join(__dirname, '..', '..');
const Puppet = require(path.join(root, 'ui', 'puppet.js'));
const L = Puppet.logic;

let n = 0;
function check(name, fn) { fn(); n += 1; console.log(`  ✓ ${name}`); }
const near = (a, b, eps, msg) => assert.ok(Math.abs(a - b) <= eps, `${msg || ''} ${a} ≈ ${b} (±${eps})`);

const NORMAL = { x: 78, y: 80, h: 480 }; // 기본 하나의 평소 그림 자리 (상자 좌표)
const BLINK = { src: '/a/blink.png', x: 258, y: 149.6, h: 24 };
const EX = { base: '/a/', blink: BLINK };
const rigOf = (over = {}) => ({
  version: 1, size: { w: 530, h: 800 }, grid: { cols: 28, rows: 42 },
  regions: {
    head: { ellipse: [292, 140, 90, 115], feather: 45 },
    hairR: { poly: [[330, 90], [400, 110], [455, 200], [505, 330], [505, 445], [430, 455], [380, 330], [350, 230]], feather: 30 },
    face: { ellipse: [298, 160, 55, 65], feather: 30 },
  },
  deformers: [
    { type: 'rotate', region: 'hairR', pivot: [360, 150], param: 'hairSway', k: 5, falloff: { from: [360, 150], to: [470, 440], power: 1.5 } },
    { type: 'shift', region: 'face', param: 'angleX', kx: 4 },
    { type: 'rotate', region: 'head', pivot: [290, 235], param: 'angleZ', k: 8 },
    { type: 'scale', region: '*', pivot: [300, 800], param: 'breath', kx: 0.003, ky: 0.006 },
    { type: 'rotate', region: '*', pivot: [300, 800], param: 'bodyZ', k: 1.5 },
    { type: 'shift', region: '*', param: 'posY', ky: -27 },
  ],
  physics: [{ out: 'hairSway', in: [['angleZ', 0.6], ['bodyZ', 0.8], ['angleX', 0.3]], stiffness: 20, damping: 3.5 }],
  ...over,
});
const clean = (over, extra = EX) => L.cleanRig(rigOf(over), NORMAL, extra);

// ---------------------------------------------------------------- 뼈대 검사
check('cleanRig: 규격 예시가 통과하고, 층이 없으면 base + blink를 자동으로 (상자 좌표 → 뼈대 좌표)', () => {
  const r = clean();
  assert.ok(r);
  assert.deepStrictEqual(r.layers.map((l) => l.id), ['base', 'blink']);
  const b = r.layers[1];
  near(b.x, 300, 1e-9); near(b.y, 116, 1e-9); near(b.h, 40, 1e-9); // (258-78)·1.667, (149.6-80)·1.667, 24·1.667
  assert.strictEqual(b.src, '/a/blink.png');
  assert.deepStrictEqual(b.moods, ['normal']);
  assert.strictEqual(b.show.param, 'eyeOpen');
  assert.strictEqual(clean({}, { base: '/a/' }).layers.length, 1, '눈 조각이 없으면 base만');
});

check('cleanRig: 전신 눈 감은 그림(eyesOnly)은 eyes 영역이 있을 때만 mask로 자동 blink', () => {
  const eyes = { ...BLINK, eyesOnly: true, x: 78, y: 80, h: 480 };
  assert.strictEqual(clean({}, { base: '/a/', blink: eyes }).layers.length, 1, 'eyes 영역이 없으면 blink 층을 만들지 않는다 (그림 전체가 깜빡이지 않게)');
  const r = clean({ regions: { ...rigOf().regions, eyes: { ellipse: [280, 150, 40, 20], feather: 20 } } }, { base: '/a/', blink: eyes });
  assert.strictEqual(r.layers[1].mask, 'eyes');
});

check('cleanRig: 명시한 층·show·mask·moods·under·bases를 검사해 담는다', () => {
  const r = clean({
    layers: [
      { id: 'back', image: 'back.png', x: 1, y: 2, h: 300, under: true },
      { id: 'base' },
      { id: 'eyes2', image: 'e.png', x: 300, y: 116, h: 40, show: { param: 'eyeOpen', max: 0.3, fade: 0.2 }, mask: 'face', moods: ['normal', 'normal', 'happy'] },
    ],
    bases: { normal: 'n-nohair.png', point: 'p-nohair.png' },
  });
  assert.ok(r);
  assert.strictEqual(r.layers[0].under, true);
  assert.deepStrictEqual(r.layers[2].moods, ['normal', 'happy']);
  assert.deepStrictEqual([r.layers[2].show.min, r.layers[2].show.max, r.layers[2].show.fade], [-Infinity, 0.3, 0.2]);
  assert.deepStrictEqual(r.bases, { normal: '/a/n-nohair.png', point: '/a/p-nohair.png' });
  assert.strictEqual(clean({}).bases, null);
});

check('cleanRig: 규격 밖은 거절 (모르는 버전·type·숫자·이름·없는 region·param·층·이상한 그림 이름)', () => {
  const bad = (over, why) => assert.strictEqual(clean(over), null, why);
  assert.strictEqual(L.cleanRig(null, NORMAL, EX), null, 'null');
  assert.strictEqual(L.cleanRig({ ...rigOf(), version: 2 }, NORMAL, EX), null, '모르는 판');
  assert.strictEqual(L.cleanRig('x', NORMAL, EX), null, '객체가 아님');
  bad({ deformers: [{ type: 'twirl', region: '*', param: 'angleZ', k: 1 }] }, '모르는 type');
  bad({ deformers: [{ type: 'rotate', region: '*', pivot: [0, 0], param: 'angleZ', k: NaN }] }, 'NaN');
  bad({ deformers: [{ type: 'rotate', region: '*', pivot: [0, 0], param: 'angleZ', k: '5' }] }, '숫자가 문자열');
  bad({ deformers: [{ type: 'rotate', region: '*', pivot: [0, 'x'], param: 'angleZ', k: 5 }] }, '좌표가 숫자가 아님');
  bad({ deformers: [{ type: 'shift', region: 'nowhere', param: 'angleX', kx: 1 }] }, '없는 region');
  bad({ deformers: [{ type: 'shift', region: '*', param: 'wobble', kx: 1 }] }, '아무도 만들지 않는 param');
  bad({ deformers: [{ type: 'shift', region: '*', param: 'angleX', kx: 1, layers: ['ghost'] }] }, '모르는 층 id를 가리키는 deformer');
  bad({ deformers: [{ type: 'shift', region: '*', param: 'angleX', kx: 1, falloff: { from: [1, 1], to: [1, 1] } }] }, 'falloff 시작=끝');
  bad({ regions: { '1head': { ellipse: [1, 1, 5, 5] } } }, '이름이 숫자로 시작');
  bad({ regions: { 'a-b': { ellipse: [1, 1, 5, 5] } } }, '이름에 -');
  bad({ regions: { [`a${'b'.repeat(24)}`]: { ellipse: [1, 1, 5, 5] } } }, '이름이 25자');
  bad({ regions: { a: { ellipse: [1, 1, 5, 5], poly: [[0, 0], [1, 0], [1, 1]] } } }, 'ellipse와 poly 둘 다');
  bad({ regions: { a: { poly: [[0, 0], [1, 0]] } } }, '점이 3개 미만');
  bad({ physics: [{ out: 'angleX', in: [['angleZ', 1]] }] }, 'physics out이 표준 매개변수 이름');
  bad({ physics: [{ out: 'a', in: [['nope', 1]] }] }, 'physics 입력이 표준 매개변수가 아님');
  bad({ layers: [{ id: 'blink', image: 'b.png', x: 0, y: 0, h: 10 }] }, 'base 층이 없음');
  bad({ layers: [{ id: 'base' }, { id: 'base' }] }, '층 id 겹침');
  for (const image of ['../x.png', 'a/b.png', 'x.svg', 'x.png?y', '']) bad({ layers: [{ id: 'base' }, { id: 'l', image, x: 0, y: 0, h: 10 }] }, `층 그림 이름 ${image}`);
  bad({ layers: [{ id: 'base' }, { id: 'l', image: 'a.png', x: 0, y: 0, h: 10, mask: 'none' }] }, '없는 mask 영역');
  bad({ layers: [{ id: 'base' }, { id: 'l', image: 'a.png', x: 0, y: 0, h: 10, moods: ['angry'] }] }, '모르는 표정');
  bad({ layers: [{ id: 'base' }, { id: 'l', image: 'a.png', x: 0, y: 0, h: 10, show: { param: 'zzz' } }] }, 'show의 모르는 param');
  bad({ bases: { angry: 'a.png' } }, 'bases의 모르는 표정');
  bad({ bases: { normal: '../a.png' } }, 'bases의 이상한 그림 이름');
  bad({ size: { w: 'a', h: 800 } }, 'size');
});

check('cleanRig: 개수 제한 (regions 32·poly 점 64·deformers 64·physics 16·layers 24·physics 입력 8)', () => {
  const many = (count, make) => Object.fromEntries(Array.from({ length: count }, (_, i) => [`r${i}`, make(i)]));
  const ell = () => ({ ellipse: [10, 10, 5, 5] });
  assert.ok(clean({ regions: many(32, ell), deformers: [], physics: [] }));
  assert.strictEqual(clean({ regions: many(33, ell), deformers: [], physics: [] }), null);
  const poly = (k) => ({ poly: Array.from({ length: k }, (_, i) => [i, (i * 7) % 50]) });
  assert.ok(clean({ regions: { p: poly(64) }, deformers: [], physics: [] }));
  assert.strictEqual(clean({ regions: { p: poly(65) }, deformers: [], physics: [] }), null);
  const def = { type: 'shift', region: '*', param: 'angleX', kx: 1 };
  assert.ok(clean({ deformers: Array(64).fill(def), physics: [] }));
  assert.strictEqual(clean({ deformers: Array(65).fill(def), physics: [] }), null);
  const phys = (k) => Array.from({ length: k }, (_, i) => ({ out: `p${i}`, in: [['angleZ', 1]] }));
  assert.ok(clean({ deformers: [], physics: phys(16) }));
  assert.strictEqual(clean({ deformers: [], physics: phys(17) }), null);
  assert.strictEqual(clean({ deformers: [], physics: [{ out: 'a', in: Array(9).fill(['angleZ', 1]) }] }), null);
  const layer = (k) => [{ id: 'base' }, ...Array.from({ length: k - 1 }, (_, i) => ({ id: `l${i}`, image: 'a.png', x: 0, y: 0, h: 10 }))];
  assert.ok(clean({ layers: layer(24) }));
  assert.strictEqual(clean({ layers: layer(25) }), null);
});

check('cleanRig: 숫자는 범위 안으로 자른다 (k·grid·feather·power·물리)', () => {
  const r = clean({
    grid: { cols: 999, rows: 1 },
    regions: { a: { ellipse: [10, 10, 5, 5], feather: -5 } },
    deformers: [{ type: 'rotate', region: 'a', pivot: [0, 0], param: 'angleZ', k: 999, falloff: { from: [0, 0], to: [1, 1], power: 99 } }],
    physics: [{ out: 'sway', in: [['angleZ', 99]], stiffness: 9999, damping: 0 }],
  });
  assert.deepStrictEqual([r.grid.cols, r.grid.rows], [64, 4]);
  assert.strictEqual(r.regions.a.feather, 0);
  assert.strictEqual(r.deformers[0].k, 180);
  assert.strictEqual(r.deformers[0].falloff.power, 4);
  assert.deepStrictEqual([r.physics[0].in[0][1], r.physics[0].stiffness, r.physics[0].damping], [4, 300, 0.1]);
});

check('cleanRig: physics 입력은 [이름, 가중치] 또는 [이름, 가중치, 속도 반영]', () => {
  const r = clean({ deformers: [], physics: [{ out: 'sway', in: [['angleZ', 0.5], ['bodyZ', 0.2, -0.05]] }] });
  assert.deepStrictEqual(r.physics[0].in, [['angleZ', 0.5, 0], ['bodyZ', 0.2, -0.05]]);
  assert.strictEqual(clean({ deformers: [], physics: [{ out: 'sway', in: [['angleZ', 0.5, 0.1, 9]] }] }), null);
});

check('parsePose: #pose=angleZ:1,hairSway:-1 → 값(범위 -1.5..1.5), 이상한 것은 버림', () => {
  assert.deepStrictEqual(L.parsePose('angleZ:1,hairSway:-1'), { angleZ: 1, hairSway: -1 });
  assert.deepStrictEqual(L.parsePose('angleZ:9,1bad:1,x:abc,y:,z'), { angleZ: 1.5 });
  assert.deepStrictEqual(L.parsePose(''), {});
  assert.deepStrictEqual(L.parsePose(undefined), {});
});

// ---------------------------------------------------------------- 영역 무게
check('regionWeight: 안 1, 먼 곳 0, 경계에서 바깥으로 단조롭게 줄어든다 (타원·다각형·*)', () => {
  const rig = clean();
  const head = rig.regions.head; // 타원 [292,140,90,115] feather 45
  assert.strictEqual(L.regionWeight(head, 292, 140), 1);
  assert.strictEqual(L.regionWeight(head, 292 + 90, 140), 1, '경계 위는 1');
  assert.strictEqual(L.regionWeight(head, 292 + 90 + 45, 140), 0, 'feather 끝은 0');
  assert.strictEqual(L.regionWeight(head, 5, 700), 0);
  let prev = 1;
  for (let x = 382; x <= 440; x += 1) { const w = L.regionWeight(head, x, 140); assert.ok(w <= prev + 1e-12, `타원 단조 x=${x}`); prev = w; }
  near(L.regionWeight(head, 382 + 22.5, 140), 0.5, 1e-9, 'smoothstep 절반');
  const hair = rig.regions.hairR; // 다각형
  assert.strictEqual(L.regionWeight(hair, 440, 330), 1);
  assert.strictEqual(L.regionWeight(hair, 20, 20), 0);
  prev = 1;
  for (let x = 505; x <= 545; x += 1) { const w = L.regionWeight(hair, x, 400); assert.ok(w <= prev + 1e-12, `다각형 단조 x=${x}`); prev = w; }
  assert.strictEqual(L.regionWeight(hair, 536, 400), 0);
  assert.strictEqual(L.regionWeight('*', 1, 2), 1);
  assert.strictEqual(L.regionWeight(null, 1, 2), 1);
  const sharp = clean({ regions: { s: { ellipse: [50, 50, 10, 10] } }, deformers: [], physics: [] }).regions.s; // feather 0
  assert.deepStrictEqual([L.regionWeight(sharp, 55, 50), L.regionWeight(sharp, 61, 50)], [1, 0]);
});

// ---------------------------------------------------------------- 그물·휘기
function gridOf(rig, layer = 'base', rect = { x: 0, y: 0, w: rig.size.w, h: rig.size.h }, opts = {}) {
  return L.buildGrid(rig, rect, { cols: rig.grid.cols, rows: rig.grid.rows, layer, ...opts });
}
const at = (g, out, c, r) => { const v = r * (g.cols + 1) + c; return [out[2 * v], out[2 * v + 1]]; };

check('buildGrid: 꼭짓점·삼각형 수, 그림 좌표(uv) 0..1, 무게는 쉬는 자리에서', () => {
  const rig = clean();
  const g = gridOf(rig);
  assert.deepStrictEqual([g.cols, g.rows, g.n, g.index.length], [28, 42, 29 * 43, 28 * 42 * 6]);
  assert.deepStrictEqual([g.uv[0], g.uv[1], g.uv[2 * (g.n - 1)], g.uv[2 * (g.n - 1) + 1]], [0, 0, 1, 1]);
  const head = rig.deformers.findIndex((d) => d.region === 'head');
  const v = 10 * 29 + 15; // 안쪽 꼭짓점
  assert.ok(g.w[head][v] > 0 && g.w[head][v] <= 1);
  assert.strictEqual(g.w[head][0], 0, '머리 밖 모서리');
  const all = rig.deformers.findIndex((d) => d.region === '*');
  assert.ok(g.w[all].every((w) => w === 1), '*는 어디나 1');
});

check('deform: rotate — pivot은 그대로, 무게 1이면 정확히 k도 (시계 방향), 값이 0이면 그대로', () => {
  const all = { all: { poly: [[-100, -100], [900, -100], [900, 1000], [-100, 1000]] } };
  const g0 = gridOf(clean({ regions: all, deformers: [], physics: [] }));
  const p = 14 * 29 + 14; // pivot으로 삼을 꼭짓점 (그물 칸 안의 한 점)
  const [px, py] = [g0.rest[2 * p], g0.rest[2 * p + 1]];
  const rig = clean({ regions: all, deformers: [{ type: 'rotate', region: 'all', pivot: [px, py], param: 'angleZ', k: 8 }], physics: [] });
  const g = gridOf(rig);
  const out = L.deform(g, rig, { angleZ: 1 });
  near(out[2 * p], px, 1e-3); near(out[2 * p + 1], py, 1e-3);
  const rad = (8 * Math.PI) / 180;
  for (const v of [0, 100, 700, 1246]) {
    const dx = g.rest[2 * v] - px; const dy = g.rest[2 * v + 1] - py;
    near(out[2 * v] - px, dx * Math.cos(rad) - dy * Math.sin(rad), 1e-3, `x v=${v}`);
    near(out[2 * v + 1] - py, dx * Math.sin(rad) + dy * Math.cos(rad), 1e-3, `y v=${v}`);
    const turned = Math.atan2(out[2 * v + 1] - py, out[2 * v] - px) - Math.atan2(dy, dx);
    if (Math.hypot(dx, dy) > 5) near((turned * 180) / Math.PI, 8, 1e-2, `각도 v=${v}`);
  }
  assert.deepStrictEqual(Array.from(L.deform(g, rig, { angleZ: 0 })), Array.from(g.rest), '값 0 = 그대로');
  assert.deepStrictEqual(Array.from(L.deform(g, rig, { angleZ: NaN })), Array.from(g.rest), 'NaN도 무시');
  assert.deepStrictEqual(Array.from(L.deform(g, rig, {})), Array.from(g.rest), '값이 없어도');
  const neg = L.deform(g, rig, { angleZ: -1 });
  const v = 100; const dx = g.rest[2 * v] - px; const dy = g.rest[2 * v + 1] - py;
  near(neg[2 * v] - px, dx * Math.cos(-rad) - dy * Math.sin(-rad), 1e-3, '반대 방향');
});

check('deform: shift·scale·무게(가장자리는 반만)·falloff(t^power)·적힌 순서', () => {
  const all = { all: { poly: [[-100, -100], [900, -100], [900, 1000], [-100, 1000]] } };
  const shiftRig = clean({ regions: all, deformers: [{ type: 'shift', region: 'all', param: 'bodyX', kx: 6, ky: -2 }], physics: [] });
  const g = gridOf(shiftRig);
  const o = L.deform(g, shiftRig, { bodyX: 0.5 });
  near(o[0] - g.rest[0], 3, 1e-4); near(o[1] - g.rest[1], -1, 1e-4);
  const sc = clean({ regions: all, deformers: [{ type: 'scale', region: 'all', pivot: [300, 800], param: 'breath', kx: 0.01, ky: 0.02 }], physics: [] });
  const gs = gridOf(sc);
  const os2 = L.deform(gs, sc, { breath: 1 });
  near(os2[0], 300 + (0 - 300) * 1.01, 1e-3); near(os2[1], 800 + (0 - 800) * 1.02, 1e-3);
  const last = 2 * (gs.n - 1);
  near(os2[last + 1], 800, 1e-3, 'pivot 높이는 그대로');
  // 무게: 가장자리(feather 중간)는 절반만 움직인다
  const feather = clean({ regions: { e: { ellipse: [265, 400, 60, 60], feather: 40 } }, deformers: [{ type: 'shift', region: 'e', param: 'bodyX', kx: 10 }], physics: [] });
  const gf = gridOf(feather);
  const of = L.deform(gf, feather, { bodyX: 1 });
  const wArr = gf.w[0];
  for (let v = 0; v < gf.n; v++) near(of[2 * v] - gf.rest[2 * v], 10 * wArr[v], 1e-4, `무게만큼 v=${v}`);
  assert.ok(wArr.some((w) => w > 0 && w < 1), '경계에서 부드럽게');
  // falloff: from→to 사영 비율의 power 제곱이 무게에 곱해진다
  const fo = clean({ regions: all, deformers: [{ type: 'shift', region: 'all', param: 'bodyX', kx: 10, falloff: { from: [0, 0], to: [0, 800], power: 2 } }], physics: [] });
  const gfo = gridOf(fo);
  const off = L.deform(gfo, fo, { bodyX: 1 });
  for (const r of [0, 10, 21, 42]) { const [x0, y0] = at(gfo, gfo.rest, 5, r); const [x1] = at(gfo, off, 5, r); near(x1 - x0, 10 * (y0 / 800) ** 2, 1e-4, `falloff 행 ${r}`); }
  // 순서: 이동 뒤 회전 ≠ 회전 뒤 이동 (나중 것은 이미 휜 자리에 적용)
  const a = clean({ regions: all, deformers: [{ type: 'shift', region: 'all', param: 'bodyX', kx: 50 }, { type: 'rotate', region: 'all', pivot: [0, 0], param: 'angleZ', k: 90 }], physics: [] });
  const b = clean({ regions: all, deformers: [{ type: 'rotate', region: 'all', pivot: [0, 0], param: 'angleZ', k: 90 }, { type: 'shift', region: 'all', param: 'bodyX', kx: 50 }], physics: [] });
  const oa = L.deform(gridOf(a), a, { bodyX: 1, angleZ: 1 });
  const ob = L.deform(gridOf(b), b, { bodyX: 1, angleZ: 1 });
  const v = 200; const g0 = gridOf(a);
  near(oa[2 * v], -g0.rest[2 * v + 1], 1e-3, '이동 뒤 회전(x)'); near(oa[2 * v + 1], g0.rest[2 * v] + 50, 1e-3, '이동 뒤 회전(y)');
  near(ob[2 * v], -g0.rest[2 * v + 1] + 50, 1e-3, '회전 뒤 이동(x)');
});

check('deform·buildGrid: deformer의 layers 칸 — 있으면 그 층 꼭짓점에만, 나머지 층(base 포함)은 건너뛴다', () => {
  const all = { all: { poly: [[-100, -100], [900, -100], [900, 1000], [-100, 1000]] } };
  const rig = clean({
    regions: all,
    deformers: [{ type: 'shift', region: 'all', param: 'hairSway', kx: 10, layers: ['hair'] }, { type: 'shift', region: 'all', param: 'bodyX', kx: 3 }],
    physics: [{ out: 'hairSway', in: [['angleZ', 1]] }],
    layers: [{ id: 'base' }, { id: 'hair', image: 'hair.png', x: 0, y: 0, h: 800 }],
  });
  assert.deepStrictEqual(rig.deformers[0].layers, ['hair']);
  assert.strictEqual(rig.deformers[1].layers, null);
  const base = gridOf(rig, 'base');
  const hair = gridOf(rig, 'hair', { x: 0, y: 0, w: 530, h: 800 });
  assert.deepStrictEqual([base.active, hair.active], [[1], [0, 1]]);
  assert.strictEqual(base.w[0], null, 'base는 이 deformer의 무게를 계산조차 안 한다');
  const pose = { hairSway: 1, bodyX: 1 };
  const ob = L.deform(base, rig, pose);
  const oh = L.deform(hair, rig, pose);
  near(ob[0] - base.rest[0], 3, 1e-4, 'base는 bodyX만');
  near(oh[0] - hair.rest[0], 13, 1e-4, 'hair 층은 둘 다');
});

check('buildGrid: mask 층은 영역 둘레만 더 촘촘한 그물로, 꼭짓점 알파 = 그 영역의 무게 (그림 좌표는 전신 기준)', () => {
  const rig = clean({ regions: { eyes: { ellipse: [280, 150, 40, 20], feather: 20 } }, deformers: [], physics: [], layers: [{ id: 'base' }, { id: 'full', image: 'f.png', x: 0, y: 0, h: 800, mask: 'eyes' }] });
  const g = L.buildGrid(rig, { x: 0, y: 0, w: 530, h: 800 }, { mask: 'eyes', layer: 'full' });
  assert.ok(g.n < 900, `작은 그물 ${g.n}`);
  const [x0, y0, x1, y1] = rig.regions.eyes.bbox;
  assert.deepStrictEqual([g.rect.x, g.rect.y, g.rect.w, g.rect.h], [x0, y0, x1 - x0, y1 - y0]);
  let inner = 0;
  for (let v = 0; v < g.n; v++) {
    const w = L.regionWeight(rig.regions.eyes, g.rest[2 * v], g.rest[2 * v + 1]);
    near(g.alpha[v], w, 1e-6);
    near(g.uv[2 * v], g.rest[2 * v] / 530, 1e-5, 'uv는 그림 전체 기준');
    if (w === 1) inner += 1;
  }
  assert.ok(inner > 4, '눈 안쪽은 알파 1');
});

// ---------------------------------------------------------------- 물리
check('stepPhysics: 목표로 수렴하고 (스프링), 큰 dt에도 NaN 없이 범위 안에 머문다', () => {
  const list = clean().physics;
  const st = L.makePhysics();
  const p = { angleZ: 1, bodyZ: 0, angleX: 0 };
  for (let i = 0; i < 300; i++) L.stepPhysics(st, list, p, 1 / 60); // 5초
  near(p.hairSway, 0.6, 0.01, '목표 0.6');
  // 스프링이라 처음에는 목표를 넘어가 출렁인다 (감쇠 0.39)
  const st2 = L.makePhysics(); const q = { angleZ: 1, bodyZ: 0, angleX: 0 };
  let peak = 0;
  for (let i = 0; i < 120; i++) { L.stepPhysics(st2, list, q, 1 / 60); peak = Math.max(peak, q.hairSway); }
  assert.ok(peak > 0.62, `출렁임 ${peak}`);
  // 큰 dt·이상한 dt
  for (const dt of [10, 1e9, -1, NaN, Infinity, 0]) {
    const st3 = L.makePhysics(); const r = { angleZ: 5, bodyZ: -5, angleX: 5 };
    L.stepPhysics(st3, list, r, dt);
    L.stepPhysics(st3, list, r, dt);
    assert.ok(Number.isFinite(r.hairSway) && Math.abs(r.hairSway) <= 1.5, `dt=${dt} → ${r.hairSway}`);
  }
  const st4 = L.makePhysics(); const big = { angleZ: 4, bodyZ: 4, angleX: 4 };
  for (let i = 0; i < 20; i++) L.stepPhysics(st4, list, big, 0.05);
  assert.strictEqual(big.hairSway, 1.5, '범위 1.5로 잘림');
  // 입력 속도 (세 번째 숫자): 입력이 움직일 때만 목표가 달라진다
  const vel = clean({ deformers: [], physics: [{ out: 'sway', in: [['angleZ', 0, 0.1]], stiffness: 300, damping: 30 }] }).physics;
  const sv = L.makePhysics(); const pv = { angleZ: 0 };
  L.stepPhysics(sv, vel, pv, 1 / 60);
  pv.angleZ = 0.1; L.stepPhysics(sv, vel, pv, 1 / 60);
  assert.ok(pv.sway > 0.05, `움직이는 동안 목표가 쏠림 ${pv.sway}`);
  for (let i = 0; i < 120; i++) L.stepPhysics(sv, vel, pv, 1 / 60);
  near(pv.sway, 0, 0.01, '멈추면 0으로');
});

check('steadyPhysics: 멈춘 자세는 입력 그대로일 때의 자리, 자세에 적힌 값은 그대로', () => {
  const list = clean().physics;
  const p = { angleZ: 1, bodyZ: 0.5, angleX: 0 };
  L.steadyPhysics(list, p);
  near(p.hairSway, 0.6 + 0.4, 1e-9);
  const q = { angleZ: 1, hairSway: -1 };
  L.steadyPhysics(list, q);
  assert.strictEqual(q.hairSway, -1);
});

// ---------------------------------------------------------------- 움직임 조종
function fakeMotion(seq, extra = {}) {
  let t = 100000;
  const clock = { t: () => t, set: (v) => { t = v; } };
  let i = 0;
  const random = () => (Array.isArray(seq) ? seq[Math.min(i++, seq.length - 1)] : seq());
  const m = L.createMotion({ now: clock.t, random, ...extra });
  return { m, clock, at: (ms) => { t = 100000 + ms; return m.update(t); } };
}

check('createMotion: 깜빡임 시간표 — 2.6~6초마다, 눈 1→0(60ms) 유지(40ms) 0→1(90ms)', () => {
  const f = fakeMotion([0, 0.9, 0.5]); // 첫 대기 2600ms, (깜빡임 때 두 번 안 함=0.9), 다음 대기 2600+0.5·3400
  assert.strictEqual(f.at(2599).eyeOpen, 1);
  near(f.at(2600).eyeOpen, 1, 1e-9);
  near(f.at(2630).eyeOpen, 0.5, 1e-9, '30ms: 반쯤 감김');
  near(f.at(2660).eyeOpen, 0, 1e-9, '60ms: 다 감김');
  near(f.at(2699).eyeOpen, 0, 1e-9, '유지(40ms)');
  near(f.at(2745).eyeOpen, 0.5, 1e-9, '100ms부터 90ms에 걸쳐 뜬다');
  near(f.at(2790).eyeOpen, 1, 1e-9, '190ms: 다 뜸');
  assert.strictEqual(f.at(2850).eyeOpen, 1);
  // 다음은 4300ms 뒤 (2600 + 0.5·3400 = 4300 → 2790 이후 시각 2600+4300)
  assert.strictEqual(f.at(6899).eyeOpen, 1);
  f.at(6900); // 시각이 되면 (다음 갱신에서) 깜빡임 시작
  near(f.at(6960).eyeOpen, 0, 1e-9, '두 번째 깜빡임');
});

check('createMotion: 25%는 두 번 깜빡인다 (첫 깜빡임 시작 260ms 뒤)', () => {
  const f = fakeMotion([0, 0.1, 0.9]); // 2600ms에 깜빡임 + 두 번(0.1<0.25)
  f.at(2600);
  near(f.at(2660).eyeOpen, 0, 1e-9);
  near(f.at(2790).eyeOpen, 1, 1e-9, '첫 깜빡임 끝');
  near(f.at(2860).eyeOpen, 1, 1e-9, '260ms 전에는 열려 있다');
  near(f.at(2890).eyeOpen, 0.5, 1e-9, '260+30ms: 두 번째가 감기는 중');
  near(f.at(2920).eyeOpen, 0, 1e-9);
  near(f.at(3060).eyeOpen, 1, 1e-9);
});

check('createMotion: 평소 얼굴일 때만 깜빡이고 (기쁨·걱정·손짓 중에는 안 함)', () => {
  const f = fakeMotion([0, 0.9, 0.9]);
  f.m.setMood('worried', true, 100000);
  for (let ms = 0; ms < 3500; ms += 20) assert.strictEqual(f.at(ms).eyeOpen, 1, `걱정 ${ms}`);
  const g = fakeMotion([0, 0.9, 0.9]);
  assert.ok(g.m.point(1300, 100000 + 2000));
  for (let ms = 2500; ms < 3000; ms += 20) assert.strictEqual(g.at(ms).eyeOpen, 1, `손짓 ${ms}`);
});

check('createMotion: 가만히 작게(±0.4 안)·가끔 완전히 쉬는 순간, 숨쉬기 4.6초 주기 0..1', () => {
  const f = fakeMotion([0.9]);
  let maxIdle = 0; let minB = 1; let maxB = 0; let still = 0; let total = 0; let maxZ = 0;
  for (let ms = 0; ms < 120000; ms += 100) {
    const p = f.at(ms);
    for (const k of ['angleX', 'angleY', 'angleZ', 'bodyX', 'bodyZ']) maxIdle = Math.max(maxIdle, Math.abs(p[k]));
    maxZ = Math.max(maxZ, Math.abs(p.angleZ));
    total += 1; if (Math.abs(p.angleZ) < 0.02 && Math.abs(p.bodyZ) < 0.02) still += 1;
    minB = Math.min(minB, p.breath); maxB = Math.max(maxB, p.breath);
    assert.ok(p.posY === 0 && p.point === 0 && p.mouthOpen === 0);
  }
  assert.ok(maxIdle > 0.05 && maxIdle <= 0.4, `가만히 최대 ${maxIdle}`);
  assert.ok(maxZ <= 0.25 + 1e-9, `갸웃 ±0.25 (뼈대 k 8도 → ±2도) ${maxZ}`);
  assert.ok(still / total > 0.05, `가끔 멈춰 있는 순간이 있다 ${(still / total).toFixed(3)}`);
  assert.ok(minB < 0.01 && maxB > 0.99);
  near(f.at(0).breath, 0, 1e-9); near(f.at(2300).breath, 1, 1e-9, '반 주기'); near(f.at(4600).breath, 0, 1e-9, '4.6초');
});

check('createMotion: 기쁨은 폴짝(0.8초, posY·squash), 걱정은 흔들림(0.7초)+고개 숙임(angleY −0.3 유지)', () => {
  const f = fakeMotion([0.9]);
  assert.ok(f.m.setMood('happy', false, 100000 + 1000));
  near(f.at(1000 + 160).posY, 1, 1e-6, '0.16초(20%)에 첫 정점');
  near(f.at(1000 + 320).posY, 0, 1e-6, '착지 (40%)');
  assert.ok(f.at(1000 + 330).squash > 0.3, '착지 때 눌림');
  near(f.at(1000 + 480).posY, 0.55, 1e-6, '두 번째는 작게 (60%)');
  near(f.at(1000 + 640).posY, 0, 1e-6, '(80%)');
  assert.strictEqual(f.at(1000 + 700).posY, 0, '끝나는 쪽');
  assert.strictEqual(f.at(1000 + 900).posY, 0, '끝난 뒤');
  const h = fakeMotion([0.9]);
  assert.ok(h.m.setMood('worried', false, 100000 + 1000));
  const early = h.at(1000 + 100);
  assert.ok(Math.abs(early.angleZ) > 0.2 || Math.abs(early.bodyX) > 0.2, '흔들림');
  const late = h.at(1000 + 750);
  assert.ok(Math.abs(late.angleZ) < 0.3, '흔들림은 끝났다');
  for (let ms = 1750; ms < 6000; ms += 50) h.at(ms);
  near(h.at(6000).angleY, -0.3, 0.08, '고개 숙임 유지 (가만히 잡음 ±0.18 포함)');
  // 같은 표정을 다시 정하면 아무것도 안 함, instant면 폴짝 없음
  assert.strictEqual(h.m.setMood('worried'), false);
  const k = fakeMotion([0.9]);
  k.m.setMood('happy', true, 100000 + 500);
  assert.strictEqual(k.at(700).posY, 0);
});

check('createMotion: 손짓 — point 0→1→0 곡선 + 판 쪽(왼쪽, −)으로 bodyZ 기울기, 평소 얼굴일 때만', () => {
  const f = fakeMotion([0.9]);
  assert.strictEqual(f.m.point(1300, 100000 + 1000), true);
  assert.strictEqual(f.at(1000).point, 0);
  const mid = f.at(1000 + 650);
  assert.strictEqual(mid.point, 1);
  assert.ok(mid.bodyZ < -0.4 && mid.bodyZ > -1.1, `왼쪽으로 기움 ${mid.bodyZ}`);
  assert.ok(f.m.isPointing(100000 + 1000 + 1200));
  const up = f.at(1000 + 150).point;
  assert.ok(up > 0 && up < 1, `올라가는 중 ${up}`);
  assert.strictEqual(f.at(1000 + 1300).point, 0);
  assert.strictEqual(f.m.isPointing(100000 + 1000 + 1300), false);
  const g = fakeMotion([0.9]);
  g.m.setMood('happy', true);
  assert.strictEqual(g.m.point(1300, 100000), false, '기쁨일 때는 손짓 안 함');
});

check('createMotion: 말하기 — 말하는 동안 0.12(다문 입)~1(벌림)을 음절처럼 오가고, 안 할 때·끝난 뒤에는 0 (입 조각 없이 원래 그림)', () => {
  const f = fakeMotion([0.9]);
  assert.strictEqual(f.at(400).mouthOpen, 0, '말하기 전');
  f.m.talk(1800, 100000 + 500);
  let max = 0; let min = 1;
  for (let ms = 700; ms < 2100; ms += 10) { // 시작 0.12초·끝 0.15초 숨을 뺀 가운데
    const v = f.at(ms).mouthOpen;
    assert.ok(v >= 0.12 - 1e-9 && v <= 1, `말하는 동안 ${v}`);
    max = Math.max(max, v); min = Math.min(min, v);
  }
  assert.ok(min < 0.3 && max > 0.75, `다문 입~벌림을 오간다 ${min}~${max}`);
  assert.strictEqual(f.at(2400).mouthOpen, 0, '끝난 뒤');
  assert.strictEqual(f.m.talk(1800, 100000 + 3000), true);
});

check('createMotion: 바라보기 — 포인터 쪽으로 머리·눈이 부드럽게, 나가면 1초쯤에 돌아온다', () => {
  const f = fakeMotion([0.9]);
  f.m.lookAt(1, 0);
  let p;
  for (let ms = 0; ms <= 2000; ms += 16) p = f.at(ms);
  assert.ok(p.angleX > 0.5 && p.angleX < 0.85 && p.eyeX > 0.9, `머리 ${p.angleX} 눈 ${p.eyeX}`);
  f.m.lookAt(-0.5, -1); // 위쪽 왼쪽
  for (let ms = 2016; ms <= 4000; ms += 16) p = f.at(ms);
  assert.ok(p.angleX < 0 && p.angleY > 0.3 && p.eyeY > 0.5, `왼쪽·위: ${p.angleX} ${p.angleY} ${p.eyeY}`);
  f.m.lookAt(null);
  const start = p.eyeX;
  let t = 4000;
  for (; t <= 5000; t += 16) p = f.at(t);
  assert.ok(Math.abs(p.eyeX) < Math.abs(start) * 0.1 + 0.02 && Math.abs(p.eyeY) < 0.08, `1초 뒤 거의 제자리 ${p.eyeX} ${p.eyeY}`);
  f.m.lookAt(9, -9);
  for (let ms = 5016; ms <= 7000; ms += 16) p = f.at(ms);
  assert.ok(p.eyeX <= 1 && p.eyeY <= 1 && p.angleX <= 1 && p.angleY <= 1, '범위 안');
  f.m.lookAt(NaN, NaN); // 이상한 값도 깨지지 않는다
  assert.ok(Number.isFinite(f.at(7100).angleX));
});

check('createMotion: 효과 끔이면 모두 0 (눈은 뜸)이고 난수도 쓰지 않는다', () => {
  let calls = 0; let off = true;
  const f = fakeMotion(() => { calls += 1; return 0; }, { reduced: () => off });
  const created = calls;
  assert.strictEqual(f.m.point(1300), false);
  assert.strictEqual(f.m.talk(1000), false);
  f.m.setMood('happy');
  for (let ms = 0; ms < 8000; ms += 100) {
    const p = f.at(ms);
    for (const k of Object.keys(L.DEFAULTS)) assert.strictEqual(p[k], L.DEFAULTS[k], `${k} @${ms}`);
  }
  assert.strictEqual(calls, created, '효과 끔에서는 난수를 더 안 쓴다');
  off = false; // 다시 켜면 움직인다
  let moved = false;
  for (let ms = 8000; ms < 20000; ms += 100) if (f.at(ms).breath > 0.1) moved = true;
  assert.ok(moved);
});

check('createMotion: 모든 값은 항상 범위 안 (-1..1, breath·eyeOpen·mouthOpen·point는 0..1)', () => {
  let s = 12345;
  const f = fakeMotion(() => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; });
  f.m.lookAt(0.7, -0.4);
  for (let ms = 0; ms < 120000; ms += 33) {
    if (ms % 7000 === 0) f.m.setMood(['normal', 'happy', 'worried'][(ms / 7000) % 3]);
    if (ms % 11000 === 0) { f.m.point(1300, 100000 + ms); f.m.talk(1500, 100000 + ms); }
    const p = f.at(ms);
    for (const [k, v] of Object.entries(p)) {
      assert.ok(Number.isFinite(v), `${k}=${v}`);
      const [lo, hi] = ['breath', 'eyeOpen', 'mouthOpen', 'point'].includes(k) ? [0, 1] : [-1, 1];
      assert.ok(v >= lo - 1e-9 && v <= hi + 1e-9, `${k}=${v} @${ms}`);
    }
  }
});

// ---------------------------------------------------------------- 두 뼈대 (실제 파일)
function pngSize(file) {
  const b = fs.readFileSync(file);
  assert.strictEqual(b.toString('latin1', 1, 4), 'PNG', file);
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

function checkRigFile(label, dir, base) {
  const raw = JSON.parse(fs.readFileSync(path.join(dir, 'mascot.json'), 'utf8'));
  assert.ok(raw.rig, `${label}: mascot.json에 rig가 있어야 한다`);
  const m = raw.moods.normal;
  const blink = raw.anim && raw.anim.blink ? { src: base + raw.anim.blink.image, x: raw.anim.blink.x, y: raw.anim.blink.y, h: raw.anim.blink.h, eyesOnly: raw.anim.blink.eyesOnly === true } : undefined;
  const rig = L.cleanRig(raw.rig, { x: m.x, y: m.y, h: m.h }, { base, blink });
  assert.ok(rig, `${label}: rig가 cleanRig를 통과해야 한다`);
  const [w, h] = pngSize(path.join(dir, m.image));
  assert.deepStrictEqual([rig.size.w, rig.size.h], [w, h], `${label}: size가 평소 그림 크기와 같아야 한다`);
  for (const [name, mood] of Object.entries(raw.moods)) assert.deepStrictEqual(pngSize(path.join(dir, mood.image)), [w, h], `${label}: ${name} 그림 크기`);
  if (raw.anim && raw.anim.point) assert.deepStrictEqual(pngSize(path.join(dir, raw.anim.point.image)), [w, h], `${label}: point 그림 크기`);
  for (const [key, src] of Object.entries(rig.bases || {})) assert.deepStrictEqual(pngSize(path.join(dir, src.slice(base.length))), [w, h], `${label}: bases.${key} 그림 크기`);
  for (const l of rig.layers) if (l.src) assert.ok(fs.existsSync(path.join(dir, l.src.slice(base.length))), `${label}: 층 ${l.id} 그림 파일`);
  return rig;
}

check('기본 하나 뼈대(ui/assets/mascot/mascot.json)가 cleanRig를 통과하고 size가 그림 크기와 같다', () => {
  const rig = checkRigFile('기본 하나', path.join(root, 'ui', 'assets', 'mascot'), '/assets/mascot/');
  assert.strictEqual(rig.size.w, 530);
  assert.ok(rig.usesPoint, '손짓은 deformer로');
  const params = new Set(L.STANDARD.concat(rig.physics.map((p) => p.out)));
  for (const d of rig.deformers) assert.ok(params.has(d.param));
  assert.ok(!rig.deformers.some((d) => d.param === 'chest' || d.region === 'chest'), '흉부만 움직이는 deformer는 없다');
  const g = gridOf(rig);
  for (let i = 0; i < 40; i++) { // 극단 자세에서도 그물이 깨지지 않는다 (NaN·폭주 없음)
    const p = {}; for (const k of L.STANDARD) p[k] = ((i * 7 + k.length) % 3) - 1; p.hairSway = 1.5; p.skirtSway = -1.5; p.sideSway = 1.5;
    const o = L.deform(g, rig, p);
    for (const v of o) assert.ok(Number.isFinite(v) && Math.abs(v) < 5000);
  }
});

check('기본 하나 부위 층: 머리카락을 뗀 몸 그림(bases)·hair 층·눈·입 조각의 그림 파일과 크기, 층마다 알맞게 보이고 흔들린다', () => {
  const dir = path.join(root, 'ui', 'assets', 'mascot');
  const rig = checkRigFile('기본 하나', dir, '/assets/mascot/');
  assert.deepStrictEqual(Object.keys(rig.bases).sort(), ['happy', 'normal', 'point', 'worried']);
  for (const [k, src] of Object.entries(rig.bases)) assert.strictEqual(src, `/assets/mascot/${k}-nohair.png`);
  assert.deepStrictEqual(rig.layers.map((l) => l.id), ['base', 'hairR', 'eyesHalf', 'blink', 'mouthClosed', 'mouthHalf'], '몸 → 머리카락 → 눈·입 조각 순서');
  const layer = Object.fromEntries(rig.layers.map((l) => [l.id, l]));
  // 각 층 그림의 크기는 층 자리와 맞고 (넓이는 그림 비율), 뼈대 안에 들어간다
  for (const l of rig.layers.filter((x) => x.src)) {
    const [w, h] = pngSize(path.join(dir, l.src.slice('/assets/mascot/'.length)));
    assert.strictEqual(h, Math.round(l.h), `${l.id}: 그림 높이 ${h} = 층 h ${l.h}`);
    assert.ok(l.x >= 0 && l.y >= 0 && l.x + w <= rig.size.w && l.y + h <= rig.size.h, `${l.id} 자리가 뼈대 안`);
  }
  assert.deepStrictEqual(pngSize(path.join(dir, 'hair.png')), [530, 800], 'hair 층은 뼈대 전체 크기');
  // 머리카락 흔들기는 머리카락 층에만 (base에는 이제 긴 머리가 없어 옷을 휘면 안 된다). 옆머리·머리·몸 전체는 모든 층
  const sway = rig.deformers.find((d) => d.param === 'hairSway');
  assert.deepStrictEqual(sway.layers, ['hairR']);
  assert.ok(sway.falloff, '뿌리는 거의 안 움직이고 끝이 더 흔들린다');
  for (const d of rig.deformers.filter((x) => x.param !== 'hairSway')) assert.strictEqual(d.layers, null, `${d.param}는 모든 층에 (머리카락 층도 머리와 함께)`);
  const g0 = L.buildGrid(rig, { x: 0, y: 0, w: 530, h: 800 }, { cols: rig.grid.cols, rows: rig.grid.rows, layer: 'base' });
  const swayIndex = rig.deformers.indexOf(sway);
  assert.strictEqual(g0.w[swayIndex], null, 'base는 hairSway 무게를 계산조차 안 한다');
  const gh = L.buildGrid(rig, { x: 0, y: 0, w: 530, h: 800 }, { cols: rig.grid.cols, rows: rig.grid.rows, layer: 'hairR' });
  const at = (x, y) => (Math.round(y / (800 / gh.rows)) * (gh.cols + 1)) + Math.round(x / (530 / gh.cols));
  assert.ok(gh.w[swayIndex][at(360, 120)] < 0.02, '머리카락 뿌리 위쪽은 안 움직인다');
  assert.ok(gh.w[swayIndex][at(500, 400)] > 0.6, '머리카락 끝은 크게');
  assert.ok(gh.w[swayIndex][at(350, 420)] < 0.05, '팔꿈치 옆(원래 팔 뒤에 있던 머리)은 거의 안 움직인다');
  // 눈: eyeOpen 1 = 원래 그림, 반쯤 = eyes-half, 감김 = blink (깜빡이는 동안 원래 → 반쯤 → 감김이 끊기지 않게 겹친다). 입: 가만히는 조각 없음
  const a = (id, param, v) => L.showAlpha(layer[id].show, { [param]: v });
  assert.deepStrictEqual([a('eyesHalf', 'eyeOpen', 1), a('blink', 'eyeOpen', 1)], [0, 0], '눈을 뜨면 조각 없음');
  assert.deepStrictEqual([a('eyesHalf', 'eyeOpen', 0.6), a('blink', 'eyeOpen', 0.6)], [1, 0], '반쯤');
  assert.deepStrictEqual([a('eyesHalf', 'eyeOpen', 0), a('blink', 'eyeOpen', 0)], [0, 1], '감김');
  for (let v = 0; v <= 1.0001; v += 0.05) assert.ok(a('eyesHalf', 'eyeOpen', v) + a('blink', 'eyeOpen', v) > 0 || v > 0.84, `눈 뜸 ${v.toFixed(2)}: 원래 눈이 비쳐 보이지 않게 조각이 이어진다`);
  assert.deepStrictEqual([a('mouthClosed', 'mouthOpen', 0), a('mouthHalf', 'mouthOpen', 0)], [0, 0], '가만히(0)는 조각 없음 = 원래 벌린 웃음');
  assert.deepStrictEqual([a('mouthClosed', 'mouthOpen', 0.2), a('mouthHalf', 'mouthOpen', 0.2)], [1, 0], '다문 입');
  assert.deepStrictEqual([a('mouthClosed', 'mouthOpen', 0.55), a('mouthHalf', 'mouthOpen', 0.55)], [0, 1], '반쯤');
  assert.deepStrictEqual([a('mouthClosed', 'mouthOpen', 0.95), a('mouthHalf', 'mouthOpen', 0.95)], [0, 0], '벌림 = 원래 그림');
  for (const id of ['eyesHalf', 'blink', 'mouthClosed', 'mouthHalf']) assert.deepStrictEqual(layer[id].moods, ['normal'], `${id}는 평소 얼굴일 때만`);
  assert.ok(!layer.base.src && rig.layers[0].id === 'base');
});

check('사장님 그림 뼈대 (진짜 data/assets/mascot 또는 연습용 사본에 있을 때)가 cleanRig를 통과하고 size가 그림 크기와 같다', () => {
  const candidates = [path.join(root, 'data', 'assets', 'mascot'), path.join(process.env.AIS_FAKE2 || path.join(os.tmpdir(), 'ais-fake2'), 'data', 'assets', 'mascot')];
  const found = candidates.find((dir) => {
    try { return JSON.parse(fs.readFileSync(path.join(dir, 'mascot.json'), 'utf8')).rig; } catch (_) { return false; }
  });
  if (!found) { console.log('    (사장님 그림 뼈대 없음 — 건너뜀)'); return; }
  const rig = checkRigFile('사장님 그림', found, '/assets/custom/mascot/');
  // A full-body blink needs a mask; a cropped eye patch is already bounded.
  const blink = rig.layers.find((l) => l.id === 'blink');
  if (blink && blink.src) {
    const dimensions = pngSize(path.join(found, blink.src.slice('/assets/custom/mascot/'.length)));
    if (dimensions[1] === rig.size.h) assert.ok(blink.mask, '전신 눈 감은 그림은 눈 영역 마스크 필요');
  }
});

// ---------------------------------------------------------------- 그리기 켜고 끄기 (가짜 DOM·가짜 GL)
function installFakeDom() {
  const calls = { draw: 0, clear: 0, upload: 0, sub: 0 };
  const rafs = []; const timers = [];
  let now = 1000;
  const glProxy = () => new Proxy({}, {
    get(_, k) {
      if (typeof k !== 'string') return undefined;
      if (k === k.toUpperCase()) return 1;
      if (k === 'getShaderParameter' || k === 'getProgramParameter') return () => true;
      if (k === 'getExtension') return () => null;
      if (k === 'drawElements') return () => { calls.draw += 1; };
      if (k === 'clear') return () => { calls.clear += 1; };
      if (k === 'texImage2D') return () => { calls.upload += 1; };
      if (k === 'bufferSubData') return () => { calls.sub += 1; };
      return () => ({});
    },
  });
  const listeners = {};
  const doc = {
    hidden: false,
    documentElement: { className: '' },
    createElement: () => ({
      style: { setProperty() {} }, listeners: {}, width: 0, height: 0,
      getContext: () => glProxy(),
      getBoundingClientRect: () => ({ left: 100, top: 50, width: 258, height: 360 }),
      setAttribute() {}, remove() {}, addEventListener() {}, removeEventListener() {},
    }),
    addEventListener: (k, f) => { (listeners[k] = listeners[k] || []).push(f); },
    removeEventListener() {},
  };
  const images = [];
  globalThis.document = doc;
  globalThis.window = { devicePixelRatio: 3, addEventListener() {}, removeEventListener() {} };
  globalThis.Image = class { constructor() { this.naturalWidth = 530; this.naturalHeight = 800; images.push(this); } };
  globalThis.requestAnimationFrame = (f) => { rafs.push(f); return rafs.length; };
  globalThis.cancelAnimationFrame = () => {};
  globalThis.MutationObserver = class { observe() {} disconnect() {} };
  globalThis.performance = { now: () => now };
  return {
    calls, doc, images, listeners,
    pending: () => rafs.length,
    step(ms = 16) { now += ms; const f = rafs.splice(0); f.forEach((fn) => fn(now)); },
    load() { images.forEach((i) => i.onload && i.onload()); },
  };
}

check('인형 그리기: 보일 때만 돌고, 안 보이면(판을 떠남·창 숨김) 멈추고, 효과 끔이면 한 장만 그리고 멈춘다', () => {
  const env = installFakeDom();
  assert.strictEqual(Puppet.supported(), true);
  const host = { append() {}, isConnected: true };
  let calm = false;
  const rig = clean();
  const cfg = { rig, box: { w: 396, h: 560 }, normal: NORMAL, images: { normal: '/a/n.png', happy: '/a/h.png', worried: '/a/w.png', point: '/a/p.png' }, pad: 8 };
  const pup = Puppet.create(host, cfg, { reduced: () => calm });
  assert.ok(pup);
  env.load();
  assert.strictEqual(env.pending(), 0, '보이기 전(setActive 전)에는 그리지 않는다');
  pup.setActive(true);
  assert.strictEqual(env.pending(), 1);
  env.step(); env.step(); env.step();
  assert.ok(env.pending() === 1, '보이는 동안 계속 돈다');
  assert.ok(env.calls.draw >= 3, `그렸다 ${env.calls.draw}`);
  assert.ok(env.calls.upload >= 1, '그림 올리기');
  pup.setActive(false);
  env.step();
  const drawn = env.calls.draw;
  assert.strictEqual(env.pending(), 0, '판을 떠나면 멈춘다');
  env.step(); assert.strictEqual(env.calls.draw, drawn);
  pup.setActive(true); env.step();
  assert.strictEqual(env.pending(), 1, '다시 보이면 다시 돈다');
  env.doc.hidden = true;
  env.step();
  assert.strictEqual(env.pending(), 0, '창이 숨으면 멈춘다');
  env.doc.hidden = false; env.doc.documentElement.className = 'x'; // 깨우기 (visibilitychange)
  (env.listeners.visibilitychange || []).forEach((f) => f());
  assert.strictEqual(env.pending(), 1);
  calm = true; env.step();
  assert.strictEqual(env.pending(), 0, '효과 끔: 한 장만 그리고 멈춘다');
  const still = env.calls.draw;
  pup.setMood('happy'); env.step();
  assert.ok(env.calls.draw > still && env.pending() === 0, '효과 끔에서도 표정이 바뀌면 한 장 다시 그리고 멈춘다');
  calm = false; pup.setMood('normal'); env.step();
  assert.strictEqual(env.pending(), 1, '효과를 다시 켜면 돈다');
  pup.setPose({ angleZ: 1 }); env.step();
  assert.strictEqual(env.pending(), 0, '멈춘 자세(pose)는 한 장만');
  assert.strictEqual(pup.params().angleZ, 1);
  assert.ok(Math.abs(pup.params().hairSway - 0.6) < 1e-9, '멈춘 자세의 물리 out은 입력이 그대로일 때의 자리');
  pup.setPose(null); env.step();
  assert.strictEqual(env.pending(), 1);
  pup.destroy();
  env.step();
  assert.strictEqual(env.pending(), 0);
});

check('인형: 뼈대의 bases가 있으면 base가 표정 그림 대신 그 그림을 쓴다 (없는 표정은 원래 그림)', () => {
  const env = installFakeDom();
  const host = { append() {}, isConnected: true };
  const rig = clean({ bases: { normal: 'nohair.png' } });
  const pup = Puppet.create(host, { rig, box: { w: 396, h: 560 }, normal: NORMAL, images: { normal: '/a/n.png', happy: '/a/h.png', worried: '/a/w.png', point: null } }, {});
  const srcs = env.images.map((i) => i.src);
  assert.ok(!srcs.includes(null) && !srcs.includes('null') && !srcs.includes(undefined), '손짓 그림이 없으면(null) 그림을 읽으려 하지 않는다');
  assert.ok(srcs.includes('/a/nohair.png') && srcs.includes('/a/h.png'), srcs.join(','));
  assert.ok(!srcs.includes('/a/n.png'), '평소 그림은 원래 그림을 안 읽는다');
  pup.destroy();
});

console.log(`인형 엔진 점검 통과 (${n}개)`);
