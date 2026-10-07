// 진행판 계산 점검 (브라우저 없이): node tools/dev/board_sim.js
// ui/board.js의 순수 계산(칸 나누기·지시별 진행·보드 앞면·바뀐 단계·캐릭터 설정 검사)만 확인한다. 화면은 캡처로 본다.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

// 인형 엔진(ui/puppet.js): 브라우저에서는 board.js보다 먼저 읽힌 전역. 뼈대(rig) 검사가 이것을 쓴다
const Puppet = require(path.join(__dirname, '..', '..', 'ui', 'puppet.js'));
globalThis.Puppet = Puppet;
const Board = require(path.join(__dirname, '..', '..', 'ui', 'board.js'));
const L = Board.logic;

let n = 0;
function check(name, fn) { fn(); n += 1; console.log(`  ✓ ${name}`); }

const T = (id, status, extra = {}) => ({
  id, status, kind: 'build', project: 'core', title: id, created_at: `2026-09-29T10:${id.slice(-2)}:00`, updated_at: `2026-09-29T11:${id.slice(-2)}:00`, ...extra,
});

check('칸 나누기: 단계별 칸, 막힘은 작업 중 칸 맨 위, 취소·보관은 안 보임', () => {
  const tasks = [T('T01', 'ready'), T('T02', 'queued'), T('T03', 'running'), T('T04', 'blocked'), T('T05', 'checking'),
    T('T06', 'awaiting_approval'), T('T07', 'done'), T('T08', 'cancelled'), T('T09', 'done', { archived: true })];
  const cols = Object.fromEntries(L.columns(tasks).map((c) => [c.key, c.tasks.map((t) => t.id)]));
  assert.deepStrictEqual(cols, { waiting: ['T01', 'T02'], running: ['T04', 'T03'], checking: ['T05'], awaiting: ['T06'], done: ['T07'] });
});

check('완료 칸: 기획 카드는 빼고 최근 5개만, 개수는 전체', () => {
  const tasks = Array.from({ length: 11 }, (_, i) => T(`T${String(i + 10)}`, 'done'));
  tasks.push(T('T99', 'done', { kind: 'plan' }));
  const done = L.columns(tasks).find((c) => c.key === 'done');
  assert.strictEqual(done.total, 11);
  assert.strictEqual(done.tasks.length, 5);
  assert.strictEqual(done.tasks[0].id, 'T20', '가장 최근에 끝난 것이 맨 위');
  assert.ok(!done.tasks.some((t) => t.kind === 'plan'));
});

check('프로젝트 거르기', () => {
  const tasks = [T('T01', 'ready'), T('T02', 'ready', { project: 'docs' })];
  assert.deepStrictEqual(L.columns(tasks, 'docs')[0].tasks.map((t) => t.id), ['T02']);
});

check('지시별 진행: 기획에서 나온 퀘스트를 세고, 나머지는 따로 맡긴 일 (보관한 기획의 퀘스트 포함)', () => {
  const tasks = [
    T('T01', 'done', { kind: 'plan' }), T('T02', 'done', { parent: 'T01' }), T('T03', 'running', { parent: 'T01' }), T('T04', 'blocked', { parent: 'T01' }),
    T('T05', 'awaiting_approval', { kind: 'plan' }), // 아직 퀘스트가 없는 기획 → 줄 없음
    T('T06', 'done', { kind: 'plan', archived: true }), T('T07', 'done', { parent: 'T06' }),
    T('T08', 'ready'), T('T09', 'cancelled', { parent: 'T01' }),
  ];
  const g = L.groups(tasks);
  assert.deepStrictEqual(g.map((x) => [x.key, x.done, x.total, x.pct, x.blocked]), [['T01', 1, 3, 33, 1], ['loose', 1, 2, 50, 0]]);
  assert.strictEqual(L.headline(tasks).key, 'T01', '안 끝난 가장 최근 지시');
});

