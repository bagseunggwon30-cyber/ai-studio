// 소설 집필실·디자인 작업실 계산 점검 (브라우저 없이): node tools/dev/rooms_sim.js
// ui/rooms.js의 순수 계산(파일 이름표·폴더 묶기·번호순·'약 N자'·요약·마크다운 줄 나누기·프로젝트 ID 제안과 검사·입력칸 검사·일 목록·몇 분 전 등)만 확인한다.
// 화면은 tools/dev/rooms_browser.cjs(연습용 서버)와 캡처로 본다.
'use strict';
const assert = require('assert');
const path = require('path');

const Rooms = require(path.join(__dirname, '..', '..', 'ui', 'rooms.js'));
const L = Rooms.logic;

let n = 0;
function check(name, fn) { fn(); n += 1; console.log(`  ✓ ${name}`); }

const T = (p, size = 300, kind = 'text') => ({ path: p, size, kind });

check('파일 이름표: 설정집·연속성 장부는 쉬운 이름, 원고는 N장, 모르는 파일은 그대로', () => {
  assert.deepStrictEqual(['bible/premise.md', 'bible/characters.md', 'bible/world.md', 'bible/outline.md', 'bible/style.md', 'notes/continuity.md'].map((p) => L.fileLabel('novel', p)),
    ['한 줄 소개', '인물', '세계', '줄거리', '문체', '연속성 장부']);
  assert.strictEqual(L.fileLabel('novel', 'chapters/001.md'), '1장');
  assert.strictEqual(L.fileLabel('novel', 'chapters/012.md'), '12장', '앞의 0은 뗀다');
  assert.strictEqual(L.fileLabel('novel', 'notes/ideas.md'), 'ideas.md', '모르는 파일은 이름 그대로');
  assert.strictEqual(L.fileLabel('novel', 'notes/ideas.md', '메모 하나'), '메모 하나', '쓸 이름을 정해 주면 그것');
  assert.strictEqual(L.fileLabel('design', 'brief/brief.md'), '디자인 기획서');
  assert.strictEqual(L.fileLabel('design', 'system/design-tokens.md'), '디자인 규칙');
  assert.strictEqual(L.fileLabel('design', 'screens/login.html'), 'login.html');
  assert.strictEqual(L.fileLabel('design', 'chapters/001.md'), '001.md', '디자인에는 원고 이름표가 없다');
});

check("약 N자: 바이트÷3을 반올림해 '약 1,000자'로", () => {
  assert.strictEqual(L.approxChars(3000), 1000);
  assert.strictEqual(L.approxChars(4), 1);
  assert.strictEqual(L.approxChars(0), 0);
  assert.strictEqual(L.approxChars(null), 0);
  assert.strictEqual(L.charsText(3000), '약 1,000자');
  assert.strictEqual(L.charsText(12345), '약 4,115자');
  assert.strictEqual(L.charsText(3_000_000), '약 1,000,000자');
});

check('크기 글: B · KB(소수 한 자리, .0은 뗀다) · MB', () => {
  assert.deepStrictEqual([0, 512, 1024, 1536, 2048, 1024 * 1024 * 2.5].map(L.sizeText), ['0B', '512B', '1KB', '1.5KB', '2KB', '2.5MB']);
});

check('폴더 묶기(소설): 설정집 · 원고 · 메모 · 기타 순서, 비어 있는 묶음은 뺀다', () => {
  const files = [T('README.md'), T('notes/continuity.md'), T('chapters/002.md'), T('bible/premise.md'), T('chapters/001.md'), T('extra/a.md')];
  const groups = L.groupFiles('novel', files);
  assert.deepStrictEqual(groups.map((g) => g.label), ['설정집', '원고', '메모', '기타']);
  assert.deepStrictEqual(groups.map((g) => g.files.length), [1, 2, 1, 2]);
  assert.deepStrictEqual(L.groupFiles('novel', []), []);
  assert.deepStrictEqual(L.groupFiles('novel', [T('chapters/001.md')]).map((g) => g.label), ['원고']);
});

check('원고는 번호순 (2장이 10장보다 앞), 번호 아닌 파일은 뒤로', () => {
  const g = L.groupFiles('novel', [T('chapters/010.md'), T('chapters/README.md'), T('chapters/002.md'), T('chapters/001.md')]).find((x) => x.label === '원고');
  assert.deepStrictEqual(g.files.map((f) => f.label), ['1장', '2장', '10장', '원고 폴더 안내']);
  assert.deepStrictEqual(g.files.map((f) => f.chapter), [1, 2, 10, null]);
  assert.strictEqual(g.files[0].meta, '약 100자', '원고는 글자 수 어림 (300바이트)');
});

