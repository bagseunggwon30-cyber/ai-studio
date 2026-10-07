// 빠른 찾기(Ctrl K) 계산 점검 (브라우저 없이): node tools/dev/finder_sim.js
// ui/finder.js의 순수 계산(낱말 나누기·점수·강조 자르기·갈래별 찾기)만 확인한다. 화면은 캡처로 본다.
'use strict';
const assert = require('assert');
const path = require('path');

const Finder = require(path.join(__dirname, '..', '..', 'ui', 'finder.js'));
const L = Finder.logic;

let n = 0;
function check(name, fn) { fn(); n += 1; console.log(`  ✓ ${name}`); }

check('낱말 나누기: 소문자, 띄어쓰기 기준, 빈 칸 무시', () => {
  assert.deepStrictEqual(L.words('  Steam   보고서 '), ['steam', '보고서']);
  assert.deepStrictEqual(L.words(''), []);
  assert.deepStrictEqual(L.words(null), []);
});

check('점수: 낱말이 모두 있어야 하고, 앞에서 시작할수록 높다', () => {
  assert.strictEqual(L.score('결재함', ['없는']), -1);
  assert.strictEqual(L.score('결재함 열기', ['결재', '열기']), 4);
  assert.ok(L.score('결재함', ['결재']) > L.score('내 결재함', ['결재']));
  assert.strictEqual(L.score('아무거나', []), 0, '찾는 글이 없으면 0점(모두 통과)');
});

check('강조 자르기: 첫 낱말이 처음 나오는 곳 [앞, 맞은 곳, 뒤]', () => {
  assert.deepStrictEqual(L.highlightParts('Steam 보고서', ['steam']), ['', 'Steam', ' 보고서']);
  assert.deepStrictEqual(L.highlightParts('HUD 만들기', ['만들']), ['HUD ', '만들', '기']);
  assert.deepStrictEqual(L.highlightParts('없음', ['xyz']), ['없음', '', '']);
  assert.deepStrictEqual(L.highlightParts('글', []), ['글', '', '']);
});

check('갈래별 찾기: 일(번호·제목·담당·종류·프로젝트) · 직원 · 스킬 · 화면. 취소·보관한 일은 안 나온다', () => {
  const data = {
    tasks: [
      { id: 'T0010', title: 'HUD에 남은 시간 표시', status: 'done', kind: 'build', project: 'core' },
      { id: 'T0011', title: 'Esc 일시정지', status: 'running', kind: 'build', project: 'core' },
      { id: 'T0012', title: '취소한 일 HUD', status: 'cancelled', kind: 'build', project: 'core' },
      { id: 'T0013', title: 'HUD 보관', status: 'done', kind: 'build', project: 'core', archived: true },
      { id: 'T0014', title: 'Steam 보고서', status: 'ready', kind: 'research', project: 'docs' },
    ],
    team: [{ id: 'sol', name: '솔', title: '개발', job: 'builder' }, { id: 'luna', name: '루나', title: '리서치', job: 'analyst' }],
    skills: [{ slug: 'quest-splitting', title: '퀘스트 잘 나누기', description: '기획 카드를 나눈다' }, { slug: 'design-review', title: '디자인 리뷰', description: '화면 점검' }],
    ownerName: (t) => (t.kind === 'research' ? '루나' : '솔'),
    kindLabel: (t) => (t.kind === 'research' ? '리서치' : '개발'),
    projectTitle: (key) => (key === 'docs' ? 'Studio Docs' : 'Core Courier'),
  };
  const ids = (q, key) => L.search(q, data)[key].map((x) => x.id || x.slug || x[0]);
  assert.deepStrictEqual(ids('hud', 'tasks'), ['T0010']);
  assert.deepStrictEqual(ids('솔', 'tasks').sort(), ['T0010', 'T0011'], '담당 이름으로도 찾는다');
  assert.deepStrictEqual(ids('리서치', 'tasks'), ['T0014'], '종류 이름으로도 찾는다');
  assert.deepStrictEqual(ids('studio docs', 'tasks'), ['T0014'], '프로젝트 이름으로도 찾는다');
  assert.deepStrictEqual(ids('t0011', 'tasks'), ['T0011'], '번호로 찾는다 (대소문자 무시)');
  assert.deepStrictEqual(ids('루나', 'people'), ['luna']);
  assert.deepStrictEqual(ids('개발', 'people'), ['sol'], '직함으로도');
  assert.deepStrictEqual(ids('퀘스트', 'skills'), ['quest-splitting']);
  assert.deepStrictEqual(ids('점검', 'skills'), ['design-review'], '설명 안의 낱말도');
  assert.ok(ids('결재', 'screens').includes('inbox'));
  assert.ok(ids('결재', 'screens').length === 1);
  assert.deepStrictEqual(ids('아무도없는말', 'tasks'), []);
});

check('화면 바로가기: 홈·진행판·이미지·영상 작업대·소설 집필실·디자인 작업실·노드 편집기·결재함·회의실·직원·스킬·MCP·자동 업무·업무 일지·완성작·주간 요약', () => {
  assert.deepStrictEqual(L.SCREENS.map((s) => s[0]), ['home', 'board', 'media', 'novel', 'design', 'workbench', 'inbox', 'meeting', 'team', 'skills', 'mcp', 'schedules', 'gateway', 'diary', 'trophies', 'digest']);
  assert.deepStrictEqual(L.SCREENS.filter((s) => ['novel', 'design'].includes(s[0])).map((s) => s[1]), ['소설 집필실', '디자인 작업실']);
  const found = (q) => L.search(q, { tasks: [], team: [], skills: [], ownerName: () => '', kindLabel: () => '', projectTitle: () => '' }).screens.map((x) => x[0]);
  assert.deepStrictEqual(found('소설'), ['novel'], '소설로 찾으면 소설 집필실');
  assert.deepStrictEqual(found('시안'), ['design'], '시안으로 찾으면 디자인 작업실');
});

console.log(`빠른 찾기 점검 통과 (${n}개)`);
