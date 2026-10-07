// 이미지·영상 작업대 계산 점검 (브라우저 없이): node tools/dev/media_sim.js
// ui/media.js의 순수 계산(제목·길이 맞추기·상태 글·거르기와 개수·몇 분 전·지난 시간·실행 본문·산출물 주소 검사·연결 상태·만들기 단추 모양 등)만 확인한다.
// 화면은 tools/dev/media_browser.cjs(연습용 모의 서버)와 캡처로 본다.
'use strict';
const assert = require('assert');
const path = require('path');

const Media = require(path.join(__dirname, '..', '..', 'ui', 'media.js'));
const L = Media.logic;

let n = 0;
function check(name, fn) { fn(); n += 1; console.log(`  ✓ ${name}`); }

const NOW = Date.parse('2026-10-06T12:00:00+09:00');
const iso = (secondsAgo) => new Date(NOW - secondsAgo * 1000).toISOString();
const J = (id, status, extra = {}) => ({ id, run: id.split('/')[0], node: 'b', title: id, created_at: iso(120), kind: 'image', status, run_status: 'running', error: '', prompt: `지시 ${id}`, duration: null, simulation: false, model_verified: false, task: null, assets: [], ...extra });
const ASSET = (run = 'W1') => [{ kind: 'image', sha256: 'abcdef0123456789', url: `/api/workbench/runs/${run}/artifacts/b/0` }];

check('제목: "그림 · 지시 앞부분", 80자 이내, 비면 새 요청, 줄바꿈은 공백으로', () => {
  assert.strictEqual(L.makeTitle('image', '작은 파란 종이배'), '그림 · 작은 파란 종이배');
  assert.strictEqual(L.makeTitle('video', '  파란  종이배\n흘러가요 '), '영상 · 파란 종이배 흘러가요');
  assert.strictEqual(L.makeTitle('image', ''), '그림 · 새 요청');
  const long = L.makeTitle('video', '가'.repeat(500));
  assert.ok([...long].length <= 80, `80자 이내 (${[...long].length})`);
  assert.ok(long.endsWith('…') && long.startsWith('영상 · '));
  assert.ok([...L.makeTitle('image', '😀'.repeat(200))].length <= 80, '이모지(두 칸 글자)도 80자 이내');
});

check('영상 길이: 1~15 정수로 맞춘다 (범위 밖·소수·빈 값·글자)', () => {
  assert.deepStrictEqual(L.clampDuration('6'), { value: 6, adjusted: false });
  assert.deepStrictEqual(L.clampDuration(10), { value: 10, adjusted: false });
  assert.deepStrictEqual(L.clampDuration('0'), { value: 1, adjusted: true });
  assert.deepStrictEqual(L.clampDuration('16'), { value: 15, adjusted: true });
  assert.deepStrictEqual(L.clampDuration('-3'), { value: 1, adjusted: true });
  assert.deepStrictEqual(L.clampDuration('6.7'), { value: 7, adjusted: true });
  assert.deepStrictEqual(L.clampDuration(''), { value: 6, adjusted: true });
  assert.deepStrictEqual(L.clampDuration('abc'), { value: 6, adjusted: true });
  assert.deepStrictEqual(L.clampDuration(null), { value: 6, adjusted: true });
});

check('글 지시 검사: 비면 안 됨, 4000자까지', () => {
  assert.strictEqual(L.validate('   ').ok, false);
  assert.strictEqual(L.validate('가'.repeat(4000)).ok, true);
  assert.strictEqual(L.validate('가'.repeat(4001)).ok, false);
  assert.match(L.validate('').message, /적어 주세요/);
});

check('실행 본문: 글 지시 a → 그림·영상 b, 영상은 길이, 프로젝트·허용 경로', () => {
  const img = L.buildBody({ kind: 'image', text: ' 작은 종이배 ', duration: 9, project: 'core' });
  assert.deepStrictEqual(img.graph.nodes, [
    { id: 'a', ref: { id: 'builtin-input', version: 1 }, params: { text: '작은 종이배' } },
    { id: 'b', ref: { id: 'builtin-grok_image', version: 1 }, params: {} },
  ]);
  assert.deepStrictEqual(img.graph.edges, [{ from: 'a', to: 'b' }]);
  assert.deepStrictEqual([img.project, img.allowed_paths, img.title], ['core', [], '그림 · 작은 종이배']);
  const vid = L.buildBody({ kind: 'video', text: '종이배', duration: '99', project: null });
  assert.deepStrictEqual(vid.graph.nodes[1], { id: 'b', ref: { id: 'builtin-grok_video', version: 1 }, params: { duration: 15 } });
  assert.strictEqual(vid.project, null);
  assert.ok([...vid.title].length <= 80);
});

