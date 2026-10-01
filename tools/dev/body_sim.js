// 몸 조절 막대 점검 (브라우저 없이 Node로 ui/looks.js의 계산만 돌린다).
//
//   node tools/dev/body_sim.js
//
// 가짜 서 있는 사람·앉은 사람 모양(줄마다 왼쪽·오른쪽 끝)에 막대 값을 넣어 Looks.bodyPlan을 확인한다:
// - 막대가 모두 0이면 아무것도 바뀌지 않는다 (배율 1, 프레임 크기 그대로)
// - 막대 끝값에서 배율이 정한 크기를 넘지 않는다 (자연스러운 범위: 한 단계 3~5%)
// - 발끝은 새 프레임 바닥에서 같은 자리 (여백 그대로), 앉은 자세는 키(다리)를 안 바꾼다
// - 뒷모습은 가슴 그대로, 옆모습은 가슴이 바라보는 쪽만, 여성형·남성형이 어깨·골반을 반대로 바꾼다
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ui = path.resolve(__dirname, '..', '..', 'ui');
const sandbox = { console, Math, JSON, Object, Array, Set, Map, Promise, String, Number, Int16Array, Float32Array };
vm.createContext(sandbox);
vm.runInContext(`${fs.readFileSync(path.join(ui, 'looks.js'), 'utf8')}\nthis.Looks = Looks;`, sandbox);
const { Looks } = sandbox;

const problems = [];
const check = (ok, text) => { if (!ok) problems.push(text); };
const near = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;

// 가짜 모양: 폭 200, 높이 360, 위 여백 5줄, 발끝 아래 여백 4줄. 머리는 넓고(0~40%) 몸통·다리는 좁다.
const FW = 200;
const FH = 360;
function person(seated = false) {
  const left = new Int16Array(FH).fill(-1);
  const right = new Int16Array(FH).fill(-1);
  const top = 5;
  const bottom = FH - 5;
  for (let y = top; y <= bottom; y++) {
    const t = (y - top) / (bottom - top);
    const half = t < 0.4 ? 60 : seated ? 50 : t < 0.7 ? 40 : 30;
    left[y] = 100 - half;
    right[y] = 100 + half - 1;
  }
  return { left, right, top, bottom };
}
const zero = Looks.bodyOf({});
const plan = (b, action = 'step', facing = 'right', seated = false) => {
  const p = person(seated || ['work', 'rest', 'frozen'].includes(action));
  return { p, r: Looks.bodyPlan(p, FW, FH, { ...zero, ...b }, action, facing, 350) };
};
const extremes = (r) => {
  let lo = 9;
  let hi = 0;
  for (const pair of r.sx) for (const s of pair) { lo = Math.min(lo, s); hi = Math.max(hi, s); }
  return [lo, hi];
};

// 1) 모두 0
{
  const { r } = plan({});
  const [lo, hi] = extremes(r);
  check(near(lo, 1) && near(hi, 1) && r.head === 1 && r.legs === 1, '막대 0인데 배율이 1이 아님');
  check(r.fh2 === FH && r.legsDelta === 0 && r.headDelta === 0, `막대 0인데 높이가 바뀜 (${r.fh2})`);
  console.log(`막대 0: 배율 ${lo}~${hi}, 프레임 ${r.fw2}x${r.fh2} (여백 ${r.margin})`);
}

// 2) 막대 하나씩 끝값: 한 단계 크기 × 끝값을 넘지 않는다
const STEP = { build: 0.04, shoulders: 0.05, waist: 0.05, hips: 0.05, chest: 0.03 };
const RANGE = { build: [-2, 2], shoulders: [-2, 2], waist: [-2, 2], hips: [-2, 2], chest: [0, 2] };
for (const [k, step] of Object.entries(STEP)) {
  for (const v of RANGE[k]) {
    if (!v) continue;
    const { r } = plan({ [k]: v }, 'call');
    const [lo, hi] = extremes(r);
    const want = 1 + step * v;
    const got = v > 0 ? hi : lo;
    check(near(got, want, 0.004) && Math.abs(got - 1) <= Math.abs(want - 1) + 1e-9, `${k} ${v}: 가장 큰 배율 ${got.toFixed(3)} (정한 값 ${want.toFixed(3)})`);
    check(lo >= 0.8 - 1e-9 && hi <= 1.25 + 1e-9, `${k} ${v}: 배율이 0.8~1.25 밖`);
    console.log(`${k.padEnd(9)} ${String(v).padStart(2)}: 배율 ${lo.toFixed(3)}~${hi.toFixed(3)}`);
  }
}

