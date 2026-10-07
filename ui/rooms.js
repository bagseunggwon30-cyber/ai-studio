/* AI 스튜디오 — 소설 집필실 · 디자인 작업실: 작품(프로젝트)의 파일을 읽고, 시작 버튼으로 직원들에게 일을 맡기는 화면.
 *
 * 한 컴포넌트(Rooms)가 모드(novel · design)만 달리해 두 페이지를 그린다. 왼쪽(파일 목록) · 가운데(읽기 화면) · 오른쪽(일 맡기기)의 3단.
 * 서버가 이미 만들어 둔 것만 쓴다: 모드·시작 버튼 GET /api/modes, 새 프로젝트 POST /api/projects/new, 파일 목록·글·그림
 * GET /api/projects/<ID>/tree·file·raw (기준 브랜치 = 사장님이 결재한 내용만), 일 맡기기 POST /api/modes/start. 새 서버 일은 없다.
 * 안전 규칙: 글 파일은 모두 textContent로 넣는다 (마크다운·HTML·SVG를 해석하거나 실행하지 않는다). 그림은 <img src>로만 연다 (스크립트가 돌지 않는다).
 *   일 맡기기·새 프로젝트 만들기는 누르는 순간 잠가 한 번만 보낸다. 서버 오류 글은 그대로 보여 준다. 동적 스타일 없음(CSP).
 * 순수 계산(Rooms.logic: 파일 이름표·폴더 묶기·번호순·'약 N자'·마크다운 줄 나누기·ID 제안·입력칸 검사 등)은 DOM 없이 돈다 — tools/dev/rooms_sim.js가 확인한다.
 * board.js가 껍데기(왼쪽 메뉴)와 두 구역(.bd-page-novel · .bd-page-design)을 만들어 주고, 필요한 도구는 init(el, helpers)로 받는다.
 */
'use strict';