check('보드 앞면: 모두 끝났으면 가장 최근 지시, 일이 없으면 없음', () => {
  const tasks = [T('T01', 'done', { kind: 'plan' }), T('T02', 'done', { parent: 'T01' })];
  assert.strictEqual(L.headline(tasks).pct, 100);
  assert.strictEqual(L.headline([]), null);
});

check('바뀐 단계: 처음 읽을 때는 알리지 않고, 바뀐 것·새 일만', () => {
  const a = [T('T01', 'ready'), T('T02', 'running')];
  assert.deepStrictEqual(L.changes(null, a), []);
  const prev = L.snapshot(a);
  const b = [T('T01', 'running'), T('T02', 'running'), T('T03', 'queued', { kind: 'plan' }), T('T04', 'cancelled')];
  assert.deepStrictEqual(L.changes(prev, b).map((c) => [c.task.id, c.from, c.to]), [['T01', 'ready', 'running'], ['T03', null, 'queued']]);
});

check('표정: 결재·완료는 기쁨, 막힘은 걱정', () => {
  assert.deepStrictEqual(['done', 'awaiting_approval', 'blocked', 'checking'].map(L.moodFor), ['happy', 'happy', 'worried', 'normal']);
});

check('기본 캐릭터 설정 파일이 규격에 맞고 그림 파일이 있다', () => {
  const dir = path.join(__dirname, '..', '..', 'ui', 'assets', 'mascot');
  const cfg = L.cleanMascot(JSON.parse(fs.readFileSync(path.join(dir, 'mascot.json'), 'utf8')), '/assets/mascot/');
  assert.ok(cfg, '기본 설정이 검사를 통과해야 한다');
  for (const m of Object.values(cfg.moods)) assert.ok(fs.existsSync(path.join(dir, m.src.replace('/assets/mascot/', ''))), m.src);
  assert.strictEqual(cfg.name, '하나');
  assert.deepStrictEqual([cfg.board.stand, cfg.board.behind], ['pole', true], '기상 캐스터: 기둥 판이 캐릭터 뒤');
  // 움직임 그림 (여덟 번째 세션): 눈 깜빡임 조각·손짓 전신
  assert.deepStrictEqual(Object.keys(cfg.anim).sort(), ['blink', 'point']);
  for (const m of Object.values(cfg.anim)) assert.ok(fs.existsSync(path.join(dir, m.src.replace('/assets/mascot/', ''))), m.src);
  assert.ok(cfg.anim.blink.h < 60, '깜빡임은 눈 둘레 조각만');
});