check('설정집은 읽는 순서대로 (한 줄 소개 → 인물 → 세계 → 줄거리 → 문체), 모르는 파일은 그 뒤 경로순', () => {
  const files = ['bible/world.md', 'bible/style.md', 'bible/zzz.md', 'bible/premise.md', 'bible/outline.md', 'bible/characters.md', 'bible/aaa.md'].map((p) => T(p));
  const g = L.groupFiles('novel', files)[0];
  assert.deepStrictEqual(g.files.map((f) => f.label), ['한 줄 소개', '인물', '세계', '줄거리', '문체', 'aaa.md', 'zzz.md']);
});

check('폴더 묶기(디자인): 기획서 · 규칙 · 시안 · 그림 · 점검 · 기타, 그림 파일은 크기 글 그대로', () => {
  const files = [T('assets/a.png', 2048, 'image'), T('screens/login.html', 975), T('system/design-tokens.md'), T('brief/brief.md'), T('reviews/README.md'), T('LICENSE.txt')];
  const groups = L.groupFiles('design', files);
  assert.deepStrictEqual(groups.map((g) => g.label), ['기획서', '규칙', '시안', '그림', '점검', '기타']);
  assert.strictEqual(groups[3].files[0].meta, '2KB');
  assert.strictEqual(groups[3].files[0].view, 'image');
  assert.strictEqual(groups[2].files[0].label, 'login.html', '폴더 안의 모르는 파일은 폴더 이름을 뗀 이름');
  assert.strictEqual(groups[5].files[0].label, 'LICENSE.txt');
});

check('요약: 소설 = 원고 N개 장 · 약 N자 (README·설정집은 안 센다), 디자인 = 시안 N개 · 그림 N개', () => {
  const s = L.summary('novel', [T('chapters/001.md', 3000), T('chapters/002.md', 6000), T('chapters/README.md', 900), T('bible/premise.md', 900)]);
  assert.strictEqual(s.text, '원고 2개 장 · 약 3,000자');
  assert.deepStrictEqual(s.parts, ['원고 ', '2', '개 장 · 약 ', '3,000', '자']);
  assert.strictEqual(L.summary('novel', []).text, '원고 0개 장 · 약 0자');
  const d = L.summary('design', [T('screens/login.html'), T('screens/README.md'), T('screens/card.svg'), T('assets/logo.svg'), T('assets/p.png', 10, 'image'), T('assets/requests.md')]);
  assert.strictEqual(d.text, '시안 2개 · 그림 2개');
});

check('읽는 방식: 그림 · svg(그림/원문) · 소설 원고 · 설명 글 · 원문', () => {
  assert.strictEqual(L.viewKindOf('novel', T('assets/a.png', 1, 'image')), 'image');
  assert.strictEqual(L.viewKindOf('design', T('assets/logo.svg')), 'svg');
  assert.strictEqual(L.viewKindOf('novel', T('chapters/001.md')), 'chapter');
  assert.strictEqual(L.viewKindOf('design', T('chapters/001.md')), 'markdown', '디자인에서는 원고가 아니다');
  assert.strictEqual(L.viewKindOf('novel', T('bible/premise.md')), 'markdown');
  assert.strictEqual(L.viewKindOf('design', T('screens/login.html')), 'raw');
  assert.strictEqual(L.viewKindOf('design', T('x.json')), 'raw');
  assert.strictEqual(L.viewKindOf('design', T('x.CSS')), 'raw');
});

check('마크다운 줄 나누기: # 큰 제목 · ## 작은 제목 · - 목록 · 빈 줄 = 문단 끝 · --- 나누기, HTML은 해석하지 않고 글 그대로', () => {
  const text = '# 제1장 비\n\n첫 문단 첫 줄\n첫 문단 둘째 줄\n\n<b>x</b> <script>alert(1)</script>\n\n## 작은 제목\n- 하나\n- 둘\n\n---\n마지막\n';
  const { blocks, truncated } = L.blocks(text);
  assert.strictEqual(truncated, false);
  assert.deepStrictEqual(blocks.map((b) => b.t), ['h1', 'p', 'p', 'h2', 'li', 'li', 'hr', 'p']);
  assert.strictEqual(blocks[0].text, '제1장 비');
  assert.strictEqual(blocks[1].text, '첫 문단 첫 줄\n첫 문단 둘째 줄', '이어진 줄은 한 문단 (줄바꿈 유지)');
  assert.strictEqual(blocks[2].text, '<b>x</b> <script>alert(1)</script>', '태그도 그냥 글자');
  assert.deepStrictEqual(blocks.filter((b) => b.t === 'li').map((b) => b.text), ['하나', '둘']);
  assert.deepStrictEqual(L.blocks('﻿# 제목\r\n\r\n본문\r\n').blocks.map((b) => [b.t, b.text]), [['h1', '제목'], ['p', '본문']], 'BOM·윈도우 줄바꿈');
  assert.strictEqual(L.blocks('###작은').blocks[0].t, 'p', '#뒤에 띄어쓰기가 없으면 제목이 아니다');
  assert.deepStrictEqual(L.blocks('* * *').blocks, [{ t: 'hr' }]);
  assert.deepStrictEqual(L.blocks('').blocks, []);
});

