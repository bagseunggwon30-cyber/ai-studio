/* AI 스튜디오 — 진행판 (칸반 보드 + 진행 발표 캐릭터)
 *
 * 모던 화면의 껍데기(왼쪽 메뉴 + 가운데 구역: 홈 · 진행판 · 이미지·영상 작업대). 모두 같은 Data(/api/state)를 쓴다.
 * 가운데: 작업을 단계별 칸(대기 → 작업 중 → 검사·리뷰 → 결재 대기 → 완료)에 놓는다. 칸을 옮기는 것은 엔진뿐이다
 *   (끌어서 옮기기 없음: 상태는 Store.transition, 완료는 CEO 승인으로만 — AGENTS.md 불변식 4).
 * 오른쪽: 발표 캐릭터가 보드판을 들고 있다가, 작업이 다음 단계로 넘어가면 판을 뒤집어 알린다.
 * 숫자는 모두 실제 작업 상태로 센다 (지어낸 퍼센트 없음). 글자는 textContent로만 넣는다 (작업 제목은 에이전트가 만든 글).
 * 캐릭터 그림은 파일만 바꿔 끼운다: data/assets/mascot/mascot.json이 있으면 그것, 없으면 ui/assets/mascot/mascot.json
 *   (규격은 docs/design/mascot.md).
 * 캐릭터 설정에 뼈대(rig)가 있으면 그림 한 장을 그물로 휘어 움직이는 인형 엔진(ui/puppet.js, WebGL)이 그린다. 없거나 못 쓰면 예전 CSS 움직임.
 * 순수 계산(columns·groups·headline·attention·widths·changes·cleanMascot)은 DOM 없이 돈다 — tools/dev/board_sim.js가 확인한다.
 * 디자인 규칙(토큰·글자 크기·칸·카드·요약 줄·메뉴)은 docs/design/board-design.md, 스타일은 board.css의 --bd-* 토큰.
 * 개발용 주소 #boarddemo=states|calm|long|empty 는 가짜 작업 목록으로 여러 상태를 보여 준다 (캡처용, 서버에 아무것도 보내지 않는다).
 */
'use strict';

