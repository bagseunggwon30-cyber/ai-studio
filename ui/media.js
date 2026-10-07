/* AI 스튜디오 — 이미지·영상 작업대: 글로 지시해서 그림과 영상을 만들고, 만든 것을 모아 보는 화면.
 *
 * 왼쪽(새로 만들기 + 내 작업물) · 가운데(작업면: 흐름도 + 큰 미리보기) · 오른쪽(속성: 새 요청 또는 지난 작업물 정보)의 3단.
 * 서버가 이미 만들어 둔 것만 쓴다: 읽기 GET /api/workbench/media, 만들기 plan → (진짜면 Grok 승인 grok-everywhere plan·consent) → start,
 * 중단 runs/<run>/halt, 연결 grok-everywhere connection-plan·configure·disconnect. 새 서버 일은 없다.
 * 안전 규칙: 한 번 누르면 한 번만 보낸다(누르는 순간 잠금 + 같은 request_id), 보내기 전에 정확한 지시 글·종류·길이를 다시 보여 주고 체크를 받는다
 *   (연습용이면 체크 없이 '연습용 · 실제 생성 아님'), 실패·불확실이면 자동으로 다시 보내지 않고 새로 승인받게 한다.
 * CSP: 글자는 모두 textContent(지시 글·제목은 믿지 않는 입력), innerHTML은 고정 SVG 아이콘만, 동적 스타일 없음, 그림·영상 주소는 같은 출처(/api/…)만.
 * 순수 계산(Media.logic: 제목·길이·상태 글·거르기·본문 만들기 등)은 DOM 없이 돈다 — tools/dev/media_sim.js가 확인한다.
 * board.js가 껍데기(왼쪽 메뉴)와 이 구역(.bd-page-media)을 만들어 주고, 필요한 도구는 init(el, helpers)로 받는다.
 */
'use strict';