check('너무 긴 글은 앞부분만 (blocks 한도)', () => {
  const text = Array.from({ length: 50 }, (_, i) => `문단 ${i}`).join('\n\n');
  const r = L.blocks(text, 10);
  assert.strictEqual(r.blocks.length, 10);
  assert.strictEqual(r.truncated, true);
});

check('새 프로젝트 ID 제안: novel-1 · design-1부터, 이미 있는 번호는 건너뛴다', () => {
  assert.strictEqual(L.suggestKey('novel', []), 'novel-1');
  assert.strictEqual(L.suggestKey('novel', ['novel-1', 'novel-2', 'design-1']), 'novel-3');
  assert.strictEqual(L.suggestKey('design', ['novel-1']), 'design-1');
  assert.strictEqual(L.suggestKey('design', ['design-1', 'design-3']), 'design-2');
});

check('프로젝트 ID 검사: 소문자 영문으로 시작 · 영문·숫자·- · 40자 이내 · 겹치지 않기', () => {
  assert.strictEqual(L.keyProblem('novel-1', []), '');
  assert.strictEqual(L.keyProblem('a', []), '');
  assert.strictEqual(L.keyProblem('a'.repeat(40), []), '');
  assert.ok(L.keyProblem('a'.repeat(41), []).includes('소문자 영문으로 시작'));
  for (const bad of ['Novel', '1novel', '-novel', 'no vel', '소설', 'novel_1', 'novel.1']) assert.strictEqual(L.keyProblem(bad, []), L.KEY_RULE, bad);
  assert.strictEqual(L.keyProblem('', []), 'ID를 적어 주세요.');
  assert.strictEqual(L.keyProblem('  ', []), 'ID를 적어 주세요.');
  assert.ok(L.keyProblem('demo', ['demo']).includes('이미 있는'));
});

check('이름·설명 검사: 비면 안 됨 · 이름 80자 · 설명 1000자 (글자 수는 이모지도 한 글자)', () => {
  assert.strictEqual(L.titleProblem('비 오는 날의 서점'), '');
  assert.strictEqual(L.titleProblem('  '), '작품 이름을 적어 주세요.');
  assert.strictEqual(L.titleProblem('', '디자인 프로젝트'), '디자인 프로젝트 이름을 적어 주세요.');
  assert.strictEqual(L.titleProblem('가'.repeat(80)), '');
  assert.strictEqual(L.titleProblem('가'.repeat(81)), '이름은 80자 이내로 적어 주세요.');
  assert.strictEqual(L.titleProblem('😀'.repeat(80)), '');
  assert.strictEqual(L.descProblem('가'.repeat(1000)), '');
  assert.strictEqual(L.descProblem('가'.repeat(1001)), '설명은 1000자 이내로 적어 주세요.');
});

const TPL = { id: 'novel-next', title: '다음 장 쓰기', fields: [
  { key: 'length', label: '분량(공백 포함 글자 수)', default: '4000', required: true, max: 6 },
  { key: 'note', label: '이번 장에서 꼭 넣을 것 (선택)', required: false, max: 600 }] };

check('시작 버튼 입력칸: 처음 값 · 보낼 값 · 필수 비움 / 글자 수 넘침 검사', () => {
  assert.deepStrictEqual(L.defaultsOf(TPL), { length: '4000', note: '' });
  assert.deepStrictEqual(L.defaultsOf({ fields: [] }), {});
  assert.deepStrictEqual(L.valuesOf(TPL, { length: '3000' }), { length: '3000', note: '' }, '모든 칸을 문자열로 보낸다');
  assert.deepStrictEqual(L.checkFields(TPL, { length: '3000', note: '' }), { ok: true, key: '', message: '' });
  const empty = L.checkFields(TPL, { length: '  ', note: '' });
  assert.deepStrictEqual([empty.ok, empty.key, empty.message], [false, 'length', "'분량(공백 포함 글자 수)'을 적어 주세요."]);
  const long = L.checkFields(TPL, { length: '1234567', note: '' });
  assert.deepStrictEqual([long.ok, long.key, long.message], [false, 'length', "'분량(공백 포함 글자 수)'은 6자 이내로 적어 주세요."]);
  assert.strictEqual(L.checkFields(TPL, { length: '4000', note: '가'.repeat(601) }).key, 'note');
  assert.strictEqual(L.checkFields({ fields: [] }, {}).ok, true, '칸이 없는 시작 버튼은 바로 보낸다');
});