const Rooms = (() => {
  // ---------------------------------------------------------------- 순수 계산
  const MODES = {
    novel: {
      id: 'novel', title: '소설 집필실', noun: '작품', obj: '작품을', subj: '작품이', icon: 'pencil', newLabel: '새 작품 만들기',
      sub: '작품을 고르고 아래 시작 버튼으로 일을 맡기면 직원들이 기획·집필·검토해요.',
      emptyTitle: '아직 작품이 없어요',
      emptyText: '새 작품을 만들면 설정집·원고·메모 폴더가 준비돼요. 그다음 직원들에게 기획과 집필을 맡길 수 있어요.',
      startFirst: '먼저 작품을 만들어 주세요.',
      dirs: ['bible/', 'chapters/', 'notes/'], idBase: 'novel', pickLabel: '작품 고르기',
    },
    design: {
      id: 'design', title: '디자인 작업실', noun: '디자인 프로젝트', obj: '디자인 프로젝트를', subj: '디자인 프로젝트가', icon: 'layout', newLabel: '새 디자인 프로젝트 만들기',
      sub: '프로젝트를 고르고 아래 시작 버튼으로 일을 맡기면 직원들이 기획·시안 제작·점검을 해요.',
      emptyTitle: '아직 디자인 프로젝트가 없어요',
      emptyText: '새 디자인 프로젝트를 만들면 기획서·규칙·시안 폴더가 준비돼요. 그다음 직원들에게 기획과 시안 제작을 맡길 수 있어요.',
      startFirst: '먼저 디자인 프로젝트를 만들어 주세요.',
      dirs: ['brief/', 'system/', 'screens/'], idBase: 'design', pickLabel: '프로젝트 고르기',
    },
  };

  // 왼쪽 파일 목록의 폴더 묶음 (위에서부터), 나머지는 '기타'
  const FOLDERS = {
    novel: [['bible', '설정집'], ['chapters', '원고'], ['notes', '메모']],
    design: [['brief', '기획서'], ['system', '규칙'], ['screens', '시안'], ['assets', '그림'], ['reviews', '점검']],
  };
  const OTHER = '기타';

  // 기본 뼈대 파일의 쉬운 이름표 (모르는 파일은 이름 그대로)
  const LABELS = {
    novel: {
      'README.md': '작품 소개', 'bible/premise.md': '한 줄 소개', 'bible/characters.md': '인물', 'bible/world.md': '세계',
      'bible/outline.md': '줄거리', 'bible/style.md': '문체', 'notes/continuity.md': '연속성 장부', 'chapters/README.md': '원고 폴더 안내',
    },
    design: {
      'README.md': '프로젝트 소개', 'brief/brief.md': '디자인 기획서', 'brief/references.md': '참고 자료', 'system/design-tokens.md': '디자인 규칙',
      'system/components.md': '부품 목록', 'screens/README.md': '시안 안내', 'assets/requests.md': '그림 요청서', 'reviews/README.md': '점검 안내',
    },
  };

  // 기본 뼈대 파일은 읽는 순서대로 먼저, 나머지는 경로순 (원고는 번호순)
  const ORDER = {
    novel: ['bible/premise.md', 'bible/characters.md', 'bible/world.md', 'bible/outline.md', 'bible/style.md', 'notes/continuity.md'],
    design: ['brief/brief.md', 'brief/references.md', 'system/design-tokens.md', 'system/components.md', 'assets/requests.md'],
  };
  const TEMPLATE_NOTICE = '하나가 기획안을 먼저 올려요. 진행판에서 결재하면 직원들이 일해요. 직원 일은 구독 사용량을 써요.';
  const KEY_RULE = '프로젝트 ID는 소문자 영문으로 시작하고 영문·숫자·-만 사용하세요 (40자까지).';
  const MAX_BLOCKS = 3000;
  const MAX_ROWS = 8;
  const STATUS_KEY = { queued: 'wait', ready: 'wait', running: 'work', checking: 'work', awaiting_approval: 'await', done: 'done', blocked: 'bad', cancelled: 'stop' };

  const chars = (s) => Array.from(String(s ?? ''));
  const comma = (n) => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const chapterNo = (path) => { const m = /^chapters\/(\d+)\.md$/i.exec(String(path)); return m ? Number(m[1]) : null; };

  // 한글 한 글자는 UTF-8로 3바이트쯤이라 바이트÷3을 글자 수 어림으로 쓴다
  function approxChars(bytes) { return Math.max(0, Math.round((Number(bytes) || 0) / 3)); }
  function charsText(bytes) { return `약 ${comma(approxChars(bytes))}자`; }
  function sizeText(bytes) {
    const n = Math.max(0, Number(bytes) || 0);
    if (n < 1024) return `${n}B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1).replace(/\.0$/, '')}KB`;
    return `${(n / 1024 / 1024).toFixed(1).replace(/\.0$/, '')}MB`;
  }

  // 파일 이름표: 원고는 'N장', 기본 뼈대 파일은 쉬운 이름, 모르는 파일은 그대로
  function fileLabel(mode, path, fallback = null) {
    const no = mode === 'novel' ? chapterNo(path) : null;
    if (no !== null) return `${no}장`;
    return (LABELS[mode] || {})[path] || fallback || String(path).split('/').pop();
  }

  // 읽는 방식: image(그림 파일) · svg(그림으로도 글로도) · chapter(소설 원고) · markdown(설명 글) · raw(코드·표 같은 원문)
  function viewKindOf(mode, file) {
    const path = String(file.path || '');
    if (file.kind === 'image') return 'image';
    if (/\.svg$/i.test(path)) return 'svg';
    if (/\.md$/i.test(path)) return mode === 'novel' && chapterNo(path) !== null ? 'chapter' : 'markdown';
    return 'raw';
  }

  // 파일 목록 → 폴더 묶음 [{key, label, files:[{path, label, name, meta, size, kind, chapter}]}] (비어 있는 묶음은 뺀다)
  function groupFiles(mode, files) {
    const defs = FOLDERS[mode] || [];
    const groups = defs.map(([dir, label]) => ({ key: dir, label, dir, files: [] }));
    const other = { key: '_other', label: OTHER, dir: '', files: [] };
    for (const f of files || []) {
      const g = groups.find((x) => f.path.startsWith(`${x.dir}/`)) || other;
      const chapter = mode === 'novel' ? chapterNo(f.path) : null;
      const label = fileLabel(mode, f.path, g.dir ? f.path.slice(g.dir.length + 1) : f.path);
      const name = f.path.split('/').pop();
      g.files.push({ path: f.path, label, name: label === name ? '' : name, size: f.size, kind: f.kind, chapter, meta: chapter !== null ? charsText(f.size) : sizeText(f.size), view: viewKindOf(mode, f) });
    }
    for (const g of [...groups, other]) {
      const rank = (f) => { const i = (ORDER[mode] || []).indexOf(f.path); return i < 0 ? 1000 : i; };
      g.files.sort((a, b) => {
        if (a.chapter !== null && b.chapter !== null) return a.chapter - b.chapter;
        if (a.chapter !== null) return -1;
        if (b.chapter !== null) return 1;
        return rank(a) - rank(b) || (a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
      });
    }
    return [...groups, other].filter((g) => g.files.length);
  }

  // 왼쪽 맨 위 요약: 소설 = 원고 N개 장 · 약 N자, 디자인 = 시안 N개 · 그림 N개
  function summary(mode, files) {
    const list = files || [];
    if (mode === 'novel') {
      const ch = list.filter((f) => chapterNo(f.path) !== null);
      const total = ch.reduce((sum, f) => sum + approxChars(f.size), 0);
      return { parts: ['원고 ', String(ch.length), '개 장 · 약 ', comma(total), '자'], text: `원고 ${ch.length}개 장 · 약 ${comma(total)}자`, chapters: ch.length, chars: total };
    }
    const screens = list.filter((f) => f.path.startsWith('screens/') && /\.(html|svg)$/i.test(f.path)).length;
    const pictures = list.filter((f) => f.path.startsWith('assets/') && (f.kind === 'image' || /\.svg$/i.test(f.path))).length;
    return { parts: ['시안 ', String(screens), '개 · 그림 ', String(pictures), '개'], text: `시안 ${screens}개 · 그림 ${pictures}개`, screens, pictures };
  }

  // 마크다운 비슷한 글을 줄 단위로 나눈다 (HTML로 해석하지 않는다): '# '=큰 제목, '## '=작은 제목, '- '=목록, 빈 줄=문단 끝, '---'=장면 나누기, 나머지는 문단
  function blocks(text, max = MAX_BLOCKS) {
    const out = [];
    let para = [];
    let truncated = false;
    const flush = () => { if (para.length) { out.push({ t: 'p', text: para.join('\n') }); para = []; } };
    for (const raw of String(text ?? '').replace(/^﻿/, '').split(/\r?\n/)) {
      if (out.length >= max) { truncated = true; para = []; break; }
      const line = raw.replace(/\s+$/, '');
      let m;
      if (!line.trim()) flush();
      else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push({ t: 'hr' }); }
      else if ((m = /^#\s+(.*)$/.exec(line))) { flush(); out.push({ t: 'h1', text: m[1] }); }
      else if ((m = /^#{2,}\s+(.*)$/.exec(line))) { flush(); out.push({ t: 'h2', text: m[1] }); }
      else if ((m = /^\s*[-*]\s+(.*)$/.exec(line))) { flush(); out.push({ t: 'li', text: m[1] }); }
      else para.push(line.trim());
    }
    if (!truncated) flush();
    return { blocks: out, truncated };
  }

  // 새 프로젝트 ID 제안: novel-1, novel-2 … 이미 있는 것과 겹치지 않는 첫 번호
  function suggestKey(mode, taken) {
    const base = (MODES[mode] || MODES.novel).idBase;
    const used = new Set((taken || []).map(String));
    for (let i = 1; i < 1000; i += 1) if (!used.has(`${base}-${i}`)) return `${base}-${i}`;
    return `${base}-${Date.now()}`;
  }
  const KEY_RE = /^[a-z][a-z0-9-]{0,39}$/;
  function keyProblem(key, taken) {
    const k = String(key ?? '').trim();
    if (!k) return 'ID를 적어 주세요.';
    if (!KEY_RE.test(k)) return KEY_RULE;
    if ((taken || []).includes(k)) return '이미 있는 프로젝트 ID예요. 다른 ID를 써 주세요.';
    return '';
  }
  function titleProblem(title, noun = '작품') {
    const t = String(title ?? '').trim();
    if (!t) return `${noun} 이름을 적어 주세요.`;
    if (chars(t).length > 80) return '이름은 80자 이내로 적어 주세요.';
    return '';
  }
  function descProblem(text) { return chars(text).length > 1000 ? '설명은 1000자 이내로 적어 주세요.' : ''; }

  // 시작 버튼 입력칸: 처음 값(default) · 보낼 값 · 보내기 전 검사 (서버 modes.render_template와 같은 말)
  function defaultsOf(tpl) {
    const out = {};
    for (const f of (tpl && tpl.fields) || []) out[f.key] = f.default || '';
    return out;
  }
  function valuesOf(tpl, draft) {
    const out = {};
    for (const f of (tpl && tpl.fields) || []) out[f.key] = String((draft || {})[f.key] ?? '');
    return out;
  }
  function checkFields(tpl, draft) {
    for (const f of (tpl && tpl.fields) || []) {
      const raw = String((draft || {})[f.key] ?? '').trim();
      if (!raw && f.required) return { ok: false, key: f.key, message: `'${f.label}'을 적어 주세요.` };
      if (chars(raw).length > (f.max || 600)) return { ok: false, key: f.key, message: `'${f.label}'은 ${f.max || 600}자 이내로 적어 주세요.` };
    }
    return { ok: true, key: '', message: '' };
  }

  // 이 모드의 프로젝트들 (종류가 모드에 맞는 것). info = GET /api/modes (아직 못 읽었으면 종류 이름 = 모드 이름)
  function projectsOf(mode, projects, info) {
    const found = info && Array.isArray(info.modes) ? info.modes.find((m) => m.id === mode) : null;
    const kinds = found && Array.isArray(found.kinds) && found.kinds.length ? found.kinds : [mode];
    return (projects || []).filter((p) => kinds.includes(p.kind));
  }

  // 이 프로젝트의 일: 새것이 먼저, 최대 8개
  function recentTasks(tasks, key, limit = MAX_ROWS) {
    return (tasks || []).filter((t) => t.project === key)
      .sort((a, b) => (Date.parse(b.created_at || '') || 0) - (Date.parse(a.created_at || '') || 0) || String(b.id).localeCompare(String(a.id)))
      .slice(0, limit);
  }
  function doneIds(tasks, key) { return (tasks || []).filter((t) => t.project === key && t.status === 'done').map((t) => t.id).sort(); }
  const statusKey = (status) => STATUS_KEY[status] || 'wait';

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

  // 이름 뒤 조사 '이/가' (하나가, 솔이)
  function josa(name) {
    const c = String(name).charCodeAt(String(name).length - 1) - 0xac00;
    return c >= 0 && c < 11172 && c % 28 ? '이' : '가';
  }

  // 새 프로젝트 창의 안내: 직원이 고칠 수 있는 폴더 (서버가 알려 준 기본 허용 경로가 있으면 그것으로)
  function folderText(mode, info) {
    const paths = (((info || {}).kinds || {})[mode] || {}).default_paths || [];
    const dirs = paths.filter((p) => typeof p === 'string' && p.endsWith('/**')).map((p) => p.slice(0, -2));
    const list = (dirs.length ? dirs : (MODES[mode] || MODES.novel).dirs).slice(0, 3);
    return `직원은 허용된 폴더(${list.join('·')} 등)만 고칠 수 있어요.`;
  }

  // 서버가 준 글의 코드 표시(`)는 화면에서 뺀다 (쉬운 글로)
  const plain = (text) => String(text ?? '').replace(/`/g, '');

  const logic = {
    MODES, FOLDERS, LABELS, OTHER, TEMPLATE_NOTICE, KEY_RULE, MAX_ROWS,
    chapterNo, approxChars, charsText, sizeText, fileLabel, viewKindOf, groupFiles, summary, blocks, suggestKey, keyProblem, titleProblem, descProblem,
    defaultsOf, valuesOf, checkFields, projectsOf, recentTasks, doneIds, statusKey, ago, josa, folderText, plain, ORDER,
  };

  // ---------------------------------------------------------------- 화면 (create로 만든 뒤 init 이후에만 DOM을 만진다)
  const h = (...a) => Popups.h(...a);
  const ICON = {
    pencil: '<svg viewBox="0 0 24 24"><path d="M4.5 19.5l1-4L16 5a2.1 2.1 0 0 1 3 3L8.5 18.5Z"/><path d="M14 7l3 3"/></svg>',
    layout: '<svg viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M3.5 9.5h17M9.5 9.5v10"/></svg>',
    file: '<svg viewBox="0 0 24 24"><path d="M6 3.5h8l4 4V20.5H6Z"/><path d="M9 12.5h6M9 16h4"/></svg>',
    chapter: '<svg viewBox="0 0 24 24"><path d="M5 5.5A1.5 1.5 0 0 1 6.5 4H18v14H6.5A1.5 1.5 0 0 0 5 19.5Z"/><path d="M5 19.5A1.5 1.5 0 0 0 6.5 21H18"/></svg>',
    image: '<svg viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="15" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="M4 17l4.5-4.5 3.5 3.5 3-3 5 4.5"/></svg>',
    code: '<svg viewBox="0 0 24 24"><path d="M9 8l-4 4 4 4M15 8l4 4-4 4"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><path d="M12 6v12M6 12h12"/></svg>',
    refresh: '<svg viewBox="0 0 24 24"><path d="M5 12a7 7 0 1 1 2.2 5.1"/><path d="M5 18.5V13h5.5"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    chevron: '<svg viewBox="0 0 24 24"><path d="M8 10l4 4 4-4"/></svg>',
    warn: '<svg viewBox="0 0 24 24"><path d="M12 4.5l8.5 15h-17Z"/><path d="M12 10v4.5M12 17.3v.2"/></svg>',
    board: '<svg viewBox="0 0 24 24"><rect x="3.5" y="4" width="4.5" height="16" rx="1.5"/><rect x="9.75" y="4" width="4.5" height="10" rx="1.5"/><rect x="16" y="4" width="4.5" height="13" rx="1.5"/></svg>',
    empty: '<svg viewBox="0 0 64 64"><path d="M8 18a4 4 0 0 1 4-4h14l5 6h21a4 4 0 0 1 4 4v24a4 4 0 0 1-4 4H12a4 4 0 0 1-4-4Z"/><path d="M22 40l6-6 5 5 4-4 7 7"/></svg>',
  };
  const ico = (name, cls = 'rm-ico') => { const el = h('span', { class: cls, 'aria-hidden': 'true' }); el.innerHTML = ICON[name] || ''; return el; };
  const fileIcon = (f) => (f.chapter !== null ? 'chapter' : f.view === 'image' || f.view === 'svg' ? 'image' : f.view === 'raw' ? 'code' : 'file');

  // 다시 그려도 키보드 초점이 그대로이게
  function keepFocus(box, fn) {
    const a = document.activeElement;
    const k = a && box.contains(a) ? a.getAttribute('data-fk') : null;
    fn();
    if (k) {
      const back = box.querySelector(`[data-fk="${CSS.escape(k)}"]`);
      if (back) back.focus({ preventScroll: true });
    }
  }

  function create(mode) {
    const M = MODES[mode];
    const storeKey = `studio.room.${mode}`;
    let root = null;
    let H = null; // board.js가 준 도구 { notify, fail, openTask, goBoard, producerName }
    let visible = false;
    let built = false;
    let key = null; // 고른 프로젝트
    let modesState = 'idle'; // idle | loading | ready | error
    let modesInfo = null;
    let modesError = '';
    const tree = { key: null, state: 'idle', files: [], error: '', seq: 0, had: false }; // had = 이 프로젝트의 목록을 한 번이라도 읽었다 (다시 읽는 동안에도 옛 목록을 보인다)
    const file = { path: null, vk: '', size: 0, view: 'text', text: null, state: 'idle', error: '', seq: 0, rev: 0 }; // rev = 그림 파일이 다시 바뀐 횟수 (주소 뒤에 붙여 옛 그림이 남지 않게)
    let openTpl = null;
    const drafts = {};
    let sending = false;
    let sendError = '';
    let sendField = '';
    let sent = null; // 방금 맡긴 일 { task, project, title }
    let doneSeen = null;
    let reloadQueued = false; // 목록을 읽는 사이에 일이 또 끝났다: 다 읽은 뒤 한 번 더 읽는다
    const E = {};
    const sig = { head: '', left: '', center: '', form: '', tasks: '' };

    const projects = () => projectsOf(mode, Data.get().projects, modesInfo);
    const templates = () => (modesInfo && modesInfo.templates && modesInfo.templates[mode]) || [];
    const remember = () => { try { localStorage.setItem(storeKey, key || ''); } catch (_) { /* 기억 못 해도 된다 */ } };
    const saved = () => { try { return localStorage.getItem(storeKey) || ''; } catch (_) { return ''; } };

    function init(el, helpers) {
      root = el;
      H = helpers || { notify: () => {}, fail: () => {}, openTask: () => {}, goBoard: () => {}, producerName: () => '하나' };
      build();
    }

    function setVisible(on) {
      visible = Boolean(on);
      if (!root || !built || !visible) return;
      ensureModes();
      syncKey();
      renderAll();
    }

    // Data가 바뀔 때마다 (일 목록·프로젝트 목록): 입력 중인 글은 그대로 두고 바뀐 부분만 고친다
    function render() {
      if (!visible || !built) return;
      syncKey();
      renderHead();
      renderLeft();
      renderCenter();
      renderRightForm();
      renderRightTasks();
      watchDone();
    }

    function renderAll() {
      sig.head = sig.left = sig.center = sig.form = sig.tasks = '';
      renderHead();
      renderLeft();
      renderCenter();
      renderRightForm();
      renderRightTasks();
      watchDone();
    }

    // ---------------------------------------------------------------- 서버에서 읽기
    function ensureModes() {
      if (modesState === 'loading' || modesState === 'ready') return;
      modesState = 'loading';
      renderRightForm();
      Data.modesGet().then((info) => {
        modesInfo = info;
        modesState = 'ready';
        modesError = '';
      }).catch((e) => {
        modesState = 'error';
        modesError = e.message || '불러오지 못했어요';
      }).finally(() => { if (visible) { syncKey(); renderAll(); } });
    }

    // 고른 프로젝트가 이 모드에 없으면 다시 고른다: 기억한 것 → 위쪽 바에서 고른 프로젝트 → 첫 번째
    function syncKey() {
      if (!Data.loaded) return;
      const list = projects();
      if (key && list.some((p) => p.key === key)) { if (tree.key !== key && tree.state === 'idle') loadTree(); return; }
      const want = [saved(), (Data.currentProject() || {}).key].map(String).find((k) => list.some((p) => p.key === k)) || (list[0] || {}).key || null;
      if (want !== key) pick(want, false);
      else if (key && tree.state === 'idle') loadTree();
    }

    function pick(k, save = true) {
      key = k || null;
      if (save) remember();
      file.seq += 1;
      Object.assign(file, { path: null, vk: '', size: 0, text: null, state: 'idle', error: '' });
      sent = null;
      sendError = '';
      sendField = '';
      doneSeen = null;
      Object.assign(tree, { key: null, state: 'idle', files: [], error: '', had: false });
      reloadQueued = false;
      tree.seq += 1;
      if (key && visible) loadTree();
      if (built && visible) renderAll();
    }

    function loadTree() {
      if (!key) return;
      const at = key;
      const seq = tree.seq + 1;
      tree.seq = seq;
      Object.assign(tree, { key: at, state: 'loading', error: '' });
      renderLeft();
      renderCenter();
      Data.projectTree(at).then((res) => {
        if (seq !== tree.seq || at !== key) return;
        tree.files = Array.isArray(res.files) ? res.files : [];
        tree.state = 'ready';
        tree.had = true;
        // 열어 둔 파일이 아직 있으면 그대로 두고, 크기가 바뀌었으면 다시 읽는다. 없어졌으면 선택을 푼다
        if (file.path) {
          const row = tree.files.find((f) => f.path === file.path);
          if (!row) Object.assign(file, { path: null, vk: '', text: null, state: 'idle', error: '' });
          else if (row.size !== file.size) { file.size = row.size; file.rev += 1; file.text = null; file.state = 'idle'; sig.center = ''; if (needsText()) loadText(); }
        }
      }).catch((e) => {
        if (seq !== tree.seq || at !== key) return;
        tree.state = 'error';
        tree.error = e.message || '불러오지 못했어요';
      }).finally(() => {
        if (seq !== tree.seq) return;
        if (visible) { renderLeft(); renderCenter(); }
        if (reloadQueued) { reloadQueued = false; loadTree(); }
      });
    }

    // 일이 새로 끝나면(결재 뒤 병합) 기준 브랜치가 바뀌었을 수 있어 파일 목록을 다시 읽는다. 처음 본 상태는 기준으로만 삼는다
    function watchDone() {
      if (!key || !Data.loaded) return;
      const ids = doneIds(Data.get().tasks, key);
      const text = ids.join(',');
      if (doneSeen === null) { doneSeen = text; return; }
      if (text !== doneSeen) {
        const grew = ids.some((id) => !doneSeen.split(',').includes(id));
        doneSeen = text;
        if (grew) { if (tree.state === 'loading') reloadQueued = true; else loadTree(); }
      }
    }

    function needsText() { return file.vk !== 'image' && (file.vk !== 'svg' || file.view === 'text'); }

    function selectFile(path) {
      const row = tree.files.find((f) => f.path === path);
      if (!row) return;
      file.seq += 1;
      const vk = viewKindOf(mode, row);
      Object.assign(file, { path, vk, size: row.size, view: vk === 'svg' ? 'img' : 'text', text: null, state: vk === 'image' ? 'ready' : 'idle', error: '', rev: 0 });
      if (needsText()) loadText();
      renderLeft();
      renderCenter();
    }

    function loadText() {
      if (file.state === 'loading' || file.text !== null) return;
      const at = key;
      const path = file.path;
      const seq = file.seq;
      file.state = 'loading';
      file.error = '';
      Data.projectFile(at, path).then((res) => {
        if (seq !== file.seq) return;
        file.text = String(res.text ?? '');
        file.size = Number.isFinite(res.size) ? res.size : file.size;
        file.state = 'ready';
      }).catch((e) => {
        if (seq !== file.seq) return;
        file.state = 'error';
        file.error = e.message || '파일을 읽지 못했어요';
      }).finally(() => { if (seq === file.seq && visible) renderCenter(); });
    }

    // ---------------------------------------------------------------- 뼈대 (한 번만 만든다)
    function build() {
      E.projects = h('div', { class: 'rm-projects', role: 'group', 'aria-label': M.pickLabel });
      E.newBtn = h('button', { type: 'button', class: 'rm-pill dark', 'data-fk': 'new', onclick: openNewDialog }, ico('plus'), h('span', { text: M.newLabel }));
      E.head = h('header', { class: 'rm-top' },
        h('nav', { class: 'bd-crumb', 'aria-label': '위치' }, h('span', { text: '작업' }), h('i', { 'aria-hidden': 'true', text: '›' }), h('span', { class: 'cur', text: M.title })),
        h('div', { class: 'rm-titlebar' },
          h('div', { class: 'rm-hello' }, h('h2', { text: M.title }), h('p', { class: 'rm-sub', text: M.sub })),
          h('div', { class: 'rm-tools' }, E.newBtn)),
        E.projects);

      E.summary = h('div', { class: 'rm-summary', hidden: true });
      E.filesNote = h('div', { class: 'rm-listnote', hidden: true });
      E.files = h('div', { class: 'rm-files', role: 'listbox', 'aria-label': '파일 목록', onkeydown: listKeys });
      E.reload = h('button', { type: 'button', class: 'rm-mini', 'aria-label': '파일 목록 다시 읽기', title: '파일 목록 다시 읽기', 'data-fk': 'reload', onclick: () => { if (key) loadTree(); } }, ico('refresh'));
      E.left = h('aside', { class: 'rm-col rm-left', 'aria-label': '파일' },
        E.summary,
        h('section', { class: 'rm-block rm-filesblock' },
          h('div', { class: 'rm-block-head' }, h('h3', { text: '파일' }), E.reload), E.filesNote, E.files));

      E.center = h('section', { class: 'rm-col rm-center', 'aria-label': '읽기 화면' });

      E.rintro = h('p', { class: 'rm-rintro', text: '일을 맡기면 하나가 먼저 기획안을 올리고, 사장님이 결재해야 시작돼요.' });
      E.sent = h('div', { class: 'rm-sentslot' });
      E.form = h('div', { class: 'rm-tpls' });
      E.tasks = h('section', { class: 'rm-block rm-tasks', 'aria-label': '이 프로젝트의 일' });
      E.right = h('aside', { class: 'rm-col rm-right', 'aria-label': '일 맡기기' },
        h('div', { class: 'rm-rhead' }, h('h3', { text: '일 맡기기' }), E.rintro),
        h('div', { class: 'rm-rbody' }, E.sent, E.form, E.tasks));

      root.replaceChildren(E.head, h('div', { class: 'rm-grid' }, E.left, E.center, E.right));
      built = true;
    }

    // ---- 위쪽 줄: 프로젝트 고르기 칩
    function renderHead() {
      const list = projects();
      const sigv = JSON.stringify([Data.loaded, list.map((p) => [p.key, p.title]), key]);
      if (sigv === sig.head) return;
      sig.head = sigv;
      keepFocus(E.projects, () => {
        if (!Data.loaded) { E.projects.replaceChildren(h('span', { class: 'rm-projnote', text: '불러오는 중이에요…' })); return; }
        if (!list.length) { E.projects.replaceChildren(h('span', { class: 'rm-projnote', text: M.emptyTitle })); return; }
        E.projects.replaceChildren(...list.map((p) => h('button', {
          type: 'button', class: `rm-proj${p.key === key ? ' on' : ''}`, 'aria-pressed': String(p.key === key), 'data-fk': `p:${p.key}`, title: p.title,
          onclick: () => { if (p.key !== key) { pick(p.key); Data.setProject(p.key); } }, // 명령창의 '대상'도 같은 프로젝트로
        }, ico(M.icon), h('span', { class: 'rm-proj-name', text: p.title }))));
      });
    }

    // ---- 왼쪽: 요약 + 폴더별 파일 목록
    function listKeys(e) {
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
      const items = [...E.files.querySelectorAll('.rm-file')];
      if (!items.length) return;
      const at = items.indexOf(document.activeElement);
      let to = at;
      if (e.key === 'ArrowDown') to = Math.min(items.length - 1, at + 1);
      else if (e.key === 'ArrowUp') to = Math.max(0, at < 0 ? 0 : at - 1);
      else if (e.key === 'Home') to = 0;
      else to = items.length - 1;
      e.preventDefault();
      items[to].focus();
    }

    function renderLeft() {
      const sigv = JSON.stringify([Data.loaded, key, tree.state, tree.error, file.path, tree.files.map((f) => `${f.path}:${f.size}`)]);
      if (sigv === sig.left) return;
      sig.left = sigv;
      keepFocus(E.left, () => {
        const ready = Boolean(key && tree.had);
        // 요약
        E.summary.hidden = !ready;
        if (ready) {
          const s = summary(mode, tree.files);
          E.summary.setAttribute('aria-label', s.text);
          E.summary.replaceChildren(...s.parts.map((p, i) => (i % 2 === 1 ? h('b', { text: p }) : h('span', { text: p }))));
        }
        E.reload.hidden = !key;
        // 안내 줄
        let note = null;
        if (!Data.loaded) note = ['불러오는 중이에요…'];
        else if (!key) note = [`${M.obj} 만들면 여기에 파일이 보여요.`];
        else if (!tree.had && tree.state !== 'error') note = ['파일을 불러오는 중이에요…'];
        else if (tree.state === 'error' && !tree.had) note = [`파일 목록을 못 불러왔어요. ${tree.error}`.trim(), '다시 불러오기'];
        else if (!tree.files.length) note = ['아직 읽을 파일이 없어요. 오른쪽 시작 버튼으로 일을 맡겨 보세요.'];
        E.filesNote.hidden = !note;
        E.filesNote.replaceChildren(...(note ? [h('p', { text: note[0] }), note[1] ? h('button', { type: 'button', class: 'rm-pill', onclick: () => loadTree() }, note[1]) : null].filter(Boolean) : []));
        // 파일 목록
        const groups = ready ? groupFiles(mode, tree.files) : [];
        let first = null;
        let selected = null;
        const nodes = groups.map((g) => h('div', { class: 'rm-group', role: 'group', 'aria-label': g.label },
          h('p', { class: 'rm-group-title', 'aria-hidden': 'true' }, h('span', { text: g.label }), h('b', { text: String(g.files.length) })),
          g.files.map((f) => {
            const on = f.path === file.path;
            const btn = h('button', {
              type: 'button', class: `rm-file${on ? ' on' : ''}`, role: 'option', 'aria-selected': String(on), 'data-path': f.path, 'data-fk': `f:${f.path}`, title: f.path,
              'aria-label': `${f.label}, ${f.meta}`, tabindex: '-1', onclick: () => selectFile(f.path),
            }, ico(fileIcon(f), 'rm-ico rm-file-ico'),
            h('span', { class: 'rm-file-main' }, h('b', { class: 'rm-file-name', text: f.label }), f.name ? h('span', { class: 'rm-file-sub', text: f.name }) : null),
            h('span', { class: 'rm-file-meta', text: f.meta }));
            if (!first) first = btn;
            if (on) selected = btn;
            return btn;
          })));
        E.files.replaceChildren(...nodes);
        E.files.hidden = !nodes.length;
        const rover = selected || first;
        if (rover) rover.tabIndex = 0;
      });
    }

    // ---- 가운데: 읽기 화면
    function stateBox(title, text, ...extra) {
      return h('div', { class: 'rm-empty' }, h('b', { text: title }), text ? h('p', { text }) : null, ...extra);
    }

    function renderCenter() {
      const sigv = JSON.stringify([Data.loaded, key, projects().length, tree.state, tree.error, tree.files.length, file.path, file.state, file.view, file.text === null ? -1 : file.text.length, file.error]);
      if (sigv === sig.center) return;
      sig.center = sigv;
      let parts;
      if (!Data.loaded) parts = [stateBox('불러오는 중이에요…')];
      else if (!key) {
        parts = [h('div', { class: 'rm-empty rm-noproject' }, ico('empty', 'rm-empty-ico'), h('b', { text: M.emptyTitle }), h('p', { text: M.emptyText }),
          h('button', { type: 'button', class: 'rm-pill dark', 'data-fk': 'new2', onclick: openNewDialog }, ico('plus'), h('span', { text: M.newLabel })))];
      } else if (tree.state === 'error' && !tree.had) {
        parts = [stateBox('파일 목록을 못 불러왔어요', tree.error, h('button', { type: 'button', class: 'rm-pill dark', onclick: () => loadTree() }, ico('refresh'), h('span', { text: '다시 불러오기' })))];
      } else if (!tree.had) {
        parts = [stateBox('파일을 불러오는 중이에요…')];
      } else if (!file.path) {
        parts = [h('div', { class: 'rm-empty' }, ico('empty', 'rm-empty-ico'),
          h('b', { text: tree.files.length ? '읽을 파일을 골라 보세요' : '아직 읽을 파일이 없어요' }),
          h('p', { text: '왼쪽에서 파일을 고르거나 오른쪽 시작 버튼으로 일을 맡겨 보세요.' }),
          h('small', { text: '직원이 쓴 글은 사장님이 결재한 뒤에 여기에 나타나요.' }))];
      } else {
        parts = [readHead(), readBody()];
      }
      keepFocus(E.center, () => E.center.replaceChildren(...parts));
    }

    function readHead() {
      const base = file.path.split('/').pop();
      const named = fileLabel(mode, file.path, base);
      const label = named === base ? '' : named;
      const size = file.vk === 'chapter' ? charsText(file.size) : sizeText(file.size);
      let toggle = null;
      if (file.vk === 'svg') {
        const mk = (view, text) => h('button', {
          type: 'button', class: `rm-seg${file.view === view ? ' on' : ''}`, 'aria-pressed': String(file.view === view), 'data-fk': `v:${view}`,
          onclick: () => { if (file.view === view) return; file.view = view; if (needsText()) loadText(); renderCenter(); },
        }, text);
        toggle = h('div', { class: 'rm-segs', role: 'group', 'aria-label': '보는 방식' }, mk('img', '그림으로'), mk('text', '글(원문)으로'));
      }
      return h('div', { class: 'rm-readhead' },
        h('div', { class: 'rm-readinfo' },
          h('b', { class: 'rm-readpath', text: file.path, title: file.path }),
          h('span', { class: 'rm-chip', text: size }),
          label ? h('span', { class: 'rm-chip soft', text: label }) : null,
          h('span', { class: 'rm-chip ok' }, ico('check', 'rm-ico rm-ico-sm'), h('span', { text: '승인된(기준 브랜치) 내용이에요' }))),
        toggle);
    }

    function readBody() {
      const url = Data.projectRawUrl(key, file.path) + (file.rev ? `&v=${file.rev}` : '');
      const picture = () => {
        const img = h('img', { class: 'rm-img', src: url, alt: `${fileLabel(mode, file.path, file.path.split('/').pop())} 그림`, decoding: 'async' });
        const broken = h('p', { class: 'rm-broken', hidden: true, text: '그림을 열지 못했어요.' });
        img.addEventListener('error', () => { img.hidden = true; broken.hidden = false; });
        return h('div', { class: 'rm-paper rm-imgbox' }, img, broken);
      };
      if (file.vk === 'image' || (file.vk === 'svg' && file.view === 'img')) return picture();
      if (file.state === 'error') return h('div', { class: 'rm-paper rm-msg' }, h('b', { text: '파일을 읽지 못했어요' }), h('p', { text: file.error }),
        h('button', { type: 'button', class: 'rm-pill dark', onclick: () => { file.state = 'idle'; file.text = null; loadText(); renderCenter(); } }, '다시 읽기'));
      if (file.text === null) return h('div', { class: 'rm-paper rm-msg' }, h('b', { text: '읽는 중이에요…' }));
      if (file.vk === 'chapter' || file.vk === 'markdown') {
        const { blocks: list, truncated } = blocks(file.text);
        const body = h('article', { class: `rm-read ${file.vk === 'chapter' ? 'chapter' : 'doc'}`, tabindex: '0', 'aria-label': '읽기' });
        let ul = null;
        for (const b of list) {
          if (b.t !== 'li') ul = null;
          if (b.t === 'h1') body.append(h('h3', { class: 'rm-h1', text: b.text }));
          else if (b.t === 'h2') body.append(h('h4', { class: 'rm-h2', text: b.text }));
          else if (b.t === 'hr') body.append(h('hr', { class: 'rm-break' }));
          else if (b.t === 'li') { if (!ul) { ul = h('ul', { class: 'rm-bullets' }); body.append(ul); } ul.append(h('li', { text: b.text })); }
          else body.append(h('p', { class: 'rm-p', text: b.text }));
        }
        if (!list.length) body.append(h('p', { class: 'rm-p rm-dim', text: '(빈 파일이에요)' }));
        if (truncated) body.append(h('p', { class: 'rm-p rm-dim', text: '(글이 너무 길어서 앞부분만 보여 줘요)' }));
        return h('div', { class: 'rm-paper' }, body);
      }
      return h('div', { class: 'rm-paper' }, h('pre', { class: 'rm-raw', tabindex: '0', 'aria-label': '파일 원문 (실행하지 않아요)', text: file.text || '(빈 파일이에요)' }));
    }

    // ---- 오른쪽: 시작 버튼 카드 + 입력칸
    const draftFor = (tpl) => {
      const id = `${key}|${tpl.id}`;
      if (!drafts[id]) drafts[id] = defaultsOf(tpl);
      return drafts[id];
    };

    const formSig = () => JSON.stringify([Data.loaded, key, projects().length, modesState, modesError, openTpl, sending, sendError, sendField, sent && sent.task, Boolean(Data.get().stopped), templates().length]);

    function renderRightForm() {
      const stopped = Boolean(Data.get().stopped);
      const sigv = formSig();
      if (sigv === sig.form) return;
      sig.form = sigv;
      E.sent.replaceChildren(...(sent ? [sentBox()] : []));
      keepFocus(E.form, () => {
        if (!Data.loaded) { E.form.replaceChildren(h('p', { class: 'rm-note', text: '불러오는 중이에요…' })); return; }
        if (!key) { E.form.replaceChildren(h('div', { class: 'rm-card rm-needproject' }, h('b', { text: M.startFirst }), h('p', { text: `${M.subj} 있어야 일을 맡길 수 있어요.` }))); return; }
        if (modesState === 'error') {
          E.form.replaceChildren(h('div', { class: 'rm-card' }, h('b', { text: '시작 버튼을 못 불러왔어요' }), h('p', { text: modesError }),
            h('button', { type: 'button', class: 'rm-pill dark', onclick: () => { modesState = 'idle'; ensureModes(); } }, '다시 불러오기')));
          return;
        }
        if (modesState !== 'ready') { E.form.replaceChildren(h('p', { class: 'rm-note', text: '시작 버튼을 불러오는 중이에요…' })); return; }
        E.form.replaceChildren(...templates().map((tpl) => templateCard(tpl, stopped)));
      });
    }

    function templateCard(tpl, stopped) {
      const open = openTpl === tpl.id;
      const bodyId = `rm-tpl-${mode}-${tpl.id}`;
      const head = h('button', {
        type: 'button', class: 'rm-tpl-head', 'aria-expanded': String(open), 'aria-controls': bodyId, 'data-fk': `tpl:${tpl.id}`,
        onclick: () => {
          openTpl = open ? null : tpl.id;
          sendError = '';
          sendField = '';
          renderRightForm();
          const opened = openTpl ? E.form.querySelector('.rm-tpl.open') : null;
          if (opened) opened.scrollIntoView({ block: 'start' }); // 단추까지 보이게 카드를 위로
          const first = opened ? opened.querySelector('.rm-input') : null;
          if (first) first.focus({ preventScroll: true });
        },
      }, h('span', { class: 'rm-tpl-text' }, h('b', { text: tpl.title }), h('span', { text: plain(tpl.hint), title: plain(tpl.hint) })), ico('chevron', 'rm-ico rm-chev'));
      const card = h('div', { class: `rm-tpl${open ? ' open' : ''}`, 'data-tpl': tpl.id }, head);
      if (!open) return card;
      const draft = draftFor(tpl);
      const fields = (tpl.fields || []).map((f) => fieldEl(tpl, f, draft));
      const err = h('p', { class: 'rm-err', role: 'alert', hidden: !sendError, text: sendError });
      const go = h('button', {
        type: 'button', class: 'rm-go', 'data-fk': `go:${tpl.id}`, disabled: sending || stopped,
        onclick: () => send(tpl),
      }, ico('pencil'), h('span', { text: sending ? '보내는 중…' : '일 맡기기' }));
      card.append(h('div', { class: 'rm-tpl-body', id: bodyId },
        ...fields,
        h('p', { class: 'rm-notice', text: TEMPLATE_NOTICE }),
        stopped ? h('p', { class: 'rm-note caution', text: '긴급 정지 중이에요. 다시 시작하면 일을 맡길 수 있어요.' }) : null,
        err, go));
      return card;
    }

    function fieldEl(tpl, f, draft) {
      const id = `rm-f-${mode}-${tpl.id}-${f.key}`;
      const max = f.max || 600;
      const long = max > 60;
      const props = {
        class: `rm-input${long ? ' rm-area' : ''}`, id, maxlength: String(max), placeholder: f.placeholder || '', autocomplete: 'off', spellcheck: 'false', 'data-fk': id,
        'aria-describedby': `${id}-n`, 'aria-required': f.required ? 'true' : null, 'aria-invalid': sendField === f.key ? 'true' : null,
      };
      if (long) props.rows = max >= 1000 ? '5' : '3';
      else props.type = 'text';
      const input = h(long ? 'textarea' : 'input', props);
      input.value = draft[f.key] ?? '';
      const count = h('span', { class: 'rm-count', id: `${id}-n`, text: long ? `${chars(input.value).length} / ${max}` : '' });
      input.addEventListener('input', () => {
        draft[f.key] = input.value;
        if (long) count.textContent = `${chars(input.value).length} / ${max}`;
        if (sendField === f.key) { sendField = ''; sendError = ''; input.removeAttribute('aria-invalid'); const e = E.form.querySelector('.rm-err'); if (e) { e.hidden = true; e.textContent = ''; } sig.form = formSig(); }
      });
      return h('div', { class: 'rm-field' },
        h('label', { class: 'rm-label', for: id }, h('span', { text: f.label }), f.required ? h('span', { class: 'rm-req', text: '필수' }) : h('span', { class: 'rm-opt', text: '선택' })),
        input, long ? count : null);
    }

    async function send(tpl) {
      if (sending || !key) return; // 한 번 누르면 한 번만
      const draft = draftFor(tpl);
      const check = checkFields(tpl, draft);
      if (!check.ok) {
        sendError = check.message;
        sendField = check.key;
        renderRightForm();
        const el = E.form.querySelector(`#rm-f-${mode}-${tpl.id}-${check.key}`);
        if (el) el.focus();
        return;
      }
      sending = true;
      sendError = '';
      sendField = '';
      renderRightForm();
      try {
        const res = await Data.startMode({ project: key, template: tpl.id, values: valuesOf(tpl, draft) });
        sent = { task: res && res.task, project: key, title: tpl.title };
        drafts[`${key}|${tpl.id}`] = defaultsOf(tpl);
        H.notify('기획을 시작했어요 — 진행판에서 확인해 주세요');
      } catch (e) {
        sendError = e.message || String(e);
      } finally {
        sending = false;
        renderRightForm();
        renderRightTasks();
      }
    }

    function sentBox() {
      const who = H.producerName();
      return h('div', { class: 'rm-sentbox', role: 'status' },
        h('span', { class: 'rm-sent-ico' }, ico('check')),
        h('div', { class: 'rm-sent-text' },
          h('b', { text: `${who}${josa(who)} 기획을 시작했어요 — 진행판에서 확인해 주세요` }),
          h('span', { text: `${sent.title}${sent.task ? ` · ${sent.task}` : ''}` })),
        h('button', { type: 'button', class: 'rm-pill dark', 'data-fk': 'goboard', onclick: () => H.goBoard(sent ? sent.project : key) }, ico('board'), h('span', { text: '진행판에서 보기' })));
    }

    // ---- 오른쪽 아래: 이 프로젝트의 일
    function renderRightTasks() {
      E.tasks.hidden = !key || !Data.loaded; // 프로젝트가 없으면 이 칸은 숨긴다
      const all = Data.get().tasks || [];
      const rows = key ? recentTasks(all, key) : [];
      const sigv = JSON.stringify([Data.loaded, key, rows.map((t) => [t.id, t.status, t.title, t.kind, t.needs_plan_input, t.created_at]), Data.projectKind(key), ago(rows[0] && rows[0].created_at)]);
      if (sigv === sig.tasks) return;
      sig.tasks = sigv;
      keepFocus(E.tasks, () => {
        const now = Date.now();
        E.tasks.replaceChildren(
          h('h3', {}, h('span', { text: '이 프로젝트의 일' }), rows.length ? h('b', { class: 'rm-cnt', text: String(rows.length) }) : null),
          !key ? h('p', { class: 'rm-note', text: `${M.obj} 고르면 맡긴 일이 여기에 보여요.` })
            : !rows.length ? h('p', { class: 'rm-note', text: '아직 맡긴 일이 없어요. 위 시작 버튼으로 맡겨 보세요.' })
              : h('ul', { class: 'rm-tasklist' }, rows.map((t) => {
                const st = statusKey(t.status);
                const owner = Data.owner(t);
                return h('li', {}, h('button', {
                  type: 'button', class: 'rm-task', 'data-id': t.id, 'data-fk': `t:${t.id}`, 'aria-label': `${t.title}, ${Data.statusLabel(t)}, ${owner.name}`, onclick: () => H.openTask(t.id),
                },
                h('span', { class: 'rm-task-top' },
                  h('span', { class: 'rm-kind', text: Data.kindLabel(t) }),
                  h('span', { class: `rm-state ${st}` }, h('i', { class: `rm-dot ${st}`, 'aria-hidden': 'true' }), h('span', { text: Data.statusLabel(t) }))),
                h('b', { class: 'rm-task-title', text: t.title, title: t.title }),
                h('span', { class: 'rm-task-who' }, Popups.face(owner.id, t.status === 'blocked' ? 'worried' : 'normal', 'rm-face'), h('span', { text: `${owner.name} · ${ago(t.created_at, now) || t.id}` }))));
              })));
      });
    }

    // ---------------------------------------------------------------- 새 작품·새 디자인 프로젝트 만들기 창
    function openNewDialog() {
      const taken = (Data.get().projects || []).map((p) => p.key);
      const S = { title: '', key: suggestKey(mode, taken), desc: '', busy: false, error: '', errorAt: '', el: null };
      const R = {};
      const sync = () => {
        if (!R.go) return;
        R.go.disabled = S.busy;
        R.goText.textContent = S.busy ? '만드는 중…' : '만들기';
        R.cancel.disabled = S.busy;
        R.err.hidden = !S.error;
        R.err.textContent = S.error;
        for (const [k, el] of Object.entries({ title: R.title, key: R.key, desc: R.desc })) {
          if (S.error && S.errorAt === k) el.setAttribute('aria-invalid', 'true'); else el.removeAttribute('aria-invalid');
        }
      };
      const bad = (at, message) => { S.error = message; S.errorAt = at; sync(); (at === 'title' ? R.title : at === 'key' ? R.key : R.desc).focus(); };
      async function submit() {
        if (S.busy) return;
        const live = (Data.get().projects || []).map((p) => p.key);
        const problem = [['title', titleProblem(S.title, M.noun)], ['key', keyProblem(S.key, live)], ['desc', descProblem(S.desc)]].find(([, m]) => m);
        if (problem) { bad(problem[0], problem[1]); return; }
        S.busy = true;
        S.error = '';
        sync();
        try {
          const body = { key: S.key.trim(), title: S.title.trim(), kind: mode, description: S.desc.trim() };
          const res = await Data.createProject(body);
          const made = (res && res.project) || body.key;
          if (S.el && S.el.isConnected) Popups.close();
          pick(made);
          Data.setProject(made);
          H.notify(`‘${body.title}’ ${M.obj} 만들었어요. 오른쪽 시작 버튼으로 일을 맡겨 보세요.`);
        } catch (e) {
          S.error = e.message || String(e);
          S.errorAt = '';
        } finally {
          S.busy = false;
          sync();
        }
      }
      const buildDlg = () => {
        R.err = h('p', { class: 'rm-err', role: 'alert', hidden: true });
        const edited = () => { if (S.error) { S.error = ''; S.errorAt = ''; sync(); } }; // 글을 고치면 옛 오류 글은 지운다
        R.title = h('input', { type: 'text', class: 'rm-input', id: 'rm-new-title', maxlength: '80', autocomplete: 'off', spellcheck: 'false', autofocus: true, 'data-focus-key': 'title', placeholder: mode === 'novel' ? '예: 비 오는 날의 서점' : '예: 동네 카페 메뉴판 디자인',
          oninput: (e) => { S.title = e.target.value; edited(); } });
        R.title.value = S.title;
        R.key = h('input', { type: 'text', class: 'rm-input mono', id: 'rm-new-key', maxlength: '40', autocomplete: 'off', spellcheck: 'false', 'data-focus-key': 'key', 'aria-describedby': 'rm-new-key-help',
          oninput: (e) => { S.key = e.target.value; edited(); } });
        R.key.value = S.key;
        R.desc = h('textarea', { class: 'rm-input rm-area', id: 'rm-new-desc', rows: '3', maxlength: '1000', spellcheck: 'false', 'data-focus-key': 'desc', placeholder: '이 프로젝트가 무엇인지 한두 문장으로 적어 주세요 (비워도 돼요).',
          oninput: (e) => { S.desc = e.target.value; edited(); } });
        R.desc.value = S.desc;
        R.goText = h('span');
        R.go = h('button', { type: 'button', class: 'btn primary', 'data-focus-key': 'go', onclick: submit }, R.goText);
        R.cancel = h('button', { type: 'button', class: 'btn', onclick: () => Popups.close() }, '취소');
        const box = h('div', { class: 'pop paper rm-dlg', role: 'dialog', 'aria-modal': 'true', 'aria-label': M.newLabel },
          h('button', { type: 'button', class: 'x-btn', 'aria-label': '닫기', onclick: () => Popups.close() }, Popups.icon('x')),
          h('h2', { text: M.newLabel }),
          h('p', { class: 'rm-plain', text: `새 Git 저장소가 projects 폴더에 만들어지고 기본 뼈대 파일이 들어가요. ${folderText(mode, modesInfo)}` }),
          h('div', { class: 'rm-field' }, h('label', { class: 'rm-label', for: 'rm-new-title' }, h('span', { text: `${M.noun} 이름` }), h('span', { class: 'rm-req', text: '필수' })), R.title),
          h('div', { class: 'rm-field' }, h('label', { class: 'rm-label', for: 'rm-new-key' }, h('span', { text: '프로젝트 ID' }), h('span', { class: 'rm-req', text: '필수' })), R.key,
            h('span', { class: 'rm-help', id: 'rm-new-key-help', text: '소문자 영문으로 시작하고 영문·숫자·-만 쓸 수 있어요 (40자까지). 만든 뒤에는 바꿀 수 없어요.' })),
          h('div', { class: 'rm-field' }, h('label', { class: 'rm-label', for: 'rm-new-desc' }, h('span', { text: '한 줄 설명' }), h('span', { class: 'rm-opt', text: '선택' })), R.desc),
          R.err,
          h('div', { class: 'rm-dlg-btns' }, R.cancel, R.go));
        S.el = box;
        sync();
        return box;
      };
      Popups.open(buildDlg, { keep: true });
    }

    return { init, setVisible, render, select: (k) => { if (k && k !== key) pick(k); }, mode };
  }

  return { create, logic };
})();

if (typeof module !== 'undefined') module.exports = Rooms; // tools/dev/rooms_sim.js (node)