check('Grok에 보낼 요청: plan이 알려 준 글·종류·길이 그대로', () => {
  assert.deepStrictEqual(L.grokRequest({ kind: 'image', input: '배', options: {} }), { kind: 'image', text: '배' });
  assert.deepStrictEqual(L.grokRequest({ kind: 'video', input: '배', options: { duration: 7 } }), { kind: 'video', text: '배', duration: 7 });
});

check('상태 → 쉬운 글: 끝남·막힘·중단·만드는 중·기다리는 중 (진행 중인지 함께)', () => {
  const s = (status, run_status = 'running') => L.statusInfo(J('W1/b', status, { run_status }));
  assert.deepStrictEqual(s('succeeded', 'succeeded'), { key: 'done', label: '끝남', active: false });
  assert.deepStrictEqual(s('blocked', 'blocked'), { key: 'bad', label: '막힘', active: false });
  assert.deepStrictEqual(s('cancelled', 'cancelled'), { key: 'stop', label: '중단', active: false });
  assert.deepStrictEqual(s('skipped'), { key: 'stop', label: '중단', active: false });
  assert.deepStrictEqual(s('running'), { key: 'work', label: '만드는 중', active: true });
  assert.deepStrictEqual(s('dispatching'), { key: 'work', label: '만드는 중', active: true });
  assert.deepStrictEqual(s('pending'), { key: 'wait', label: '기다리는 중', active: true });
  assert.deepStrictEqual(s('waiting'), { key: 'wait', label: '기다리는 중', active: true });
  assert.strictEqual(s('pending', 'blocked').key, 'bad', '실행이 막혔으면 기다리던 노드도 막힘');
  assert.strictEqual(s('pending', 'cancelled').key, 'stop');
  assert.strictEqual(s('running', 'cancelled').active, false, '중단된 실행은 더 읽지 않는다');
});

check('산출물 주소: 같은 출처 /api/… 만 (blob·data·바깥 주소·.. 금지)', () => {
  assert.ok(L.safeUrl('/api/workbench/runs/W1/artifacts/b/0'));
  for (const bad of ['blob:http://x/1', 'data:image/png;base64,AAAA', 'http://evil.test/a.png', '//evil.test/a.png', '/api/../etc/passwd', 'javascript:alert(1)', '', null, undefined, 5]) assert.ok(!L.safeUrl(bad), `막혀야 함: ${bad}`);
  assert.deepStrictEqual(L.pickAsset(J('W1/b', 'succeeded', { assets: ASSET() })), { kind: 'image', url: '/api/workbench/runs/W1/artifacts/b/0', sha256: 'abcdef0123456789' });
  assert.strictEqual(L.pickAsset(J('W1/b', 'succeeded', { assets: [{ kind: 'image', url: 'http://evil.test/x.png' }] })), null);
  assert.strictEqual(L.pickAsset(J('W1/b', 'running')), null);
});

check('거르기와 개수: 전체·그림·영상', () => {
  const jobs = [J('W1/b', 'succeeded'), J('W2/b', 'running', { kind: 'video' }), J('W3/b', 'blocked', { kind: 'video' })];
  assert.deepStrictEqual(L.counts(jobs), { all: 3, image: 1, video: 2 });
  assert.deepStrictEqual(L.filterJobs(jobs, 'all').map((j) => j.id), ['W1/b', 'W2/b', 'W3/b']);
  assert.deepStrictEqual(L.filterJobs(jobs, 'video').map((j) => j.id), ['W2/b', 'W3/b']);
  assert.deepStrictEqual(L.filterJobs(jobs, 'image').map((j) => j.id), ['W1/b']);
  assert.deepStrictEqual(L.counts([]), { all: 0, image: 0, video: 0 });
});

check('몇 분 전 · 지난 시간 · 날짜 글', () => {
  assert.deepStrictEqual([10, 120, 3 * 3600, 2 * 86400].map((s) => L.ago(iso(s), NOW)), ['방금', '2분 전', '3시간 전', '2일 전']);
  assert.strictEqual(L.ago('', NOW), '');
  assert.strictEqual(L.ago('엉터리', NOW), '');
  assert.deepStrictEqual([0, 34000, 72000, 120000, 3720000, 7200000, -5].map(L.elapsedText), ['0초', '34초', '1분 12초', '2분', '1시간 2분', '2시간', '0초']);
  assert.match(L.whenText('2026-10-06T15:42:00'), /^10월 6일 15:42$/);
  assert.strictEqual(L.whenText(''), '');
});