check('모드의 프로젝트: 종류가 맞는 것만 (서버 모드 설명이 있으면 그 종류 목록으로)', () => {
  const ps = [{ key: 'a', kind: 'generic' }, { key: 'n', kind: 'novel' }, { key: 'd', kind: 'design' }, { key: 'g', kind: 'godot' }, { key: 'n2', kind: 'novel' }];
  assert.deepStrictEqual(L.projectsOf('novel', ps).map((p) => p.key), ['n', 'n2']);
  assert.deepStrictEqual(L.projectsOf('design', ps).map((p) => p.key), ['d']);
  assert.deepStrictEqual(L.projectsOf('novel', ps, { modes: [{ id: 'novel', kinds: ['novel', 'docs'] }] }).map((p) => p.key), ['n', 'n2']);
  assert.deepStrictEqual(L.projectsOf('novel', [{ key: 'x', kind: 'docs' }], { modes: [{ id: 'novel', kinds: ['novel', 'docs'] }] }).map((p) => p.key), ['x']);
  assert.deepStrictEqual(L.projectsOf('novel', null), []);
});

check('이 프로젝트의 일: 그 프로젝트 것만, 새것이 먼저, 최대 8개', () => {
  const tasks = Array.from({ length: 10 }, (_, i) => ({ id: `T${String(i + 1).padStart(4, '0')}`, project: 'n', created_at: new Date(Date.UTC(2026, 9, 1, 0, i)).toISOString(), status: 'ready' }));
  tasks.push({ id: 'T0099', project: 'other', created_at: '2026-10-02T00:00:00Z', status: 'ready' });
  const rows = L.recentTasks(tasks, 'n');
  assert.strictEqual(rows.length, 8);
  assert.strictEqual(rows[0].id, 'T0010');
  assert.strictEqual(rows[7].id, 'T0003');
  assert.ok(rows.every((t) => t.project === 'n'));
  assert.strictEqual(L.recentTasks(tasks, 'n', 3).length, 3);
  assert.deepStrictEqual(L.recentTasks([], 'n'), []);
  const same = [{ id: 'T1', project: 'n', created_at: 'x' }, { id: 'T2', project: 'n', created_at: 'x' }];
  assert.deepStrictEqual(L.recentTasks(same, 'n').map((t) => t.id), ['T2', 'T1'], '때를 모르면 번호가 큰 것이 먼저');
});

check('끝난 일 번호 · 상태 색 · 몇 분 전 · 이름 뒤 조사', () => {
  assert.deepStrictEqual(L.doneIds([{ id: 'T2', project: 'n', status: 'done' }, { id: 'T1', project: 'n', status: 'done' }, { id: 'T3', project: 'n', status: 'ready' }, { id: 'T4', project: 'x', status: 'done' }], 'n'), ['T1', 'T2']);
  assert.deepStrictEqual(['queued', 'ready', 'running', 'checking', 'awaiting_approval', 'done', 'blocked', 'cancelled', '???'].map(L.statusKey), ['wait', 'wait', 'work', 'work', 'await', 'done', 'bad', 'stop', 'wait']);
  const NOW = Date.parse('2026-10-06T12:00:00Z');
  assert.deepStrictEqual([0, 30, 120, 3600 * 3, 86400 * 2].map((s) => L.ago(new Date(NOW - s * 1000).toISOString(), NOW)), ['방금', '방금', '2분 전', '3시간 전', '2일 전']);
  assert.strictEqual(L.ago('', NOW), '');
  assert.deepStrictEqual(['하나', '솔', '클로', '루나'].map(L.josa), ['가', '이', '가', '가']);
});

