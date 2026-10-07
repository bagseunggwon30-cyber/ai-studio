// 휴대폰 리모컨(/m) 계산·규칙 점검 (브라우저 없이): node tools/dev/m_sim.js
// ui/m.js의 순수 계산(결재함 요약 숫자·진행판 칸·'몇 분 전')과, CSP 규칙(인라인 스크립트·스타일 없음, innerHTML은 고정 아이콘만)을 확인한다. 화면은 캡처로 본다.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const UI = path.join(__dirname, '..', '..', 'ui');
const M = require(path.join(UI, 'm.js'));
const L = M.logic;

let n = 0;
function check(name, fn) { fn(); n += 1; console.log(`  ✓ ${name}`); }

const T = (id, status, extra = {}) => ({ id, status, kind: 'build', kind_label: '개발', status_label: status, title: id, who: '솔', updated_at: '2026-10-05T12:00:00+09:00', ...extra });
const STATE = {
  inbox: [T('A1', 'awaiting_approval'), T('A2', 'awaiting_approval', { kind: 'plan' })],
  active: [T('B1', 'blocked'), T('R1', 'running'), T('C1', 'checking'), T('Q1', 'queued'), T('Y1', 'ready')],
  done: [T('D1', 'done'), T('D2', 'done')],
  current: { who: '솔', title: 'R1' },
};

check('node에서 불러와도 화면 코드는 돌지 않는다 (document 없음)', () => {
  assert.strictEqual(typeof document, 'undefined');
  assert.ok(L && typeof L.counts === 'function');
});

check('숫자 세기: 결재 기다림 · 막힘 · 일하는 중(작업 중+검사 중)은 서버가 준 목록으로만', () => {
  assert.deepStrictEqual(L.counts(STATE), { approvals: 2, blocked: 1, working: 2 });
  assert.deepStrictEqual(L.counts({ inbox: [], active: [], done: [] }), { approvals: 0, blocked: 0, working: 0 });
  assert.deepStrictEqual(L.counts({}), { approvals: 0, blocked: 0, working: 0 }, '빠진 목록은 0');
});

check('한 줄 요약: 0건은 말하지 않고, 정할 일이 없으면 일하는 중 · 조용함', () => {
  assert.strictEqual(L.summaryText({ approvals: 2, blocked: 1, working: 3 }), '정할 일 2건 · 막힌 일 1건');
  assert.strictEqual(L.summaryText({ approvals: 0, blocked: 1, working: 0 }), '막힌 일 1건');
  assert.strictEqual(L.summaryText({ approvals: 3, blocked: 0, working: 0 }), '정할 일 3건');
  assert.match(L.summaryText({ approvals: 0, blocked: 0, working: 2 }), /2건이 일하는 중/);
  assert.match(L.summaryText({ approvals: 0, blocked: 0, working: 0 }), /정할 일이 없어요/);
  assert.ok(!/0건/.test(L.summaryText({ approvals: 0, blocked: 0, working: 0 })), '0건이라고 쓰지 않는다');
});

check('진행판 맨 위 한 줄: 막힘 > 결재 > 일하는 중 > 조용함', () => {
  assert.strictEqual(L.nowLine(STATE).tone, 'blocked');
  assert.strictEqual(L.nowLine({ ...STATE, active: STATE.active.filter((t) => t.status !== 'blocked') }).tone, 'awaiting');
  const run = L.nowLine({ inbox: [], active: [T('R1', 'running')], done: [], current: { who: '솔', title: '단추' } });
  assert.strictEqual(run.tone, 'running');
  assert.match(run.text, /솔 · '단추'/);
  assert.strictEqual(L.nowLine({ inbox: [], active: [], done: [] }).tone, 'idle');
});

check('진행판 다섯 칸: 대기 · 작업 중(막힘 먼저) · 검사 · 결재 · 완료, 칸 안은 상태 순서', () => {
  const cols = L.columns(STATE);
  assert.deepStrictEqual(cols.map((c) => c.key), ['wait', 'work', 'check', 'approve', 'done']);
  assert.deepStrictEqual(cols.map((c) => c.label), ['대기', '작업 중', '검사·리뷰', '결재 대기', '완료']);
  assert.deepStrictEqual(cols.map((c) => c.tasks.map((t) => t.id)), [['Q1', 'Y1'], ['B1', 'R1'], ['C1'], ['A1', 'A2'], ['D1', 'D2']]);
  assert.strictEqual(cols.reduce((s, c) => s + c.tasks.length, 0), 9, '모든 작업이 어느 한 칸에 들어간다');
});