check('영상 길이 글: 요청 N초 · 실제 N초 (소수 둘째 자리까지), 그림은 비어 있다', () => {
  assert.strictEqual(L.durationText(J('W1/b', 'succeeded', { kind: 'video', duration: 6, requested_duration: 6, measured_duration_s: 6.04 })), '요청 6초 · 실제 6.04초');
  assert.strictEqual(L.durationText(J('W1/b', 'succeeded', { kind: 'video', duration: 6, measured_duration_s: 6 })), '요청 6초 · 실제 6초');
  assert.strictEqual(L.durationText(J('W1/b', 'running', { kind: 'video', duration: 8 })), '요청 8초');
  assert.strictEqual(L.durationText(J('W1/b', 'succeeded')), '');
});

check('결과 아래 주의 글: 연습용 · 요청과 다른 길이 · 길이 못 잼 · 모델 미확인', () => {
  assert.deepStrictEqual(L.captionNotes(J('W1/b', 'succeeded', { simulation: true })), [{ tone: 'warn', text: 'MOCK / 연습용 · 실제 생성 아님' }]);
  assert.deepStrictEqual(L.captionNotes(J('W1/b', 'succeeded', { kind: 'video', duration_check: 'mismatch' })), [{ tone: 'warn', text: '요청과 다른 길이' }]);
  assert.deepStrictEqual(L.captionNotes(J('W1/b', 'succeeded', { kind: 'video', duration_check: 'unknown' })), [{ tone: 'info', text: '길이를 확인하지 못했어요' }]);
  assert.deepStrictEqual(L.captionNotes(J('W1/b', 'succeeded', { kind: 'video', duration_check: 'ok' })), []);
  assert.deepStrictEqual(L.captionNotes(J('W1/b', 'succeeded', { duration_check: 'mismatch' })), [], '그림에는 길이 주의가 없다');
  assert.strictEqual(L.modelLine(J('W1/b', 'succeeded')), '모델은 확인되지 않았어요');
  assert.strictEqual(L.modelLine(J('W1/b', 'succeeded', { model_verified: true })), '');
});

check('막힘·중단·결과 없음: 이유와 "자동으로 다시 보내지 않아요" 안내', () => {
  const bad = L.problemInfo(J('W1/b', 'blocked', { run_status: 'blocked', error: '로그인이 필요해요' }));
  assert.deepStrictEqual([bad.title, bad.reason], ['여기서 멈췄어요', '로그인이 필요해요']);
  assert.match(bad.help, /자동으로 다시 보내지 않아요/);
  assert.strictEqual(L.problemInfo(J('W1/b', 'blocked', { run_status: 'blocked' })).reason, '이유가 적혀 있지 않아요.');
  assert.strictEqual(L.problemInfo(J('W1/b', 'cancelled', { run_status: 'cancelled' })).title, '중단했어요');
  const none = L.problemInfo(J('W1/b', 'succeeded', { run_status: 'succeeded' }));
  assert.match(none.title, /파일을 찾지 못했어요/);
  assert.match(none.help, /자동으로 다시 보내지 않아요/);
  assert.strictEqual(L.problemInfo(J('W1/b', 'succeeded', { run_status: 'succeeded', assets: ASSET() })), null);
  assert.strictEqual(L.problemInfo(J('W1/b', 'running')), null);
});

check('변화 감지: 같은 작업이면 같은 글, 상태·결과가 바뀌면 다른 글', () => {
  const a = J('W1/b', 'running');
  assert.strictEqual(L.jobSig(a), L.jobSig({ ...a }));
  assert.notStrictEqual(L.jobSig(a), L.jobSig({ ...a, status: 'succeeded', assets: ASSET() }));
  assert.notStrictEqual(L.jobSig(a), L.jobSig({ ...a, error: '막힘' }));
});