check('새 프로젝트 창 안내: 서버가 준 허용 경로의 폴더를 앞 세 개까지, 없으면 기본 글', () => {
  const info = { kinds: { novel: { default_paths: ['bible/**', 'chapters/**', 'notes/**', 'README.md'] }, design: { default_paths: ['brief/**', 'system/**', 'screens/**', 'assets/**', 'reviews/**', 'README.md'] } } };
  assert.strictEqual(L.folderText('novel', info), '직원은 허용된 폴더(bible/·chapters/·notes/ 등)만 고칠 수 있어요.');
  assert.strictEqual(L.folderText('design', info), '직원은 허용된 폴더(brief/·system/·screens/ 등)만 고칠 수 있어요.');
  assert.strictEqual(L.folderText('novel', null), '직원은 허용된 폴더(bible/·chapters/·notes/ 등)만 고칠 수 있어요.');
  assert.strictEqual(L.folderText('design', {}), '직원은 허용된 폴더(brief/·system/·screens/ 등)만 고칠 수 있어요.');
});

check('서버 글의 코드 표시(`)는 화면에서 뺀다 · 모드 글(제목·한 줄 설명)', () => {
  assert.strictEqual(L.plain('`brief/brief.md`와 참고'), 'brief/brief.md와 참고');
  assert.strictEqual(L.MODES.novel.title, '소설 집필실');
  assert.strictEqual(L.MODES.design.title, '디자인 작업실');
  assert.strictEqual(L.MODES.novel.newLabel, '새 작품 만들기');
  assert.strictEqual(L.MODES.design.newLabel, '새 디자인 프로젝트 만들기');
  assert.ok(L.MODES.novel.sub.includes('기획·집필·검토'));
  assert.ok(L.TEMPLATE_NOTICE.includes('진행판에서 결재하면') && L.TEMPLATE_NOTICE.includes('구독 사용량'));
});

// ui/data.js의 작업 종류 이름 (프로젝트 종류에 따라 집필·디자인 …): 화면 없이 data.js만 불러 온다
function loadData() {
  const vm = require('vm');
  const fs = require('fs');
  const src = fs.readFileSync(path.join(__dirname, '..', '..', 'ui', 'data.js'), 'utf8');
  const store = { getItem: () => null, setItem: () => {} };
  return vm.runInNewContext(`${src}
;Data`, { document: { querySelector: () => null }, localStorage: store, fetch: () => Promise.reject(new Error('x')), setTimeout, clearTimeout, console });
}

check('작업 종류 이름(Data.kindLabel): 소설 build=집필·research=자료 조사, 디자인 build=디자인·research=디자인 조사, 개발·다른 종류는 그대로', () => {
  const Data = loadData();
  Data.get().projects = [{ key: 'n', kind: 'novel' }, { key: 'd', kind: 'design' }, { key: 'g', kind: 'godot' }, { key: 'x', kind: 'generic' }, { key: 'k' }];
  const label = (project, kind) => Data.kindLabel({ project, kind });
  assert.deepStrictEqual(['build', 'research', 'plan'].map((k) => label('n', k)), ['집필', '자료 조사', '기획']);
  assert.deepStrictEqual(['build', 'research', 'plan'].map((k) => label('d', k)), ['디자인', '디자인 조사', '기획']);
  assert.deepStrictEqual(['build', 'research', 'plan'].map((k) => label('g', k)), ['개발', '리서치', '기획']);
  assert.deepStrictEqual(['build', 'research'].map((k) => label('x', k)), ['개발', '리서치']);
  assert.strictEqual(label('k', 'build'), '개발', '종류를 모르는 프로젝트는 개발 이름 그대로');
  assert.strictEqual(label('nope', 'build'), '개발', '없는 프로젝트도 그대로');
  for (const k of ['skill', 'look', 'hire', 'tool']) assert.strictEqual(label('n', k), Data.KIND_LABELS[k], `${k}는 소설 프로젝트에서도 그대로`);
  assert.strictEqual(label('n', 'mystery'), 'mystery', '모르는 종류는 그대로 보인다');
  assert.strictEqual(Data.kindLabel(null), '');
  assert.strictEqual(Data.KIND_LABELS.build, '개발', '기존 이름표는 바뀌지 않는다');
  assert.deepStrictEqual(['generic', 'godot', 'docs', 'design', 'novel', 'x'].map(Data.projectKindLabel), ['개발', 'Godot', '문서', '디자인', '소설', '']);
  assert.strictEqual(Data.projectKind('n'), 'novel');
  assert.strictEqual(Data.projectKind('nope'), '');
  assert.strictEqual(Data.projectRawUrl('novel-1', 'assets/a b.png'), '/api/projects/novel-1/raw?path=assets%2Fa%20b.png');
});

console.log(`소설 집필실·디자인 작업실 계산 점검 통과 (${n}개)`);