check("'몇 분 전' 말: 방금 · 분 · 시간 · 일, 읽을 수 없는 시각은 빈 글", () => {
  const now = Date.parse('2026-10-05T12:00:00Z');
  const ago = (sec) => L.ago(new Date(now - sec * 1000).toISOString(), now);
  assert.deepStrictEqual([ago(5), ago(18 * 60), ago(2 * 3600), ago(3 * 86400)], ['방금', '18분 전', '2시간 전', '3일 전']);
  assert.strictEqual(ago(-30), '방금', '미래 시각도 방금으로');
  assert.deepStrictEqual([L.ago('', now), L.ago(undefined, now), L.ago('어제', now)], ['', '', '']);
});

check('이름 첫 글자 · 에너지 부족 · 종류 이름', () => {
  assert.deepStrictEqual([L.initial('솔'), L.initial(''), L.initial(null), L.initial('😀하나')], ['솔', '', '', '😀']);
  assert.strictEqual(L.energyLow({ max: 40, left: 3 }), true);
  assert.strictEqual(L.energyLow({ max: 40, left: 39 }), false);
  assert.strictEqual(L.energyLow({ max: 0, left: 0 }), false);
  assert.strictEqual(L.KIND_LABELS.plan, '기획');
  assert.strictEqual(L.KIND_LABELS.qwerty, undefined, '모르는 종류를 영어 그대로 보이지 않기 위해 이름표가 없으면 비운다');
});

// ---- 규칙 점검 (소스 글자 검사): CSP·안전 규칙이 깨지지 않았는지
const js = fs.readFileSync(path.join(UI, 'm.js'), 'utf8');
const css = fs.readFileSync(path.join(UI, 'm.css'), 'utf8');
const html = fs.readFileSync(path.join(UI, 'm.html'), 'utf8');

check('m.js: innerHTML은 고정 아이콘 두 곳뿐, 서버 글을 HTML로 넣는 길 없음', () => {
  const uses = js.split('\n').filter((l) => /innerHTML|insertAdjacentHTML|document\.write|outerHTML|\beval\(|new Function/.test(l.split('//')[0])); // 주석 글은 뺀다
  assert.strictEqual(uses.length, 2, uses.join('\n'));
  assert.ok(uses.every((l) => l.includes('ICONS[')), '아이콘 표에서 꺼낸 고정 글자열만');
  assert.ok(!/setAttribute\(\s*['"]style['"]/.test(js) && !/\.style\s*=|cssText/.test(js), '인라인 스타일 없음');
});

check('m.js: 연습 화면(#demo)은 서버·토큰·저장소를 건드리지 않는다', () => {
  assert.match(js, /async function api\(path, body\) \{\s*\n\s*if \(DEMO\) throw/, 'api()는 연습 화면에서 첫 줄에 거절');
  assert.match(js, /if \(!DEMO\) \{ try \{ token = localStorage\.getItem/, '연습 화면은 저장된 토큰을 읽지 않는다');
  assert.match(js, /function forget\(\) \{\s*\n\s*if \(DEMO\)/, '연습 화면은 연결 끊기도 저장소를 안 건드린다');
  assert.match(js, /async function refresh\(\) \{\s*\n\s*if \(DEMO\) return;/);
});

check('m.html: 인라인 스크립트·스타일 없음, 스크립트는 /m.js 하나 (서버 시험이 찾는 그 글자 그대로)', () => {
  assert.ok(html.includes('<script src="/m.js" defer>'));
  assert.ok(!/<style|\sstyle=|<script(?![^>]*\ssrc=)/i.test(html));
  assert.ok(html.includes('name="theme-color" content="#ffffff"'));
  assert.ok(!html.includes('mascot') && !html.includes('assets/'), '발표 캐릭터·그림 파일을 가리키지 않는다');
});

check('m.css: 외부 글꼴·주소 없음, 픽셀 글꼴 없음, 발표 캐릭터 규칙 없음, 움직임 줄이기 지원', () => {
  assert.ok(!/@import|@font-face|https?:\/\/|Galmuri/i.test(css));
  assert.ok(!/\.host\b|host-img|host-bubble/.test(css));
  assert.ok(/prefers-reduced-motion/.test(css));
  assert.ok(/--bd-accent:\s*#4f46e5/.test(css) && /--bd-dark:\s*#16181d/.test(css), '--bd-* 토큰 이름 그대로');
});

console.log(`\nm_sim: ${n}개 확인 통과`);