check('캐릭터 설정 검사: 이상한 파일 이름·판·숫자는 막거나 상자 안으로', () => {
  const ok = { version: 1, box: { w: 300, h: 400 }, board: { x: 150, y: 20, w: 400, h: 200 }, moods: { normal: { image: 'a.png', h: 300 } } };
  const c = L.cleanMascot(ok, '/assets/custom/mascot/');
  assert.strictEqual(c.board.w, 150, '판이 상자 밖으로 나가지 않는다');
  assert.strictEqual(c.moods.happy.src, '/assets/custom/mascot/a.png', '없는 표정은 평소 그림');
  assert.strictEqual(c.name, '진행 요원');
  for (const bad of ['../x.png', 'a/b.png', 'x.svg', 'x.png?y', '']) {
    assert.strictEqual(L.cleanMascot({ ...ok, moods: { normal: { image: bad, h: 300 } } }, '/'), null, bad);
  }
  assert.strictEqual(L.cleanMascot({ ...ok, version: 2 }, '/'), null, '모르는 판');
  assert.strictEqual(L.cleanMascot({ ...ok, board: { x: 'a', y: 0, w: 100, h: 100 } }, '/'), null, '숫자가 아님');
  assert.strictEqual(L.cleanMascot({ ...ok, board: { x: 280, y: 0, w: 100, h: 100 } }, '/'), null, '판이 너무 작아짐');
  assert.strictEqual(L.cleanMascot({}, '/'), null, '빈 설정 (사장님 그림 없음)');
  assert.strictEqual(L.cleanMascot({ ...ok, name: '아주아주아주아주긴이름입니다요' }, '/').name.length, 12);
  // 받침·앞뒤·표정마다 판 자리
  const stand = (v) => L.cleanMascot({ ...ok, board: { ...ok.board, stand: v } }, '/').board.stand;
  assert.deepStrictEqual([stand('pole'), stand(true), stand('easel'), stand('x'), stand(undefined)], ['pole', 'easel', 'easel', null, null]);
  assert.strictEqual(L.cleanMascot({ ...ok, board: { ...ok.board, behind: true } }, '/').board.behind, true);
  const per = L.cleanMascot({ ...ok, moods: { normal: { image: 'a.png', h: 300, board: { x: 10, y: 10, w: 100, h: 90 } }, happy: { image: 'b.png', h: 300, board: { x: 'no' } } } }, '/');
  assert.deepStrictEqual([per.moods.normal.board.w, per.moods.happy.board.w], [100, 150], '틀린 표정 판 자리는 공통 판 자리로');
  // 움직임 그림은 없어도 되고, 이상한 이름은 버린다
  assert.deepStrictEqual(c.anim, {});
  const an = L.cleanMascot({ ...ok, anim: { blink: { image: 'e.png', x: 10, y: 20, h: 12 }, point: { image: '../x.png', h: 300 }, wave: { image: 'w.png', h: 300 } } }, '/m/');
  assert.deepStrictEqual(an.anim, { blink: { src: '/m/e.png', x: 10, y: 20, h: 12 } });
  const full = L.cleanMascot({ ...ok, anim: { blink: { image: 'closed.png', h: 300, eyesOnly: true }, chest: { image: 'a.png', h: 300 } } }, '/m/');
  assert.strictEqual(full.anim.blink.eyesOnly, true);
  assert.strictEqual(full.anim.chest.src, '/m/a.png');
});

// ---------------------------------------------------------------- 뼈대(rig): 인형 엔진 (docs/design/mascot.md '뼈대')
check('기본 캐릭터의 뼈대(rig)가 검사를 통과해 cfg.rig가 된다 (눈 조각은 뼈대 좌표의 blink 층으로)', () => {
  const dir = path.join(__dirname, '..', '..', 'ui', 'assets', 'mascot');
  const cfg = L.cleanMascot(JSON.parse(fs.readFileSync(path.join(dir, 'mascot.json'), 'utf8')), '/assets/mascot/');
  assert.ok(cfg.rig, 'rig가 있어야 한다');
  assert.strictEqual(cfg.rigBad, false);
  assert.deepStrictEqual([cfg.rig.size.w, cfg.rig.size.h], [530, 800]);
  const blink = cfg.rig.layers.find((l) => l.id === 'blink');
  assert.strictEqual(blink.src, '/assets/mascot/blink.png');
  assert.deepStrictEqual([blink.x, blink.y, blink.h], [300, 116, 40], '상자 좌표 (258,149.6,24) → 뼈대 좌표');
  assert.deepStrictEqual(cfg.anim.chest, undefined, '기본 캐릭터에는 흉부 조각이 없다');
});

