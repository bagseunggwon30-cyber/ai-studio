/* AI 스튜디오 — 화면이 쓰는 데이터 (SPEC 4단계: 감독 프로그램 API)
 *
 * 화면은 이 파일의 Data만 본다. /api/state를 1.5초마다 읽고(버전이 같으면 건너뜀) 바뀌면 'change'를 알린다.
 * 새 알림(결재 올림·합격·막힘 등)은 'event'로 알린다. 행동은 POST /api/...로 보내고 곧바로 다시 읽는다.
 * 무거운 것(작업 상세·보고서 요약·변경 내용·일지)은 처음 볼 때 불러오고, 오는 대로 'change'로 다시 그리게 한다.
 * 쓰기 요청에는 페이지에 심어 둔 세션 토큰(X-Studio-Token)을 붙인다.
 */
'use strict';

const Data = (() => {
  const TOKEN = (document.querySelector('meta[name="studio-token"]') || {}).content || '';
  const POLL_MS = 1500;
  const RETRY_MS = 5000; // 불러오기에 실패한 것은 이만큼 지난 뒤에 다시 부른다
  const OFFLINE = '감독 프로그램과 연결이 끊겼어요';
  const STATUS_LABELS = {
    queued: '기획 대기', ready: '준비', running: '작업 중', checking: '검증 중',
    awaiting_approval: '결재 대기', done: '완료', blocked: '막힘', cancelled: '취소',
  };
  const KIND_LABELS = { plan: '기획', build: '개발', research: '리서치', skill: '스킬 공부', look: '의상 제작', hire: '새 직원', tool: 'MCP 만들기' };
  const KIND_ROLE = { plan: 'producer', build: 'builder', research: 'analyst', skill: 'reviewer', look: 'builder', hire: 'producer' };

  // 서버를 읽기 전에도 장면을 그릴 수 있게 기본 직원 (studio.toml의 기본값과 같다)
  const DEFAULT_TEAM = [
    { id: 'hana', role: 'producer', name: '하나', title: '기획', memo: '', skills: [] },
    { id: 'sol', role: 'builder', name: '솔', title: '개발', memo: '', skills: [] },
    { id: 'clo', role: 'reviewer', name: '클로', title: '리뷰', memo: '', skills: [] },
    { id: 'luna', role: 'analyst', name: '루나', title: '리서치', memo: '', skills: [] },
  ];

  let raw = null;
  let view = {
    studio: { name: 'AI 스튜디오' }, day: 1, energy: { max: 40, runsToday: 0, minutesToday: 0 },
    stopped: false, goals: { week: '', month: 5 }, tasks: [], events: [], trophies: [], skills: [], projects: [], unread: 0,
    floors: { count: 1, max: 1, desks: [6], staff_max: 2, staff: 0, next_desks: 0 },
  };
  let team = DEFAULT_TEAM.map((p) => ({ ...p, look: null, stats: null, state: 'rest', phase: null }));
  let byRole = {};
  let byId = {};
  let version = -1;
  let seen = null; // 이미 본 알림 키
  let online = true;
  let project = null;
  const caches = { detail: new Map(), report: new Map(), diff: new Map(), diary: new Map(), skill: new Map(), ai: new Map(), grades: new Map() };
  const loading = new Map(); // 불러오는 중: 'kind:key' → Promise
  const edits = {}; // 기획안 카드 고른 것·고친 제목 (승인 때 보낸다)
  const listeners = { change: [], event: [], connection: [] };

  indexTeam();

  function on(type, fn) { listeners[type].push(fn); }
  function emit(type, payload) { for (const fn of listeners[type]) fn(payload); }

  function indexTeam() {
    byRole = Object.fromEntries(team.map((p) => [p.role, p]));
    byId = Object.fromEntries(team.map((p) => [p.id, p]));
  }

  // ---------------------------------------------------------------- 서버 통신
  async function request(method, path, body) {
    const opts = { method, cache: 'no-store', headers: {} };
    if (method === 'POST') {
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-Studio-Token'] = TOKEN;
      opts.body = JSON.stringify(body || {});
    }
    let res;
    try {
      res = await fetch(path, opts);
    } catch (_) {
      throw new Error(OFFLINE); // 브라우저의 영어 오류 문구("Failed to fetch") 대신
    }
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok) throw new Error((data && data.error) || `요청 실패 (${res.status})`);
    return data;
  }

  async function poll() {
    try {
      const s = await request('GET', '/api/state');
      const back = !online;
      if (back) {
        online = true;
        forgetErrors(); // 끊긴 동안 실패한 것은 다시 불러오게
        emit('connection', true);
      }
      if (s.version !== version) apply(s);
      else if (back) emit('change', view);
    } catch (_) {
      if (online) { online = false; emit('connection', false); }
    }
  }

  // 연결이 끊기면 5초마다만 다시 묻는다 (감독 프로그램을 껐다 켤 때 요청이 쌓이지 않게)
  function start() {
    const loop = () => poll().finally(() => setTimeout(loop, online ? POLL_MS : 5000));
    loop();
  }

  function refresh() { return poll(); }

  // ---------------------------------------------------------------- 서버 상태 → 화면 모양
  function shortTitle(title) { return String(title || '').replace(/\s*담당$/, '').split('·')[0]; }

  function apply(s) {
    const first = raw === null;
    raw = s;
    version = s.version;
    const st = s.status || {};
    const today = st.today || {};
    const limits = st.limits || {};
    team = (s.team || []).filter((m) => m.character).map((m) => ({
      id: m.character, role: m.key, name: m.name, title: shortTitle(m.title), fullTitle: m.title,
      memo: m.memo, skills: m.skills || [], look: m.look, stats: m.stats, state: m.state, phase: m.phase,
      task: m.task, runtime: m.runtime, model: m.model, job: m.job || m.key, // 맡은 일 (새 직원은 기본 직원의 일)
      desk: m.seat || 0, floor: m.floor || 1, // 책상 번호·층 (studio/floors.py)
      card: m.card || null, sandbox: m.sandbox, // 업무 카드 (임무·할 수 있는 것·못 하는 것·만드는 것)
      ai: m.ai || { runtime: m.runtime, model: '', effort: m.effort || '' }, aiCustom: Boolean(m.ai_custom), // AI 탑재
    }));
    if (!team.length) team = DEFAULT_TEAM.map((p) => ({ ...p }));
    indexTeam();
    view = {
      studio: s.studio || { name: 'AI 스튜디오' },
      day: s.day || 1,
      energy: { max: limits.max_runs_per_day || 40, runsToday: today.runs || 0, minutesToday: today.minutes || 0 },
      stopped: Boolean(st.stopped),
      stopReason: st.stop_reason,
      needsLogin: st.needs_login || null, // 한도·로그인 만료로 멈춤 {runtime, reason, at, opened, error}
      goals: s.goals || { week: '', month: 5 },
      tasks: s.tasks || [],
      events: (s.alerts || []).map((a) => ({
        key: a.key, time: a.time, who: a.who, name: a.name, role: a.role, text: a.text, type: a.type, status: a.status,
        // 스킬 알림은 스킬 게시판으로, 나머지는 작업 화면으로
        target: a.skill ? { screen: 'skills', skill: a.skill } : a.task ? { screen: a.screen || 'task', task: a.task } : null,
      })),
      unread: s.unread_alerts || 0,
      trophies: s.trophies || [],
      skills: s.skills || [],
      mcp: s.mcp || [], // MCP 보관소 (토큰 값은 없음, env_set에 넣었는지만)
      schedules: s.schedules || [], // 업무 자동 시작 (벽시계): when(글)·next(다음 때)
      selfLearning: s.self_learning || { on: true, limit: 3, today: 0 }, // 스스로 배우기 스위치·오늘 횟수
      projects: s.projects || [],
      lookOptions: s.look_options || null,
      floors: s.floors || { count: 1, max: 1, desks: [6], staff_max: 2, staff: 0, next_desks: 0 },
      leftStaff: s.left_staff || {}, // 내보낸 직원 {키: {name, job}}
      current: st.current || null,
      lastError: st.last_error || null,
    };
    if (!project || !view.projects.some((p) => p.key === project)) project = pickProject();
    // 상세 캐시는 작업이 바뀌면 버린다
    for (const t of view.tasks) {
      const d = caches.detail.get(t.id);
      if (d && detailStale(d, t)) caches.detail.delete(t.id);
    }
    caches.diary.delete(view.day);
    // 새 알림 → 'event'
    const keys = view.events.map((e) => e.key);
    if (first || !seen) {
      seen = new Set(keys);
    } else {
      const fresh = view.events.filter((e) => !seen.has(e.key)).reverse();
      for (const e of fresh) seen.add(e.key);
      for (const e of fresh) emit('event', e);
    }
    emit('change', view);
  }

  function pickProject() {
    let saved = null;
    try { saved = localStorage.getItem('studio.project'); } catch (_) { saved = null; }
    if (saved && view.projects.some((p) => p.key === saved)) return saved;
    const game = view.projects.find((p) => p.kind === 'godot');
    return (game || view.projects[0] || {}).key || null;
  }

  // ---------------------------------------------------------------- 읽기
  function get() { return view; }
  function task(id) { return view.tasks.find((t) => t.id === id) || null; }
  // 작업을 맡은 직원. 내보낸 직원이면 같은 일을 하는 기본 직원의 얼굴로 (이름은 떠난 직원 것)
  function owner(t) {
    const role = (t && t.role) || KIND_ROLE[t && t.kind];
    if (byRole[role]) return byRole[role];
    const gone = (view.leftStaff || {})[role];
    if (gone && byRole[gone.job]) return { ...byRole[gone.job], name: gone.name, left: true };
    return byRole[KIND_ROLE[t && t.kind]] || team[0];
  }

  function columns() {
    const live = view.tasks.filter((t) => t.status !== 'cancelled');
    return [
      { key: 'waiting', label: '대기', tasks: live.filter((t) => ['queued', 'ready'].includes(t.status)) },
      { key: 'active', label: '진행 중', tasks: live.filter((t) => ['running', 'checking', 'blocked'].includes(t.status)) },
      { key: 'awaiting', label: '결재 대기', tasks: live.filter((t) => t.status === 'awaiting_approval') },
      { key: 'done', label: '완료', tasks: live.filter((t) => t.status === 'done' && t.kind !== 'plan').slice(-5).reverse() },
    ];
  }

  function inbox(archived = false) {
    return view.tasks.filter((t) => t.status === 'awaiting_approval' && Boolean(t.archived) === archived);
  }

  function unreadAlerts() { return view.unread; }

  function markAlertsRead() {
    view.unread = 0;
    emit('change', view);
    request('POST', '/api/alerts/read').catch(() => {});
  }

  // 직원 상태창 (SPEC 5.3). 기록이 없으면 null.
  function sheet(id) {
    const p = byId[id] || team[0];
    const s = p.stats || {};
    return {
      person: p,
      level: s.level || 1,
      xp: s.xp || 0,
      xpMax: s.xp_max || 5,
      speed: s.speed ?? null,
      accuracy: s.accuracy ?? null,
      thorough: s.thorough ?? null,
      done: s.done || 0,
      todayDone: s.today_done || 0,
      todayFix: s.today_fix || 0,
      mood: s.mood || 'normal',
    };
  }

  // 처음 볼 때 불러오는 것들: 있으면 주고, 없으면 null을 주고 불러온 뒤 'change'
  function fetchInto(kind, key, path) {
    const tag = `${kind}:${key}`;
    if (!loading.has(tag)) {
      loading.set(tag, request('GET', path)
        .catch((err) => ({ error: err.message, failedAt: Date.now() }))
        .then((data) => {
          caches[kind].set(key, data);
          loading.delete(tag);
          emit('change', view);
          return data;
        }));
    }
    return loading.get(tag);
  }

  // 실패도 기억해서 오류를 보여 주지만, RETRY_MS가 지나면 뒤에서 다시 불러온다 (한 번 실패로 창이 계속 깨져 있지 않게)
  function lazy(kind, key, path) {
    const cache = caches[kind];
    if (cache.has(key)) {
      const v = cache.get(key);
      if (v && v.error && online && Date.now() - v.failedAt > RETRY_MS) fetchInto(kind, key, path);
      return v;
    }
    fetchInto(kind, key, path);
    return null;
  }

  // 실패해서 기억해 둔 것을 지운다 (다시 연결됐을 때, '다시 불러오기' 버튼)
  function forgetErrors() {
    for (const cache of Object.values(caches)) {
      for (const [k, v] of cache) if (v && v.error) cache.delete(k);
    }
  }

  function retry() {
    forgetErrors();
    emit('change', view);
  }

  // 같은 초에 기획 대기→완료가 바뀌거나 오래 걸린 조회가 뒤늦게 도착해도 이전 결과를 쓰지 않는다.
  function detailStale(d, t) {
    return d.updated_at !== t.updated_at || (d.status && d.status !== t.status)
      || (Array.isArray(d.runs) && t.usage?.runs != null && d.runs.length !== t.usage.runs);
  }
  function detail(id) {
    const cached = caches.detail.get(id), t = task(id);
    if (cached && !cached.error && t && detailStale(cached, t)) caches.detail.delete(id);
    return lazy('detail', id, `/api/tasks/${encodeURIComponent(id)}`);
  }
  function report(id) {
    const t = task(id);
    return lazy('report', `${id}|${t ? t.updated_at : ''}`, `/api/tasks/${encodeURIComponent(id)}/report`);
  }
  function diff(id) {
    const t = task(id);
    return lazy('diff', `${id}|${t ? t.updated_at : ''}`, `/api/tasks/${encodeURIComponent(id)}/diff`);
  }
  function diary(day) { return lazy('diary', day, `/api/diary?day=${Number(day)}`); }
  // 스킬 본문·진화 기록·사용 기록 (게시판의 요약에는 없다). 판이 오르거나 끝난 일·오늘 실행이 늘면 다시 읽는다
  function skill(slug) {
    const sk = view.skills.find((x) => x.slug === slug);
    const done = view.tasks.filter((t) => t.status === 'done').length;
    return lazy('skill', `${slug}@${sk ? sk.version : 0}|${done}|${view.energy.runsToday}`, `/api/skills/${encodeURIComponent(slug)}`);
  }
  // 스킬 성적표 (쓴 횟수·한 번에 풀린 수·배우기 전후). 끝난 일·스킬 판·배운 직원이 바뀌면 다시 읽는다
  function skillGrades() {
    const done = view.tasks.filter((t) => t.status === 'done').length;
    const key = `${done}|${view.energy.runsToday}|${view.skills.map((x) => `${x.slug}@${x.version}:${x.learned_by.join(',')}`).join(';')}`;
    return lazy('grades', key, '/api/skills/report');
  }
  // 책장을 넘기기 전에 그날 일지를 미리 불러 둔다 (있으면 바로)
  function loadDiary(day) {
    if (caches.diary.has(day)) return Promise.resolve(caches.diary.get(day));
    return fetchInto('diary', day, `/api/diary?day=${Number(day)}`);
  }

  // 회의실 카드: 기획안 + CEO가 고른 것·고친 제목
  function planCards(id) {
    const d = detail(id);
    if (!d || d.error || !d.proposal) return null;
    const mine = edits[id] || {};
    return (d.proposal.tasks || []).map((c, i) => ({
      title: (mine[i] && mine[i].title) || c.title,
      role: KIND_ROLE[c.kind] || 'builder',
      difficulty: c.difficulty || 1,
      brief: c.brief,
      acceptance: c.acceptance || [],
      checked: mine[i] && 'checked' in mine[i] ? mine[i].checked : true,
    }));
  }

  function editCard(id, i, patch) {
    edits[id] = edits[id] || {};
    edits[id][i] = { ...(edits[id][i] || {}), ...patch };
    emit('change', view);
  }

  function planPayload(id) {
    const cards = planCards(id) || [];
    const payload = { selected: [], edits: {} };
    cards.forEach((c, i) => {
      if (c.checked) payload.selected.push(i);
      if (edits[id] && edits[id][i] && edits[id][i].title) payload.edits[String(i)] = { title: edits[id][i].title };
    });
    return payload;
  }

  // ---------------------------------------------------------------- 행동
  async function post(path, body) {
    const data = await request('POST', path, body);
    await refresh();
    return data;
  }

  function act(id, action, body = {}) {
    if (action === 'approve' && task(id)?.approval) body = { ...body, candidate_sha: task(id).candidate_sha, revision: task(id).approval.revision };
    if (action === 'approve' && task(id) && task(id).kind === 'plan') body = planPayload(id);
    if (action === 'archive') body = { archived: !(task(id) || {}).archived };
    return post(`/api/tasks/${encodeURIComponent(id)}/${action}`, body);
  }

  function directive(text) {
    if (!project) return Promise.reject(new Error('프로젝트가 없어요. trusted/projects를 확인하세요.'));
    return post('/api/directive', { text, project });
  }

  function setProject(key) {
    project = key;
    try { localStorage.setItem('studio.project', key); } catch (_) { /* 저장 못 해도 괜찮다 */ }
    emit('change', view);
  }
  function projectDefaults() { return request('GET', '/api/projects/defaults'); }
  function registerProject(data) { return post('/api/projects', data); }
  function retarget(id, data) { return post(`/api/tasks/${encodeURIComponent(id)}/retarget`, data); }
  function currentProject() { return view.projects.find((p) => p.key === project) || null; }
  function workbenchGet(suffix = '') { return request('GET', `/api/workbench${suffix}`); }
  function workbenchPost(action, body = {}) { return request('POST', `/api/workbench/${action}`, body); }
  function statusLabel(t) { return t.needs_plan_input ? '답변 필요' : (STATUS_LABELS[t.status] || t.status); }

  // 작업이 어느 프로젝트 것인지 (프로젝트가 둘 이상일 때만 이름을 준다. 하나면 굳이 보이지 않는다)
  function projectTitle(key) {
    if (view.projects.length < 2) return null;
    const p = view.projects.find((x) => x.key === key);
    return p ? p.title : key || null;
  }

  function setGoal(text) { return post('/api/settings/goals', { week: text }); }
  function setStopped(value) { return post(value ? '/api/control/stop' : '/api/control/resume'); }
  function saveLook(role, look) { return post(`/api/team/${encodeURIComponent(role)}/look`, { look }); }
  function addFloor() { return post('/api/floors/add', {}); }
  function addTrophy(id) { return post('/api/trophies/add', { task: id, kind: 'game' }); }
  function removeTrophy(id) { return post('/api/trophies/remove', { task: id }); }
  function play(id) { return post('/api/trophies/play', { task: id }); }

  // 스킬 학습: 직접 가르치기, 공부 맡기기(지금 고른 프로젝트에서), 배우기·잊기, 쓰는 곳 바꾸기, 지우기
  function teachSkill(data) { return post('/api/skills', data); }
  // 쓰는 곳: projects·kinds (비우면 모든 프로젝트·모든 일)
  function setSkillScope(slug, projects, kinds) { return post(`/api/skills/${encodeURIComponent(slug)}/scope`, { projects, kinds }); }
  // target: '더 좋게 고쳐 오기'로 고칠 스킬 (주제는 비워도 된다)
  function studySkill(role, topic, target = null) {
    if (!project) return Promise.reject(new Error('프로젝트가 없어요. trusted/projects를 확인하세요.'));
    return post('/api/skills/study', { role, topic, project, target });
  }
  // MCP 보관소: 바깥 MCP 등록, 장착·켜기·토큰·연결 확인·지우기 (action = equip | enable | secrets | check | remove)
  function mcpAdd(data) { return post('/api/mcp', data); }
  function mcpAction(name, action, body = {}) { return post(`/api/mcp/${encodeURIComponent(name)}/${action}`, body); }
  // 직원에게 MCP 만들기 맡기기 (지금 고른 프로젝트 폴더를 읽으며). target: 직원이 만든 도구 고쳐 오기
  function mcpOrder(role, request, target = null) {
    if (!project) return Promise.reject(new Error('프로젝트가 없어요. trusted/projects를 확인하세요.'));
    return post('/api/mcp/order', { role, request, project, target });
  }
  // 업무 자동 시작 (벽시계): 만들기(지금 고른 프로젝트), action = enable | remove | run
  function addSchedule(data) {
    if (!project) return Promise.reject(new Error('프로젝트가 없어요. trusted/projects를 확인하세요.'));
    return post('/api/schedules', { ...data, project });
  }
  // 휴대폰 리모컨 (이 PC에서만): 상태 읽기, 짝짓기 번호, 같은 와이파이 켜기·끄기, Tailscale 주소 찾기·빼기, 기기 끊기
  // 다른 아이디로 로그인: 로그인 창 열기(새 명령 창), 로그인 끝 → 재개하고 막힌 일 다시 하기
  function loginOpen(runtime = '') { return post('/api/login/open', { runtime }); }
  function loginDone() { return post('/api/login/done', {}); }
  function remoteInfo() { return request('GET', '/api/remote'); }
  function remoteCheck() { return request('GET', '/api/remote/check'); }
  function remotePair() { return request('POST', '/api/remote/pair', {}); }
  function remoteLan(on) { return request('POST', '/api/remote/lan', { on }); }
  function remoteTailscale(body) { return request('POST', '/api/remote/tailscale', body); }
  function remoteForget(id) { return request('POST', `/api/remote/devices/${encodeURIComponent(id)}/remove`, {}); }
  function scheduleAction(id, action, body = {}) { return post(`/api/schedules/${encodeURIComponent(id)}/${action}`, body); }
  function setSelfLearning(on) { return post('/api/settings/self-learning', { enabled: Boolean(on) }); }

  // AI 탑재: 끼울 수 있는 AI 목록(Codex 공식 목록·Claude 별칭)은 처음 볼 때 한 번 읽는다
  function aiOptions() { return lazy('ai', 'options', '/api/ai/options'); }
  function setAI(role, value) { return post(`/api/team/${encodeURIComponent(role)}/ai`, value); }
  function resetAI(role) { return post(`/api/team/${encodeURIComponent(role)}/ai/reset`); }

  // 의상 제조실: 새 옷 주문, 승인 전 미리보기 그림 주소
  // 꾸미기 공방 주문: kind = outfit | body | hair | accessory | face (지금 모습에서 그것만 바꿔 새로 그린다)
  function orderOutfit(role, label, desc, kind = 'outfit', draw = 'codex') { return post(`/api/team/${encodeURIComponent(role)}/outfit`, { label, desc, kind, draw }); }
  // 꾸미기 옷 ✕: 공방에서 만든 옷은 휴지통으로, 배포 옷(여름 옷 등)은 그 직원 목록에서 숨긴다. restore = 숨긴 옷 되살리기
  function removeLook(role, set) { return post(`/api/team/${encodeURIComponent(role)}/looks/${encodeURIComponent(set)}/remove`); }
  function restoreLook(role, set) { return post(`/api/team/${encodeURIComponent(role)}/looks/${encodeURIComponent(set)}/restore`); }
  function lookPreview(id, name) { return `/api/tasks/${encodeURIComponent(id)}/look/${name}`; }

  // 캐릭터 제조실: 새 직원 주문, 담당 바꾸기
  function hire(data) { return post('/api/staff', data); }
  function dismiss(role) { return post(`/api/team/${encodeURIComponent(role)}/dismiss`, {}); }
  function assign(id, role) { return post(`/api/tasks/${encodeURIComponent(id)}/assign`, { role }); }
  function learnSkill(slug, role, learned) { return post(`/api/skills/${encodeURIComponent(slug)}/learn`, { role, learned }); }
  function removeSkill(slug) {
    for (const k of [...caches.skill.keys()]) if (k.startsWith(`${slug}@`)) caches.skill.delete(k);
    return post(`/api/skills/${encodeURIComponent(slug)}/remove`);
  }

  return {
    get TEAM() { return team; },
    get BY_ROLE() { return byRole; },
    get BY_ID() { return byId; },
    STATUS_LABELS, KIND_LABELS, statusLabel,
    start, refresh, on, get, task, owner, columns, inbox, sheet, unreadAlerts, markAlertsRead,
    detail, report, diff, diary, loadDiary, skill, skillGrades, planCards, editCard, retry, projectTitle,
    act, directive, setProject, currentProject, projectDefaults, registerProject, retarget, workbenchGet, workbenchPost, setGoal, setStopped, saveLook, addFloor, addTrophy, removeTrophy, play,
    teachSkill, studySkill, learnSkill, setSkillScope, removeSkill, setSelfLearning, mcpAdd, mcpAction, mcpOrder, addSchedule, scheduleAction,
    remoteInfo, remoteCheck, remotePair, remoteLan, remoteTailscale, remoteForget, loginOpen, loginDone, aiOptions, setAI, resetAI, orderOutfit, removeLook, restoreLook, lookPreview, hire, dismiss, assign,
    isOnline: () => online,
    get loaded() { return raw !== null; }, // 서버 상태를 한 번이라도 읽었는지
  };
})();
