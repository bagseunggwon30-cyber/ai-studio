// 홈(오늘) 계산 점검 (브라우저 없이): node tools/dev/home_sim.js
// ui/home.js의 순수 계산(인사·한 줄 요약·이번 주 숫자·전체 진행·직원별·결정이 필요한 일·최근 끝난 일)만 확인한다. 화면은 캡처로 본다.
'use strict';
const assert = require('assert');
const path = require('path');

const Home = require(path.join(__dirname, '..', '..', 'ui', 'home.js'));
const L = Home.logic;

let n = 0;
function check(name, fn) { fn(); n += 1; console.log(`  ✓ ${name}`); }

const NOW = Date.parse('2026-10-05T12:00:00');
const ago = (days) => new Date(NOW - days * 86400000).toISOString();
const T = (id, status, extra = {}) => ({ id, status, kind: 'build', project: 'core', title: id, role: 'builder', created_at: ago(9), updated_at: ago(1), ...extra });

check('인사: 시각에 맞는 말', () => {
  assert.deepStrictEqual([3, 8, 12, 15, 20, 23].map(L.greeting), ['늦은 시간이에요', '좋은 아침이에요', '안녕하세요', '좋은 오후예요', '좋은 저녁이에요', '늦은 시간이에요']);
});

check('한 줄 요약: 정할 일이 있으면 그 수를, 없으면 순조롭다고, 일이 없으면 첫 지시를 권한다', () => {
  assert.match(L.summaryText({ approvals: 2, blocked: 1, working: 1 }, 5), /결재 2건 · 막힌 일 1건/);
  assert.match(L.summaryText({ approvals: 0, blocked: 1, working: 0 }, 5), /막힌 일 1건/);
  assert.ok(!/결재/.test(L.summaryText({ approvals: 0, blocked: 1, working: 0 }, 5)), '결재가 0이면 결재 얘기는 안 한다');
  assert.match(L.summaryText({ approvals: 0, blocked: 0, working: 2 }, 5), /일하는 중/);
  assert.match(L.summaryText({ approvals: 0, blocked: 0, working: 0 }, 5), /할 일이 없어요/);
  assert.match(L.summaryText({ approvals: 0, blocked: 0, working: 0 }, 0), /첫 지시/);
});

check('이번 주 숫자: 최근 7일에 끝낸 일(기획 제외) · 검사 통과율 · 일한 직원 수 · 열린 일', () => {
  const tasks = [
    T('T01', 'done', { updated_at: ago(1), qa: { verdict: 'pass' } }), T('T02', 'done', { updated_at: ago(3), role: 'analyst', qa: { verdict: 'pass' } }),
    T('T03', 'done', { updated_at: ago(20), qa: { verdict: 'pass' } }), // 오래전
    T('T04', 'done', { kind: 'plan', updated_at: ago(1) }), // 기획은 안 센다
    T('T05', 'blocked', { updated_at: ago(0), qa: { verdict: 'fail' } }), T('T06', 'cancelled', { updated_at: ago(0) }), T('T07', 'ready'),
  ];
  const w = L.weekStats(tasks, NOW, (t) => t.role);
  assert.deepStrictEqual([w.done, w.checked, w.passPct, w.workers, w.open], [2, 3, 67, 2, 2]);
  assert.deepStrictEqual(L.weekStats([], NOW).passPct, null, '검사한 일이 없으면 통과율은 없음(–)');
});

check('전체 진행: 끝남·일하는 중·기다림·막힘 (기획 카드·취소·보관은 빼고)', () => {
  const tasks = [T('T01', 'done'), T('T02', 'done'), T('T03', 'running'), T('T04', 'checking'), T('T05', 'ready'), T('T06', 'awaiting_approval'),
    T('T07', 'blocked'), T('T08', 'done', { kind: 'plan' }), T('T09', 'cancelled'), T('T10', 'done', { archived: true })];
  assert.deepStrictEqual(L.progressSplit(tasks), { total: 7, done: 2, working: 2, waiting: 2, blocked: 1 });
});

check('직원별: 끝낸 일·열린 일·끝낸 비율', () => {
  const tasks = [T('T01', 'done'), T('T02', 'running'), T('T03', 'done', { role: 'analyst' }), T('T04', 'done', { kind: 'plan' })];
  const team = [{ id: 'sol', name: '솔', title: '개발', state: 'work' }, { id: 'luna', name: '루나', title: '리서치' }, { id: 'hana', name: '하나', title: '기획' }];
  const owner = (t) => (t.role === 'builder' ? 'sol' : t.role === 'analyst' ? 'luna' : null);
  const rows = L.peopleRows(tasks, team, owner);
  assert.deepStrictEqual(rows.map((r) => [r.id, r.done, r.open, r.pct, r.state]), [['sol', 1, 1, 50, 'work'], ['luna', 1, 0, 100, 'rest'], ['hana', 0, 0, 0, 'rest']]);
});

check('결정이 필요한 일: 막힘이 먼저, 그다음 결재 기다림, 같은 것끼리는 오래된 순', () => {
  const tasks = [T('T03', 'awaiting_approval', { created_at: ago(2) }), T('T02', 'awaiting_approval', { created_at: ago(5) }), T('T09', 'blocked', { created_at: ago(1) }),
    T('T05', 'running'), T('T06', 'blocked', { archived: true })];
  assert.deepStrictEqual(L.attentionItems(tasks).map((t) => t.id), ['T09', 'T02', 'T03']);
});

check('최근 끝난 일: 기획 제외, 최근 것이 먼저, 개수 제한', () => {
  const tasks = [T('T01', 'done', { updated_at: ago(3) }), T('T02', 'done', { updated_at: ago(1) }), T('T03', 'done', { kind: 'plan', updated_at: ago(0) }), T('T04', 'done', { updated_at: ago(2) })];
  assert.deepStrictEqual(L.recentDone(tasks, 2).map((t) => t.id), ['T02', 'T04']);
});

console.log(`홈 점검 통과 (${n}개)`);