check('뼈대가 없으면 rig null (경고 없음), 잘못된 뼈대는 rig null + rigBad (예전 CSS 움직임 + 경고), 나머지 설정은 그대로', () => {
  const ok = { version: 1, box: { w: 300, h: 400 }, board: { x: 150, y: 20, w: 100, h: 200 }, moods: { normal: { image: 'a.png', h: 300 } } };
  const none = L.cleanMascot(ok, '/');
  assert.deepStrictEqual([none.rig, none.rigBad], [null, false]);
  const rig = { version: 1, size: { w: 100, h: 200 }, deformers: [{ type: 'shift', region: '*', param: 'angleX', kx: 3 }] };
  const good = L.cleanMascot({ ...ok, rig }, '/m/');
  assert.ok(good.rig && !good.rigBad);
  assert.strictEqual(good.moods.normal.src, '/m/a.png');
  for (const bad of [{ ...rig, version: 2 }, { ...rig, deformers: [{ type: 'twirl', region: '*', param: 'angleX' }] }, { ...rig, size: { w: 'a', h: 5 } }, 'x', 5, null]) {
    const c = L.cleanMascot({ ...ok, rig: bad }, '/');
    assert.ok(c, '뼈대가 틀려도 설정 자체는 살아 있다 (예전 CSS 움직임)');
    assert.deepStrictEqual([c.rig, c.rigBad], [null, true], JSON.stringify(bad));
    assert.strictEqual(c.moods.normal.src, '/a.png');
  }
  // 뼈대의 그림 이름 규칙도 board.js와 같다 (층 그림·bases)
  const layers = [{ id: 'base' }, { id: 'l', image: '../x.png', x: 0, y: 0, h: 10 }];
  assert.strictEqual(L.cleanMascot({ ...ok, rig: { ...rig, layers } }, '/').rigBad, true);
  assert.strictEqual(L.cleanMascot({ ...ok, rig: { ...rig, bases: { normal: 'b.png' } } }, '/m/').rig.bases.normal, '/m/b.png');
});

check('인형 엔진이 없어도(node·읽기 실패) cleanMascot이 깨지지 않는다', () => {
  const ok = { version: 1, box: { w: 300, h: 400 }, board: { x: 150, y: 20, w: 100, h: 200 }, moods: { normal: { image: 'a.png', h: 300 } } };
  delete globalThis.Puppet;
  try {
    const c = L.cleanMascot({ ...ok, rig: { version: 1, size: { w: 100, h: 200 } } }, '/');
    assert.ok(c);
    assert.deepStrictEqual([c.rig, c.rigBad], [null, false], '엔진이 없으면 뼈대를 못 쓸 뿐, 경고 없이 예전 움직임');
  } finally { globalThis.Puppet = Puppet; }
});

// ---- 홈·진행판 새 기능 (2026-10-05): 보기 칩 · 묶기 · 찾기 · 얼마 전 · 표 파일
const NOW = Date.parse('2026-10-05T12:00:00');
const day = (n) => new Date(NOW - n * 86400000).toISOString();

check('보기 칩 개수: 열린 일만, 전체 = 열린 일 수 (끝난 일·취소·보관은 안 센다), 프로젝트 거름 안에서', () => {
  const tasks = [
    T('T01', 'ready', { created_at: day(5) }), T('T02', 'awaiting_approval', { created_at: day(1) }), T('T03', 'blocked', { created_at: day(4) }),
    T('T04', 'running', { created_at: day(0) }), T('T05', 'done', { created_at: day(9) }), T('T06', 'cancelled', { created_at: day(9) }),
    T('T07', 'ready', { project: 'docs', created_at: day(3) }),
  ];
  assert.deepStrictEqual(L.viewCounts(tasks, null, NOW), { all: 5, approval: 1, blocked: 1, old: 3 });
  assert.deepStrictEqual(L.viewCounts(tasks, 'docs', NOW), { all: 1, approval: 0, blocked: 0, old: 1 });
  assert.strictEqual(L.inView(T('T09', 'done', { created_at: day(30) }), 'old', NOW), false, '끝난 일은 오래된 일이 아니다');
  assert.strictEqual(L.inView(T('T09', 'ready', { created_at: day(3) }), 'old', NOW), true, '3일부터 오래된 일');
  assert.strictEqual(L.inView(T('T09', 'ready', { created_at: day(2) }), 'old', NOW), false);
  assert.strictEqual(L.ageDays({ created_at: '엉망' }, NOW), 0, '시각을 모르면 0일');
});