const Board = (() => {
  // ---------------------------------------------------------------- 순수 계산
  const COLUMNS = [
    { key: 'waiting', label: '대기', statuses: ['queued', 'ready'] },
    { key: 'running', label: '작업 중', statuses: ['running', 'blocked'] },
    { key: 'checking', label: '검사·리뷰', statuses: ['checking'] },
    { key: 'awaiting', label: '결재 대기', statuses: ['awaiting_approval'] },
    { key: 'done', label: '완료', statuses: ['done'] },
  ];
  const STAGE = { queued: 0, ready: 0, running: 1, blocked: 1, checking: 2, awaiting_approval: 3, done: 4 };
  const STAGE_NAMES = ['대기', '작업', '검사', '결재', '완료'];
  const STATUS_SHORT = {
    queued: '기획 대기', ready: '준비', running: '작업 중', checking: '검사·리뷰', awaiting_approval: '결재 대기', done: '완료', blocked: '막힘',
  };
  const DONE_SHOWN = 5; // 완료 칸은 최근 5개만 보통 카드로 (나머지는 '더 보기 · 업무 일지')
  const GROUPS_SHOWN = 4;
  const LIST_DONE = 60; // 목록 보기에서 보이는 끝난 일 수
  // 칸 너비 비율: 카드가 없는 칸은 좁게, 있는 칸은 1, 결재 대기·완료는 조금 넓게
  const WIDTH_EMPTY = 0.7; // 좁아도 '검사·리뷰' 같은 칸 제목이 잘리지 않는 너비
  const WIDTH_NORMAL = 1;
  const WIDTH_WIDE = 1.15;
  // 빈 칸 안내: 칸마다 다른 짧은 말
  const EMPTY_TEXT = {
    waiting: '시작을 기다리는 일이 없어요',
    running: '지금 일하는 직원이 없어요',
    checking: '검사 중인 일이 없어요',
    awaiting: '결재할 일이 없어요',
    done: '아직 끝난 일이 없어요',
  };

  const shown = (t) => t.status !== 'cancelled' && !t.archived;
  const newer = (a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || ''));
  const older = (a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')) || String(a.id).localeCompare(String(b.id));

  // 보기(저장된 거름): 열린 일(안 끝난 것) 안에서 거른다. all은 전부.
  const VIEWS = [
    { key: 'all', label: '전체' },
    { key: 'approval', label: '결재 기다림' },
    { key: 'blocked', label: '막힘' },
    { key: 'old', label: '3일 넘은 일' },
  ];
  const OLD_DAYS = 3;

  // 만든 지 며칠 됐는지 (모르면 0)
  function ageDays(t, now = Date.now()) {
    const at = Date.parse(t.created_at || '');
    return Number.isFinite(at) ? Math.max(0, Math.floor((now - at) / 86400000)) : 0;
  }

  function inView(t, key, now = Date.now()) {
    if (key === 'approval') return t.status === 'awaiting_approval';
    if (key === 'blocked') return t.status === 'blocked';
    if (key === 'old') return t.status !== 'done' && ageDays(t, now) >= OLD_DAYS;
    return true;
  }

  // 보기마다 몇 개인지: 프로젝트 거름 안의 열린 일만 센다 (전체 = 열린 일 수)
  function viewCounts(tasks, project = null, now = Date.now()) {
    const open = tasks.filter(shown).filter((t) => t.status !== 'done' && (!project || t.project === project));
    const out = {};
    for (const v of VIEWS) out[v.key] = open.filter((t) => inView(t, v.key, now)).length;
    return out;
  }

  // 찾기: 제목·번호·종류·프로젝트·(extraOf가 주는) 담당 이름에 글자가 들어 있으면. 띄어쓰기로 나눈 낱말이 모두 있어야 한다 (대소문자 무시)
  function matches(t, query, extraOf = null) {
    const words = String(query || '').toLowerCase().split(' ').filter(Boolean);
    if (!words.length) return true;
    const hay = [t.id, t.title, t.kind, t.project, extraOf ? extraOf(t) : ''].map((x) => String(x || '').toLowerCase()).join(' ');
    return words.every((w) => hay.includes(w));
  }

  // 칸마다 작업 목록. project가 있으면 그 프로젝트만, view(보기)·query(찾기)에 맞는 것만. 완료 칸의 기획 카드는 빼고(퀘스트로 나뉘었으니) 최근 doneLimit개만.
  // group이면 칸 안에서 프로젝트별로 모은다 (프로젝트 안의 차례는 그대로).
  function columns(tasks, project = null, o = {}) {
    const { query = '', extraOf = null, view = 'all', now = Date.now(), doneLimit = DONE_SHOWN, group = false } = o;
    const live = tasks.filter(shown).filter((t) => !project || t.project === project)
      .filter((t) => inView(t, view, now)).filter((t) => matches(t, query, extraOf));
    return COLUMNS.map((c) => {
      let list = live.filter((t) => c.statuses.includes(t.status));
      if (c.key === 'done') list = list.filter((t) => t.kind !== 'plan');
      const total = list.length;
      if (c.key === 'done') list = list.sort(newer).slice(0, doneLimit);
      else if (c.key === 'running') list = list.sort((a, b) => (b.status === 'blocked') - (a.status === 'blocked') || older(a, b));
      else list = list.sort(older);
      if (group) list = list.map((t, i) => ({ t, i })).sort((a, b) => String(a.t.project || '').localeCompare(String(b.t.project || '')) || a.i - b.i).map((x) => x.t);
      return { key: c.key, label: c.label, tasks: list, total };
    });
  }

  // 아직 안 끝난 일 중 가장 오래된 것이 며칠 됐는지 (만든 날 기준, 일이 없으면 0)
  function oldestDays(tasks, now = Date.now()) {
    let first = null;
    for (const t of tasks.filter(shown)) {
      if (t.status === 'done') continue;
      const at = Date.parse(t.created_at || '');
      if (Number.isFinite(at) && (first === null || at < first)) first = at;
    }
    return first === null ? 0 : Math.max(0, Math.floor((now - first) / 86400000));
  }

  // 얼마 전인지 (방금 · N분 전 · N시간 전 · N일 전). 시각을 모르면 빈 글
  function ago(iso, now = Date.now()) {
    const at = Date.parse(iso || '');
    if (!Number.isFinite(at)) return '';
    const m = Math.floor((now - at) / 60000);
    if (m < 1) return '방금';
    if (m < 60) return `${m}분 전`;
    const hr = Math.floor(m / 60);
    return hr < 24 ? `${hr}시간 전` : `${Math.floor(hr / 24)}일 전`;
  }

  // 표 파일(CSV): 쉼표·따옴표·줄바꿈이 든 칸은 따옴표로 감싼다 (줄 끝은 CR LF)
  function toCsv(rows) {
    const NL = String.fromCharCode(10);
    const CR = String.fromCharCode(13);
    const cell = (v) => {
      const t = String(v ?? '');
      return t.includes(',') || t.includes('"') || t.includes(NL) || t.includes(CR) ? `"${t.split('"').join('""')}"` : t;
    };
    return rows.map((r) => r.map(cell).join(',')).join(CR + NL);
  }

  // 지시(기획 카드)마다 나온 퀘스트 중 끝난 수. 기획에서 나오지 않은 일은 '따로 맡긴 일' 한 줄로.
  function groups(tasks) {
    const live = tasks.filter(shown);
    const plans = live.filter((t) => t.kind === 'plan').sort((a, b) => -older(a, b));
    const out = [];
    const used = new Set();
    for (const p of plans) {
      const kids = live.filter((t) => t.parent === p.id && t.kind !== 'plan');
      if (!kids.length) continue;
      used.add(p.id);
      out.push(group(p.id, p.title, kids));
    }
    const loose = live.filter((t) => t.kind !== 'plan' && !used.has(t.parent));
    if (loose.length) out.push(group('loose', '따로 맡긴 일', loose));
    return out;
  }

  function group(key, title, list) {
    const done = list.filter((t) => t.status === 'done').length;
    return {
      key, title, done, total: list.length, pct: Math.round((done / list.length) * 100),
      blocked: list.filter((t) => t.status === 'blocked').length,
      waiting: list.filter((t) => t.status === 'awaiting_approval').length,
    };
  }

  // 보드판 앞면: 아직 안 끝난 가장 최근 지시 → 없으면 가장 최근 지시 → 일이 없으면 null
  function headline(tasks) {
    const list = groups(tasks);
    return list.find((g) => g.done < g.total) || list[0] || null;
  }

  // 지난번 상태(Map id→status)와 비교해 단계가 바뀐 작업. prev가 null이면 처음 읽은 것이라 알리지 않는다.
  function changes(prev, tasks) {
    if (!prev) return [];
    const out = [];
    for (const t of tasks) {
      const before = prev.get(t.id);
      if (before === t.status || !shown(t)) continue;
      out.push({ task: t, from: before === undefined ? null : before, to: t.status });
    }
    return out;
  }

  function snapshot(tasks) { return new Map(tasks.map((t) => [t.id, t.status])); }

  // 한눈 요약 (CEO가 제일 먼저 알 것): 결재 기다림 · 막힘 · 일하는 중. 전부 실제 작업 상태로만 센다.
  // inboxCount는 결재함 개수(Data.inbox) — 없으면 작업 상태로 센다. 일하는 중 = 작업 중 + 검사·리뷰 중 (막힘은 따로).
  // firstBlocked = 작업 중 칸 맨 위(가장 오래된) 막힌 작업의 번호. 셋 다 0이면 idle.
  function attention(tasks, inboxCount = null) {
    const live = tasks.filter(shown);
    const blocked = live.filter((t) => t.status === 'blocked').sort(older);
    const working = live.filter((t) => t.status === 'running' || t.status === 'checking').length;
    const approvals = Number.isFinite(inboxCount) ? inboxCount : live.filter((t) => t.status === 'awaiting_approval').length;
    return {
      approvals, blocked: blocked.length, working,
      firstBlocked: blocked.length ? blocked[0].id : null,
      idle: approvals === 0 && blocked.length === 0 && working === 0,
    };
  }

  // 칸 너비 비율 (columns()의 결과 순서대로)
  function widths(cols) {
    return cols.map((c) => (!c.tasks.length ? WIDTH_EMPTY : c.key === 'awaiting' || c.key === 'done' ? WIDTH_WIDE : WIDTH_NORMAL));
  }

  // 카드의 단계 색 이름: 막힘은 빨강, 나머지는 있는 칸의 이름
  function stageKey(status) {
    if (status === 'blocked') return 'blocked';
    const col = COLUMNS.find((c) => c.statuses.includes(status));
    return col ? col.key : 'waiting';
  }

  // 캐릭터 설정 검사 (사장님이 넣는 파일이라 믿지 않는다): 그림은 같은 폴더의 png 이름만, 숫자는 상자 안으로.
  const IMAGE_RE = /^[A-Za-z0-9_@.-]{1,80}\.png$/;
  const num = (v, lo, hi) => (typeof v === 'number' && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : null);

  // 판 자리: 상자 안으로 자르고, 너무 작으면(60 미만) 못 쓴다
  function cleanRect(b, bw, bh) {
    if (!b || typeof b !== 'object') return null;
    const r = { x: num(b.x, 0, bw), y: num(b.y, 0, bh), w: num(b.w, 60, bw), h: num(b.h, 60, bh) };
    if ([r.x, r.y, r.w, r.h].includes(null)) return null;
    r.w = Math.min(r.w, bw - r.x);
    r.h = Math.min(r.h, bh - r.y);
    return r.w < 60 || r.h < 60 ? null : r;
  }

  function cleanMascot(raw, base) {
    if (!raw || typeof raw !== 'object' || raw.version !== 1) return null;
    const bw = num((raw.box || {}).w, 120, 900);
    const bh = num((raw.box || {}).h, 120, 1200);
    if (bw === null || bh === null) return null;
    const rect = cleanRect(raw.board, bw, bh);
    if (!rect) return null;
    // stand = 판 밑 받침 ('pole' 가운데 기둥, 'easel'·true 이젤 다리), frame = 테두리 (false면 종이만: 손에 든 판의 흰 종이 자리에 겹칠 때),
    // behind = 판을 캐릭터 뒤에 (기상 캐스터처럼 캐릭터가 판 앞에 서서 가리킬 때)
    const st = raw.board.stand;
    const stand = st === 'pole' ? 'pole' : st === true || st === 'easel' ? 'easel' : null;
    const board = { ...rect, stand, frame: raw.board.frame !== false, behind: raw.board.behind === true };
    const moods = {};
    for (const [name, m] of Object.entries(raw.moods || {})) {
      if (!['normal', 'happy', 'worried'].includes(name) || !m || !IMAGE_RE.test(String(m.image || ''))) continue;
      const h = num(m.h, 20, bh);
      if (h === null) continue;
      // 표정마다 판 자리가 조금 다르면 그 표정의 board (없거나 틀리면 공통 board)
      moods[name] = { src: base + m.image, x: num(m.x, -bw, bw) ?? 0, y: num(m.y, -bh, bh) ?? 0, h, board: cleanRect(m.board, bw, bh) || rect };
    }
    if (!moods.normal) return null;
    moods.happy = moods.happy || moods.normal;
    moods.worried = moods.worried || moods.normal;
    // 애니메이션 (없어도 된다): blink = 평소 그림 위에 잠깐 겹치는 '눈 감은 조각' (상자 기준 자리·높이),
    // point = 판이 돌 때 잠깐 바꾸는 손짓 전신 그림 (표정 그림과 같은 자리 규칙)
    const anim = {};
    for (const key of ['blink', 'point', 'chest']) {
      const a = (raw.anim || {})[key];
      if (!a || !IMAGE_RE.test(String(a.image || ''))) continue;
      const h = num(a.h, 4, bh);
      if (h !== null) anim[key] = { src: base + a.image, x: num(a.x, -bw, bw) ?? 0, y: num(a.y, -bh, bh) ?? 0, h };
    }
    if (anim.blink && raw.anim.blink.eyesOnly === true) anim.blink.eyesOnly = true;
    const name = typeof raw.name === 'string' ? raw.name.trim().slice(0, 12) : '';
    // 뼈대(rig, 없어도 된다): 검사에서 걸리면 rig 없이(예전 CSS 움직임) 쓰고 rigBad로 알린다 (docs/design/mascot.md '뼈대')
    let rig = null;
    let rigBad = false;
    if (raw.rig !== undefined && puppetLib()) {
      rig = puppetLib().logic.cleanRig(raw.rig, moods.normal, { base, blink: anim.blink });
      rigBad = !rig;
    }
    return { name: name || '진행 요원', box: { w: bw, h: bh }, board, moods, anim, rig, rigBad };
  }

  // 인형 엔진(puppet.js)은 브라우저에서는 먼저 읽힌 전역, node(board_sim)에서는 없을 수도 있다
  function puppetLib() { return typeof Puppet !== 'undefined' ? Puppet : null; }

  // 알릴 때 캐릭터 표정: 결재 올림·완료는 기쁨, 막힘은 걱정
  function moodFor(to) {
    if (to === 'done' || to === 'awaiting_approval') return 'happy';
    if (to === 'blocked') return 'worried';
    return 'normal';
  }

  // 개발용 가짜 작업 (#boarddemo=states|calm|long|empty): 여러 상태가 한 화면에 보이게. 실제 작업이 아니다 — 캡처·화면 확인 전용.
  // 스킬 딱지(★)는 실제 회사에 있는 스킬 이름(godot-scene-wiring)을 쓴다.
  const DEMO_ROLE = { plan: 'producer', build: 'builder', research: 'analyst', skill: 'reviewer' };
  const DEMO_NAMES = ['states', 'calm', 'long', 'empty'];

  function demoTasks(name, projects = []) {
    if (!DEMO_NAMES.includes(name) || name === 'empty') return [];
    const a = (projects[0] || {}).key || 'core-courier';
    const b = (projects[1] || {}).key || a;
    const T = (id, status, kind, title, extra = {}) => ({
      id, status, kind, title, project: a, role: DEMO_ROLE[kind], attempts: 1, depends_on: [], parent: null,
      created_at: `2026-09-30T09:${id.slice(-2)}:00`, updated_at: `2026-09-30T10:${id.slice(-2)}:00`, archived: false,
      blocked_reason: null, waiting: null, qa: null, review: null, usage: { runs: 2, minutes: 5.5, skills: [], applied: [], told: true }, ...extra,
    });
    const pass = { qa: { verdict: 'pass', passed: 8, total: 8 }, review: { verdict: 'approve' } };
    const skill = { usage: { runs: 3, minutes: 20.2, skills: ['godot-scene-wiring'], applied: ['godot-scene-wiring'], told: true } };
    if (name === 'calm') {
      return [
        T('D01', 'done', 'plan', '코어 쿠리어 4단계를 기획해 줘'),
        T('D02', 'done', 'build', '체력 표시와 남은 시간을 화면에 넣기', { parent: 'D01', ...pass }),
        T('D03', 'done', 'build', 'Esc로 일시정지하고 다시 시작하기', { parent: 'D01', ...pass, ...skill }),
        T('D04', 'done', 'research', 'Steam 스토어 등록 절차 보고서', { project: b, ...pass }),
      ];
    }
    if (name === 'long') {
      const longWord = 'Superlongfilenamewithoutanyspaces_export_presets.cfg_와_project.godot_설정_확인';
      return [
        T('D01', 'ready', 'build', `${longWord} 를 고쳐서 윈도우용 내보내기 설정을 완전히 새로 만들고 실행 파일 이름과 아이콘까지 한꺼번에 정리하기`),
        T('D02', 'blocked', 'build', '아주 긴 제목의 막힌 일: 내보내기 도구가 없어서 게임을 윈도우용 실행 파일로 만들 수 없는 상태를 확인하기', {
          project: b, attempts: 3, blocked_reason: '내보내기 도구(export templates)를 이 컴퓨터에서 찾지 못했어요. 도구를 내려받아도 되는지 사장님이 정해 주세요. 정하기 전에는 이 일을 더 할 수 없어요.',
        }),
        T('D03', 'awaiting_approval', 'research', '웹 게임 내보내기와 윈도우 내보내기의 차이를 비교한 아주 긴 이름의 조사 보고서', { project: b, ...pass, ...skill }),
        T('D04', 'done', 'build', longWord, { ...pass }),
      ];
    }
    // states: 다섯 칸 모두 차 있고, 막힘·결재·스킬·검사 딱지가 다 보인다. 완료는 7개(그중 5개만 카드)
    return [
      T('D01', 'done', 'plan', '코어 쿠리어 5단계를 기획해 줘: 윈도우로 내보내기와 스크린샷'),
      T('D02', 'done', 'build', '윈도우용으로 내보내기 설정 만들기', { parent: 'D01', ...pass }),
      T('D03', 'blocked', 'build', '게임 아이콘과 실행 파일 이름 정하기', { parent: 'D01', attempts: 2, blocked_reason: '내보내기 도구를 찾지 못했어요. 도구를 깔아도 되는지 알려 주세요.' }),
      T('D04', 'running', 'build', '스크린샷을 저장하는 단추와 저장 폴더 안내를 화면에 넣기', { parent: 'D01', ...skill, usage: { runs: 1, minutes: 3, skills: ['godot-scene-wiring'], applied: [], told: false } }),
      T('D05', 'checking', 'research', 'Steam 스토어 페이지에 필요한 그림 크기 정리', { parent: 'D01', project: b, qa: { verdict: 'pass', passed: 6, total: 6 } }),
      T('D06', 'awaiting_approval', 'build', '결과 화면에 다시 하기 단추 넣기', { parent: 'D01', ...pass, ...skill }),
      T('D07', 'awaiting_approval', 'research', 'Steam 스토어 등록 절차 보고서', { project: b, qa: { verdict: 'pass', passed: 6, total: 6 }, review: { verdict: 'approve' } }),
      T('D08', 'ready', 'build', '타이틀 화면 만들기'),
      T('D09', 'queued', 'plan', '다음 단계를 기획해 줘', { waiting: '앞의 일이 끝나기를 기다려요' }),
      T('D10', 'done', 'plan', '코어 쿠리어 4단계를 기획해 줘: 화면에 남은 시간과 체력'),
      T('D11', 'done', 'build', '체력과 남은 시간 표시', { parent: 'D10', ...pass }),
      T('D12', 'done', 'build', 'Esc 일시정지', { parent: 'D10', ...pass, ...skill }),
      T('D13', 'done', 'build', '적 접촉 피격과 무적 시간', { parent: 'D10', ...pass }),
      T('D14', 'done', 'build', '승패 결과와 재시작 흐름 연결', { parent: 'D10', ...pass }),
      T('D15', 'done', 'research', 'Godot 4에서 윈도우 내보내기 조사', { project: b, ...pass }),
      T('D16', 'done', 'research', '회고: 플레이어 이동 씬 정리', { project: b, ...pass }),
    ];
  }

  // 개발용 가짜 '지금 일하는 직원' (states만 일하는 중, 나머지는 쉬는 중)
  function demoCurrent(name) {
    return name === 'states' ? { task: 'D04', role: 'builder', title: '스크린샷 저장 단추 넣기' } : null;
  }

  const logic = { COLUMNS, STAGE, DONE_SHOWN, EMPTY_TEXT, VIEWS, OLD_DAYS, ageDays, inView, viewCounts, ago, toCsv, matches, oldestDays, columns, groups, headline, changes, snapshot, attention, widths, stageKey, cleanMascot, moodFor, demoTasks, demoCurrent };

  // ---------------------------------------------------------------- 화면 (init 뒤에만 DOM을 만진다)
  // CEO 결정 2026-10-05: 맨 오른쪽 발표 캐릭터 판은 쓰지 않는다. true로 바꾸면 예전처럼 오른쪽에 붙고 캐릭터가 움직인다 (그림·코드는 그대로).
  const PRESENTER = false;
  const FLOW_SHOWN = 3; // 지시별 진행 줄에 보이는 지시 수
  const SHOW_MS = 4200; // 뒤집은 판을 보여 주는 시간
  const QUEUE_MAX = 6;
  const TALK_MS = 1800; // 판이 돌아 알릴 때 인형이 말하는(입을 여닫는) 시간
  const MASCOT_W = 396; // 오른쪽 칸 안쪽 넓이 (board.css .bd-side)
  const PUPPET_PAD = 8; // 인형 캔버스를 상자 둘레로 넓히는 여유(상자 좌표): 오른쪽 끝의 머리카락이 흔들려도 잘리지 않게

  // 개발용 주소 #boarddemo=states|calm|long|empty: 가짜 작업으로 여러 상태를 보여 준다 (node에서는 없음)
  const DEMO = (() => {
    if (typeof location === 'undefined') return null;
    const name = new URLSearchParams(location.hash.slice(1)).get('boarddemo');
    return DEMO_NAMES.includes(name) ? name : null;
  })();

  let root = null;
  let hooks = { notify: () => {}, fail: () => {} };
  let visible = false;
  let dirty = true;
  let prev = null; // 지난번 작업 상태
  let project = null; // 보는 프로젝트 (null = 모두)
  let mascot = null; // { cfg, el, img, card, front, back, fallback }
  let mood = 'normal';
  const queue = [];
  let showing = null; // 지금 뒤집어 보여 주는 알림
  let timer = null;
  let held = false; // #demo=boardflip: 뒤집은 채로 멈춤
  let heldMood = null; // #pose=mood:happy: 그 표정으로 멈춤

  const h = (...a) => Popups.h(...a);

  function init(el, opts = {}) {
    root = el;
    hooks = { ...hooks, ...opts };
    try { project = localStorage.getItem('studio.boardProject') || null; } catch (_) { project = null; }
    // 마지막으로 고른 '묶기'·'보기 방식'은 이 브라우저에 기억한다
    try {
      byProject = localStorage.getItem('studio.boardGroup') === '1';
      mode = localStorage.getItem('studio.boardMode') === 'list' ? 'list' : 'kanban';
    } catch (_) { /* 기억 못 해도 됨 */ }
    // 개발·캡처용 주소: #mode=list|kanban · #group=1 · #boardview=approval|blocked|old (저장하지 않는다)
    const hp = new URLSearchParams(location.hash.slice(1));
    if (hp.get('mode') === 'list' || hp.get('mode') === 'kanban') mode = hp.get('mode');
    if (hp.get('group') === '1') byProject = true;
    if (VIEWS.some((v) => v.key === hp.get('boardview'))) viewKey = hp.get('boardview');
    // 가운데는 뼈대(홈 · 진행판 머리줄·지시별 진행·칸 틀)를 한 번만 만들고 render()가 안을 채운다 (칸 너비가 바뀔 때 부드럽게 넘어가도록 칸 틀은 그대로 둔다)
    const cols = h('div', { class: 'bd-cols' });
    cols.addEventListener('transitionend', (e) => { if (e.target === cols) for (const c of cols.querySelectorAll('.bd-cards')) fade(c); });
    const home = h('section', { class: 'bd-main bd-home', 'aria-label': '홈', hidden: true });
    const media = h('section', { class: 'bd-main bd-page-media', 'aria-label': '이미지·영상 작업대', hidden: true });
    const novel = h('section', { class: 'bd-main bd-page-novel', 'aria-label': '소설 집필실', hidden: true });
    const design = h('section', { class: 'bd-main bd-page-design', 'aria-label': '디자인 작업실', hidden: true });
    root.append(sidebar(), home, media, novel, design, h('section', { class: 'bd-main bd-page-board', 'aria-label': '진행판' },
      h('header', { class: 'bd-head' }), h('div', { class: 'bd-flow', role: 'group', 'aria-label': '지시별 진행' }), cols));
    if (typeof Home !== 'undefined') Home.init(home, homeHelpers());
    if (typeof Media !== 'undefined') Media.init(media, mediaHelpers());
    if (typeof Rooms !== 'undefined') {
      for (const [name, el] of [['novel', novel], ['design', design]]) { rooms[name] = Rooms.create(name); rooms[name].init(el, roomHelpers()); }
    }
    if (PRESENTER) {
      root.classList.add('bd-has-side');
      root.append(side());
      // 인형이 있으면 진행판 위의 포인터를 바라본다 (나가면 제자리로)
      root.addEventListener('pointermove', (e) => { if (mascot && mascot.puppet) mascot.puppet.lookAt(e.clientX, e.clientY); });
      root.addEventListener('pointerleave', () => { if (mascot && mascot.puppet) mascot.puppet.lookAt(null); });
      loadMascot();
    }
  }

  // 홈 화면이 쓰는 도구 (홈은 board.js 안쪽을 직접 만지지 않는다)
  function homeHelpers() {
    return {
      h, viewNow, attention, groups, oldestDays, ago, actionOf, focusCommand, shown, COLUMNS,
      goBoard: (key) => { viewKey = VIEWS.some((v) => v.key === key) ? key : 'all'; query = ''; hooks.setView('board'); },
    };
  }

  // 이미지·영상 작업대 화면이 쓰는 도구
  function mediaHelpers() {
    const producer = () => (Data.BY_ROLE.producer || Data.TEAM[0]).name;
    return {
      h,
      notify: (text) => hooks.notify(producer(), text),
      fail: (err) => hooks.fail(err),
      openTask: (id) => { const t = Data.task(id); if (t) Popups.openTask(t); else Popups.taskCard(id); },
      openWorkbench: () => hooks.setView('workbench'),
    };
  }

  // 소설 집필실·디자인 작업실이 쓰는 도구
  function roomHelpers() {
    const producer = () => Data.BY_ROLE.producer || Data.TEAM[0];
    return {
      h,
      producerName: () => producer().name,
      notify: (text) => hooks.notify(producer().name, text),
      fail: (err) => hooks.fail(err),
      // 결재를 기다리는 일은 결재 창으로, 나머지는 작업 카드로 (진행판 카드와 같다)
      openTask: (id) => { const t = Data.task(id); if (t && t.status === 'awaiting_approval') Popups.openTask(t); else Popups.taskCard(id); },
      // 맡긴 일은 진행판에서 결재한다: 그 프로젝트의 일만 보이게 해서 연다
      goBoard: (key) => { Data.setProject(key); project = key; saveProject(); viewKey = 'all'; query = ''; hooks.setView('board'); },
    };
  }

  // 소설 집필실·디자인 작업실을 열고(프로젝트를 정해서) 보여 준다 (완성작·프로젝트 고르기 창에서)
  function openRoom(mode, key = null) {
    if (!rooms[mode]) return;
    if (key) rooms[mode].select(key);
    hooks.setView(mode);
  }

  // 왼쪽 메뉴의 홈·진행판·이미지·영상 작업대·소설 집필실·디자인 작업실 전환: 모두 같은 껍데기 안의 가운데 구역이다
  function setPage(name) {
    page = SHELL_PAGES.includes(name) ? name : 'board';
    if (!root) return;
    root.querySelector('.bd-home').hidden = page !== 'home';
    root.querySelector('.bd-page-media').hidden = page !== 'media';
    root.querySelector('.bd-page-novel').hidden = page !== 'novel';
    root.querySelector('.bd-page-design').hidden = page !== 'design';
    root.querySelector('.bd-page-board').hidden = page !== 'board';
    for (const b of root.querySelectorAll('.bd-nav-btn')) {
      if (!NAV_PAGES.includes(b.dataset.action)) continue;
      const on = b.dataset.action === page;
      b.classList.toggle('on', on);
      if (on) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    }
    if (typeof Media !== 'undefined') Media.setVisible(visible && page === 'media');
    for (const [name, room] of Object.entries(rooms)) room.setVisible(visible && page === name);
    if (visible) render();
  }

  // ---- 왼쪽 메뉴: app.js의 data-action 동작을 그대로 쓴다. 세 묶음: 작업 | 회사 | 기록 (묶음 제목은 작은 회색 글자)
  // 옛 노드 편집기(workbench)는 메뉴에서 빼고, 이미지·영상 작업대 위쪽의 '노드 편집기 (고급)' 단추로만 연다
  const MENU = [
    ['작업', [['home', '홈'], ['board', '진행판'], ['media', '이미지·영상 작업대'], ['novel', '소설 집필실'], ['design', '디자인 작업실'], ['inbox', '결재함'], ['meeting', '회의실']]],
    ['회사', [['team', '직원'], ['skills', '스킬 학습'], ['mcp', 'MCP 보관소'], ['schedules', '자동 업무'], ['gateway', '외부 연결']]],
    ['기록', [['diary', '업무 일지'], ['trophies', '완성작']]],
  ];

  // 고정 SVG 선 아이콘 (데이터가 아님): 모두 같은 굵기·크기라 한 벌로 보인다 (색은 글자색을 따른다)
  const NAV_SVG = {
    home: '<svg viewBox="0 0 24 24"><path d="M4 11l8-6.5L20 11"/><path d="M6 9.5V19a1 1 0 0 0 1 1h3.5v-5h3v5H17a1 1 0 0 0 1-1V9.5"/></svg>',
    digest: '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="3"/><path d="M4 10h16M9 3.5v3M15 3.5v3"/></svg>',
    board: '<svg viewBox="0 0 24 24"><rect x="3.5" y="4" width="4.5" height="16" rx="1.5"/><rect x="9.75" y="4" width="4.5" height="10" rx="1.5"/><rect x="16" y="4" width="4.5" height="13" rx="1.5"/></svg>',
    workbench: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="7" height="6" rx="1.5"/><rect x="14" y="14" width="7" height="6" rx="1.5"/><path d="M10 7h2.5a2 2 0 0 1 2 2v5"/></svg>',
    media: '<svg viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M10.2 9.3v5.4l4.5-2.7Z"/></svg>',
    novel: '<svg viewBox="0 0 24 24"><path d="M4.5 19.5l1-4L16 5a2.1 2.1 0 0 1 3 3L8.5 18.5Z"/><path d="M14 7l3 3"/></svg>',
    design: '<svg viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M3.5 9.5h17M9.5 9.5v10"/></svg>',
    inbox: '<svg viewBox="0 0 24 24"><path d="M4 13l2.2-7a2 2 0 0 1 1.9-1.4h7.8a2 2 0 0 1 1.9 1.4L20 13"/><path d="M4 13v4.5A1.5 1.5 0 0 0 5.5 19h13a1.5 1.5 0 0 0 1.5-1.5V13h-4.5a1.5 1.5 0 0 0-1.5 1.5 1.5 1.5 0 0 1-1.5 1.5h-1a1.5 1.5 0 0 1-1.5-1.5A1.5 1.5 0 0 0 8.5 13Z"/></svg>',
    meeting: '<svg viewBox="0 0 24 24"><path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-4 3.5V16h-.5A2.5 2.5 0 0 1 4 13.5Z"/></svg>',
    team: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19c.5-3.2 2.9-5 5.5-5s5 1.8 5.5 5"/><circle cx="17" cy="9.5" r="2.5"/><path d="M16 14.2c2.6-.3 4.5 1.2 5 4"/></svg>',
    skills: '<svg viewBox="0 0 24 24"><path d="M12 3.5l2.4 5 5.4.7-4 3.8 1 5.4-4.8-2.6-4.8 2.6 1-5.4-4-3.8 5.4-.7Z"/></svg>',
    mcp: '<svg viewBox="0 0 24 24"><path d="M9.5 14.5l5-5"/><path d="M11 6.8l1.3-1.3a3.5 3.5 0 0 1 5 5L16 11.8"/><path d="M13 17.2l-1.3 1.3a3.5 3.5 0 0 1-5-5L8 12.2"/></svg>',
    schedules: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
    gateway: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.4 3.8 5.2 3.8 8.5s-1.2 6.1-3.8 8.5M12 3.5C9.4 5.9 8.2 8.7 8.2 12s1.2 6.1 3.8 8.5"/></svg>',
    diary: '<svg viewBox="0 0 24 24"><path d="M5 5.5A1.5 1.5 0 0 1 6.5 4H19v14H6.5A1.5 1.5 0 0 0 5 19.5Z"/><path d="M5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3"/></svg>',
    trophies: '<svg viewBox="0 0 24 24"><path d="M8 4h8v5a4 4 0 0 1-8 0Z"/><path d="M8 6H5a2 2 0 0 0 2 4M16 6h3a2 2 0 0 1-2 4"/><path d="M12 13v4M9 20h6M10 17h4"/></svg>',
  };

  function navIcon(name) {
    const el = h('span', { class: 'icon', 'aria-hidden': 'true' });
    el.innerHTML = NAV_SVG[name] || '';
    return el;
  }

  function sidebar() {
    const item = ([action, name]) => h('button', {
      type: 'button', class: `bd-nav-btn ${action === page ? 'on' : ''}`, 'data-action': action,
      'aria-current': action === page ? 'page' : null,
    }, navIcon(action), h('span', { text: name }), action === 'inbox' ? h('b', { class: 'bd-badge', hidden: true }) : null);
    return h('nav', { class: 'bd-nav', 'aria-label': '메뉴' },
      MENU.map(([label, items]) => h('div', { class: 'bd-nav-group', role: 'group', 'aria-label': label },
        h('p', { class: 'bd-nav-label', 'aria-hidden': 'true', text: label }),
        items.map(item))),
      h('div', { class: 'bd-nav-foot' }, item(['digest', '주간 요약'])));
  }

  // ---- 오른쪽: 발표 캐릭터 + 지시별 진행 (PRESENTER가 true일 때만)
  function side() {
    return h('aside', { class: 'bd-side', 'aria-label': '진행 발표' },
      h('h2', { class: 'bd-side-title' }, h('span', { text: '진행 발표' }), h('small', { class: 'bd-mascot-name' })),
      h('div', { class: 'bd-mascot', 'aria-live': 'polite' }),
      h('p', { class: 'bd-now' }),
      h('h3', { class: 'bd-groups-title', text: '지시별 진행' }),
      h('ul', { class: 'bd-groups' }));
  }

  async function loadMascot() {
    let cfg = null;
    let fallback = false;
    for (const base of ['/assets/custom/mascot/', '/assets/mascot/']) {
      try {
        const res = await fetch(`${base}mascot.json`, { cache: 'no-store' });
        if (!res.ok) continue;
        const raw = await res.json();
        const empty = raw && typeof raw === 'object' && !Object.keys(raw).length; // 사장님 그림이 아직 없음
        cfg = cleanMascot(raw, base);
        if (cfg) break;
        if (!empty) fallback = true; // 넣은 설정이 규격에 안 맞아 기본 그림으로
      } catch (_) {
        if (base.includes('custom')) fallback = true;
      }
    }
    if (!cfg) return;
    buildMascot(cfg, fallback);
    render();
  }

  // 뼈대 모드에서 인형이 쓰는 표정 그림 (뼈대의 bases가 있으면 puppet.js가 base에 그것을 대신 쓴다)
  function puppetImages(cfg) {
    return { normal: cfg.moods.normal.src, happy: cfg.moods.happy.src, worried: cfg.moods.worried.src, point: cfg.anim.point ? cfg.anim.point.src : null };
  }

  function buildMascot(cfg, fallback) {
    const box = root.querySelector('.bd-mascot');
    const k = MASCOT_W / cfg.box.w;
    box.style.setProperty('width', `${MASCOT_W}px`);
    box.style.setProperty('height', `${Math.round(cfg.box.h * k)}px`);
    if (mascot && mascot.puppet) mascot.puppet.destroy();
    // 뼈대(rig)가 있고 WebGL을 쓸 수 있으면 캔버스 인형이 상자 전체에 그리고, 아니면 아래의 예전 CSS 방식
    const fig = h('div', { class: 'bd-mascot-fig' });
    const P = puppetLib();
    let puppet = null;
    if (cfg.rig && P && P.supported()) {
      fig.classList.add('rig');
      puppet = P.create(fig, { rig: cfg.rig, box: cfg.box, normal: cfg.moods.normal, images: puppetImages(cfg), pad: PUPPET_PAD }, { reduced: () => Fx.reduced() });
      if (!puppet) fig.classList.remove('rig');
    }
    let img = null;
    let chest = null;
    let blink = null;
    if (!puppet) {
      img = h('img', { class: 'bd-mascot-img', alt: '', draggable: 'false' });
      img.addEventListener('error', () => { img.hidden = true; });
      img.addEventListener('load', () => { img.hidden = false; });
      // 숨쉬기·폴짝·흔들림은 그림과 눈 조각을 함께 담은 틀(fig)이 움직인다 (board.css)
      chest = cfg.anim.chest ? h('img', { class: 'bd-mascot-chest', alt: '', draggable: 'false', src: cfg.anim.chest.src }) : null;
      blink = cfg.anim.blink ? h('img', { class: cfg.anim.blink.eyesOnly ? 'bd-mascot-blink eyes-only' : 'bd-mascot-blink', alt: '', draggable: 'false', src: cfg.anim.blink.src, hidden: true }) : null;
      fig.append(...[img, chest, blink].filter(Boolean));
    }
    const front = h('div', { class: 'bd-face bd-front' });
    const back = h('div', { class: 'bd-face bd-back' });
    const card = h('div', { class: 'bd-card3d' }, front, back);
    const b = cfg.board;
    const board = h('div', { class: ['bd-board', b.stand ? `stand ${b.stand}` : '', b.frame ? '' : 'paper', b.behind ? 'behind' : ''].join(' ').replace(/\s+/g, ' ').trim() },
      card, b.stand ? h('span', { class: 'bd-legs', 'aria-hidden': 'true' }) : null);
    board.style.setProperty('--k', String(k));
    box.replaceChildren(fig, board);
    const warns = [];
    if (fallback) warns.push('캐릭터 설정 파일이 규격에 맞지 않아 기본 그림을 썼어요');
    if (cfg.rigBad) warns.push('캐릭터 뼈대 설정이 규격에 맞지 않아 예전 움직임을 썼어요');
    if (warns.length) box.append(h('p', { class: 'bd-mascot-warn', text: warns.join(' · ') }));
    if (!puppet) for (const m of [...Object.values(cfg.moods), ...Object.values(cfg.anim)]) new Image().src = m.src; // 그림 미리 읽기
    root.querySelector('.bd-mascot-name').textContent = cfg.name;
    mascot = { cfg, k, img, fig, chest, blink, board, card, front, back, pointing: false, puppet };
    if (puppet) puppet.setActive(visible);
    setMood(mood, true);
    scheduleBlink();
  }

  // ---- 발표 캐릭터 움직임 (CEO 요청 '자연스러운 움직임'): 숨쉬기(CSS), 눈 깜빡임, 판이 돌 때 손짓, 기쁘면 폴짝, 걱정하면 흔들림.
  // 효과 스위치가 꺼져 있으면(html.calm) 움직이지 않는다.
  let blinkTimer = null;
  function scheduleBlink() {
    clearTimeout(blinkTimer);
    if (!mascot || !mascot.blink) return;
    blinkTimer = setTimeout(() => {
      // 평소 얼굴·손짓 아닐 때·보이는 때만. 가끔은 두 번 연달아
      if (visible && mood === 'normal' && !mascot.pointing && !Fx.reduced() && !document.hidden) {
        blinkOnce();
        if (Math.random() < 0.25) setTimeout(blinkOnce, 260);
      }
      scheduleBlink();
    }, 2600 + Math.random() * 3600);
  }

  function blinkOnce() {
    if (!mascot || !mascot.blink) return;
    mascot.blink.hidden = false;
    setTimeout(() => { if (mascot && mascot.blink) mascot.blink.hidden = true; }, 130);
  }

  // 틀에 잠깐 움직임 이름을 붙인다 (hop·shake·lean). 같은 것을 다시 붙이면 처음부터
  function play(name, ms) {
    if (!mascot || Fx.reduced()) return;
    const fig = mascot.fig;
    fig.classList.remove('hop', 'shake', 'lean');
    void fig.offsetWidth; // 다시 시작하게
    fig.classList.add(name);
    setTimeout(() => fig.classList.remove(name), ms);
  }

  // 판이 도는 동안 손짓 그림 (없으면 몸만 판 쪽으로 살짝 기울임)
  function gesture() {
    if (!mascot || Fx.reduced() || mood !== 'normal') return; // 기쁨·걱정은 폴짝·흔들림이 대신한다 (setMood)
    if (mascot.puppet) { mascot.puppet.point(1300); return; } // 인형: 손짓 곡선(또는 손짓 그림)과 판 쪽 기울기는 엔진이
    play('lean', 1300);
    const p = mascot.cfg.anim.point;
    if (!p) return;
    mascot.pointing = true;
    placeImage(p);
    setTimeout(() => {
      if (!mascot) return;
      mascot.pointing = false;
      placeImage(mascot.cfg.moods[mood] || mascot.cfg.moods.normal);
    }, 1300);
  }

  function placeImage(m) {
    const { img, fig, k } = mascot;
    img.src = m.src;
    fig.style.setProperty('left', `${Math.round(m.x * k)}px`);
    fig.style.setProperty('top', `${Math.round(m.y * k)}px`);
    fig.style.setProperty('height', `${Math.round(m.h * k)}px`);
    const b = mascot.cfg.anim.blink;
    if (b && mascot.blink) { // 눈 조각: 평소 그림 기준 자리 (틀 안에서)
      const n = mascot.cfg.moods.normal;
      mascot.blink.style.setProperty('left', `${Math.round((b.x - n.x) * k)}px`);
      mascot.blink.style.setProperty('top', `${Math.round((b.y - n.y) * k)}px`);
      mascot.blink.style.setProperty('height', `${Math.round(b.h * k)}px`);
    }
    const c = mascot.cfg.anim.chest;
    if (c && mascot.chest) {
      const n = mascot.cfg.moods.normal;
      mascot.chest.style.setProperty('left', `${Math.round((c.x - n.x) * k)}px`);
      mascot.chest.style.setProperty('top', `${Math.round((c.y - n.y) * k)}px`);
      mascot.chest.style.setProperty('height', `${Math.round(c.h * k)}px`);
      mascot.chest.hidden = mascot.pointing || mood !== 'normal';
    }
  }

  function setMood(name, force = false) {
    if (!mascot || (name === mood && !force)) return;
    const was = mood;
    mood = name;
    const m = mascot.cfg.moods[name] || mascot.cfg.moods.normal;
    const { board, k } = mascot;
    if (mascot.puppet) mascot.puppet.setMood(name, force); // 인형: 겹쳐 바꾸기·폴짝·흔들림·고개 숙임은 엔진이
    else {
      if (!mascot.pointing) placeImage(m);
      if (mascot.blink) mascot.blink.hidden = true;
      if (!force && was !== name) { // 표정이 바뀔 때: 기쁨이면 폴짝, 걱정이면 흔들림
        if (name === 'happy') play('hop', 800);
        else if (name === 'worried') play('shake', 700);
      }
    }
    const b = m.board;
    for (const [prop, v] of [['left', b.x], ['top', b.y], ['width', b.w], ['height', b.h]]) board.style.setProperty(prop, `${Math.round(v * k)}px`);
    board.style.setProperty('--pole', `${Math.max(0, Math.round((mascot.cfg.box.h - b.y - b.h) * k))}px`); // 기둥은 상자 바닥까지
    // 판 글자 크기: 기본 판(178×214)을 1로 보고 판 크기에 맞춘다
    board.style.setProperty('--bs', String(Math.max(0.6, Math.min(1.6, Math.min((b.w * k) / 178, (b.h * k) / 214)))));
  }

  // ---- 데이터가 바뀔 때마다 (보이지 않아도 상태는 기억한다: 다시 볼 때 한꺼번에 알리지 않게)
  function update(view) {
    const found = changes(prev, view.tasks);
    prev = snapshot(view.tasks);
    if (visible && !held) for (const c of found) enqueue(c);
    dirty = true;
    if (visible) render();
  }

  function setVisible(on) {
    visible = on;
    root.hidden = !on;
    if (typeof Media !== 'undefined') Media.setVisible(on && page === 'media'); // 숨으면 3초 읽기도 멈춘다
    for (const [name, room] of Object.entries(rooms)) room.setVisible(on && page === name);
    if (mascot && mascot.puppet) mascot.puppet.setActive(on); // 진행판을 떠나면 그리기를 멈춘다
    if (!on) { queue.length = 0; return; }
    if (dirty) render();
  }

  function enqueue(change) {
    const same = queue.findIndex((c) => c.task.id === change.task.id);
    if (same >= 0) queue[same] = { ...change, from: queue[same].from }; // 같은 작업이 또 바뀌면 처음 → 마지막으로 합친다
    else queue.push(change);
    while (queue.length > QUEUE_MAX) queue.shift();
    if (!showing) next();
  }

  function next() {
    clearTimeout(timer);
    showing = queue.shift() || null;
    if (!mascot) { showing = null; queue.length = 0; return; }
    if (!showing) {
      mascot.card.classList.remove('flipped');
      setMood(baseMood());
      return;
    }
    fillBack(showing);
    setMood(moodFor(showing.to));
    mascot.card.classList.add('flipped');
    if (mascot.puppet) mascot.puppet.talk(TALK_MS);
    gesture();
    Sfx.play('flip');
    // 판이 되돌아 도는 시간(board.css 1.1초)을 다 기다린 뒤 다음 알림
    if (!held) timer = setTimeout(() => { mascot.card.classList.remove('flipped'); timer = setTimeout(next, 1200); }, SHOW_MS);
  }

  // 막힌 일이 있으면 평소 얼굴이 걱정
  function baseMood() { return heldMood || (viewNow().tasks.some((t) => t.status === 'blocked' && shown(t)) ? 'worried' : 'normal'); }

  function fillBack(c) {
    const t = c.task;
    const p = Data.owner(t);
    const stage = STAGE[c.to] ?? 0;
    const was = c.from ? STAGE[c.from] ?? 0 : null;
    mascot.back.classList.toggle('bad', c.to === 'blocked');
    mascot.back.classList.toggle('good', moodFor(c.to) === 'happy');
    mascot.back.replaceChildren(
      h('span', { class: 'bd-b-who', text: `${t.id} · ${p.name}` }),
      h('b', { class: 'bd-b-title', text: t.title }),
      h('span', { class: 'bd-b-move' },
        c.from ? h('span', { class: 'from', text: STATUS_SHORT[c.from] || c.from }) : h('span', { class: 'from', text: '새 일' }),
        h('span', { class: 'arrow', text: '→' }),
        h('span', { class: 'to', text: STATUS_SHORT[c.to] || c.to })),
      h('span', { class: 'bd-b-dots', 'aria-hidden': 'true' }, STAGE_NAMES.map((name, i) => h('i', {
        class: `${i < stage || (i === stage && c.to === 'done') ? 'past' : ''} ${i === stage ? 'now' : ''} ${c.to === 'blocked' && i === stage ? 'stop' : ''} ${was === i && was !== stage ? 'was' : ''}`.trim(),
        title: name,
      }))));
    mascot.back.setAttribute('aria-label', `${t.title}: ${c.from ? STATUS_SHORT[c.from] : '새 일'}에서 ${STATUS_SHORT[c.to]}(으)로`);
  }

  function fillFront(view) {
    const g = headline(view.tasks);
    const f = mascot.front;
    if (!g) {
      f.replaceChildren(h('span', { class: 'bd-f-label', text: '진행 상황' }), h('b', { class: 'bd-f-empty', text: '아직 맡긴 일이 없어요' }),
        h('span', { class: 'bd-f-sub', text: '아래 명령창에 지시를 적어 주세요' }));
      return;
    }
    const bar = h('span', { class: 'bd-f-bar' }, h('i'));
    bar.firstChild.style.setProperty('--pct', `${g.pct}%`);
    f.replaceChildren(
      h('span', { class: 'bd-f-label', text: g.key === 'loose' ? '맡긴 일 진행' : '이번 지시' }),
      h('span', { class: 'bd-f-title', text: g.title }),
      h('b', { class: 'bd-f-pct' }, String(g.pct), h('small', { text: '%' })),
      bar,
      h('span', { class: 'bd-f-sub', text: `${g.total}개 중 ${g.done}개 완료` }),
      g.blocked ? h('span', { class: 'bd-f-bad', text: `막힘 ${g.blocked}개` }) : g.waiting ? h('span', { class: 'bd-f-wait', text: `결재 기다림 ${g.waiting}개` }) : '');
  }

  // ---- 그리기
  // 지금 보여 줄 데이터: 개발용 주소(#boarddemo)면 가짜 작업, 아니면 실제 (Data)
  function viewNow() {
    const v = Data.get();
    return DEMO ? { ...v, tasks: demoTasks(DEMO, v.projects), stopped: false, current: demoCurrent(DEMO) } : v;
  }

  // 다시 그려도 키보드 초점이 그대로이게: 초점이 있던 카드·단추의 data-fk를 기억했다가 되돌린다
  function activeKey() {
    const a = document.activeElement;
    return a && root.contains(a) ? a.getAttribute('data-fk') : null;
  }

  // 스크롤이 생기는 칸만 아래쪽 가장자리를 흐리게 (끝까지 내리면 없어짐)
  function fade(cards) {
    const scrolls = cards.scrollHeight > cards.clientHeight + 1;
    cards.classList.toggle('scrolls', scrolls);
    cards.classList.toggle('at-end', !scrolls || cards.scrollTop + cards.clientHeight >= cards.scrollHeight - 2);
  }

  function render() {
    if (!root || !visible) return;
    dirty = false;
    const view = viewNow();
    const att = attention(view.tasks, DEMO ? null : Data.inbox().length);
    const badge = root.querySelector('.bd-badge');
    if (badge) {
      badge.hidden = !att.approvals;
      badge.textContent = String(att.approvals);
    }
    if (page === 'home') {
      if (typeof Home !== 'undefined') Home.render(view, att);
      return;
    }
    if (page === 'media') {
      if (typeof Media !== 'undefined') Media.render();
      return;
    }
    if (rooms[page]) {
      rooms[page].render();
      return;
    }
    const projects = view.projects || [];
    if (project && !projects.some((p) => p.key === project)) project = null;
    const main = root.querySelector('.bd-page-board');
    const colsEl = main.querySelector('.bd-cols');
    const focusKey = activeKey();
    const scroll = {};
    for (const col of colsEl.querySelectorAll('.bd-col')) scroll[col.dataset.key] = col.querySelector('.bd-cards').scrollTop;
    const oldList = colsEl.querySelector('.bd-list-body');
    const listTop = oldList ? oldList.scrollTop : 0;

    const now = Date.now();
    const cols = columns(view.tasks, project, { query, extraOf, view: viewKey, now, group: byProject && projects.length > 1, doneLimit: mode === 'list' ? LIST_DONE : DONE_SHOWN });
    main.querySelector('.bd-head').replaceChildren(...headerParts(view, projects, cols, now));
    main.querySelector('.bd-flow').replaceChildren(...flowParts(view));
    colsEl.classList.toggle('bd-list-mode', mode === 'list');
    if (mode === 'list') {
      colsEl.style.removeProperty('--bd-cols');
      colsEl.replaceChildren(listEl(cols, view));
      const body = colsEl.querySelector('.bd-list-body');
      if (body) body.scrollTop = listTop;
    } else {
      colsEl.style.setProperty('--bd-cols', widths(cols).map((w) => `${w}fr`).join(' '));
      colsEl.replaceChildren(...cols.map((c) => column(c, view, project)));
      for (const col of colsEl.querySelectorAll('.bd-col')) {
        const cards = col.querySelector('.bd-cards');
        cards.scrollTop = scroll[col.dataset.key] || 0;
        fade(cards);
      }
    }
    if (focusKey) {
      const again = root.querySelector(`[data-fk="${CSS.escape(focusKey)}"]`);
      if (again) again.focus({ preventScroll: true });
    }

    if (PRESENTER && mascot) {
      fillFront(view);
      if (!showing) setMood(baseMood());
    }
    if (PRESENTER) {
      root.querySelector('.bd-now').replaceChildren(...nowLine(view));
      const list = groups(view.tasks).slice(0, GROUPS_SHOWN);
      root.querySelector('.bd-groups').replaceChildren(...(list.length ? list.map(groupRow) : [h('li', { class: 'bd-g-empty', text: '아직 없어요' })]));
    }
  }

  function saveProject() {
    try { localStorage.setItem('studio.boardProject', project || ''); } catch (_) { /* 저장 못 해도 됨 */ }
  }

  // 머리줄: 위치(›) · 큰 제목 + 도구(프로젝트·묶기·보기 방식·내보내기·새 지시) · 보기 칩(개수) + 이번 주 목표 + 직원 얼굴
  const SVG = {
    kanban: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="4" width="4.5" height="16" rx="1.5"/><rect x="9.75" y="4" width="4.5" height="10" rx="1.5"/><rect x="16" y="4" width="4.5" height="13" rx="1.5"/></svg>',
    list: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6.5h12M8 12h12M8 17.5h12"/><circle cx="4.2" cy="6.5" r="1"/><circle cx="4.2" cy="12" r="1"/><circle cx="4.2" cy="17.5" r="1"/></svg>',
    download: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/></svg>',
  };
  const withSvg = (el, svg) => { el.innerHTML = svg; return el; };

  function headerParts(view, projects, cols, now) {
    const goal = view.goals.week || '정하지 않음';
    const pj = project ? (projects.find((p) => p.key === project) || {}).title : null;
    const counts = viewCounts(view.tasks, project, now);
    const filter = projects.length > 1 ? h('div', { class: 'bd-seg', role: 'group', 'aria-label': '프로젝트' },
      [{ key: null, title: '전체' }, ...projects].map((p) => h('button', {
        type: 'button', class: `bd-chip ${project === p.key ? 'on' : ''}`, 'data-fk': `chip:${p.key || ''}`, 'aria-pressed': String(project === p.key),
        onclick: () => { project = p.key; saveProject(); render(); },
      }, p.title))) : null;
    const grouper = projects.length > 1 ? h('button', {
      type: 'button', class: `bd-toggle ${byProject ? 'on' : ''}`, 'data-fk': 'group', role: 'switch', 'aria-checked': String(byProject), title: '칸 안에서 프로젝트별로 모아 보기',
      onclick: () => { byProject = !byProject; try { localStorage.setItem('studio.boardGroup', byProject ? '1' : '0'); } catch (_) { /* 저장 못 해도 됨 */ } render(); },
    }, h('span', { text: '프로젝트별로 묶기' }), h('i', { 'aria-hidden': 'true' })) : null;
    const modeBtn = (key, label) => withSvg(h('button', {
      type: 'button', class: `bd-chip bd-mode ${mode === key ? 'on' : ''}`, 'data-fk': `mode:${key}`, 'aria-pressed': String(mode === key), 'aria-label': `${label} 보기`, title: `${label} 보기`,
      onclick: () => { mode = key; try { localStorage.setItem('studio.boardMode', key); } catch (_) { /* 저장 못 해도 됨 */ } render(); },
    }), SVG[key]);
    const exporter = withSvg(h('button', {
      type: 'button', class: 'bd-iconbtn', 'data-fk': 'export', 'aria-label': '표 파일로 내려받기', title: '지금 보이는 일을 표 파일(CSV)로 내려받기',
      onclick: () => exportCsv(view),
    }), SVG.download);
    return [
      h('nav', { class: 'bd-crumb', 'aria-label': '위치' }, h('span', { text: '진행판' }), h('i', { 'aria-hidden': 'true', text: '›' }),
        h('span', { class: 'cur', text: query ? `“${query}” 찾기` : `${pj || '전체'} · ${(VIEWS.find((v) => v.key === viewKey) || VIEWS[0]).label}` }),
        query ? h('button', { type: 'button', class: 'bd-clear', text: '지우기', onclick: () => { query = ''; render(); } }) : null),
      h('div', { class: 'bd-titlebar' }, h('h2', { text: '진행판' }), h('div', { class: 'bd-tools' }, filter, grouper,
        h('div', { class: 'bd-seg bd-modes', role: 'group', 'aria-label': '보기 방식' }, modeBtn('kanban', '칸반'), modeBtn('list', '목록')), exporter, newButton())),
      h('div', { class: 'bd-viewsrow' },
        h('div', { class: 'bd-views', role: 'group', 'aria-label': '보기' }, VIEWS.map((v) => h('button', {
          type: 'button', class: `bd-vchip ${v.key} ${viewKey === v.key ? 'on' : ''} ${counts[v.key] ? 'some' : 'zero'}`, 'data-fk': `view:${v.key}`, 'aria-pressed': String(viewKey === v.key),
          onclick: () => { viewKey = v.key; render(); },
        }, h('span', { text: v.label }), h('b', { text: String(counts[v.key]) })))),
        DEMO ? h('span', { class: 'bd-demo-tag', text: '개발용 가짜 작업' }) : null,
        h('button', { type: 'button', class: 'bd-goal', 'data-fk': 'goal', title: `이번 주 목표: ${goal} · 눌러서 고치기`,
          onclick: DEMO ? null : () => Popups.memo('이번 주 목표', view.goals.week, '정하기', (text) => Data.setGoal(text.slice(0, 40)).catch(hooks.fail)) },
        h('span', { text: '이번 주 목표' }), h('b', { text: goal })),
        staffStack()),
    ].filter(Boolean);
  }

  // 검은 알약 '새 지시': 아래 명령창으로 가서 바로 쓰게 한다
  function newButton() {
    const el = h('button', { type: 'button', class: 'bd-new', 'data-fk': 'new', onclick: focusCommand });
    el.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
    el.append(h('span', { text: '새 지시' }));
    return el;
  }

  function focusCommand() {
    const input = document.getElementById('command-input');
    const form = document.getElementById('command');
    if (!input || input.disabled) return;
    input.focus();
    if (!form) return;
    form.classList.remove('ping');
    void form.offsetWidth; // 애니메이션을 처음부터
    form.classList.add('ping');
    setTimeout(() => form.classList.remove('ping'), 1200);
  }

  // 지금 보이는 일을 표 파일(CSV)로: 프로젝트·보기·찾기 거름을 그대로 따르고, 끝난 일도 모두 넣는다. 엑셀에서 한글이 안 깨지게 맨 앞에 BOM을 붙인다.
  function exportCsv(view) {
    const cols = columns(view.tasks, project, { query, extraOf, view: viewKey, now: Date.now(), doneLimit: 100000 });
    const rows = [['번호', '제목', '단계', '종류', '프로젝트', '담당', '실행 횟수', '실행 분', '만든 때', '바뀐 때']];
    for (const c of cols) {
      for (const t of c.tasks) {
        const u = t.usage || {};
        rows.push([t.id, t.title, Data.statusLabel(t), Data.kindLabel(t), Data.projectTitle(t.project) || '', Data.owner(t).name, u.runs ?? '', u.minutes ?? '', t.created_at || '', t.updated_at || '']);
      }
    }
    const url = URL.createObjectURL(new Blob([String.fromCharCode(0xFEFF) + toCsv(rows)], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `ai-studio-진행판-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    hooks.notify((Data.BY_ROLE.producer || Data.TEAM[0]).name, `일 ${rows.length - 1}개를 표 파일로 내려받았어요`);
  }

  // 직원 얼굴을 겹쳐 놓고 일하는 직원은 초록 테두리
  function staffStack() {
    const team = Data.TEAM || [];
    if (!team.length) return null;
    const working = team.filter((p) => p.state === 'work').length;
    return h('div', { class: 'bd-stack', role: 'img', 'aria-label': `직원 ${team.length}명, ${working}명 일하는 중` },
      ...team.map((p) => h('span', { class: `bd-stack-item ${p.state === 'work' ? 'work' : ''}`.trim(), title: `${p.name} · ${p.title || ''}${p.state === 'work' ? ' · 일하는 중' : ''}` },
        Popups.face(p.id, p.state === 'blocked' ? 'worried' : 'normal'))),
      h('span', { class: 'bd-stack-txt', text: working ? `${working}명 일하는 중` : `직원 ${team.length}명` }));
  }

  // 지시별 진행: 아직 안 끝난 지시만 (최대 FLOW_SHOWN개). 다 끝났으면 줄이 없다
  function flowParts(view) {
    return groups(view.tasks).filter((g) => g.done < g.total).slice(0, FLOW_SHOWN).map((g) => {
      const bar = h('span', { class: 'bd-g-bar' }, h('i'));
      bar.firstChild.style.setProperty('--pct', `${g.pct}%`);
      return h('div', { class: `bd-g ${g.blocked ? 'bad' : ''}`.trim(), title: `${g.title} · ${g.total}개 중 ${g.done}개 완료${g.blocked ? ` · 막힘 ${g.blocked}개` : ''}` },
        h('span', { class: 'bd-g-title', text: g.title }), h('span', { class: 'bd-g-num', text: `${g.done}/${g.total}` }), bar);
    });
  }

  // 고정 SVG 체크 표시 (데이터가 아님)
  function checkIcon() {
    const el = h('span', { class: 'icon', 'aria-hidden': 'true' });
    el.innerHTML = '<svg viewBox="0 0 24 24"><path d="M5 12.5L10 17L19 7" stroke="currentColor" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    return el;
  }

  // 첫 막힌 카드로 스크롤하고 잠깐 강조 (프로젝트 거름 때문에 안 보이면 '전체'로)
  let flash = null; // { id, until }
  let page = 'board'; // 'home' | 'board' | 'media' | 'novel' | 'design' (왼쪽 메뉴의 홈·진행판·이미지·영상 작업대·소설 집필실·디자인 작업실)
  const SHELL_PAGES = ['home', 'media', 'novel', 'design']; // 진행판 말고 껍데기 안에서 따로 그리는 페이지
  const NAV_PAGES = ['home', 'board', 'media', 'novel', 'design']; // 켜진 쪽이 표시되는 메뉴 단추
  const rooms = {}; // 소설 집필실·디자인 작업실 (rooms.js)
  let viewKey = 'all'; // 보기 칩 (VIEWS)
  let byProject = false; // 프로젝트별로 묶기
  let mode = 'kanban'; // 'kanban' | 'list'
  let query = ''; // 빠른 찾기에서 '진행판에서 보기'로 넘어온 글 (없으면 빈 글)
  const extraOf = (t) => `${Data.owner(t).name} ${Data.kindLabel(t)} ${Data.projectTitle(t.project) || ''}`; // 찾기에 보태는 글: 담당 이름·종류·프로젝트 이름
  function focusBlocked(id) {
    if (!id) return;
    const t = viewNow().tasks.find((x) => x.id === id);
    if (project && t && t.project !== project) { project = null; saveProject(); render(); }
    const el = root.querySelector(`.bd-card[data-id="${CSS.escape(id)}"]`);
    if (!el) return;
    const cards = el.closest('.bd-cards');
    const r = el.getBoundingClientRect();
    const c = cards.getBoundingClientRect();
    const k = c.height / cards.clientHeight || 1; // 무대 배율
    if (r.top < c.top) cards.scrollTo({ top: cards.scrollTop - (c.top - r.top) / k - 12, behavior: Fx.reduced() ? 'auto' : 'smooth' });
    else if (r.bottom > c.bottom) cards.scrollTo({ top: cards.scrollTop + (r.bottom - c.bottom) / k + 12, behavior: Fx.reduced() ? 'auto' : 'smooth' });
    flash = { id, until: Date.now() + 1600 };
    el.classList.remove('flash');
    void el.offsetWidth; // 애니메이션을 처음부터
    el.classList.add('flash');
    el.focus({ preventScroll: true });
    setTimeout(() => {
      if (flash && flash.id === id) flash = null;
      const now = root.querySelector(`.bd-card[data-id="${CSS.escape(id)}"]`);
      if (now) now.classList.remove('flash');
    }, 1600);
  }

  // 빈 칸: 작은 그림 + 한 줄 안내 (대기 칸만 '새 지시' 단추)
  const EMPTY_SVG = '<svg viewBox="0 0 120 72" aria-hidden="true"><rect x="8" y="10" width="72" height="44" rx="10" fill="#fff" stroke="#dfe2e8"/><rect x="20" y="22" width="30" height="6" rx="3" fill="#dfe2e8"/><rect x="20" y="34" width="46" height="6" rx="3" fill="#eceef2"/><rect x="60" y="28" width="48" height="36" rx="10" fill="#fff" stroke="#dfe2e8"/><circle cx="96" cy="46" r="10" fill="#e3e5ff"/><path d="M96 41v10M91 46h10" stroke="#4f46e5" stroke-width="2" stroke-linecap="round"/></svg>';
  function emptyState(key) {
    const el = h('div', { class: 'bd-empty' });
    el.innerHTML = EMPTY_SVG;
    const text = query ? '찾는 일이 없어요'
      : viewKey !== 'all' ? (key === 'done' ? '끝난 일은 ‘전체’ 보기에서 볼 수 있어요' : '이 보기에는 해당하는 일이 없어요')
        : key === 'list' ? '아직 일이 없어요. 새 지시를 적어 보세요' : EMPTY_TEXT[key];
    el.append(h('p', { text }));
    if ((key === 'waiting' || key === 'list') && !query && viewKey === 'all') el.append(newButton());
    return el;
  }

  function column(c, view, projectKey) {
    const more = c.total - c.tasks.length;
    const has = c.tasks.length > 0;
    const grouped = byProject && (view.projects || []).length > 1;
    const items = [];
    let last;
    for (const t of c.tasks) {
      if (grouped && t.project !== last) {
        last = t.project;
        items.push(h('p', { class: 'bd-glabel', text: Data.projectTitle(t.project) || '프로젝트 없음' }));
      }
      items.push(card(t, view));
    }
    const cards = h('div', { class: 'bd-cards' },
      has ? items : emptyState(c.key),
      more > 0 ? h('button', { type: 'button', class: 'bd-more', 'data-action': 'diary', text: `${more}개 더 보기 · 업무 일지` }) : null);
    cards.addEventListener('scroll', () => fade(cards), { passive: true });
    // 빈 칸은 개수 알약(0)을 그리지 않는다 — 좁은 칸에서 제목이 잘리지 않게, 안내 글이 이미 비었다고 말한다
    return h('section', { class: `bd-col c-${c.key} ${has ? 'has' : 'empty'}`, 'data-key': c.key, 'aria-label': `${c.label} ${c.total}개` },
      h('h3', {}, h('i', { class: 'bd-dot', 'aria-hidden': 'true' }), h('span', { class: 'bd-col-name', text: c.label }), c.total ? h('b', { class: 'bd-count', text: String(c.total) }) : null),
      cards);
  }

  // 목록 보기: 같은 일을 한 줄씩 (단계 · 번호 · 제목 · 담당 · 종류 · 프로젝트 · 실행 · 바뀐 때). 줄을 누르면 카드와 같은 창이 열린다
  const LIST_HEAD = ['단계', '번호', '제목', '담당', '종류', '프로젝트', '실행', '바뀐 때'];
  function listEl(cols, view) {
    const rows = cols.flatMap((c) => c.tasks.map((t) => listRow(t)));
    const total = cols.reduce((n, c) => n + c.total, 0);
    const more = total - rows.length;
    return h('div', { class: 'bd-list', role: 'table', 'aria-label': `일 목록 ${total}개` },
      h('div', { class: 'bd-list-head', role: 'row' }, LIST_HEAD.map((t) => h('span', { role: 'columnheader', text: t }))),
      h('div', { class: 'bd-list-body' }, rows.length ? rows : emptyState('list'),
        more > 0 ? h('button', { type: 'button', class: 'bd-more', 'data-action': 'diary', text: `${more}개 더 보기 · 업무 일지` }) : null));
  }

  function listRow(t) {
    const p = Data.owner(t);
    const blocked = t.status === 'blocked';
    const open = DEMO ? () => {} : () => (t.status === 'awaiting_approval' ? Popups.openTask(t) : Popups.taskCard(t.id));
    const u = t.usage || {};
    const proj = Data.projectTitle(t.project) || '';
    return h('div', {
      class: `bd-row s-${stageKey(t.status)}`, role: 'row', tabindex: '0', 'data-id': t.id, 'data-fk': `row:${t.id}`,
      'aria-label': `${t.title}, ${Data.statusLabel(t)}, ${p.name}`, onclick: open,
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } },
    },
    h('span', { class: 'bd-row-st', role: 'cell' }, h('i', { class: 'bd-dot', 'aria-hidden': 'true' }), h('span', { text: Data.statusLabel(t) })),
    h('span', { class: 'bd-row-id', role: 'cell', text: t.id }),
    h('b', { class: 'bd-row-title', role: 'cell', text: t.title, title: t.title }),
    h('span', { class: 'bd-row-who', role: 'cell' }, Popups.face(p.id, blocked ? 'worried' : 'normal', 'bd-face-mini'), h('span', { text: p.name })),
    h('span', { class: 'bd-row-kind', role: 'cell', text: Data.kindLabel(t) }),
    h('span', { class: 'bd-row-proj', role: 'cell', text: proj, title: proj }),
    h('span', { class: 'bd-row-use', role: 'cell', text: u.runs ? `${u.runs}번 · ${u.minutes}분` : '–' }),
    h('span', { class: 'bd-row-at', role: 'cell', text: ago(t.updated_at) }));
  }

  function card(t, view) {
    const p = Data.owner(t);
    const blocked = t.status === 'blocked';
    const open = DEMO ? () => {} : () => (t.status === 'awaiting_approval' ? Popups.openTask(t) : Popups.taskCard(t.id));
    const proj = Data.projectTitle(t.project);
    const lit = flash && flash.id === t.id && Date.now() < flash.until;
    const u = t.usage || {};
    return h('article', {
      class: ['bd-card', `s-${stageKey(t.status)}`, blocked ? 'blocked' : '', lit ? 'flash' : ''].filter(Boolean).join(' '),
      tabindex: '0', role: 'button', 'data-id': t.id, 'data-fk': `card:${t.id}`,
      'aria-label': `${t.title}, ${Data.statusLabel(t)}, ${p.name}`,
      onclick: open,
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } },
    },
    h('span', { class: 'bd-card-top' }, h('span', { class: 'bd-kind', text: Data.kindLabel(t) }),
      blocked ? h('span', { class: 'bd-flag', text: t.needs_plan_input ? '답변 필요' : '막힘' }) : null, h('span', { class: 'bd-id', text: t.id })),
    h('b', { class: 'bd-title', text: t.title, title: t.title }),
    proj ? h('span', { class: 'bd-proj', text: proj, title: proj }) : null,
    ...infoLines(t, view),
    h('span', { class: 'bd-foot' }, h('span', { class: 'bd-who' }, Popups.face(p.id, blocked ? 'worried' : 'normal', 'bd-face-mini'), h('span', { class: 'bd-name', text: p.name })),
      u.runs ? h('span', { class: 'bd-use', text: `실행 ${u.runs}번 · ${u.minutes}분` }) : null),
    action(t));
  }

  function qaText(qa) {
    if (!qa || !qa.verdict) return null;
    if (qa.verdict === 'none') return ['검사 없음', 'soft']; // 검사가 없는 것을 '통과'로 보이지 않게
    const n = qa.total ? ` ${qa.passed}/${qa.total}` : '';
    return qa.verdict === 'pass' ? [`검사${n} 통과`, 'ok'] : [`검사${n} 탈락`, 'bad'];
  }

  function reviewText(rv) {
    if (!rv || !rv.verdict) return null;
    if (rv.verdict === 'approve') return ['리뷰 통과', 'ok'];
    if (rv.verdict === 'changes_requested' || rv.verdict === 'request_changes') return ['리뷰 수정 요청', 'bad'];
    if (rv.verdict === 'unavailable') return ['리뷰 못 함', 'soft'];
    return [`리뷰 ${rv.verdict}`, 'soft'];
  }

  const SKILL_SAID = { yes: '따랐어요', no: '안 따랐대요', unknown: '알리지 않았어요' };
  function skillChip(used) {
    if (used.length === 1) {
      const s = used[0];
      return h('span', { class: `bd-skill ${s.state}`, text: `★ ${s.title}`, title: `배운 스킬 · ${SKILL_SAID[s.state]}` });
    }
    const yes = used.filter((s) => s.state === 'yes').length;
    const said = yes === used.length ? '모두 따랐어요' : yes ? `${yes}개 따랐어요` : used.some((s) => s.state === 'no') ? '안 따랐대요' : '알리지 않았어요';
    return h('span', { class: `bd-skill ${yes === used.length ? 'yes' : ''}`.trim(), text: `★ 스킬 ${used.length}개 · ${said}`,
      title: used.map((s) => `${s.title} (${SKILL_SAID[s.state]})`).join(' · ') });
  }

  function infoLines(t, view) {
    const out = [];
    const cur = view.current && view.current.task === t.id ? view.current : null;
    if (t.status === 'blocked' && t.blocked_reason) out.push(h('span', { class: 'bd-why', text: t.blocked_reason, title: t.blocked_reason }));
    if (t.waiting) out.push(h('span', { class: 'bd-wait', text: t.waiting }));
    if (t.status === 'running') out.push(h('span', { class: 'bd-live', text: cur ? `지금 일하는 중${t.attempts > 1 ? ` · 시도 ${t.attempts}` : ''}` : '곧 시작해요' }));
    if (t.status === 'checking') {
      const reviewing = cur && String(cur.stage || '') === 'review';
      out.push(h('span', { class: 'bd-live', text: reviewing ? `리뷰 중 · ${Data.BY_ROLE[cur.role] ? Data.BY_ROLE[cur.role].name : ''}`.replace(/ · $/, '') : '신뢰 검사 중' }));
    }
    const tags = [qaText(t.qa), reviewText(t.review)].filter(Boolean).filter(() => ['checking', 'awaiting_approval', 'done', 'blocked'].includes(t.status));
    if (tags.length) out.push(h('span', { class: 'bd-tags' }, tags.map(([text, tone]) => h('span', { class: `bd-tag ${tone}`, text }))));
    // 배운 스킬: 하나면 ★ 제목, 둘 이상이면 ★ 스킬 N개 · 따른 정도 (따랐다고 알렸으면 초록). 자세한 이름은 title과 작업 카드에서
    const used = Popups.skillUse(t);
    if (used.length) out.push(h('span', { class: 'bd-skills' }, skillChip(used)));
    return out;
  }

  // 카드·홈이 함께 쓰는 '다음에 할 행동': 실행 · 결재하기 · 도와주기. 없으면 null
  function actionOf(t) {
    if (t.status === 'ready' || (t.status === 'queued' && (t.created_by || '').startsWith('supervisor:'))) {
      return { label: '실행', cls: 'go', needsRun: true, run: () => Data.act(t.id, 'run').then(() => hooks.notify(Data.owner(t).name, `${t.title} 시작할게요!`)).catch(hooks.fail) };
    }
    // 기획은 회의실에서 퀘스트를 고르는 결재라 이름을 그렇게
    if (t.status === 'awaiting_approval') return { label: t.kind === 'plan' ? '퀘스트 고르기' : '결재하기', cls: 'approve', run: () => Popups.openTask(t) };
    if (t.status === 'blocked') return { label: t.needs_plan_input ? '질문 보기' : '도와주기', cls: 'help', run: () => Popups.taskCard(t.id) };
    return null;
  }

  function action(t) {
    const a = actionOf(t);
    if (!a) return null;
    const stopped = Data.get().stopped;
    return h('button', {
      type: 'button', class: `bd-act ${a.cls}`, disabled: a.needsRun && stopped, title: a.needsRun && stopped ? '정지 중이에요' : null,
      onclick: (e) => { e.stopPropagation(); if (!DEMO) a.run(); },
    }, a.label);
  }

  // 지금 하는 일: 점 있는 알약 (일하면 파란 점, 없으면 회색 점, 긴급 정지면 빨간 점)
  function nowLine(view) {
    const cur = view.current;
    if (view.stopped) return [h('span', { class: 'dot stop', 'aria-hidden': 'true' }), h('span', { class: 'bad', text: '긴급 정지 중이에요' })];
    if (!cur || !cur.task) return [h('span', { class: 'dot', 'aria-hidden': 'true' }), h('span', { text: '지금 일하는 직원이 없어요' })];
    const who = Data.BY_ROLE[cur.role];
    return [h('span', { class: 'dot on', 'aria-hidden': 'true' }), h('span', { text: `지금: ${who ? who.name : cur.role_title || ''} · ${cur.title || cur.task}` })];
  }

  // 지시별 진행 한 줄: 다 끝났으면 ✓, 제목(두 줄까지), 3/3, 8px 막대
  function groupRow(g) {
    const bar = h('span', { class: 'bd-g-bar' }, h('i'));
    bar.firstChild.style.setProperty('--pct', `${g.pct}%`);
    return h('li', { class: `bd-g ${g.done === g.total ? 'full' : ''} ${g.blocked ? 'bad' : ''}`.trim() },
      h('span', { class: 'bd-g-check', 'aria-hidden': 'true' }, g.done === g.total ? checkIcon() : null),
      h('span', { class: 'bd-g-title', text: g.title, title: g.title }),
      h('span', { class: 'bd-g-num', text: `${g.done}/${g.total}`, title: `${g.total}개 중 ${g.done}개 완료` }),
      bar);
  }

  // 개발용 (#demo=boardflip): 첫 작업을 '작업 중 → 검사·리뷰'로 뒤집은 채 멈춘다 (캡처용, 서버에 아무것도 보내지 않는다)
  function demoFlip() {
    held = true;
    const tryShow = () => {
      const t = Data.get().tasks.find(shown);
      if (!mascot || !t) { setTimeout(tryShow, 300); return; }
      queue.length = 0;
      queue.push({ task: t, from: 'running', to: 'checking' });
      next();
    };
    tryShow();
  }

  // 개발용 (#view=board&pose=angleZ:1,hairSway:-1): 그 값으로 멈춘 자세 (캡처용, 서버에 아무것도 보내지 않는다)
  // 개발용 (#view=board&demo=rig): 가운데 칸에 큰 인형 + 영역 색·그물 선·매개변수 슬라이더 판 (pose가 있으면 그 값으로 시작)
  function whenPuppet(run, tries = 40) {
    if (mascot && mascot.puppet) run(mascot);
    else if (tries > 0) setTimeout(() => whenPuppet(run, tries - 1), 250);
  }

  function demoPose(text) {
    const mood = /(?:^|,)mood:(normal|happy|worried)(?:,|$)/.exec(String(text || '')); // mood:happy처럼 표정도 멈출 수 있다
    if (mood) heldMood = mood[1];
    whenPuppet((m) => {
      if (heldMood) setMood(heldMood, true);
      m.puppet.setPose(puppetLib().logic.parsePose(text));
    });
  }

  function demoRig(text, overlay) {
    whenPuppet((m) => {
      const pose = text ? puppetLib().logic.parsePose(text) : {};
      if (text) m.puppet.setPose(pose);
      puppetLib().devView(root, { rig: m.cfg.rig, box: m.cfg.box, normal: m.cfg.moods.normal, images: puppetImages(m.cfg) }, { reduced: () => Fx.reduced(), pose, overlay });
    });
  }

  return { logic, init, update, setVisible, setPage, render, view: () => viewNow(), focusCommand, actionOf, openRoom, setQuery: (q) => { query = String(q || '').trim(); render(); }, demoFlip, demoPose, demoRig, isVisible: () => visible };
})();

if (typeof module !== 'undefined') module.exports = Board; // tools/dev/board_sim.js (node)