// 3) 키·머리: 서 있으면 다리가 늘고 발끝 아래 여백은 그대로, 앉으면 다리 그대로
for (const v of [-2, 2]) {
  const { p, r } = plan({ height: v, head: v });
  const marginBefore = FH - 1 - p.bottom;
  const marginAfter = r.fh2 - 1 - (p.bottom + (r.fh2 - FH));
  check(marginBefore === marginAfter, `키 ${v}: 발끝 아래 여백이 바뀜`);
  check(near(r.legs, 1 + 0.05 * v) && near(r.head, 1 + 0.05 * v), `키·머리 ${v}: 배율 ${r.legs}, ${r.head}`);
  const seated = plan({ height: v }, 'work');
  check(seated.r.legs === 1 && seated.r.legsDelta === 0, `앉은 자세인데 키가 바뀜 (${v})`);
  console.log(`키·머리 ${String(v).padStart(2)}: 다리 ${r.legs.toFixed(2)}배(+${r.legsDelta}줄), 머리 ${r.head.toFixed(2)}배(${r.headDelta}줄), 앉은 자세 다리 ${seated.r.legs}배`);
}

// 4) 가슴: 뒷모습은 그대로, 옆모습은 바라보는 쪽만, 정면은 양쪽
{
  const back = extremes(plan({ chest: 2 }, 'work').r);
  check(near(back[1], 1), '뒷모습인데 가슴이 바뀜');
  const side = plan({ chest: 2 }, 'step', 'right').r;
  const front = side.sx.reduce((m, [l, r]) => Math.max(m, r), 1);
  const rear = side.sx.reduce((m, [l]) => Math.max(m, l), 1);
  check(front > 1.1 && near(rear, 1), `옆모습 가슴: 앞 ${front.toFixed(3)} · 뒤 ${rear.toFixed(3)}`);
  const leftFacing = plan({ chest: 2 }, 'walk', 'left').r;
  check(leftFacing.sx.reduce((m, [l]) => Math.max(m, l), 1) > 1.1, '왼쪽을 보는데 가슴이 왼쪽으로 안 나옴');
  console.log(`가슴 +2: 뒷모습 ${back[1].toFixed(3)} · 옆모습 앞 ${front.toFixed(3)}/뒤 ${rear.toFixed(3)}`);
}

// 5) 여성형·남성형: 어깨 띠와 골반 띠가 반대로
{
  const fem = plan({ shoulders: -1, chest: 1, waist: -1, hips: 1 }, 'call').r;
  const mas = plan({ shoulders: 1, hips: -1 }, 'call').r;
  const at = (r, k) => r.sx[Math.round(r.lines[k])][0];
  check(at(fem, 'shoulders') < 1 && at(fem, 'hips') > 1, '여성형: 어깨가 좁고 골반이 넓어야');
  check(at(mas, 'shoulders') > 1 && at(mas, 'hips') < 1, '남성형: 어깨가 넓고 골반이 좁아야');
  console.log(`여성형 어깨 ${at(fem, 'shoulders').toFixed(3)} 골반 ${at(fem, 'hips').toFixed(3)} · 남성형 어깨 ${at(mas, 'shoulders').toFixed(3)} 골반 ${at(mas, 'hips').toFixed(3)}`);
}

// 6) 범위 밖 값은 잘린다 (bodyOf)
{
  const b = Looks.bodyOf({ chest: 9, waist: -7, head: '2', height: 'tall', hips: 1.8 });
  check(b.chest === 2 && b.waist === -2 && b.head === 2 && b.height === 0 && b.hips === 1, `범위 자르기: ${JSON.stringify(b)}`);
}

console.log(problems.length ? `문제: ${problems.join(' / ')}` : '몸 조절 점검 통과');
process.exitCode = problems.length ? 1 : 0;