const Media = (() => {
  // ---------------------------------------------------------------- 순수 계산
  const KINDS = { image: '그림', video: '영상' };
  const TITLE_MAX = 80;
  const TEXT_MAX = 4000;
  const DUR_MIN = 1;
  const DUR_MAX = 15;
  const DUR_DEFAULT = 6;
  const POLL_MS = 3000;
  const NODE = 'b'; // 흐름 안 그림·영상 노드 이름 (a = 글 지시)
  const ACTIVE = new Set(['pending', 'running', 'waiting', 'dispatching']);
  const RUN_ENDED = new Set(['blocked', 'cancelled', 'failed', 'succeeded', 'completed', 'done']);
  const EXAMPLES = {
    image: ['작은 파란 종이배가 잔잔한 물 위에 떠 있는 그림', '비 오는 날 창가에 앉아 있는 하얀 고양이', '노을 진 바닷가에 서 있는 작은 등대'],
    video: ['파란 종이배가 잔잔한 물 위를 천천히 흘러가는 영상', '창밖에 비가 내리고 고양이가 하품하는 장면', '바닷가 등대 위로 구름이 지나가는 노을'],
  };
  const EXT = { 'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'image/gif': '.gif', 'video/mp4': '.mp4', 'video/webm': '.webm', 'video/quicktime': '.mov' };
  const AGAIN = '같은 요청을 자동으로 다시 보내지 않아요. 다시 만들려면 “같은 지시로 다시 만들기”를 눌러 새로 승인해 주세요.';

  const chars = (s) => Array.from(String(s ?? ''));
  const p2 = (n) => String(n).padStart(2, '0');
  const kindLabel = (kind) => KINDS[kind] || '파일';

  // 한 줄로 줄인 글 (n글자 넘으면 …)
  function excerpt(text, n = 40) {
    const one = chars(String(text ?? '').replace(/\s+/g, ' ').trim());
    return one.length > n ? `${one.slice(0, Math.max(1, n - 1)).join('').trimEnd()}…` : one.join('');
  }

  // 작업 제목 (80자 이내): "그림 · 작은 파란 종이배"
  function makeTitle(kind, text) {
    const head = `${kindLabel(kind)} · `;
    return head + (excerpt(text, TITLE_MAX - head.length) || '새 요청');
  }

  // 영상 길이: 1~15초 정수. 비었거나 숫자가 아니면 기본 6초. adjusted = 사장님이 적은 값과 달라졌는가
  function clampDuration(raw) {
    const text = String(raw ?? '').trim();
    const n = Number(text);
    if (!text || !Number.isFinite(n)) return { value: DUR_DEFAULT, adjusted: true };
    const value = Math.min(DUR_MAX, Math.max(DUR_MIN, Math.round(n)));
    return { value, adjusted: String(value) !== text };
  }

  // 글 지시 검사
  function validate(text) {
    const t = String(text ?? '').trim();
    if (!t) return { ok: false, message: '무엇을 만들지 먼저 적어 주세요.' };
    if (chars(t).length > TEXT_MAX) return { ok: false, message: `글이 너무 길어요 (${TEXT_MAX}자까지).` };
    return { ok: true, message: '' };
  }

  // 실행 본문: [글 지시 a] → [그림·영상 b]. 영상이면 길이를 넣는다
  function buildBody({ kind, text, duration, project }) {
    const t = String(text ?? '').trim();
    const params = kind === 'video' ? { duration: clampDuration(duration).value } : {};
    return {
      title: makeTitle(kind, t),
      graph: {
        nodes: [
          { id: 'a', ref: { id: 'builtin-input', version: 1 }, params: { text: t } },
          { id: NODE, ref: { id: `builtin-grok_${kind === 'video' ? 'video' : 'image'}`, version: 1 }, params },
        ],
        edges: [{ from: 'a', to: NODE }],
      },
      project: project || null,
      allowed_paths: [],
    };
  }

  // 진짜 Grok에 보낼 요청 (plan이 알려 준 정확한 글·종류·길이 그대로)
  function grokRequest(item) {
    const request = { kind: item.kind, text: item.input };
    if (item.kind === 'video') request.duration = (item.options || {}).duration;
    return request;
  }

  // 노드 상태 → 쉬운 글 + 종류(칩 색) + 아직 진행 중인가
  function statusInfo(job) {
    const s = String((job && job.status) || 'pending');
    const r = String((job && job.run_status) || '');
    if (s === 'succeeded') return { key: 'done', label: '끝남', active: false };
    if (s === 'blocked') return { key: 'bad', label: '막힘', active: false };
    if (s === 'cancelled' || s === 'skipped') return { key: 'stop', label: '중단', active: false };
    if (ACTIVE.has(s)) {
      if (r === 'blocked') return { key: 'bad', label: '막힘', active: false };
      if (r === 'cancelled') return { key: 'stop', label: '중단', active: false };
      if (RUN_ENDED.has(r)) return { key: 'wait', label: '기다리는 중', active: false };
      if (s === 'running' || s === 'dispatching') return { key: 'work', label: '만드는 중', active: true };
      return { key: 'wait', label: '기다리는 중', active: true };
    }
    return { key: 'wait', label: '기다리는 중', active: false };
  }

  // 같은 출처의 서버 산출물 주소만 연다 (blob:·data:·바깥 주소 금지)
  const safeUrl = (url) => typeof url === 'string' && /^\/api\/[A-Za-z0-9._~/-]+$/.test(url) && !url.includes('..');
  function pickAsset(job) {
    const found = ((job && job.assets) || []).find((a) => a && safeUrl(a.url));
    return found ? { kind: found.kind || job.kind, url: found.url, sha256: typeof found.sha256 === 'string' ? found.sha256 : '' } : null;
  }

  function filterJobs(jobs, filter) {
    return filter === 'image' || filter === 'video' ? jobs.filter((j) => j.kind === filter) : jobs;
  }
  function counts(jobs) {
    return { all: jobs.length, image: jobs.filter((j) => j.kind === 'image').length, video: jobs.filter((j) => j.kind === 'video').length };
  }

  // 얼마 전인지 (방금 · N분 전 · N시간 전 · N일 전)
  function ago(iso, now = Date.now()) {
    const at = Date.parse(iso || '');
    if (!Number.isFinite(at)) return '';
    const m = Math.floor((now - at) / 60000);
    if (m < 1) return '방금';
    if (m < 60) return `${m}분 전`;
    const hr = Math.floor(m / 60);
    return hr < 24 ? `${hr}시간 전` : `${Math.floor(hr / 24)}일 전`;
  }

  // 지난 시간 글: 34초 · 1분 12초 · 2분 · 1시간 2분
  function elapsedText(ms) {
    const s = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
    if (s < 60) return `${s}초`;
    const m = Math.floor(s / 60);
    if (m < 60) return s % 60 ? `${m}분 ${s % 60}초` : `${m}분`;
    return m % 60 ? `${Math.floor(m / 60)}시간 ${m % 60}분` : `${Math.floor(m / 60)}시간`;
  }

  // 날짜·시각: 10월 6일 15:42
  function whenText(iso) {
    const d = new Date(Date.parse(iso || ''));
    return Number.isNaN(d.getTime()) ? '' : `${d.getMonth() + 1}월 ${d.getDate()}일 ${p2(d.getHours())}:${p2(d.getMinutes())}`;
  }

  // 영상 길이 글: 요청 6초 · 실제 6.04초
  function durationText(job) {
    if (!job || job.kind !== 'video') return '';
    const req = Number.isFinite(job.requested_duration) ? job.requested_duration : job.duration;
    const out = [];
    if (Number.isFinite(req)) out.push(`요청 ${req}초`);
    if (Number.isFinite(job.measured_duration_s)) out.push(`실제 ${Math.round(job.measured_duration_s * 100) / 100}초`);
    return out.join(' · ');
  }

  // 결과 아래 주의 칩: 연습용 · 길이가 다름 · 길이를 못 쟀음
  function captionNotes(job) {
    const out = [];
    if (job.simulation) out.push({ tone: 'warn', text: 'MOCK / 연습용 · 실제 생성 아님' });
    if (job.kind === 'video' && job.duration_check === 'mismatch') out.push({ tone: 'warn', text: '요청과 다른 길이' });
    else if (job.kind === 'video' && job.duration_check === 'unknown' && !job.simulation) out.push({ tone: 'info', text: '길이를 확인하지 못했어요' });
    return out;
  }
  const modelLine = (job) => (job.model_verified ? '' : '모델은 확인되지 않았어요');

  // 막힘·중단·결과 없음일 때 보여 줄 말
  function problemInfo(job) {
    const st = statusInfo(job);
    if (st.key === 'bad') return { title: '여기서 멈췄어요', reason: job.error || '이유가 적혀 있지 않아요.', help: AGAIN };
    if (st.key === 'stop') return { title: '중단했어요', reason: job.error || '', help: AGAIN };
    if (st.key === 'done' && !pickAsset(job)) return { title: '결과 파일을 찾지 못했어요', reason: '끝났다는 기록은 있는데 열 수 있는 파일이 없어요. 결과가 확실하지 않아요.', help: AGAIN };
    return null;
  }

  // 한 작업의 변화 감지용 글 (같으면 다시 그리지 않는다)
  function jobSig(job) {
    const a = pickAsset(job);
    return JSON.stringify([job.id, job.status, job.run_status, job.error, job.kind, job.duration, job.task, job.simulation, job.duration_check, job.measured_duration_s,
      job.requested_duration, job.model_verified, a ? a.url : '', a ? a.sha256 : '', job.prompt, job.title, job.created_at]);
  }

  // 3초마다 읽을지: 이 화면이 보이고, 만드는 중인 작업이 있을 때만
  const shouldPoll = (jobs, visible, hidden) => Boolean(visible) && !hidden && jobs.some((j) => statusInfo(j).active);

  // Grok 연결 상태: loading | unknown(못 읽음) | sim(연습용) | on | off
  function connState(loadState, conn, caps) {
    if (!caps) return loadState === 'error' ? 'unknown' : 'loading';
    if ((caps.image && caps.image.simulation) || (caps.video && caps.video.simulation)) return 'sim';
    return conn && conn.enabled && conn.mode === 'official_cli' ? 'on' : 'off';
  }
  const canMake = (caps, kind) => Boolean(caps && caps[kind] && caps[kind].enabled);

  // [만들기] 단추 모양
  function makeState({ reviewing, loadState, caps, kind, text }) {
    if (reviewing) return { label: '확인하는 중…', disabled: true, reason: '' };
    if (!caps) return { label: '만들기', disabled: true, reason: loadState === 'error' ? '연결 상태를 읽지 못했어요. 잠시 뒤 다시 해 주세요.' : '연결 상태를 확인하는 중이에요.' };
    if (!canMake(caps, kind)) return { label: '연결하고 만들기', disabled: false, reason: 'Grok을 먼저 연결해야 만들 수 있어요.' };
    if (!String(text ?? '').trim()) return { label: '만들기', disabled: true, reason: '무엇을 만들지 먼저 적어 주세요.' };
    return { label: '만들기', disabled: false, reason: '' };
  }

  // 내려받는 파일 이름: ai-studio-그림-20261006-1542.png (확장자는 서버가 알려 준 종류로, 모르면 없음)
  function fileName(job, mime) {
    const type = String(mime || '').split(';')[0].trim().toLowerCase();
    const d = new Date(Date.parse(job.created_at || ''));
    const stamp = Number.isNaN(d.getTime()) ? '' : `-${d.getFullYear()}${p2(d.getMonth() + 1)}${p2(d.getDate())}-${p2(d.getHours())}${p2(d.getMinutes())}`;
    return `ai-studio-${kindLabel(job.kind)}${stamp}${EXT[type] || ''}`;
  }

  const logic = {
    KINDS, TEXT_MAX, DUR_MIN, DUR_MAX, DUR_DEFAULT, POLL_MS, EXAMPLES, AGAIN,
    excerpt, makeTitle, clampDuration, validate, buildBody, grokRequest, statusInfo, safeUrl, pickAsset, filterJobs, counts, ago, elapsedText,
    whenText, durationText, captionNotes, modelLine, problemInfo, jobSig, shouldPoll, connState, canMake, makeState, fileName,
  };

  // ---------------------------------------------------------------- 화면 (init 뒤에만 DOM을 만진다)
  let root = null;
  let H = null; // board.js가 준 도구 { notify, fail, openTask, openWorkbench }
  let visible = false;
  let built = false;
  let jobs = []; // 서버가 알려 준 작업물 (새것이 먼저)
  const placeholders = new Map(); // 방금 시작했는데 서버 목록에는 아직 없는 작업: id → job
  let conn = null;
  let caps = null;
  let loadState = 'idle'; // idle | loading | ready | error
  let loadError = '';
  let selectedId = null; // null = 새 요청
  let filter = 'all';
  const draft = { kind: 'image', text: '', duration: DUR_DEFAULT };
  let reviewing = false; // 계획을 받아 오는 중 (누르는 순간 잠금)
  let sending = false; // 확인 창에서 보내는 중
  let connectOpening = false;
  let fetching = false;
  let again = false; // 읽는 동안 또 읽어 달라는 요청이 왔다
  let pollTimer = 0;
  let tickTimer = 0;
  const E = {}; // 자주 쓰는 요소
  const sig = { head: '', stage: '', right: '' };
  const cards = new Map(); // 작업 id → 카드 요소

  const h = (...a) => Popups.h(...a);
  const ICON = {
    image: '<svg viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="15" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="M4 17l4.5-4.5 3.5 3.5 3-3 5 4.5"/></svg>',
    video: '<svg viewBox="0 0 24 24"><rect x="3.5" y="5.5" width="13" height="13" rx="3"/><path d="M16.5 10.5l4-2.5v8l-4-2.5"/></svg>',
    text: '<svg viewBox="0 0 24 24"><path d="M5 6.5h14M5 11h14M5 15.5h9"/></svg>',
    result: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="4"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/></svg>',
    download: '<svg viewBox="0 0 24 24"><path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/></svg>',
    redo: '<svg viewBox="0 0 24 24"><path d="M5 12a7 7 0 1 1 2.2 5.1"/><path d="M5 18.5V13h5.5"/></svg>',
    task: '<svg viewBox="0 0 24 24"><path d="M6 3.5h8l4 4V20.5H6Z"/><path d="M9 12.5h6M9 16h4"/></svg>',
    stop: '<svg viewBox="0 0 24 24"><rect x="6.5" y="6.5" width="11" height="11" rx="2.5"/></svg>',
    plug: '<svg viewBox="0 0 24 24"><path d="M9 4v4M15 4v4M7 8h10v3a5 5 0 0 1-10 0Z"/><path d="M12 16v4.5"/></svg>',
    warn: '<svg viewBox="0 0 24 24"><path d="M12 4.5l8.5 15h-17Z"/><path d="M12 10v4.5M12 17.3v.2"/></svg>',
    minus: '<svg viewBox="0 0 24 24"><path d="M6 12h12"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><path d="M12 6v12M6 12h12"/></svg>',
    node: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="7" height="6" rx="1.5"/><rect x="14" y="14" width="7" height="6" rx="1.5"/><path d="M10 7h2.5a2 2 0 0 1 2 2v5"/></svg>',
    folder: '<svg viewBox="0 0 64 64"><path d="M8 18a4 4 0 0 1 4-4h14l5 6h21a4 4 0 0 1 4 4v24a4 4 0 0 1-4 4H12a4 4 0 0 1-4-4Z"/><path d="M22 40l6-6 5 5 4-4 7 7"/></svg>',
  };
  const ico = (name, cls = 'md-ico') => { const el = h('span', { class: cls, 'aria-hidden': 'true' }); el.innerHTML = ICON[name] || ''; return el; };
  const dot = (key) => h('i', { class: `md-dot ${key}`, 'aria-hidden': 'true' });

  const selectedJob = () => (selectedId ? allJobs().find((j) => j.id === selectedId) || null : null);
  function allJobs() {
    const now = Date.now();
    for (const [id, p] of placeholders) if (p.until < now || jobs.some((j) => j.id === id)) placeholders.delete(id);
    return [...placeholders.values(), ...jobs];
  }
  const isSim = () => connState(loadState, conn, caps) === 'sim';

  // 다시 그려도 키보드 초점이 그대로이게
  function keepFocus(box, fn) {
    const a = document.activeElement;
    const key = a && box.contains(a) ? a.getAttribute('data-fk') : null;
    fn();
    if (key) {
      const back = box.querySelector(`[data-fk="${CSS.escape(key)}"]`);
      if (back) back.focus({ preventScroll: true });
    }
  }

  function init(el, helpers) {
    root = el;
    H = helpers || { notify: () => {}, fail: () => {}, openTask: () => {}, openWorkbench: () => {} };
    build();
    document.addEventListener('visibilitychange', () => {
      if (!visible) return;
      if (document.hidden) stopTimers();
      else { refresh(); startTick(); }
    });
  }

  function setVisible(on) {
    visible = Boolean(on);
    if (!root || !built) return;
    if (visible) {
      renderAll();
      refresh();
      startTick();
    } else {
      stopTimers();
      for (const v of root.querySelectorAll('video')) v.pause(); // 숨기면 소리도 멈춘다
    }
  }

  function render() { if (visible && built) renderAll(); }

  function stopTimers() {
    clearTimeout(pollTimer);
    clearInterval(tickTimer);
    pollTimer = 0;
    tickTimer = 0;
  }
  function startTick() {
    clearInterval(tickTimer);
    tickTimer = setInterval(tick, 1000);
  }
  // 1초마다: 만드는 중이면 지난 시간 글만 바꾼다 (다시 그리지 않는다)
  function tick() {
    if (!visible || document.hidden || !E.elapsed || !E.elapsed.isConnected) return;
    const job = selectedJob();
    if (job) E.elapsed.textContent = elapsedText(Date.now() - Date.parse(job.created_at || ''));
  }

  // ---------------------------------------------------------------- 서버에서 읽기
  async function refresh() {
    if (!visible) return;
    if (fetching) { again = true; return; }
    fetching = true;
    if (loadState === 'idle') { loadState = 'loading'; if (built) renderAll(); }
    try {
      const data = await Data.workbenchGet('/media');
      jobs = (Array.isArray(data.jobs) ? data.jobs : []).filter((j) => j && typeof j.id === 'string' && (j.kind === 'image' || j.kind === 'video'));
      conn = data.connection || null;
      caps = data.capabilities || null;
      loadState = 'ready';
      loadError = '';
    } catch (e) {
      if (loadState !== 'ready') { loadState = 'error'; loadError = e.message || '불러오지 못했어요'; }
    } finally {
      fetching = false;
    }
    if (built && visible) renderAll();
    schedule();
    if (again) { again = false; refresh(); }
  }

  function schedule() {
    clearTimeout(pollTimer);
    pollTimer = 0;
    if (!shouldPoll(allJobs(), visible, document.hidden)) return;
    pollTimer = setTimeout(() => { pollTimer = 0; refresh(); }, POLL_MS);
  }

  // ---------------------------------------------------------------- 뼈대 (한 번만 만든다)
  function build() {
    E.head = h('header', { class: 'md-head' });
    E.left = buildLeft();
    E.center = buildCenter();
    E.right = h('aside', { class: 'md-col md-right', 'aria-label': '속성' });
    E.form = buildForm();
    root.replaceChildren(E.head, h('div', { class: 'md-grid' }, E.left, E.center, E.right));
    built = true;
  }

  // ---- 위쪽 줄: 위치 · 큰 제목 + 설명 · Grok 연결 칩 · 노드 편집기(고급)
  function renderHead() {
    const state = connState(loadState, conn, caps);
    const key = [state, Boolean(conn && conn.configured), connectOpening].join('|');
    if (key === sig.head) return;
    sig.head = key;
    const chipText = { loading: '연결 확인하는 중…', unknown: '연결 상태를 못 읽었어요', sim: '연습용 · 실제 생성 아님', on: 'Grok 연결됨', off: 'Grok 연결 안 됨' }[state];
    const chip = h('span', { class: `md-conn ${state}`, role: 'status' }, h('i', { class: 'md-conn-dot', 'aria-hidden': 'true' }), h('span', { text: chipText }));
    const manage = state === 'sim' || state === 'loading' ? null : h('button', {
      type: 'button', class: `md-pill ${state === 'on' ? '' : 'dark'}`, 'data-fk': 'conn', disabled: connectOpening,
      onclick: state === 'unknown' ? () => { refresh(); } : connectDialog,
    }, ico('plug'), h('span', { text: state === 'on' ? '연결 관리' : state === 'unknown' ? '다시 확인' : '연결하기' }));
    keepFocus(E.head, () => E.head.replaceChildren(
      h('nav', { class: 'bd-crumb', 'aria-label': '위치' }, h('span', { text: '작업' }), h('i', { 'aria-hidden': 'true', text: '›' }), h('span', { class: 'cur', text: '이미지·영상 작업대' })),
      h('div', { class: 'md-titlebar' },
        h('div', { class: 'md-hello' }, h('h2', { text: '이미지·영상 작업대' }), h('p', { class: 'md-sub', text: '글로 지시하면 그림과 영상을 만들어 줘요. 만든 것은 왼쪽 ‘내 작업물’에 모여요.' })),
        h('div', { class: 'md-tools' }, chip, manage,
          h('button', { type: 'button', class: 'md-pill', 'data-fk': 'node', onclick: () => H.openWorkbench() }, ico('node'), h('span', { text: '노드 편집기 (고급)' }))))));
  }

  // ---- 왼쪽: 새로 만들기 + 내 작업물
  function buildLeft() {
    E.makeBtns = {};
    const make = (kind, name, desc) => {
      const b = h('button', { type: 'button', class: 'md-new', 'data-kind': kind, 'aria-label': `${name}: ${desc}`, onclick: () => startNew(kind) },
        h('span', { class: 'md-new-ico' }, ico(kind)), h('span', { class: 'md-new-text' }, h('b', { text: name }), h('span', { text: desc })));
      E.makeBtns[kind] = b;
      return b;
    };
    E.chips = {};
    const chip = (key, label) => {
      const b = h('button', { type: 'button', class: 'md-fchip', 'data-filter': key, 'aria-pressed': 'false', onclick: () => { filter = key; renderList(); } },
        h('span', { text: label }), h('b', { text: '0' }));
      E.chips[key] = b;
      return b;
    };
    E.listNote = h('div', { class: 'md-listnote', hidden: true });
    E.listBody = h('div', { class: 'md-list', role: 'listbox', 'aria-label': '내 작업물', onkeydown: listKeys });
    return h('aside', { class: 'md-col md-left', 'aria-label': '만들기와 내 작업물' },
      h('section', { class: 'md-block' }, h('h3', { text: '새로 만들기' }),
        h('div', { class: 'md-makes' }, make('image', '그림 만들기', '글 한 줄로 그림 한 장'), make('video', '영상 만들기', '글 한 줄로 짧은 영상'))),
      h('section', { class: 'md-block md-works' }, h('h3', {}, h('span', { text: '내 작업물' })),
        h('div', { class: 'md-filters', role: 'group', 'aria-label': '종류로 거르기' }, chip('all', '전체'), chip('image', '그림'), chip('video', '영상')),
        E.listNote, E.listBody));
  }

  function startNew(kind) {
    selectedId = null;
    if (kind) draft.kind = kind;
    renderAll();
    E.form.text.focus();
  }

  function select(id) {
    selectedId = id;
    renderAll();
  }

  function listKeys(e) {
    const key = e.key;
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(key)) return;
    const list = [...E.listBody.querySelectorAll('.md-card')];
    if (!list.length) return;
    const at = list.indexOf(document.activeElement);
    let to = at;
    if (key === 'ArrowDown') to = Math.min(list.length - 1, at + 1);
    else if (key === 'ArrowUp') to = Math.max(0, at < 0 ? 0 : at - 1);
    else if (key === 'Home') to = 0;
    else to = list.length - 1;
    e.preventDefault();
    list[to].focus();
  }

  // 썸네일: 끝난 그림은 <img>, 영상은 첫 장면(<video preload=metadata muted>), 아직이면 상태 그림
  function thumb(job, cls = 'md-thumb') {
    const st = statusInfo(job);
    const asset = st.key === 'done' ? pickAsset(job) : null;
    const box = h('span', { class: `${cls} ${st.key}`, 'aria-hidden': 'true' });
    if (asset && job.kind === 'video') {
      box.append(h('video', { preload: 'metadata', muted: true, playsinline: true, tabindex: '-1', src: `${asset.url}#t=0.1` }));
      box.querySelector('video').muted = true;
    } else if (asset) {
      box.append(h('img', { src: asset.url, alt: '', loading: 'lazy', decoding: 'async' }));
    } else {
      box.append(ico(st.key === 'bad' ? 'warn' : st.key === 'work' ? 'plug' : job.kind));
      if (st.key === 'work') box.classList.add('spin');
    }
    return box;
  }

  function makeCard(job) {
    const el = h('button', { type: 'button', class: 'md-card', role: 'option', 'data-id': job.id, 'data-fk': `job:${job.id}`, onclick: () => select(job.id) });
    el.append(h('span', { class: 'md-thumbslot' }), h('span', { class: 'md-card-main' },
      h('b', { class: 'md-card-title' }),
      h('span', { class: 'md-card-chips' }, h('span', { class: 'md-kind' }), h('span', { class: 'md-state' }, dot('wait'), h('span'))),
      h('span', { class: 'md-card-when' })));
    return el;
  }

  function fillCard(el, job, now, on) {
    const st = statusInfo(job);
    const key = [jobSig(job), ago(job.created_at, now), on].join('|');
    if (el.dataset.sig === key) return;
    el.dataset.sig = key;
    const title = excerpt(job.prompt || job.title, 60) || job.title || '(제목 없음)';
    el.classList.toggle('on', on);
    el.setAttribute('aria-selected', String(on));
    el.setAttribute('aria-label', `${kindLabel(job.kind)}, ${title}, ${st.label}, ${ago(job.created_at, now)}`);
    el.title = job.prompt || job.title || '';
    const slot = el.querySelector('.md-thumbslot');
    const asset = st.key === 'done' ? pickAsset(job) : null;
    const thumbKey = `${st.key}|${asset ? asset.url : ''}|${job.kind}`;
    if (slot.dataset.key !== thumbKey) { slot.dataset.key = thumbKey; slot.replaceChildren(thumb(job)); }
    el.querySelector('.md-card-title').textContent = title;
    const kind = el.querySelector('.md-kind');
    kind.textContent = kindLabel(job.kind);
    kind.className = `md-kind ${job.kind}`;
    const state = el.querySelector('.md-state');
    state.className = `md-state ${st.key}`;
    state.querySelector('.md-dot').className = `md-dot ${st.key}`;
    state.querySelector('span').textContent = st.label;
    el.querySelector('.md-card-when').textContent = `${ago(job.created_at, now)}${job.simulation ? ' · 연습용' : ''}`;
  }

  function renderList() {
    const all = allJobs();
    const count = counts(all);
    for (const [key, btn] of Object.entries(E.chips)) {
      btn.setAttribute('aria-pressed', String(filter === key));
      btn.classList.toggle('on', filter === key);
      btn.querySelector('b').textContent = String(count[key]);
    }
    const shown = filterJobs(all, filter);
    const now = Date.now();
    // 안내 줄
    let note = null;
    if (loadState === 'idle' || loadState === 'loading') note = ['불러오는 중이에요…'];
    else if (loadState === 'error' && !all.length) note = [`작업물을 못 불러왔어요. ${loadError}`.trim(), '다시 불러오기'];
    else if (!all.length) note = ['아직 만든 것이 없어요. 위에서 그림이나 영상을 만들어 보세요.'];
    else if (!shown.length) note = [filter === 'image' ? '만든 그림이 없어요.' : '만든 영상이 없어요.'];
    const noteKey = note ? note.join('|') : '';
    if (E.listNote.dataset.key !== noteKey) {
      E.listNote.dataset.key = noteKey;
      E.listNote.hidden = !note;
      E.listNote.replaceChildren(...(note ? [h('p', { text: note[0] }), note[1] ? h('button', { type: 'button', class: 'md-pill', onclick: () => { loadState = 'idle'; refresh(); } }, note[1]) : null].filter(Boolean) : []));
    }
    // 카드는 자리를 지키며 고친다 (영상 썸네일이 깜빡이지 않게)
    const want = new Set(shown.map((j) => j.id));
    for (const [id, el] of cards) if (!want.has(id)) { el.remove(); cards.delete(id); }
    let first = null;
    shown.forEach((job, i) => {
      let el = cards.get(job.id);
      if (!el) { el = makeCard(job); cards.set(job.id, el); }
      fillCard(el, job, now, job.id === selectedId);
      if (E.listBody.children[i] !== el) E.listBody.insertBefore(el, E.listBody.children[i] || null);
      el.tabIndex = -1;
      if (!first) first = el;
    });
    const rover = (selectedId && cards.get(selectedId)) || first;
    if (rover && rover.isConnected && want.has(rover.dataset.id)) rover.tabIndex = 0;
    for (const [kind, btn] of Object.entries(E.makeBtns)) {
      const on = selectedId === null && draft.kind === kind;
      btn.classList.toggle('on', on);
      btn.setAttribute('aria-pressed', String(on));
    }
  }

  // ---- 가운데: 작업면 (흐름도 + 큰 미리보기)
  function buildCenter() {
    E.nodes = {};
    const node = (key, iconName) => {
      const n = {
        el: h('div', { class: 'md-node', 'data-node': key }),
        name: h('b', { class: 'md-node-name' }),
        sub: h('span', { class: 'md-node-sub' }),
        state: h('span', { class: 'md-node-state' }, dot('wait'), h('span')),
        extra: h('span', { class: 'md-node-extra' }),
      };
      n.el.append(h('span', { class: 'md-node-head' }, h('span', { class: 'md-node-ico' }, ico(iconName)), n.name), n.sub, n.extra, n.state);
      E.nodes[key] = n;
      return n.el;
    };
    const link = () => h('span', { class: 'md-link', 'aria-hidden': 'true' });
    E.links = [link(), link()];
    E.flow = h('div', { class: 'md-flow', role: 'group', 'aria-label': '만드는 순서' }, node('text', 'text'), E.links[0], node('make', 'image'), E.links[1], node('result', 'result'));
    E.stage = h('div', { class: 'md-stage', 'aria-live': 'polite' });
    return h('section', { class: 'md-col md-canvas', 'aria-label': '작업면' }, E.flow, E.stage);
  }

  function setNodeState(n, key, label) {
    n.el.dataset.state = key;
    n.state.firstChild.className = `md-dot ${key}`;
    n.state.lastChild.textContent = label;
  }

  // 흐름도: 글 지시 → 그림·영상 만들기 → 결과. 글을 칠 때마다 글자만 바꾼다
  function renderFlow() {
    const job = selectedJob();
    const kind = job ? job.kind : draft.kind;
    const text = job ? job.prompt || '' : draft.text;
    const st = job ? statusInfo(job) : null;
    const seconds = job ? job.duration : clampDuration(draft.duration).value;
    const asset = job && st.key === 'done' ? pickAsset(job) : null;
    const t = E.nodes.text;
    t.name.textContent = '글 지시';
    t.sub.textContent = excerpt(text, 80) || '아직 적지 않았어요';
    setNodeState(t, text.trim() ? 'done' : 'wait', text.trim() ? '준비됨' : '비어 있어요');
    const m = E.nodes.make;
    m.name.textContent = kind === 'video' ? `영상 만들기${Number.isFinite(seconds) ? ` · ${seconds}초` : ''}` : '그림 만들기';
    m.sub.textContent = kind === 'video' ? '먼저 장면 그림 한 장을 만들고, 그 그림으로 영상을 만들어요' : '글을 읽고 정사각형 그림 한 장을 만들어요';
    m.el.querySelector('.md-node-ico').replaceChildren(ico(kind));
    setNodeState(m, st ? st.key : 'wait', st ? st.label : '대기');
    const r = E.nodes.result;
    r.name.textContent = '결과';
    const resultState = !st ? ['wait', '대기', '아직 없어요'] : st.key === 'done' ? ['done', '끝남', asset ? (kind === 'video' ? '영상 1개가 나왔어요' : '그림 1장이 나왔어요') : '파일이 없어요']
      : st.key === 'bad' ? ['bad', '막힘', '만들지 못했어요'] : st.key === 'stop' ? ['stop', '중단', '중단했어요']
        : st.key === 'work' ? ['wait', '기다려요', '만들고 있어요'] : ['wait', '기다려요', '곧 시작해요'];
    r.sub.textContent = resultState[2];
    setNodeState(r, resultState[0], resultState[1]);
    const extraKey = asset ? `${kind}|${asset.url}` : '';
    if (r.extra.dataset.key !== extraKey) {
      r.extra.dataset.key = extraKey;
      r.extra.replaceChildren(...(asset ? [thumb(job, 'md-node-thumb')] : []));
    }
    r.el.classList.toggle('has-thumb', Boolean(asset));
    E.links[0].classList.toggle('live', Boolean(st && st.key === 'work'));
    E.links[1].classList.toggle('live', Boolean(st && st.key === 'work'));
    E.links[0].classList.toggle('on', Boolean(text.trim()));
    E.links[1].classList.toggle('on', Boolean(st && (st.key === 'done' || st.key === 'work')));
  }

  const stageKey = (job) => {
    if (!job) return `empty|${draft.kind}`;
    const a = pickAsset(job);
    return [job.id, statusInfo(job).key, a ? a.url : '', job.error, job.duration_check, job.measured_duration_s, job.task, job.simulation, job.model_verified, job.prompt].join('|');
  };

  function renderStage() {
    const job = selectedJob();
    const key = stageKey(job);
    if (key === sig.stage) return;
    sig.stage = key;
    E.elapsed = null;
    keepFocus(E.stage, () => {
      if (!job) E.stage.replaceChildren(emptyStage());
      else {
        const st = statusInfo(job);
        const asset = pickAsset(job);
        if (st.key === 'done' && asset) E.stage.replaceChildren(resultStage(job, asset));
        else if (st.active) E.stage.replaceChildren(workingStage(job));
        else E.stage.replaceChildren(problemStage(job));
      }
    });
  }

  // 선택이 없을 때: 작은 그림 + 안내 + 예시 지시 3개
  function emptyStage() {
    const kind = draft.kind;
    return h('div', { class: 'md-empty' },
      ico('folder', 'md-empty-ico'),
      h('b', { text: '무엇을 만들어 볼까요?' }),
      h('p', { text: '왼쪽에서 만들기를 누르거나 지난 작업물을 골라 보세요.' }),
      h('div', { class: 'md-examples', role: 'group', 'aria-label': `${kindLabel(kind)} 예시 지시` },
        EXAMPLES[kind].map((text) => h('button', { type: 'button', class: 'md-example', title: text, onclick: () => fillDraft(text) }, text))),
      h('small', { text: '예시를 누르면 오른쪽 칸에 글이 채워져요. 보내지는 않아요.' }));
  }

  function workingStage(job) {
    const el = h('div', { class: 'md-working' },
      h('span', { class: 'md-ring', 'aria-hidden': 'true' }),
      h('b', {}, h('span', { text: statusInfo(job).key === 'work' ? '만드는 중 · ' : '기다리는 중 · ' }), E.elapsed = h('span', { class: 'md-elapsed', text: elapsedText(Date.now() - Date.parse(job.created_at || '')) })),
      h('p', { text: job.kind === 'video' ? '영상은 1~3분 걸려요. 이 화면을 열어 둔 채 기다려 주세요.' : '조금만 기다려 주세요. 끝나면 여기에 바로 보여 드려요.' }),
      job.simulation ? h('span', { class: 'md-note caution', text: 'MOCK / 연습용 · 실제 생성 아님' }) : null,
      h('button', { type: 'button', class: 'md-pill stop', 'data-fk': 'halt', onclick: (e) => halt(job, e.currentTarget) }, ico('stop'), h('span', { text: '중단' })));
    return el;
  }

  function problemStage(job) {
    const info = problemInfo(job) || { title: '아직 결과가 없어요', reason: '', help: '' };
    return h('div', { class: 'md-problem' },
      h('span', { class: 'md-problem-ico' }, ico('warn')),
      h('b', { text: info.title }),
      info.reason ? h('span', { class: 'md-reason-label', text: '남아 있는 이유 (기록된 글 그대로)' }) : null,
      info.reason ? h('pre', { class: 'md-reason', tabindex: '0', text: info.reason }) : null,
      info.help ? h('p', { text: info.help }) : null,
      h('div', { class: 'md-actions' }, redoButton(job), taskButton(job)));
  }

  function redoButton(job, primary = true) {
    return h('button', { type: 'button', class: `md-pill ${primary ? 'dark' : ''}`, 'data-fk': 'redo', onclick: () => reuse(job) }, ico('redo'), h('span', { text: '같은 지시로 다시 만들기' }));
  }
  function taskButton(job) {
    return job.task ? h('button', { type: 'button', class: 'md-pill', 'data-fk': 'task', onclick: () => H.openTask(job.task) }, ico('task'), h('span', { text: '연결된 작업 보기' })) : null;
  }

  function resultStage(job, asset) {
    const label = `${kindLabel(job.kind)}: ${excerpt(job.prompt, 60)}`;
    const media = job.kind === 'video'
      ? h('video', { class: 'md-media', controls: true, preload: 'metadata', playsinline: true, src: asset.url, 'aria-label': `만든 영상 · ${excerpt(job.prompt, 40)}` })
      : h('img', { class: 'md-media', src: asset.url, alt: `만든 ${label}`, decoding: 'async' });
    const broken = h('p', { class: 'md-broken', hidden: true, text: `${kindLabel(job.kind)}을(를) 열지 못했어요. 파일 내려받기를 눌러 보세요.` });
    media.addEventListener('error', () => { media.hidden = true; broken.hidden = false; });
    const stage = h('div', { class: 'md-preview' }, media, broken, job.simulation ? h('span', { class: 'md-ribbon', text: 'MOCK / 연습용' }) : null);
    const notes = captionNotes(job);
    const dur = durationText(job);
    const model = modelLine(job);
    const save = h('a', { class: 'md-pill dark', href: asset.url, download: '', 'data-fk': 'save', 'aria-label': `${kindLabel(job.kind)} 파일 내려받기` }, ico('download'), h('span', { text: '파일 내려받기' }));
    save.addEventListener('click', (e) => { e.preventDefault(); download(job, asset, save); });
    return h('div', { class: 'md-result' }, stage,
      h('div', { class: 'md-caption' },
        h('div', { class: 'md-chips' },
          h('span', { class: `md-kind ${job.kind}`, text: kindLabel(job.kind) }),
          dur ? h('span', { class: 'md-chip', text: dur }) : null,
          notes.map((n) => h('span', { class: `md-chip ${n.tone === 'warn' ? 'caution' : n.tone}`, text: n.text }))),
        h('p', { class: 'md-when', text: `${whenText(job.created_at)} · ${ago(job.created_at)}에 만들었어요` }),
        model ? h('p', { class: 'md-model', text: model }) : null,
        h('div', { class: 'md-actions' }, save, redoButton(job, false), taskButton(job))));
  }

  // 내려받기: 서버가 알려 준 파일 종류로 이름을 붙여 저장한다 (같은 출처 주소만)
  async function download(job, asset, btn) {
    if (btn.dataset.busy) return;
    btn.dataset.busy = '1';
    btn.setAttribute('aria-disabled', 'true');
    try {
      const res = await fetch(asset.url, { cache: 'no-store' });
      if (!res.ok) throw new Error(`파일을 가져오지 못했어요 (${res.status})`);
      const blob = await res.blob();
      const name = fileName(job, res.headers.get('content-type') || blob.type);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      H.notify(`${name} 파일을 내려받았어요`);
    } catch (e) {
      H.fail(e);
    } finally {
      delete btn.dataset.busy;
      btn.removeAttribute('aria-disabled');
    }
  }

  // 같은 지시로 다시 만들기: 오른쪽 칸에 채우기만 한다 (자동으로 보내지 않는다)
  function reuse(job) {
    draft.kind = job.kind;
    draft.text = String(job.prompt || '').slice(0, TEXT_MAX);
    if (job.kind === 'video') draft.duration = clampDuration(job.duration ?? job.requested_duration ?? DUR_DEFAULT).value;
    E.form.text.value = draft.text;
    selectedId = null;
    renderAll();
    E.form.text.focus();
    setFormNote('지시를 채웠어요. 고친 뒤 ‘만들기’를 눌러 주세요. 자동으로 보내지 않아요.', '');
  }

  function fillDraft(text) {
    draft.text = String(text).slice(0, TEXT_MAX);
    E.form.text.value = draft.text;
    renderAll();
    E.form.text.focus();
  }

  // 중단: 한 번만 보낸다
  async function halt(job, btn) {
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      await Data.workbenchPost(`runs/${encodeURIComponent(job.run)}/halt`, {});
      H.notify('중단을 요청했어요. 이미 Grok에 보낸 요청은 되돌리지 못할 수 있어요.');
    } catch (e) {
      H.fail(e);
      btn.disabled = false;
    }
    refresh();
  }

  // ---- 오른쪽: 새 요청 (글상자 · 길이 · 안내 · 만들기)
  function buildForm() {
    const f = { kindBtns: {} };
    f.toggle = h('div', { class: 'md-toggle', role: 'group', 'aria-label': '만들 종류' },
      ['image', 'video'].map((k) => (f.kindBtns[k] = h('button', { type: 'button', class: 'md-toggle-btn', 'aria-pressed': 'false', 'data-fk': `kind:${k}`, onclick: () => setKind(k) }, ico(k), h('span', { text: kindLabel(k) })))));
    f.text = h('textarea', {
      class: 'md-text', id: 'md-text', rows: '6', maxlength: String(TEXT_MAX), 'aria-describedby': 'md-count md-note', spellcheck: 'false',
      oninput: () => { draft.text = f.text.value; syncForm(); renderFlow(); renderStageIfEmpty(); },
      onkeydown: (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); onMake(); } },
    });
    f.count = h('span', { class: 'md-count', id: 'md-count' });
    f.durNum = h('input', {
      class: 'md-durnum', id: 'md-dur-num', type: 'number', inputmode: 'numeric', min: String(DUR_MIN), max: String(DUR_MAX), step: '1', 'aria-label': '영상 길이(초)',
      oninput: () => {
        const v = f.durNum.value.trim();
        if (/^\d+$/.test(v) && Number(v) >= DUR_MIN && Number(v) <= DUR_MAX) { draft.duration = Number(v); f.durRange.value = v; renderFlow(); }
      },
      onchange: () => setDuration(f.durNum.value, true),
    });
    f.durRange = h('input', { class: 'md-range', type: 'range', min: String(DUR_MIN), max: String(DUR_MAX), step: '1', 'aria-label': '영상 길이 슬라이더', oninput: () => setDuration(f.durRange.value, false) });
    f.dur = h('div', { class: 'md-field md-dur', hidden: true },
      h('label', { class: 'md-label', for: 'md-dur-num', text: '영상 길이' }),
      h('div', { class: 'md-dur-row' },
        h('button', { type: 'button', class: 'md-step', 'aria-label': '1초 줄이기', onclick: () => setDuration(clampDuration(draft.duration).value - 1, true) }, ico('minus')),
        f.durNum, h('span', { class: 'md-unit', text: '초' }),
        h('button', { type: 'button', class: 'md-step', 'aria-label': '1초 늘리기', onclick: () => setDuration(clampDuration(draft.duration).value + 1, true) }, ico('plus'))),
      f.durRange,
      h('span', { class: 'md-help', text: `${DUR_MIN}~${DUR_MAX}초 · 정수만 돼요` }));
    f.fixed = h('p', { class: 'md-fixed' });
    f.info = h('div', { class: 'md-infobox' });
    f.note = h('p', { class: 'md-note', id: 'md-note', role: 'status' });
    f.make = h('button', { type: 'button', class: 'md-go', 'data-fk': 'make', onclick: onMake });
    f.hint = h('span', { class: 'md-gohint' });
    f.body = h('div', { class: 'md-formbody' },
      h('h3', { text: '새 요청' }), f.toggle,
      h('div', { class: 'md-field' }, h('label', { class: 'md-label', for: 'md-text', text: '무엇을 만들까요?' }), f.text, f.count),
      f.dur, f.fixed, f.info, f.note);
    f.el = h('div', { class: 'md-form' }, f.body, h('div', { class: 'md-formfoot' }, f.hint, f.make));
    return f;
  }

  function setKind(k) {
    if (draft.kind === k) return;
    draft.kind = k;
    renderAll();
  }

  function setFormNote(text, tone) {
    E.form.note.textContent = text || '';
    E.form.note.className = `md-note ${tone === 'warn' ? 'caution' : tone || ''}`.trim(); // 'warn'은 style.css 전역 규칙(막힘 말풍선)과 겹쳐서 caution으로
  }

  function setDuration(raw, writeBack) {
    const r = clampDuration(raw);
    draft.duration = r.value;
    E.form.durRange.value = String(r.value);
    if (writeBack) E.form.durNum.value = String(r.value);
    if (writeBack && r.adjusted && String(raw).trim() !== '') setFormNote(`영상 길이는 ${DUR_MIN}~${DUR_MAX}초 정수만 돼요. ${r.value}초로 맞췄어요.`, 'warn');
    else if (writeBack) setFormNote('', '');
    renderFlow();
    syncForm();
  }

  function syncForm() {
    const f = E.form;
    const k = draft.kind;
    for (const [key, btn] of Object.entries(f.kindBtns)) { btn.setAttribute('aria-pressed', String(k === key)); btn.classList.toggle('on', k === key); }
    f.dur.hidden = k !== 'video';
    f.text.placeholder = k === 'video' ? '예: 파란 종이배가 잔잔한 물 위를 천천히 흘러가요' : '예: 작은 파란 종이배가 잔잔한 물 위에 떠 있어요';
    const n = chars(draft.text).length;
    f.count.textContent = `${n} / ${TEXT_MAX}`;
    f.count.classList.toggle('caution', n > TEXT_MAX * 0.95);
    if (document.activeElement !== f.durNum) f.durNum.value = String(clampDuration(draft.duration).value);
    f.durRange.value = String(clampDuration(draft.duration).value);
    f.fixed.textContent = k === 'video' ? '정해진 옵션 · 영상은 16:9 · 720p예요. 지금은 바꿀 수 없어요.' : '정해진 옵션 · 그림은 정사각형(1:1)이에요. 지금은 바꿀 수 없어요.';
    const sim = isSim();
    f.info.replaceChildren(...(sim
      ? [h('b', { text: '연습용 · 실제 생성 아님' }), h('p', { text: '지금은 연습용으로 돌아가요. 실제 Grok에는 아무것도 보내지 않고, 미리 만든 보기용 파일이 나와요.' })]
      : [h('b', { text: '요청마다 한 번 승인해요' }), h('p', { text: '비용은 알 수 없어요. 구독으로 되는지도 확인되지 않았고, 추가 요금은 승인하지 않았어요.' }),
        k === 'video' ? h('p', { text: '영상은 그림을 먼저 만들어서, 그림보다 사용량이 더 커요.' }) : null].filter(Boolean)));
    const mk = makeState({ reviewing, loadState, caps, kind: k, text: draft.text });
    f.make.textContent = '';
    f.make.append(ico(mk.label === '연결하고 만들기' ? 'plug' : k), h('span', { text: mk.label }));
    f.make.disabled = mk.disabled;
    f.hint.textContent = mk.reason;
  }

  function renderStageIfEmpty() { if (!selectedJob()) renderStage(); }

  // ---- 오른쪽: 지난 작업물 정보 (읽기 전용)
  function viewPanel(job) {
    const st = statusInfo(job);
    const asset = pickAsset(job);
    const now = Date.now();
    const row = (label, ...value) => [h('dt', { text: label }), h('dd', {}, ...value)];
    const dur = durationText(job);
    const facts = [
      row('만든 때', `${whenText(job.created_at)} (${ago(job.created_at, now)})`),
      row('종류', kindLabel(job.kind)),
      dur ? row('영상 길이', dur) : null,
      row('상태', h('span', { class: `md-state ${st.key}` }, dot(st.key), h('span', { text: st.label }))),
      asset && asset.sha256 ? row('파일 확인값', h('code', { text: asset.sha256.slice(0, 8), title: '파일이 바뀌지 않았는지 확인하는 값의 앞 8자리' })) : null,
      row('연결된 작업', job.task ? h('button', { type: 'button', class: 'md-link-btn', onclick: () => H.openTask(job.task) }, `${job.task} 보기`) : '없어요'),
      job.simulation ? row('연습용', 'MOCK · 실제 생성 아님') : null,
    ].filter(Boolean).flat();
    return h('div', { class: 'md-form md-view' },
      h('div', { class: 'md-formbody' },
        h('h3', { text: '작업 정보' }),
        h('div', { class: 'md-field' }, h('span', { class: 'md-label', text: '지시 글' }), h('pre', { class: 'md-prompt', tabindex: '0', 'aria-label': '지시 글 전체', text: job.prompt || '(지시 글이 기록되지 않았어요)' })),
        h('dl', { class: 'md-facts' }, facts)),
      h('div', { class: 'md-formfoot' }, redoButton(job, true)));
  }

  function renderRight() {
    const job = selectedJob();
    const key = job ? ['view', jobSig(job), ago(job.created_at)].join('|') : 'new';
    if (!job) {
      if (E.right.firstChild !== E.form.el) {
        const keep = E.form.text.scrollTop;
        E.right.replaceChildren(E.form.el);
        E.form.text.scrollTop = keep;
      }
      sig.right = key;
      syncForm();
      return;
    }
    if (key === sig.right) return;
    sig.right = key;
    keepFocus(E.right, () => E.right.replaceChildren(viewPanel(job)));
  }

  function renderAll() {
    if (!built || !root) return;
    if (selectedId && !selectedJob() && loadState === 'ready') selectedId = null; // 사라진 작업을 고르고 있었다면 새 요청으로
    renderHead();
    renderList();
    renderFlow();
    renderStage();
    renderRight();
  }

  // ---------------------------------------------------------------- 만들기: 계획 확인 → 확인 창 → (Grok 승인) → 시작
  function onMake() {
    if (reviewing || sending) return;
    if (!canMake(caps, draft.kind)) {
      if (caps) connectDialog();
      return;
    }
    const v = validate(draft.text);
    if (!v.ok) { setFormNote(v.message, 'bad'); E.form.text.focus(); return; }
    review();
  }

  function projectKey() {
    const view = Data.get() || {};
    const found = (Data.currentProject && Data.currentProject()) || (view.projects || [])[0] || null;
    return found ? found.key : null;
  }

  async function review() {
    if (reviewing) return;
    reviewing = true;
    syncForm();
    setFormNote('', '');
    try {
      const body = buildBody({ kind: draft.kind, text: draft.text, duration: draft.duration, project: projectKey() });
      const plan = await Data.workbenchPost('plan', body);
      const items = Array.isArray(plan.provider_requests) ? plan.provider_requests : [];
      if (!items.length) throw new Error('이 요청을 보낼 곳을 찾지 못했어요. 아무것도 보내지 않았어요.');
      confirmDialog({ body, plan, items, requestId: crypto.randomUUID().replaceAll('-', '') });
    } catch (e) {
      setFormNote(e.message || String(e), 'bad');
    } finally {
      reviewing = false;
      syncForm();
    }
  }

  // 정확한 요청을 다시 보여 주고 체크를 받는 창 (진짜면 체크 필수, 연습용이면 체크 없이 크게 표시)
  function confirmDialog({ body, plan, items, requestId }) {
    const item = items[0];
    const real = items.filter((i) => !i.simulation);
    const sim = real.length === 0;
    const S = { sending: false, failed: false, done: false, checked: false, error: '', el: null };
    const R = {};
    const opts = item.options || {};
    const sync = () => {
      if (!R.send) return;
      R.send.disabled = S.sending || S.failed || S.done || (!sim && !S.checked);
      R.sendText.textContent = S.sending ? '보내는 중…' : sim ? '연습용으로 만들기' : '한 번 보내기';
      if (R.check) R.check.disabled = S.sending || S.failed || S.done;
      R.err.hidden = !S.error;
      R.err.textContent = S.error;
    };
    const fact = (label, value) => h('div', { class: 'md-fact' }, h('dt', { text: label }), h('dd', { text: value }));
    const build = () => {
      R.err = h('p', { class: 'md-err', role: 'alert', hidden: true });
      R.sendText = h('span');
      R.send = h('button', { type: 'button', class: 'btn primary md-send', 'data-focus-key': 'send', autofocus: sim ? true : null, onclick: send }, R.sendText);
      R.check = sim ? null : h('input', { type: 'checkbox', name: 'media-send-confirm', autofocus: true, checked: S.checked ? true : null, onchange: (e) => { S.checked = e.target.checked; sync(); } });
      const box = h('div', { class: 'pop paper md-dlg', role: 'dialog', 'aria-modal': 'true', 'aria-label': sim ? '연습용으로 만들기' : '이 요청을 Grok에 보내기' },
        h('button', { type: 'button', class: 'x-btn', 'aria-label': '닫기', onclick: () => Popups.close() }, Popups.icon('x')),
        h('h2', { text: sim ? '연습용으로 만들까요?' : '이 요청을 Grok에 보낼까요?' }),
        sim ? h('div', { class: 'md-simbanner' }, h('b', { text: '연습용 · 실제 생성 아님' }), h('span', { text: '실제 Grok에는 아무것도 보내지 않아요. 보기용 파일이 나와요.' })) : null,
        h('dl', { class: 'md-facts big' },
          fact('종류', kindLabel(item.kind)),
          item.kind === 'video' ? fact('길이', `${opts.duration}초`) : null,
          fact('화면', item.kind === 'video' ? '16:9 · 720p (바꿀 수 없어요)' : '정사각형 1:1 (바꿀 수 없어요)'),
          item.model ? fact('요청 모델', `${item.model} (실제 모델은 확인되지 않아요)`) : null),
        h('span', { class: 'md-label', text: '보내는 지시 글 (그대로)' }),
        h('pre', { class: 'md-exact', tabindex: '0', 'aria-label': '보내는 지시 글', text: item.input }),
        item.kind === 'video' ? h('p', { class: 'md-plain', text: '영상은 먼저 장면 그림 한 장을 만들고, 그 그림으로 영상을 만들어요. 그래서 요청이 두 번 들어가요.' }) : null,
        h('details', { class: 'md-raw' }, h('summary', { text: '보내는 옵션 원문 보기' }), h('pre', { text: JSON.stringify(opts, null, 2) })),
        sim ? null : h('div', { class: 'md-warnbox' }, h('b', { text: '비용은 알 수 없어요' }),
          h('span', { text: '구독으로 되는지 확인되지 않았고 추가 요금은 승인하지 않았어요. 실패해도 같은 요청을 자동으로 다시 보내지 않아요.' })),
        sim ? null : h('label', { class: 'md-check' }, R.check, h('span', { text: '이 요청을 Grok에 한 번 보냅니다 · 비용 알 수 없음' })),
        R.err,
        h('div', { class: 'md-dlg-btns' }, h('button', { type: 'button', class: 'btn', onclick: () => Popups.close() }, '닫기'), R.send));
      S.el = box;
      sync();
      return box;
    };
    async function send() {
      if (sending || S.sending || S.done || S.failed) return; // 한 번만
      if (!sim && !S.checked) return;
      sending = true;
      S.sending = true;
      sync();
      let step = 'grant';
      try {
        const grants = {};
        if (!sim) {
          const status = await Data.workbenchGet('/planner');
          for (const it of real) {
            const request = grokRequest(it);
            const reviewed = await Data.grokPost('plan', request);
            const receipt = await Data.grokPost('consent', { request, request_hash: reviewed.request_hash, config_hash: status.config_hash, consents: reviewed.approval_checklist });
            grants[it.node] = receipt.grant_id;
          }
        }
        step = 'start';
        const res = await Data.workbenchPost('start', { ...body, plan_hash: plan.hash, request_id: requestId, confirmed: true, allow_models: plan.uses_models, provider_grants: grants });
        S.done = true;
        started(res, body, item);
        if (S.el && S.el.isConnected) Popups.close();
      } catch (e) {
        S.failed = true;
        S.error = step === 'grant'
          ? `승인을 받지 못했어요. Grok에는 아무것도 보내지 않았어요. (${e.message || e}) 같은 요청을 자동으로 다시 보내지 않아요. 창을 닫고 처음부터 새로 승인해 주세요.`
          : `시작하지 못했거나 시작됐는지 확실하지 않아요. (${e.message || e}) 먼저 왼쪽 ‘내 작업물’을 확인해 주세요. 같은 요청을 자동으로 다시 보내지 않아요. 새로 만들려면 창을 닫고 처음부터 새로 승인해 주세요.`;
        refresh();
      } finally {
        S.sending = false;
        sending = false;
        sync();
      }
    }
    Popups.open(build, { keep: true });
  }

  // 시작이 받아들여졌을 때: 방금 만든 작업을 바로 보여 주고 3초 읽기를 켠다
  function started(res, body, item) {
    const run = (res && res.run) || {};
    if (!run.id) { refresh(); return; }
    const id = `${run.id}/${NODE}`;
    const kind = item.kind === 'video' ? 'video' : 'image';
    placeholders.set(id, {
      id, run: run.id, node: NODE, title: body.title, created_at: new Date().toISOString(), kind, status: 'pending', run_status: 'running', error: '',
      prompt: item.input, duration: kind === 'video' ? (item.options || {}).duration ?? null : null, simulation: Boolean(item.simulation), transport: null,
      requested_duration: null, measured_duration_s: null, duration_check: null, model_verified: false, task: null, assets: [], until: Date.now() + 30000,
    });
    selectedId = id;
    filter = 'all';
    draft.text = '';
    E.form.text.value = '';
    setFormNote('', '');
    renderAll();
    refresh();
    H.notify(item.simulation ? '연습용 작업을 시작했어요. 곧 보기용 결과가 나와요.' : '작업을 시작했어요. 만드는 동안 이 화면에서 진행을 볼 수 있어요.');
  }

  // ---------------------------------------------------------------- Grok 연결 창 (공식 Grok 프로그램, 내 grok.com 로그인)
  async function connectDialog() {
    if (connectOpening) return;
    connectOpening = true;
    renderHead();
    try {
      const state = await Data.grokGet('/catalog');
      const c = state.connection || {};
      const connected = Boolean(c.enabled && c.mode === 'official_cli');
      let review = null;
      let reviewError = '';
      try { review = await Data.grokPost('connection-plan', { mode: 'official_cli' }); } catch (e) { reviewError = e.message || String(e); }
      openConnect({ connected, configured: Boolean(c.configured), c, review, reviewError });
    } catch (e) {
      H.fail(e);
    } finally {
      connectOpening = false;
      renderHead();
    }
  }

  function openConnect({ connected, configured, c, review, reviewError }) {
    const S = { busy: false, checked: false, error: '', el: null };
    const R = {};
    const sync = () => {
      if (!R.go) return;
      R.go.disabled = S.busy || !S.checked || !review;
      R.go.querySelector('span').textContent = S.busy ? '연결하는 중…' : connected ? '다시 연결' : '연결하기';
      if (R.off) R.off.disabled = S.busy;
      if (R.check) R.check.disabled = S.busy;
      R.err.hidden = !S.error;
      R.err.textContent = S.error;
    };
    const summary = connected ? '연결됨 · 이 PC의 공식 Grok 프로그램을 씁니다.' : configured && c.mode === 'official_cli' ? '연결 확인에 실패했어요. 다시 연결해 주세요.' : '아직 연결되지 않았어요.';
    const notes = [
      '이 PC에 설치된 공식 Grok 프로그램을 그대로 불러 그림과 영상을 만들어요. 로그인 정보 파일은 AI 스튜디오가 읽지 않아요.',
      'Grok이 쓸 수 있는 도구를 그림·영상 만들기로만 막아 두었고, 요청마다 한 번씩 승인을 받아요.',
      '영상은 먼저 그림 한 장을 만든 뒤 그 그림으로 만들어요 (길이 1~15초). 조사(리서치)는 이 연결로 하지 않아요.',
      '구독 요금제로 되는지는 확인되지 않았어요. 추가 요금은 승인하지 않았고, 비용은 알 수 없음으로 기록해요.',
    ];
    const close = () => Popups.close();
    async function connect() {
      if (S.busy || !S.checked || !review) return;
      S.busy = true;
      S.error = '';
      sync();
      try {
        await Data.grokPost('configure', { mode: 'official_cli', review_hash: review.review_hash, consents: review.consents });
        if (S.el && S.el.isConnected) Popups.close();
        H.notify('Grok 그림·영상 연결을 켰어요. 만들 때 로그인을 한 번 더 확인해요.');
        refresh();
      } catch (e) {
        S.error = e.message || String(e);
      } finally {
        S.busy = false;
        sync();
      }
    }
    async function disconnect() {
      if (S.busy) return;
      S.busy = true;
      sync();
      try {
        await Data.grokPost('disconnect', {});
        if (S.el && S.el.isConnected) Popups.close();
        H.notify('Grok 연결을 껐어요.');
        refresh();
      } catch (e) {
        S.error = e.message || String(e);
      } finally {
        S.busy = false;
        sync();
      }
    }
    const build = () => {
      R.err = h('p', { class: 'md-err', role: 'alert', hidden: true });
      R.check = h('input', { type: 'checkbox', name: 'media-connect-confirm', autofocus: true, checked: S.checked ? true : null, onchange: (e) => { S.checked = e.target.checked; sync(); } });
      R.go = h('button', { type: 'button', class: 'btn primary', 'data-focus-key': 'go', onclick: connect }, h('span'));
      R.off = configured ? h('button', { type: 'button', class: 'btn', onclick: disconnect }, '연결 끊기') : null;
      const box = h('div', { class: 'pop paper md-dlg', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Grok 그림·영상 연결' },
        h('button', { type: 'button', class: 'x-btn', 'aria-label': '닫기', onclick: close }, Popups.icon('x')),
        h('h2', { text: 'Grok 그림·영상 연결' }),
        h('p', { class: `md-plain md-status ${connected ? 'on' : ''}`, text: summary }),
        h('ul', { class: 'md-notes' }, notes.map((text) => h('li', { text }))),
        review ? h('p', { class: 'md-help', text: `찾은 프로그램: ${(review.config || {}).cli_path || ''} · ${review.cli_version || ''}` }) : h('p', { class: 'md-help', text: reviewError ? `연결 준비를 못 했어요: ${reviewError}` : '연결 준비를 못 했어요.' }),
        h('label', { class: 'md-check' }, R.check, h('span', { text: '위 내용을 확인했고 이 연결을 허용합니다' })),
        R.err,
        h('div', { class: 'md-dlg-btns' }, h('button', { type: 'button', class: 'btn', onclick: close }, '닫기'), R.off, R.go));
      S.el = box;
      sync();
      return box;
    };
    Popups.open(build, { keep: true });
  }

  return { init, setVisible, render, refresh, logic };
})();

if (typeof module !== 'undefined') module.exports = Media; // tools/dev/media_sim.js (node)