check('columns 옵션: 보기·찾기·끝난 일 개수·프로젝트별 묶기 (순서는 그대로 유지)', () => {
  const tasks = [
    T('T01', 'ready', { project: 'docs', title: '보고서 쓰기' }), T('T02', 'ready', { project: 'core', title: 'HUD 만들기' }), T('T03', 'ready', { project: 'docs', title: '표지' }),
    T('T04', 'awaiting_approval', { title: '결재 HUD' }), ...Array.from({ length: 7 }, (_, i) => T(`T1${i}`, 'done')),
  ];
  const ids = (cols, key) => cols.find((c) => c.key === key).tasks.map((t) => t.id);
  assert.deepStrictEqual(ids(L.columns(tasks, null, { view: 'approval', now: NOW }), 'waiting'), [], '결재 기다림 보기에는 대기 칸이 비는다');
  assert.deepStrictEqual(ids(L.columns(tasks, null, { view: 'approval', now: NOW }), 'awaiting'), ['T04']);
  assert.deepStrictEqual(L.columns(tasks, null, { view: 'approval', now: NOW }).find((c) => c.key === 'done').total, 0, '끝난 일은 열린 일 보기에서 안 보인다');
  assert.deepStrictEqual(ids(L.columns(tasks, null, { query: 'hud' }), 'waiting'), ['T02'], '찾기: 대소문자 무시');
  assert.deepStrictEqual(ids(L.columns(tasks, null, { query: '보고서 쓰기' }), 'waiting'), ['T01'], '찾기: 띄어쓰기로 나눈 낱말이 모두 있어야');
  assert.deepStrictEqual(ids(L.columns(tasks, null, { query: '없는말' }), 'waiting'), []);
  const done = L.columns(tasks, null, { doneLimit: 3 }).find((c) => c.key === 'done');
  assert.strictEqual(done.tasks.length, 3);
  assert.strictEqual(done.total, 7);
  assert.deepStrictEqual(ids(L.columns(tasks, null, { group: true }), 'waiting'), ['T02', 'T01', 'T03'], '묶으면 프로젝트별(core, docs) · 안의 차례는 그대로');
  assert.deepStrictEqual(ids(L.columns(tasks, null), 'waiting'), ['T01', 'T02', 'T03'], '묶지 않으면 만든 차례');
  assert.deepStrictEqual(ids(L.columns(tasks, null, { query: '담당솔', extraOf: () => '담당솔 개발' }), 'waiting'), ['T01', 'T02', 'T03'], 'extraOf가 주는 글(담당 이름)도 찾는다');
});

check('찾기·며칠·얼마 전·표 파일(CSV)', () => {
  assert.strictEqual(L.matches(T('T01', 'ready', { title: 'Steam 보고서' }), 'steam 보'), true);
  assert.strictEqual(L.matches(T('T01', 'ready'), ''), true, '빈 글은 모두');
  assert.strictEqual(L.oldestDays([T('T01', 'ready', { created_at: day(6) }), T('T02', 'running', { created_at: day(2) }), T('T03', 'done', { created_at: day(30) })], NOW), 6, '끝난 일은 빼고 가장 오래된 열린 일');
  assert.strictEqual(L.oldestDays([], NOW), 0);
  assert.deepStrictEqual([0.2, 5, 130, 60 * 30, 60 * 24 * 3].map((m) => L.ago(new Date(NOW - m * 60000).toISOString(), NOW)), ['방금', '5분 전', '2시간 전', '1일 전', '3일 전']);
  assert.strictEqual(L.ago('엉망', NOW), '');
  const csv = L.toCsv([['번호', '제목'], ['T1', '쉼표, 있는 "제목"'], ['T2', '두\n줄']]);
  assert.strictEqual(csv, ['번호,제목', 'T1,"쉼표, 있는 ""제목"""', 'T2,"두\n줄"'].join('\r\n'));
});

console.log(`진행판 점검 통과 (${n}개)`);