check('3초 읽기: 이 화면이 보이고 만드는 중인 작업이 있을 때만', () => {
  const running = [J('W1/b', 'running'), J('W2/b', 'succeeded')];
  const idle = [J('W2/b', 'succeeded'), J('W3/b', 'blocked', { run_status: 'blocked' })];
  assert.strictEqual(L.shouldPoll(running, true, false), true);
  assert.strictEqual(L.shouldPoll(running, false, false), false, '화면이 안 보이면 멈춤');
  assert.strictEqual(L.shouldPoll(running, true, true), false, '탭이 숨으면 멈춤');
  assert.strictEqual(L.shouldPoll(idle, true, false), false, '끝난 것만 있으면 멈춤');
  assert.strictEqual(L.shouldPoll([], true, false), false);
  assert.strictEqual(L.POLL_MS, 3000);
});

check('Grok 연결 상태: 연습용 · 연결됨 · 연결 안 됨 · 읽는 중 · 못 읽음', () => {
  const sim = { image: { enabled: true, simulation: true }, video: { enabled: true, simulation: true } };
  const on = { image: { enabled: true, simulation: false }, video: { enabled: true, simulation: false } };
  const off = { image: { enabled: false }, video: { enabled: false } };
  assert.strictEqual(L.connState('ready', { enabled: false }, sim), 'sim');
  assert.strictEqual(L.connState('ready', { enabled: true, mode: 'official_cli' }, on), 'on');
  assert.strictEqual(L.connState('ready', { enabled: true, mode: 'old' }, on), 'off');
  assert.strictEqual(L.connState('ready', { enabled: false, configured: false }, off), 'off');
  assert.strictEqual(L.connState('loading', null, null), 'loading');
  assert.strictEqual(L.connState('error', null, null), 'unknown');
  assert.ok(L.canMake(sim, 'video') && L.canMake(on, 'image') && !L.canMake(off, 'image') && !L.canMake(null, 'image'));
});

check('[만들기] 단추: 읽는 중·연결 안 됨은 "연결하고 만들기", 글이 비면 꺼짐, 확인 중에는 잠김', () => {
  const on = { image: { enabled: true }, video: { enabled: true } };
  const off = { image: { enabled: false }, video: { enabled: false } };
  const base = { reviewing: false, loadState: 'ready', caps: on, kind: 'image', text: '배' };
  assert.deepStrictEqual(L.makeState(base), { label: '만들기', disabled: false, reason: '' });
  assert.deepStrictEqual([L.makeState({ ...base, text: '  ' }).label, L.makeState({ ...base, text: '  ' }).disabled], ['만들기', true]);
  assert.deepStrictEqual([L.makeState({ ...base, caps: off }).label, L.makeState({ ...base, caps: off }).disabled], ['연결하고 만들기', false]);
  assert.strictEqual(L.makeState({ ...base, caps: off, text: '' }).label, '연결하고 만들기', '글이 비어도 연결은 먼저 할 수 있다');
  assert.strictEqual(L.makeState({ ...base, reviewing: true }).disabled, true);
  assert.strictEqual(L.makeState({ ...base, caps: null, loadState: 'loading' }).disabled, true);
  assert.match(L.makeState({ ...base, caps: null, loadState: 'error' }).reason, /읽지 못했어요/);
});

check('내려받는 파일 이름: 종류·때·서버가 알려 준 파일 종류의 확장자', () => {
  const j = J('W1/b', 'succeeded', { created_at: '2026-10-06T15:42:00' });
  assert.strictEqual(L.fileName(j, 'image/png'), 'ai-studio-그림-20261006-1542.png');
  assert.strictEqual(L.fileName({ ...j, kind: 'video' }, 'video/webm; codecs=vp9'), 'ai-studio-영상-20261006-1542.webm');
  assert.strictEqual(L.fileName(j, ''), 'ai-studio-그림-20261006-1542', '종류를 모르면 확장자 없이');
  assert.ok(!/[\\/:*?"<>|]/.test(L.fileName(j, 'image/jpeg')), '윈도우에서 못 쓰는 글자 없음');
});

check('예시 지시: 그림 3개·영상 3개, 4000자 안', () => {
  for (const kind of ['image', 'video']) {
    assert.strictEqual(L.EXAMPLES[kind].length, 3);
    for (const text of L.EXAMPLES[kind]) assert.ok(L.validate(text).ok);
  }
});

check('줄인 글: 줄바꿈은 공백으로, 길면 …', () => {
  assert.strictEqual(L.excerpt('a\nb   c', 40), 'a b c');
  assert.strictEqual(L.excerpt('가나다라마바사', 5), '가나다라…');
  assert.strictEqual(L.excerpt('', 5), '');
});

console.log(`이미지·영상 작업대 점검 통과 (${n}개)`);
