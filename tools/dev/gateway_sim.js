'use strict';
// 외부 연결 창의 순수 계산 점검: node tools/dev/gateway_sim.js (브라우저·서버 없이)
const assert = require('assert');
const { logic: L } = require('../../ui/gateway.js');

const results = [];
const check = (name, fn) => { fn(); results.push(name); console.log(`  ✓ ${name}`); };

check('공개 주소 검사: https만, 경로·쿼리·집 안 주소·빈 값은 쉬운 말로 거절', () => {
  for (const ok of ['https://gw.example.test', ' HTTPS://Gw.Example.Test/ ', 'https://a-b.trycloudflare.com', 'https://x.example.test:8443']) assert.strictEqual(L.checkUrl(ok), '', ok);
  const bad = { '': '넣어 주세요', '   ': '넣어 주세요', 'gw.example.test': 'https://', 'http://gw.example.test': 'http는 안 돼요', 'https://gw.example.test/mcp': '경로',
    'https://gw.example.test/?a=1': '경로', 'https://gw.example.test#x': '경로', 'https://user@gw.example.test': '경로', 'https://127.0.0.1': '숫자 주소', 'https://localhost': '모양',
    'https://nas.local': '집 안', 'https://gw example.test': '띄어쓰기', 'https://gw.example.test:70000': '포트', 'ftp://gw.example.test': 'https://' };
  for (const [value, word] of Object.entries(bad)) { const msg = L.checkUrl(value); assert.ok(msg && msg.includes(word), `${value} → ${msg}`); assert.ok(/[가-힣]/.test(msg)); }
});

check('폴더 범위 입력 → 목록 (쉼표·줄바꿈, 빈 것 버림)', () => {
  assert.deepStrictEqual(L.parsePaths('docs/**, ui/app.js\n  tests/** ,,'), ['docs/**', 'ui/app.js', 'tests/**']);
  assert.deepStrictEqual(L.parsePaths(''), []);
  assert.deepStrictEqual(L.parsePaths(null), []);
});

check('몇 분 전', () => {
  const now = 1_000_000_000;
  assert.strictEqual(L.ago(0, now), '');
  assert.strictEqual(L.ago(now - 5_000, now), '방금');
  assert.strictEqual(L.ago(now - 5 * 60_000, now), '5분 전');
  assert.strictEqual(L.ago(now - 3 * 3600_000, now), '3시간 전');
  assert.strictEqual(L.ago(now - 2 * 86400_000, now), '2일 전');
});

check('연결의 권한 이름: 허용한 것과 지금 설정을 같이 본다', () => {
  assert.deepStrictEqual(L.scopeLabel({ granted: ['studio:read'], scopes: ['studio:read'] }), { text: '읽기만', tone: 'soft' });
  assert.deepStrictEqual(L.scopeLabel({ granted: ['studio:read', 'studio:submit'], scopes: ['studio:read', 'studio:submit'] }), { text: '읽기 + 일 맡기기', tone: 'on' });
  assert.ok(L.scopeLabel({ granted: ['studio:read', 'studio:submit'], scopes: ['studio:read'] }).text.includes('꺼짐'));
});

check('프로젝트 단계: 저장된 값 ↔ 선택칸 (읽기만·일 맡기기·실행 시작)', () => {
  assert.strictEqual(L.levelOf(undefined), 'read');
  assert.strictEqual(L.levelOf({ paths: ['docs/**'], write: false, run: false }), 'read');
  assert.strictEqual(L.levelOf({ paths: ['docs/**'], write: true, run: false }), 'submit');
  assert.strictEqual(L.levelOf({ paths: ['docs/**'], write: true, run: true }), 'run');
  assert.strictEqual(L.levelOf({ paths: ['docs/**'], write: true }), 'submit', 'run 칸이 없는 옛 저장값은 실행 시작이 꺼진 일 맡기기');
  assert.deepStrictEqual(L.levelSpec('read'), { write: false, run: false });
  assert.deepStrictEqual(L.levelSpec('submit'), { write: true, run: false });
  assert.deepStrictEqual(L.levelSpec('run'), { write: true, run: true });
  assert.deepStrictEqual(L.levelSpec('nonsense'), { write: false, run: false }, '모르는 단계는 읽기만');
  assert.deepStrictEqual(Object.keys(L.LEVELS), ['read', 'submit', 'run']);
  for (const lv of Object.values(L.LEVELS)) assert.ok(/[가-힣]/.test(lv.label) && /[가-힣]/.test(lv.hint));
  assert.ok(/\[실행\]/.test(L.LEVELS.submit.hint) && /사용량/.test(L.LEVELS.run.hint));
  for (const level of Object.keys(L.LEVELS)) assert.strictEqual(L.levelOf(L.levelSpec(level)), level);
});

check('연결 번호 남은 시간', () => {
  assert.strictEqual(L.countdown(300_000), '5:00');
  assert.strictEqual(L.countdown(299_001), '5:00');
  assert.strictEqual(L.countdown(61_000), '1:01');
  assert.strictEqual(L.countdown(9_000), '0:09');
  assert.strictEqual(L.countdown(0), '');
  assert.strictEqual(L.countdown(-5), '');
});

check('기록 시각', () => {
  assert.strictEqual(L.clock('2027-01-15T17:03:09+09:00'), '17:03:09');
  assert.strictEqual(L.clock(null), '');
});

console.log(`외부 연결 창 계산 점검 통과 (${results.length}개)`);
