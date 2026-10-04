/* 기능 서랍 · 재사용 노드 작업대 · 실행 장부. 모든 실행은 기존 서버 엔진으로 보낸다. */
'use strict';

const Workbench = (() => {
  const h = (...args) => Popups.h(...args);
  const children = nodes => nodes.flat(Infinity).filter(n => n != null && n !== false);
  const copy = value => JSON.parse(JSON.stringify(value));
  const MODE = { code: '고정 처리', model: '모델 판단', human: '사람 확인', unsupported: '지원 전' };
  const STATUS = { pending: '순서 대기', dispatching: '작업 연결 중', running: '처리 중', waiting: '결재 대기',
    succeeded: '완료', blocked: '막힘', skipped: '선행 오류', cancelled: '중단' };
  const TYPE = { text: '글', candidate: '구현 후보', plan: '기획안', task: '작업', approved: '승인 결과', result: '정리 결과', any: '결과' };
  const NOTE = { purpose: '목적', inputs: '입력 설명', outputs: '출력 설명', cautions: '주의', example: '예시·참고 코드' };
  const PARAM = { text: '실행 입력', prefix: '앞에 붙일 글', suffix: '뒤에 붙일 글', acceptance: '수용 기준 (한 줄에 하나)',
    contains: '반드시 포함할 문구', min_length: '최소 글자 수', dedupe: '같은 줄 제거', sort: '가나다순 정렬' };
  let root, hooks, visible = false, catalog = null, draft = null, selected = null, folder = 'all', tab = 'nodes';
  let active = null, ledger = [], loading = false, graphBusy = false, unsaved = false, pollTimer = null, dialogEl = null;
  let refreshAgain = false, lastSignature = '', drag = null;
  const definitions = new Map();
  const DRAFT_KEY = 'studio.workbench.draft.v1';
  const LAST_RUN = 'studio.workbench.lastRun';

  function button(text, run, props = {}) {
    const b = h('button', { type: 'button', class: 'wb-btn', text, ...props });
    if (run) b.addEventListener('click', () => perform(b, run));
    return b;
  }

  async function perform(b, run) {
    if (b.disabled || b.dataset.busy) return;
    b.dataset.busy = '1'; b.disabled = true;
    try { await run(); } catch (e) { message(e.message, true); }
    finally { delete b.dataset.busy; if (b.isConnected) b.disabled = false; }
  }

  function message(text = '', error = false) {
    const el = root.querySelector('.wb-message');
    el.textContent = text; el.hidden = !text; el.classList.toggle('error', error);
    if (error && dialogEl) {
      const note = dialogEl.querySelector('.wb-dialog-error');
      note.textContent = text; note.hidden = false;
    }
  }

  function field(label, control, cls = '') {
    return h('label', { class: `wb-field ${cls}` }, h('span', { text: label }), control);
  }

  function select(options, value, onChange, label) {
    const el = h('select', { 'aria-label': label }, options.map(([id, text]) => h('option', { value: id, text })));
    el.value = value;
    if (onChange) el.addEventListener('change', () => onChange(el.value));
    return el;
  }

  function folderSelect(value, onChange, includeAll = false) {
    return select([...(includeAll ? [['all', '모든 폴더']] : []), ...catalog.folders.map(f => [f.id, f.title])], value, onChange, '폴더');
  }

  function input(value, max, onChange, attrs = {}) {
    const el = h('input', { type: 'text', maxlength: max, ...attrs });
    el.value = value;
    if (onChange) el.addEventListener('input', () => onChange(el.value));
    return el;
  }

  function textarea(value, max, onChange, attrs = {}) {
    const el = h('textarea', { maxlength: max, rows: 3, ...attrs });
    el.value = value;
    if (onChange) el.addEventListener('input', () => onChange(el.value));
    return el;
  }

  function parameterFields(operation, params, onChange) {
    const op = catalog.operations[operation];
    return Object.entries(op.params).map(([key, initial]) => {
      const value = params[key] ?? initial;
      let el;
      if (typeof initial === 'boolean') {
        el = h('input', { type: 'checkbox' }); el.checked = value;
        el.addEventListener('change', () => onChange(key, el.checked));
      } else if (typeof initial === 'number') {
        el = h('input', { type: 'number', min: 1, max: 4000 }); el.value = value;
        el.addEventListener('input', () => onChange(key, Number(el.value)));
      } else {
        el = textarea(Array.isArray(value) ? value.join('\n') : value, 4000,
          val => onChange(key, key === 'acceptance' ? val.split('\n').map(v => v.trim()).filter(Boolean) : val));
      }
      el.name = key;
      return field(PARAM[key] || key, el, typeof initial === 'boolean' ? 'wb-check' : '');
    });
  }

  function init(el, options = {}) {
    root = el; hooks = options;
    root.append(h('header', { class: 'wb-header' },
      h('div', { class: 'wb-brand' }, h('span', { class: 'wb-mark', text: '▤', 'aria-hidden': true }), h('div', {}, h('h1', { text: '기능 작업대' }), h('p', { text: '꺼내서 연결하고, 결과는 장부에 남겨요' }))),
      h('nav', { 'aria-label': '작업대 메뉴' }, button('진행판', () => hooks.back()), button('결재함', () => hooks.inbox()), button('업무 일지', () => hooks.diary()))),
      h('div', { class: 'wb-message', role: 'status', 'aria-live': 'polite', hidden: true }),
      h('div', { class: 'wb-layout' }, h('aside', { class: 'wb-drawer', 'aria-label': '기능 서랍' }),
        h('main', { class: 'wb-main', 'aria-label': '노드 연결 작업대' }), h('aside', { class: 'wb-detail', 'aria-label': '노드 상세', tabindex: 0 })),
      h('section', { class: 'wb-ledger', 'aria-label': '실행 장부' }));
    root.addEventListener('keydown', e => {
      if (e.key === 'Escape' && !dialogEl && !e.target.matches('input,textarea,select')) { e.preventDefault(); hooks.back(); }
    });
    Data.on('change', () => {
      if (!visible) return;
      const picker = root.querySelector('.wb-scope select'), projects = Data.get().projects || [];
      if (!active && draft && picker && picker.options.length !== projects.length + 1) {
        picker.replaceChildren(h('option', { value: '', text: '글 처리만' }), ...projects.map(p => h('option', { value: p.key, text: p.title })));
        if (!draft.project) draft.project = Data.currentProject()?.key || '';
        picker.value = draft.project;
        if (!draft.scope_touched) {
          draft.allowed_paths = [...(projects.find(p => p.key === draft.project)?.default_allowed_paths || [])];
          root.querySelector('.wb-scope textarea').value = draft.allowed_paths.join('\n');
        }
        remember();
      }
      refresh();
    });
    Data.on('connection', ok => { if (visible) { message(ok ? '다시 연결됐어요. 저장된 실행 기록을 확인합니다.' : '연결이 끊겼어요. 작성 중인 흐름은 이 브라우저에 보존됩니다.', !ok); if (ok) refresh(); } });
  }

  function remember() {
    if (!draft || active) return;
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ draft, selected, unsaved })); } catch (_) { message('브라우저 임시 저장을 할 수 없습니다. 서랍에 저장해 주세요.', true); }
  }

  function edited() { unsaved = true; remember(); renderSaveState(); }
  function definition(n) { return definitions.get(`${n.ref.id}@${n.ref.version}`) || catalog.nodes.find(d => d.id === n.ref.id && d.version === n.ref.version); }
  function graph() { return active ? { nodes: active.snapshot.graph.nodes, edges: active.snapshot.graph.edges } : draft.graph; }
  function nodeTitle(n) { return definition(n)?.title || n.ref.id; }
  function nodeState(id) { return active?.nodes[id] || { status: 'pending' }; }
  function runLabel(r) { return STATUS[r.status] || r.status; }
  function key() { return 'n-' + crypto.randomUUID().replaceAll('-', '').slice(0, 12); }

  async function setVisible(on) {
    visible = on; root.hidden = !on;
    if (pollTimer) clearInterval(pollTimer); pollTimer = null;
    if (!on) { remember(); closeDialog(); return; }
    try {
      if (!catalog) {
        await loadCatalog();
        try {
          const saved = JSON.parse(localStorage.getItem(DRAFT_KEY));
          if (saved?.draft?.graph) {
            const validated = await validate(saved.draft.graph);
            draft = { ...saved.draft, graph: validated }; selected = saved.selected; unsaved = Boolean(saved.unsaved);
          }
        } catch (_) { /* invalid local draft never executes; server copies remain in the drawer */ }
        if (!draft) template('text', false);
      }
      renderEditor(); renderDrawer(); await refresh();
      pollTimer = setInterval(() => { if (visible) refresh(); }, 1800);
    } catch (e) { message(e.message.includes('404') ? '새 기능을 쓰려면 실행 중인 AI Studio 서버를 안전하게 껐다 켜 주세요. 기존 작업을 먼저 확인하세요.' : e.message + ' · 다시 열면 다시 연결합니다.', true); }
  }

  async function loadCatalog() {
    catalog = await Data.workbenchGet();
    for (const d of catalog.nodes) definitions.set(`${d.id}@${d.version}`, d);
    const target = root.querySelector('.wb-toolbar select');
    if (target && draft && !active) {
      target.replaceChildren(...catalog.folders.map(f => h('option', { value: f.id, text: f.title })));
      target.value = draft.folder;
    }
  }

  async function validate(g) {
    const res = await Data.workbenchPost('validate', { graph: g });
    for (const d of res.definitions) definitions.set(`${d.id}@${d.version}`, d);
    return res.graph;
  }

  async function refresh() {
    if (!visible || !catalog) return;
    if (loading) { refreshAgain = true; return; }
    loading = true;
    try {
      const results = await Promise.allSettled([Data.workbenchGet('/ledger'), active ? Data.workbenchGet('/runs/' + encodeURIComponent(active.id)) : Promise.resolve(null)]);
      if (results[0].status === 'fulfilled') { ledger = results[0].value.runs; renderLedger(); }
      else message(results[0].reason.message, true);
      if (results[1].status === 'fulfilled' && results[1].value && active?.id === results[1].value.id) {
        const next = results[1].value, signature = JSON.stringify(next);
        if (signature !== lastSignature) { active = next; lastSignature = signature; updateGraphStates(); renderRunDetail(); renderRunBar(); }
      } else if (results[1].status === 'rejected') message(results[1].reason.message, true);
    } finally {
      loading = false;
      if (refreshAgain) { refreshAgain = false; refresh(); }
    }
  }

  function renderDrawer() {
    const el = root.querySelector('.wb-drawer');
    const rows = tab === 'nodes' ? catalog.nodes : catalog.flows;
    const filtered = rows.filter(n => folder === 'all' || n.folder === folder);
    el.replaceChildren(h('div', { class: 'wb-section-head' }, h('h2', { text: '기능 서랍' }), button('+ 노트', () => editNote())),
      h('div', { class: 'wb-tabs', role: 'group', 'aria-label': '서랍 종류' },
        button('기능', () => { tab = 'nodes'; renderDrawer(); }, { 'aria-pressed': String(tab === 'nodes') }),
        button('작업 묶음', () => { tab = 'flows'; renderDrawer(); }, { 'aria-pressed': String(tab === 'flows') })),
      folderSelect(folder, val => { folder = val; renderDrawer(); }, true),
      h('div', { class: 'wb-folder-actions' }, button('+ 폴더', () => editFolder()), folder !== 'all' && folder !== 'basic' ? button('이름 변경', () => editFolder(catalog.folders.find(f => f.id === folder))) : null),
      h('div', { class: 'wb-shelf' }, filtered.length ? filtered.map(n => {
        const enabled = tab === 'flows' || n.capability.enabled;
        return h('article', { class: `wb-library ${!enabled ? 'disabled' : ''}`, 'data-library': n.id },
          h('div', {}, h('strong', { text: n.title }), h('small', { text: tab === 'nodes' ? `${MODE[n.capability.mode]} · v${n.version}` : `${n.graph.nodes.length}개 노드 · v${n.version}` })),
          tab === 'nodes' ? h('p', { text: enabled ? n.note.purpose : n.capability.reason }) : null,
          h('div', { class: 'wb-library-actions' }, tab === 'nodes' ? button('꺼내기', () => addNode(n), { disabled: !enabled || Boolean(active), 'aria-label': `${n.title} 꺼내기` }) : button('불러오기', () => loadFlow(n)),
            button(tab === 'nodes' ? '노트 보기·편집' : '이름·폴더 편집', () => tab === 'nodes' ? editNote(n) : editFlowMeta(n))));
      }) : h('p', { class: 'wb-empty', text: '이 폴더는 비어 있어요. 기능이나 작업 묶음을 저장해 보세요.' })),
      h('p', { class: 'wb-hint', text: '꺼낸 기능은 서랍에도 남아요. 노트의 설명·참고 코드는 자동 실행되지 않습니다.' }));
  }

  function renderEditor() {
    const main = root.querySelector('.wb-main');
    main.replaceChildren(h('div', { class: 'wb-run-bar', hidden: !active }));
    if (active) {
      main.append(h('div', { class: 'wb-toolbar' }, h('h2', { text: active.title }), button('수정용 사본 꺼내기', () => copyRun()), button('내 작업대로 돌아가기', () => { active = null; renderEditor(); renderDrawer(); renderDetail(); remember(); })));
    } else {
      main.append(h('div', { class: 'wb-toolbar' },
        field('작업 묶음 이름', input(draft.title, 80, val => { draft.title = val; edited(); }, { name: 'flow-title' })),
        field('보관 폴더', folderSelect(draft.folder, val => { draft.folder = val; edited(); })),
        button('서랍에 저장', saveFlow, { class: 'wb-btn primary', 'data-save-flow': '1' })),
        h('div', { class: 'wb-tools' }, h('span', { class: 'wb-save-state' }),
          button('새 글 처리', () => template('text')), button('구현 묶음', () => template('build')), button('기획 묶음', () => template('plan')),
          button('문서 내보내기', exportFlow), button('문서 불러오기', importFlow), button('실행 계획 확인', prepare, { class: 'wb-btn primary', 'data-prepare': '1' })));
      const projects = Data.get().projects || [];
      const project = projects.find(p => p.key === draft.project) || Data.currentProject();
      if (!draft.project && project) draft.project = project.key;
      if (draft.allowed_paths == null) draft.allowed_paths = [...(project?.default_allowed_paths || [])];
      main.append(h('div', { class: 'wb-scope' }, field('모델 작업 대상', select([['', '글 처리만'], ...projects.map(p => [p.key, p.title])], draft.project || '', val => {
        draft.project = val; draft.allowed_paths = [...(projects.find(p => p.key === val)?.default_allowed_paths || [])]; edited(); renderEditor();
      }, '모델 작업 대상')),
      field('파일 변경 허용 범위 (한 줄에 하나)', textarea(draft.allowed_paths.join('\n'), 2000, val => { draft.allowed_paths = val.split('\n').map(p => p.trim()).filter(Boolean); draft.scope_touched = true; edited(); }, { rows: 2, name: 'scope' }))));
    }
    main.append(h('div', { class: 'wb-graph-scroll', tabindex: 0, 'aria-label': '노드 연결도 · 노드는 방향키로도 이동할 수 있어요' },
      h('div', { class: 'wb-canvas' })), h('div', { class: 'wb-connections' }));
    renderGraph(); renderConnections(); renderSaveState(); renderDetail(); renderRunBar();
  }

  function renderSaveState() {
    const text = root.querySelector('.wb-save-state');
    if (text) text.textContent = unsaved ? '● 아직 서랍에 저장하지 않은 변경' : draft?.id ? `저장된 v${draft.version}` : '새 작업대';
  }

  function graphSize() {
    const nodes = graph().nodes;
    return { width: Math.max(800, ...nodes.map(n => n.position.x + 255)), height: Math.max(390, ...nodes.map(n => n.position.y + 175)) };
  }

  function renderGraph() {
    const canvas = root.querySelector('.wb-canvas');
    if (!canvas) return;
    canvas.replaceChildren();
    const size = graphSize();
    canvas.style.setProperty('width', `${size.width}px`); canvas.style.setProperty('height', `${size.height}px`);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'wb-wires'); svg.setAttribute('width', size.width); svg.setAttribute('height', size.height);
    svg.setAttribute('aria-hidden', 'true');
    canvas.append(svg);
    if (!graph().nodes.length) canvas.append(h('p', { class: 'wb-empty', text: '왼쪽 서랍에서 기능을 꺼내 연결해 주세요.' }));
    for (const n of graph().nodes) {
      const d = definition(n), op = catalog.operations[d?.spec.operation] || {}, st = nodeState(n.id);
      const el = h('button', { type: 'button', class: `wb-node s-${st.status}`, 'data-node': n.id, 'aria-pressed': String(selected === n.id),
        'aria-label': `${nodeTitle(n)} · ${MODE[op.mode] || ''} · ${STATUS[st.status]}` },
        h('span', { class: 'wb-node-top' }, h('small', { text: MODE[op.mode] }), h('small', { text: `v${n.ref.version}` })),
        h('strong', { text: nodeTitle(n) }), h('span', { class: 'wb-ports', text: `${TYPE[op.input] || '직접 입력'} → ${TYPE[op.output] || ''}` }),
        h('span', { class: 'wb-node-state', text: active ? STATUS[st.status] : '설정 확인' }));
      if (op.job) {
        const assigned = active?.snapshot.models.find(m => m.node === n.id && m.job === op.job)?.role;
        const person = assigned ? Data.BY_ROLE[assigned] : Data.TEAM.find(p => p.job === op.job || p.role === op.job);
        if (person) el.append(h('span', { class: 'wb-assignee' }, Popups.face(person.id, 'normal', 'wb-face'), h('small', { text: person.name + ' 담당' })));
      }
      el.style.setProperty('--node-x', `${n.position.x}px`); el.style.setProperty('--node-y', `${n.position.y}px`);
      el.addEventListener('click', () => { if (drag?.moved) { drag = null; return; } selected = n.id; updateSelection(); renderDetail(); remember(); });
      if (!active) {
        el.addEventListener('keydown', e => {
          const delta = { ArrowLeft: [-20, 0], ArrowRight: [20, 0], ArrowUp: [0, -20], ArrowDown: [0, 20] }[e.key];
          if (delta) { e.preventDefault(); moveNode(n, n.position.x + delta[0], n.position.y + delta[1]); }
        });
        el.addEventListener('pointerdown', e => {
          if (e.button !== 0) return;
          drag = { id: n.id, x: e.clientX, y: e.clientY, nx: n.position.x, ny: n.position.y, moved: false };
          el.setPointerCapture(e.pointerId);
        });
        el.addEventListener('pointermove', e => {
          if (!drag || drag.id !== n.id || !el.hasPointerCapture(e.pointerId)) return;
          const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
          if (Math.abs(dx) + Math.abs(dy) > 6) drag.moved = true;
          if (drag.moved) moveNode(n, drag.nx + dx, drag.ny + dy);
        });
        el.addEventListener('pointerup', e => { if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId); });
        el.addEventListener('pointercancel', () => { drag = null; });
      }
      canvas.append(el);
    }
    drawWires(); updateGraphStates();
  }

  function moveNode(n, x, y) {
    n.position = { x: Math.round(Math.max(0, Math.min(9500, x))), y: Math.round(Math.max(0, Math.min(9500, y))) };
    const el = root.querySelector(`[data-node="${n.id}"]`);
    el.style.setProperty('--node-x', `${n.position.x}px`); el.style.setProperty('--node-y', `${n.position.y}px`);
    const size = graphSize(), canvas = root.querySelector('.wb-canvas'), svg = canvas.querySelector('svg');
    canvas.style.setProperty('width', `${size.width}px`); canvas.style.setProperty('height', `${size.height}px`);
    svg.setAttribute('width', size.width); svg.setAttribute('height', size.height);
    drawWires(); edited();
  }

  function wireState(e) {
    if (!active) return 'pending';
    const a = nodeState(e.from).status, b = nodeState(e.to).status;
    return ['blocked', 'skipped', 'cancelled'].includes(a) || ['blocked', 'skipped', 'cancelled'].includes(b) ? 'blocked' : a === 'succeeded' ? b : 'pending';
  }

  function drawWires() {
    const svg = root.querySelector('.wb-wires'); if (!svg) return;
    svg.replaceChildren();
    const map = Object.fromEntries(graph().nodes.map(n => [n.id, n]));
    for (const e of graph().edges) {
      const a = map[e.from]?.position, b = map[e.to]?.position; if (!a || !b) continue;
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const ax = a.x + 222, ay = a.y + 76, bx = b.x, by = b.y + 76, bend = Math.max(40, Math.abs(bx - ax) * .5);
      path.setAttribute('d', `M${ax},${ay} C${ax + bend},${ay} ${bx - bend},${by} ${bx},${by}`);
      path.setAttribute('class', `wb-wire s-${wireState(e)}`); path.dataset.edge = `${e.from}:${e.to}`;
      svg.append(path);
    }
  }

  function updateSelection() { for (const el of root.querySelectorAll('[data-node]')) el.setAttribute('aria-pressed', String(el.dataset.node === selected)); }
  function updateGraphStates() {
    for (const n of graph().nodes) {
      const el = root.querySelector(`[data-node="${n.id}"]`); if (!el) continue;
      const st = nodeState(n.id);
      el.className = `wb-node s-${st.status}`;
      el.querySelector('.wb-node-state').textContent = active ? `${STATUS[st.status]}${st.progress === 'checking' ? ' · 신뢰 검증·검토' : ''}` : '설정 확인';
      el.setAttribute('aria-label', `${nodeTitle(n)} · ${MODE[catalog.operations[definition(n)?.spec.operation]?.mode]} · ${STATUS[st.status]}`);
    }
    drawWires();
    for (const el of root.querySelectorAll('[data-edge-status]')) {
      const e = graph().edges.find(e => `${e.from}:${e.to}` === el.dataset.edgeStatus);
      if (e) el.textContent = STATUS[wireState(e)];
    }
  }

  function renderConnections() {
    const el = root.querySelector('.wb-connections'), g = graph();
    el.replaceChildren(h('h3', { text: '연결' }));
    if (!active) {
      const opts = g.nodes.map(n => [n.id, `${nodeTitle(n)} (${n.id.slice(-4)})`]);
      const from = select(opts, g.nodes[0]?.id, null, '출발 노드'), to = select(opts, g.nodes[1]?.id, null, '도착 노드');
      el.append(h('div', { class: 'wb-connect-form' }, field('출발', from), h('span', { text: '→' }), field('도착', to), button('연결하기', async () => {
        await mutateGraph({ ...copy(draft.graph), edges: [...copy(draft.graph.edges), { from: from.value, to: to.value }] });
        message('연결했어요.');
      }, { disabled: g.nodes.length < 2 })));
    }
    el.append(h('ul', { class: 'wb-edge-list' }, g.edges.map(e => h('li', {},
      h('span', { text: `${nodeTitle(g.nodes.find(n => n.id === e.from))} → ${nodeTitle(g.nodes.find(n => n.id === e.to))}` }),
      h('small', { 'data-edge-status': `${e.from}:${e.to}`, text: STATUS[wireState(e)] }),
      !active ? button('연결 끊기', () => mutateGraph({ ...copy(draft.graph), edges: draft.graph.edges.filter(x => x !== e) }), { 'aria-label': `${e.from}에서 ${e.to} 연결 끊기` }) : null))));
  }

  async function mutateGraph(g) {
    if (graphBusy) throw new Error('연결을 확인 중이에요. 확인이 끝나면 다시 선택해 주세요.');
    if (active) return;
    graphBusy = true;
    try { draft.graph = await validate(g); edited(); renderGraph(); renderConnections(); renderDetail(); }
    finally { graphBusy = false; }
  }

  async function addNode(d) {
    if (active) return;
    if (draft.graph.nodes.length >= catalog.max_nodes) throw new Error(`노드는 ${catalog.max_nodes}개까지 꺼낼 수 있어요.`);
    const idx = draft.graph.nodes.length, n = { id: key(), ref: { id: d.id, version: d.version }, params: copy(d.spec.params), position: { x: 30 + (idx % 3) * 275, y: 25 + Math.floor(idx / 3) * 190 } };
    selected = n.id;
    await mutateGraph({ ...copy(draft.graph), nodes: [...copy(draft.graph.nodes), n] });
    message(`${d.title}을 꺼냈어요. 원래 기능은 서랍에 남아 있어요.`);
  }

  function renderDetail() {
    if (active) return renderRunDetail();
    const el = root.querySelector('.wb-detail'), n = draft.graph.nodes.find(n => n.id === selected);
    if (!n) { el.replaceChildren(h('h2', { text: '기능 상세' }), h('p', { class: 'wb-empty', text: '노드를 선택하면 노트와 실행 입력을 볼 수 있어요.' })); return; }
    const d = definition(n), op = catalog.operations[d.spec.operation];
    el.replaceChildren(h('h2', { text: d.title }), h('p', { class: 'wb-kind', text: `${MODE[op.mode]} · 서랍 v${n.ref.version}` }),
      h('p', { class: 'wb-hint', text: op.description }),
      h('h3', { text: '이번 실행 입력' }),
      ...parameterFields(d.spec.operation, n.params, (key, value) => { n.params[key] = value; edited(); }),
      h('p', { class: 'wb-hint', text: '이 입력은 이번 작업 묶음에 저장됩니다. 서랍 노트의 원본은 그대로입니다.' }),
      noteView(d),
      h('div', { class: 'wb-detail-actions' }, button('서랍 노트 편집', () => editNote(d)), button('작업대에서 제거', async () => {
        const g = draft.graph;
        await mutateGraph({ nodes: g.nodes.filter(x => x.id !== n.id), edges: g.edges.filter(e => e.from !== n.id && e.to !== n.id) });
        selected = null; renderDetail();
      })));
  }

  function noteView(d) {
    return h('details', { class: 'wb-note', open: true }, h('summary', { text: '재사용 노트 · 실행 명세와 구분' }),
      h('dl', {}, Object.entries(NOTE).map(([key, label]) => [h('dt', { text: label }), h('dd', { text: d.note[key] || '작성하지 않음' })])));
  }

  function renderRunDetail() {
    if (!active) return;
    const el = root.querySelector('.wb-detail'), g = graph(), n = g.nodes.find(n => n.id === selected) || g.nodes[0];
    if (!n) return;
    selected = n.id;
    const state = nodeState(n.id), d = definition(n);
    const scroll = el.scrollTop, focus = el.contains(document.activeElement) ? document.activeElement.dataset.wbFocus : null;
    el.replaceChildren(...children([h('h2', { text: d.title }), h('p', { class: `wb-kind s-${state.status}`, text: `${STATUS[state.status]} · 실행 당시 v${n.ref.version}` }),
      state.error ? h('p', { class: 'wb-error', text: state.error }) : null,
      state.task ? h('div', { class: 'wb-task-link' }, h('p', { text: `기존 작업 ${state.task}` }), button(state.status === 'waiting' ? '기존 결재 창 열기' : '작업·일지·산출물 보기', () => hooks.task(state.task), { 'data-wb-focus': 'task' })) : null,
      h('h3', { text: '노드별 입력' }), h('pre', { text: state.inputs === null ? '선행 입력 대기' : typeof state.inputs === 'string' ? state.inputs : JSON.stringify(state.inputs, null, 2) }),
      h('h3', { text: '출력·결과' }), h('pre', { text: state.output === null ? '아직 결과가 없습니다.' : typeof state.output === 'string' ? state.output : JSON.stringify(state.output, null, 2) }),
      h('details', {}, h('summary', { text: '실행 당시 명세' }), h('pre', { text: JSON.stringify({ operation: d.spec.operation, params: n.params }, null, 2) })), noteView(d)]));
    el.scrollTop = scroll;
    if (focus) el.querySelector(`[data-wb-focus="${focus}"]`)?.focus({ preventScroll: true });
    updateSelection();
  }

  function renderRunBar() {
    const el = root.querySelector('.wb-run-bar'); if (!el || !active) return;
    el.hidden = false;
    el.replaceChildren(...children([h('div', {}, h('strong', { text: `${runLabel(active)} · 실행 당시 흐름` }), h('small', { text: active.created_at })),
      h('p', { text: active.error || `${active.snapshot.uses_models ? '모델 사용 · ' : '고정 처리 · '}${active.snapshot.project_title} · ${active.snapshot.allowed_paths.join(', ') || '파일 변경 없음'}` }),
      active.status === 'blocked' ? button('기록 다시 확인', async () => { active = (await Data.workbenchPost(`runs/${active.id}/reconcile`)).run; lastSignature = ''; await refresh(); }) : null,
      ['running', 'waiting', 'blocked'].includes(active.status) ? button('후속 노드 중단', async () => { active = (await Data.workbenchPost(`runs/${active.id}/halt`)).run; renderEditor(); renderDrawer(); await refresh(); }) : null]));
  }

  function renderLedger() {
    const el = root.querySelector('.wb-ledger');
    const scroll = el.querySelector('.wb-ledger-list')?.scrollLeft || 0;
    el.replaceChildren(h('div', { class: 'wb-section-head' }, h('h2', { text: '실행 장부' }), h('span', { text: '실행 당시 노트 버전·그래프·입출력 보관' })),
      h('div', { class: 'wb-ledger-list' }, ledger.length ? ledger.map(r => button('', () => openRun(r.id), { class: `wb-run s-${r.status}`, 'aria-pressed': String(active?.id === r.id), 'data-run': r.id })).map((b, i) => {
        const r = ledger[i]; b.append(h('strong', { text: r.title }), h('span', { text: `${runLabel(r)} · ${r.nodes}개 노드 · ${r.uses_models ? '모델 포함' : '고정 처리'}` }), h('small', { text: r.created_at })); if (r.error) b.append(h('small', { text: r.error })); return b;
      }) : h('p', { class: 'wb-empty', text: '아직 실행 기록이 없어요. 실행 전에 계획과 허용 범위를 확인합니다.' })));
    el.querySelector('.wb-ledger-list').scrollLeft = scroll;
  }

  async function openRun(id) {
    remember();
    active = await Data.workbenchGet('/runs/' + encodeURIComponent(id));
    for (const n of active.snapshot.graph.nodes) definitions.set(`${n.ref.id}@${n.ref.version}`, n.definition);
    selected = active.snapshot.graph.nodes[0]?.id; lastSignature = '';
    try { localStorage.setItem(LAST_RUN, id); } catch (_) { /* optional shortcut */ }
    renderEditor(); renderDrawer(); renderLedger(); message('장부의 실행 당시 흐름을 보고 있어요. 편집하려면 수정용 사본을 꺼내세요.');
  }

  async function copyRun() {
    const g = { nodes: active.snapshot.graph.nodes.map(({ definition, ...n }) => copy(n)), edges: copy(active.snapshot.graph.edges) };
    draft = { title: active.title + ' 사본', folder: 'personal', graph: await validate(g), project: active.snapshot.project || '', allowed_paths: [...active.snapshot.allowed_paths] };
    active = null; unsaved = true; selected = g.nodes[0]?.id; remember(); renderEditor(); renderDrawer();
  }

  function confirmReplace(run) {
    if (!active && unsaved) return ask('작성 중인 흐름 바꾸기', '아직 서랍에 저장하지 않은 변경이 있어요. 저장하거나, 바꾸기를 선택해 주세요.', [
      ['닫기', closeDialog], ['현재 흐름 저장', async () => { await saveFlow(); closeDialog(); await run(); }], ['바꾸기', async () => { closeDialog(); await run(); }],
    ]);
    return run();
  }

  function template(type, confirm = true) {
    const run = () => {
      const ops = type === 'build' ? ['input', 'implement', 'test', 'review', 'approve', 'summary'] : type === 'plan' ? ['input', 'requirements', 'approve', 'summary'] : ['input', 'lines', 'summary'];
      const nodes = ops.map((op, i) => ({ id: key(), ref: { id: 'builtin-' + op, version: 1 }, params: copy(catalog.operations[op].params), position: { x: 25 + (i % 3) * 275, y: 25 + Math.floor(i / 3) * 190 } }));
      draft = { title: type === 'build' ? '구현·검증·결재' : type === 'plan' ? '요구정리·기획결재' : '목록 정리', folder: 'personal', project: Data.currentProject()?.key || '', allowed_paths: null,
        graph: { nodes, edges: nodes.slice(1).map((n, i) => ({ from: nodes[i].id, to: n.id })) } };
      active = null; selected = nodes[0].id; unsaved = true; remember();
      if (confirm) { renderEditor(); renderDrawer(); message('새 묶음을 꺼냈어요. 입력을 적고 연결을 확인해 주세요.'); }
    };
    return confirm ? confirmReplace(run) : run();
  }

  async function loadFlow(flow) {
    return confirmReplace(async () => {
      const g = await validate(flow.graph); draft = { ...copy(flow), graph: g, project: flow.project || '', allowed_paths: flow.allowed_paths || [] };
      active = null; selected = g.nodes[0]?.id; unsaved = false; remember(); renderEditor(); renderDrawer(); message(`${flow.title} v${flow.version}을 불러왔어요.`);
    });
  }

  async function saveFlow() {
    if (active) throw new Error('장부를 수정할 수 없습니다. 수정용 사본을 꺼내 주세요.');
    const flow = (await Data.workbenchPost('flows', { id: draft.id, version: draft.version || 0, title: draft.title, folder: draft.folder, graph: draft.graph, project: draft.project || null, allowed_paths: draft.allowed_paths || [] })).flow;
    // Keep the live graph objects that the open input controls edit.
    draft = { ...draft, ...flow, graph: draft.graph }; unsaved = false; remember(); await loadCatalog(); renderDrawer(); renderSaveState(); message(`${flow.title} v${flow.version}을 서랍에 저장했어요.`);
  }

  function modal(title) {
    closeDialog();
      const d = h('dialog', { class: 'wb-dialog', 'aria-label': title },
        h('header', {}, h('h2', { text: title }), button('닫기', closeDialog, { 'aria-label': `${title} 닫기` })),
        h('div', { class: 'wb-dialog-body' }), h('p', { class: 'wb-dialog-error', role: 'alert', hidden: true }), h('footer', {}));
      d.addEventListener('keydown', e => {
        if (e.key !== 'Tab') return;
        const items = [...d.querySelectorAll('button, input, textarea, select, a[href], [tabindex]')]
          .filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length);
        const next = e.shiftKey ? items.at(-1) : items[0];
        if (items.length && (document.activeElement === (e.shiftKey ? items[0] : items.at(-1)) || !d.contains(document.activeElement))) {
          e.preventDefault(); next.focus();
        }
      });
      d.addEventListener('close', () => { d.remove(); if (dialogEl === d) dialogEl = null; });
    root.append(d); dialogEl = d; d.showModal(); return d;
  }

  function closeDialog() { if (dialogEl) { const d = dialogEl; dialogEl = null; d.close(); d.remove(); } }
  function ask(title, text, actions) { const d = modal(title); d.querySelector('.wb-dialog-body').append(h('p', { text })); d.querySelector('footer').append(...actions.map(([text, run]) => button(text, run))); }

  function editFolder(old = null) {
    const d = modal(old ? '폴더 이름 변경' : '새 폴더');
    const name = input(old?.title || '', 60, null, { name: 'folder-title' });
    d.querySelector('.wb-dialog-body').append(field('폴더 이름', name));
    d.querySelector('footer').append(button('저장', async () => {
      const saved = (await Data.workbenchPost('folders', { id: old?.id, title: name.value, revision: catalog.revision })).folder;
      await loadCatalog(); folder = saved.id; closeDialog(); renderDrawer(); message('폴더를 저장했어요.');
    }, { class: 'wb-btn primary' })); name.focus();
  }

  function editNote(old = null) {
    const d = modal(old ? '기능 노트 보기·편집' : '새 기능 노트'), body = d.querySelector('.wb-dialog-body');
    const note = copy(old?.note || Object.fromEntries(Object.keys(NOTE).map(k => [k, ''])));
    let operation = old?.spec.operation || 'format', params = copy(old?.spec.params || catalog.operations.format.params);
    const title = input(old?.title || '', 80, null, { name: 'note-title' }), targetFolder = folderSelect(old?.builtin ? 'personal' : old?.folder || 'personal');
    const paramBox = h('div', { class: 'wb-note-params' });
    const renderParams = () => paramBox.replaceChildren(...parameterFields(operation, params, (k, v) => { params[k] = v; }), h('p', { class: 'wb-hint', text: catalog.operations[operation].description }));
    const opSelect = select(Object.entries(catalog.operations).map(([id, op]) => [id, `${op.title} · ${MODE[op.mode]}`]), operation, val => { operation = val; params = copy(catalog.operations[val].params); renderParams(); }, '실행 종류');
    body.append(field('기능 제목', title), field('보관 폴더', targetFolder), h('h3', { text: '노트 · 사람과 직원이 읽는 설명' }),
      ...Object.entries(NOTE).map(([key, label]) => field(label, textarea(note[key] || '', 4000, val => { note[key] = val; }, { name: key }))),
      h('h3', { text: '실행 명세 · 등록된 기능만 허용' }), field('실행 종류', opSelect), paramBox,
      h('p', { class: 'wb-hint', text: '참고 코드·예시에 쓴 글은 자동 실행하지 않습니다. 기본 노트는 사본으로 저장하며 기존 직원 스킬과 회사 설정은 변경하지 않습니다.' }));
    renderParams();
    d.querySelector('footer').append(button(old?.builtin ? '내 기능으로 사본 저장' : '기능 저장', async () => {
      const saved = (await Data.workbenchPost('nodes', { id: old && !old.builtin ? old.id : undefined, version: old && !old.builtin ? old.version : 0,
        title: title.value, folder: targetFolder.value, note, spec: { operation, params } })).node;
      await loadCatalog(); closeDialog(); tab = 'nodes'; folder = saved.folder; renderDrawer(); message(`${saved.title} v${saved.version}을 저장했어요. 기존 묶음은 이전 버전을 유지합니다.`);
    }, { class: 'wb-btn primary' })); title.focus();
  }

  function editFlowMeta(old) {
    const d = modal('작업 묶음 이름·폴더 편집'), name = input(old.title, 80), targetFolder = folderSelect(old.folder);
    d.querySelector('.wb-dialog-body').append(field('이름', name), field('폴더', targetFolder));
    d.querySelector('footer').append(button('저장', async () => {
      await Data.workbenchPost('flows', { ...old, title: name.value, folder: targetFolder.value });
      await loadCatalog(); closeDialog(); renderDrawer(); message('작업 묶음을 저장했어요.');
    }, { class: 'wb-btn primary' })); name.focus();
  }

  function exportFlow() {
    const g = graph(), payload = { schema: 'ai-studio-flow/v1', title: active?.title || draft.title,
      project: active?.snapshot.project || draft.project || null, allowed_paths: active?.snapshot.allowed_paths || draft.allowed_paths || [],
      graph: { nodes: g.nodes.map(({ definition, ...n }) => n), edges: g.edges } };
    const d = modal('작업 묶음 내보내기');
    d.querySelector('.wb-dialog-body').append(h('p', { text: '아래 내용을 복사해 보관할 수 있어요. 기능 ID와 버전을 참조하므로 같은 서랍에서 불러옵니다.' }), textarea(JSON.stringify(payload, null, 2), 100000, null, { readonly: true, 'aria-label': '내보내기 내용', rows: 14 }));
  }

  function importFlow() {
    const d = modal('작업 묶음 불러오기'), text = textarea('', 100000, null, { 'aria-label': '불러올 작업 묶음', rows: 14 });
    d.querySelector('.wb-dialog-body').append(h('p', { text: '내보낸 작업 묶음을 붙여 넣으세요. 없는 기능·잘못된 연결은 거부합니다.' }), text);
    d.querySelector('footer').append(button('확인하고 불러오기', async () => {
      let value; try { value = JSON.parse(text.value); } catch (_) { throw new Error('작업 묶음의 문서 형식이 잘못됐어요.'); }
      if (!value || typeof value !== 'object' || value.schema !== 'ai-studio-flow/v1') throw new Error('AI Studio 작업 묶음 형식이 필요해요.');
      const g = await validate(value.graph);
      closeDialog(); confirmReplace(() => { draft = { title: String(value.title || '불러온 묶음').slice(0, 80), folder: 'personal', graph: g, project: value.project || '', allowed_paths: Array.isArray(value.allowed_paths) ? value.allowed_paths : [] };
        active = null; selected = g.nodes[0]?.id; edited(); renderEditor(); renderDrawer(); message('불러왔어요. 실행 전 입력·대상·범위를 다시 확인해 주세요.'); });
    }, { class: 'wb-btn primary' })); text.focus();
  }

  async function prepare() {
    const hasModel = draft.graph.nodes.some(n => catalog.operations[definition(n)?.spec.operation]?.mode === 'model');
    const body = { title: draft.title, graph: copy(draft.graph), project: draft.project || null, allowed_paths: hasModel ? draft.allowed_paths : [] };
    const plan = await Data.workbenchPost('plan', body), requestId = crypto.randomUUID().replaceAll('-', '');
    const d = modal('실행 전 계획 확인'), content = d.querySelector('.wb-dialog-body');
      content.append(...children([h('p', { class: 'wb-plan-summary', text: `${plan.project_title} · 모델 호출 최대 ${plan.max_model_calls}회` }),
      h('h3', { text: '처리 순서' }), h('ol', {}, plan.steps.map(s => h('li', {}, h('strong', { text: `${s.title} · ${MODE[s.mode]}` }), h('p', { text: s.description })))),
      h('h3', { text: '파일 변경 허용 범위' }), h('pre', { text: plan.allowed_paths.join('\n') || '없음 · 글 처리만 수행' }),
      plan.models.length ? h('div', {}, h('h3', { text: '기존 직원·선택한 모델' }), ...plan.models.map(m => h('p', { text: `${m.title} · ${m.effective_runtime} / ${m.effective_model || '기본 모델'} · ${m.sandbox} · 도구 ${m.mcp.map(s => s.name).join(', ') || '없음'}` }))) : null,
      h('p', { class: 'wb-hint', text: plan.policy }),
        plan.uses_models && Data.get().studio.fake ? h('p', { class: 'wb-hint', text: '현재 연습용 회사입니다. 기존 가짜 실행기를 사용하며 실제 모델을 호출하지 않습니다.' }) : null]));
    const confirmed = h('input', { type: 'checkbox', name: 'plan-confirm' }), allowModels = h('input', { type: 'checkbox', name: 'model-confirm' });
    content.append(field('계획과 허용 범위를 확인했습니다', confirmed, 'wb-check'));
    if (plan.uses_models) content.append(field('표시된 직원·모델 사용을 허용합니다', allowModels, 'wb-check'));
    const start = button('확인한 계획 실행', async () => {
      if (!confirmed.checked || (plan.uses_models && !allowModels.checked)) return;
      const res = await Data.workbenchPost('start', { ...body, plan_hash: plan.hash, request_id: requestId, confirmed: true, allow_models: plan.uses_models });
      remember(); closeDialog(); await openRun(res.run.id); await refresh(); message('실행을 시작했어요. 결재는 기존 결재 창에서 직접 확인합니다.');
    }, { class: 'wb-btn primary', disabled: true });
    const check = () => { start.disabled = !confirmed.checked || (plan.uses_models && !allowModels.checked) || Boolean(start.dataset.busy); };
    confirmed.addEventListener('change', check); allowModels.addEventListener('change', check);
    d.querySelector('footer').append(button('닫기', closeDialog), start);
  }

  return { init, setVisible, refresh };
})();
