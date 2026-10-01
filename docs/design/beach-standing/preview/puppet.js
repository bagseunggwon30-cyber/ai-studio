/* AI 스튜디오 — 인형 엔진 (그림 한 장을 촘촘한 그물로 나눠 WebGL로 휘어서 라이브2D처럼 움직인다)
 *
 * 진짜 라이브2D는 유료 SDK와 부위별 원화가 필요하고 우리 규칙(외부 라이브러리·CDN 없음)에 맞지 않아 작은 엔진을 직접 만들었다.
 * 진행판 발표 캐릭터(board.js)가 쓴다. 뼈대 규격은 mascot.json의 `rig` (docs/design/mascot.md '뼈대(rig)').
 *
 * 구조: [규격 검사 cleanRig] → [영역 무게·그물 buildGrid·휘기 deform] → [스프링 물리 stepPhysics] → [움직임 조종 createMotion] → [WebGL 그리기 create]
 * 앞의 네 조각은 DOM·WebGL 없이 도는 순수 계산이라 node에서 시험한다 (tools/dev/puppet_sim.js, Puppet.logic).
 *
 * 좌표는 모두 '뼈대 좌표' = 평소(normal) 그림의 픽셀 좌표. 매개변수는 -1..1 (breath·eyeOpen·mouthOpen·point는 0..1).
 * 화면에 넣는 글자는 textContent로만, 스타일은 CSSOM으로만 (CSP). 그림 이름·숫자는 믿지 않고 cleanRig가 다 걸러 낸다.
 */
'use strict';

const Puppet = (() => {
  // ---------------------------------------------------------------- 규격
  const STANDARD = ['angleX', 'angleY', 'angleZ', 'bodyX', 'bodyZ', 'breath', 'eyeOpen', 'eyeX', 'eyeY', 'mouthOpen', 'point', 'posY', 'squash'];
  const STD = new Set(STANDARD);
  const UNIT01 = new Set(['breath', 'eyeOpen', 'mouthOpen', 'point']); // 0..1 (나머지는 -1..1)
  const DEFAULTS = { angleX: 0, angleY: 0, angleZ: 0, bodyX: 0, bodyZ: 0, breath: 0, eyeOpen: 1, eyeX: 0, eyeY: 0, mouthOpen: 0, point: 0, posY: 0, squash: 0 };
  const NAME_RE = /^[A-Za-z][A-Za-z0-9_]{0,23}$/;
  const IMAGE_RE = /^[A-Za-z0-9_@.-]{1,80}\.png$/; // board.js의 IMAGE_RE와 같은 규칙
  const MOOD_NAMES = ['normal', 'happy', 'worried'];
  const BASE_KEYS = ['normal', 'happy', 'worried', 'point'];
  const TYPES = ['rotate', 'shift', 'scale'];
  const LIMIT = { regions: 32, poly: 64, deformers: 64, physics: 16, layers: 24, inputs: 8 };
  const PHYS_LIMIT = 1.5; // 물리 값 범위

  const fin = (v) => typeof v === 'number' && Number.isFinite(v);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const clamp01 = (v) => Math.min(1, Math.max(0, v));
  const smooth = (t) => { const u = clamp01(t); return u * u * (3 - 2 * u); };
  const rangeOf = (name) => (UNIT01.has(name) ? [0, 1] : [-1, 1]);

  // ---------------------------------------------------------------- 1) 규격 검사
  // 검사에서 걸리면 예외로 빠져나와 cleanRig가 null을 돌려준다 (숫자는 범위 안으로 자르되, 숫자가 아니면 거절)
  function need(ok) { if (!ok) throw new Error('rig'); }
  function numIn(v, lo, hi) { need(fin(v)); return clamp(v, lo, hi); }
  const isObj = (v) => Boolean(v) && typeof v === 'object' && !Array.isArray(v);
  const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

  function cleanPoint(v, size) {
    need(Array.isArray(v) && v.length === 2);
    return [numIn(v[0], -size.w, size.w * 2), numIn(v[1], -size.h, size.h * 2)];
  }

  function cleanRegion(r, size) {
    need(isObj(r) && (r.ellipse !== undefined) !== (r.poly !== undefined));
    const feather = r.feather === undefined ? 0 : numIn(r.feather, 0, Math.max(size.w, size.h));
    if (r.ellipse !== undefined) {
      need(Array.isArray(r.ellipse) && r.ellipse.length === 4);
      const [cx, cy] = cleanPoint(r.ellipse.slice(0, 2), size);
      const rx = numIn(r.ellipse[2], 1, size.w * 2);
      const ry = numIn(r.ellipse[3], 1, size.h * 2);
      return { kind: 'ellipse', c: [cx, cy, rx, ry], feather, bbox: [cx - rx - feather, cy - ry - feather, cx + rx + feather, cy + ry + feather] };
    }
    need(Array.isArray(r.poly) && r.poly.length >= 3 && r.poly.length <= LIMIT.poly);
    const pts = [];
    const bbox = [Infinity, Infinity, -Infinity, -Infinity];
    for (const p of r.poly) {
      const [x, y] = cleanPoint(p, size);
      pts.push(x, y);
      bbox[0] = Math.min(bbox[0], x); bbox[1] = Math.min(bbox[1], y); bbox[2] = Math.max(bbox[2], x); bbox[3] = Math.max(bbox[3], y);
    }
    return { kind: 'poly', pts, feather, bbox: [bbox[0] - feather, bbox[1] - feather, bbox[2] + feather, bbox[3] + feather] };
  }

  function cleanShow(s, isParam) {
    if (s === undefined) return null;
    need(isObj(s) && typeof s.param === 'string' && isParam(s.param));
    const min = s.min === undefined ? -Infinity : numIn(s.min, -100, 100);
    const max = s.max === undefined ? Infinity : numIn(s.max, -100, 100);
    need(min <= max);
    return { param: s.param, min, max, fade: s.fade === undefined ? 0.1 : numIn(s.fade, 0.001, 2) };
  }

  // raw = mascot.json의 rig, normal = 평소 그림 { x, y, h } (상자 좌표), extra = { base: 그림 폴더 주소, blink: cleanMascot의 anim.blink }
  function clean(raw, normal, extra) {
    need(isObj(raw) && raw.version === 1);
    need(isObj(raw.size));
    const size = { w: Math.round(numIn(raw.size.w, 16, 8192)), h: Math.round(numIn(raw.size.h, 16, 8192)) };
    const g = raw.grid === undefined ? {} : raw.grid;
    need(isObj(g));
    const grid = {
      cols: g.cols === undefined ? clamp(Math.round(size.w / 19), 4, 64) : Math.round(numIn(g.cols, 4, 64)),
      rows: g.rows === undefined ? clamp(Math.round(size.h / 19), 4, 64) : Math.round(numIn(g.rows, 4, 64)),
    };
    const base = typeof extra.base === 'string' ? extra.base : '';

    const regions = {};
    const rawRegions = raw.regions === undefined ? {} : raw.regions;
    need(isObj(rawRegions) && Object.keys(rawRegions).length <= LIMIT.regions);
    for (const name of Object.keys(rawRegions)) {
      need(NAME_RE.test(name));
      regions[name] = cleanRegion(rawRegions[name], size);
    }

    // 물리 (out은 표준 매개변수 이름이 아닌 아무 이름. 표준 매개변수만 입력으로 받는다)
    const physics = [];
    const rawPhys = raw.physics === undefined ? [] : raw.physics;
    need(Array.isArray(rawPhys) && rawPhys.length <= LIMIT.physics);
    const outs = new Set();
    for (const p of rawPhys) {
      need(isObj(p) && typeof p.out === 'string' && NAME_RE.test(p.out) && !STD.has(p.out) && !outs.has(p.out));
      need(Array.isArray(p.in) && p.in.length >= 1 && p.in.length <= LIMIT.inputs);
      // 입력 [이름, 가중치, (선택) 속도 반영 초]: 세 번째 숫자는 입력이 움직이는 속도를 목표에 얼마나 더할지 (음수면 반대로 쏠림)
      const ins = p.in.map((pair) => {
        need(Array.isArray(pair) && (pair.length === 2 || pair.length === 3) && typeof pair[0] === 'string' && STD.has(pair[0]));
        return [pair[0], numIn(pair[1], -4, 4), pair.length === 3 ? numIn(pair[2], -1, 1) : 0];
      });
      outs.add(p.out);
      physics.push({
        out: p.out, in: ins,
        stiffness: p.stiffness === undefined ? 20 : numIn(p.stiffness, 1, 300),
        damping: p.damping === undefined ? 3.5 : numIn(p.damping, 0.1, 60),
      });
    }
    const isParam = (n) => STD.has(n) || outs.has(n);

    // 층 (그리는 순서). 없으면 base + (anim.blink가 있으면) blink 층을 자동으로
    const layers = [];
    if (raw.layers === undefined) {
      layers.push({ id: 'base', src: null, x: 0, y: 0, h: size.h, show: null, mask: null, moods: null, under: false });
      const b = extra.blink;
      if (b && normal && fin(normal.h) && normal.h > 0 && fin(b.x) && fin(b.y) && fin(b.h) && typeof b.src === 'string') {
        const s = size.h / normal.h; // 상자 좌표 → 뼈대 좌표
        const eyesOnly = b.eyesOnly === true;
        if (!eyesOnly || hasOwn(regions, 'eyes')) { // 전신 눈 감은 그림은 eyes 영역이 있어야 눈 주변만 겹친다
          layers.push({
            id: 'blink', src: b.src, x: (b.x - normal.x) * s, y: (b.y - normal.y) * s, h: b.h * s,
            show: { param: 'eyeOpen', min: -Infinity, max: 0.35, fade: 0.1 }, mask: eyesOnly ? 'eyes' : null, moods: ['normal'], under: false,
          });
        }
      }
    } else {
      need(Array.isArray(raw.layers) && raw.layers.length >= 1 && raw.layers.length <= LIMIT.layers);
      const seen = new Set();
      for (const l of raw.layers) {
        need(isObj(l) && typeof l.id === 'string' && NAME_RE.test(l.id) && !seen.has(l.id));
        seen.add(l.id);
        if (l.id === 'base') {
          need(l.image === undefined);
          layers.push({ id: 'base', src: null, x: 0, y: 0, h: size.h, show: null, mask: null, moods: null, under: false });
          continue;
        }
        need(typeof l.image === 'string' && IMAGE_RE.test(l.image));
        need(l.mask === undefined || (typeof l.mask === 'string' && hasOwn(regions, l.mask)));
        let moods = null;
        if (l.moods !== undefined) {
          need(Array.isArray(l.moods) && l.moods.length >= 1 && l.moods.every((m) => MOOD_NAMES.includes(m)));
          moods = [...new Set(l.moods)];
        }
        layers.push({
          id: l.id, src: base + l.image, x: numIn(l.x, -size.w, size.w * 2), y: numIn(l.y, -size.h, size.h * 2), h: numIn(l.h, 1, size.h * 2),
          show: cleanShow(l.show, isParam), mask: l.mask === undefined ? null : l.mask, moods, under: l.under === true,
        });
      }
      need(seen.has('base'));
    }
    const layerIds = new Set(layers.map((l) => l.id));

    // 휘기 (적힌 순서대로 적용)
    const deformers = [];
    const rawDef = raw.deformers === undefined ? [] : raw.deformers;
    need(Array.isArray(rawDef) && rawDef.length <= LIMIT.deformers);
    for (const d of rawDef) {
      need(isObj(d) && TYPES.includes(d.type));
      need(d.region === '*' || (typeof d.region === 'string' && hasOwn(regions, d.region)));
      need(typeof d.param === 'string' && isParam(d.param));
      const out = { type: d.type, region: d.region, param: d.param, falloff: null, layers: null };
      if (d.type === 'rotate') {
        out.pivot = cleanPoint(d.pivot, size);
        out.k = numIn(d.k, -180, 180);
      } else if (d.type === 'shift') {
        out.pivot = [0, 0];
        out.kx = d.kx === undefined ? 0 : numIn(d.kx, -size.w, size.w);
        out.ky = d.ky === undefined ? 0 : numIn(d.ky, -size.h, size.h);
      } else {
        out.pivot = cleanPoint(d.pivot, size);
        out.kx = d.kx === undefined ? 0 : numIn(d.kx, -0.9, 3);
        out.ky = d.ky === undefined ? 0 : numIn(d.ky, -0.9, 3);
      }
      if (d.falloff !== undefined) {
        need(isObj(d.falloff));
        const from = cleanPoint(d.falloff.from, size);
        const to = cleanPoint(d.falloff.to, size);
        need(from[0] !== to[0] || from[1] !== to[1]);
        out.falloff = { from, to, power: d.falloff.power === undefined ? 1 : numIn(d.falloff.power, 0.2, 4) };
      }
      if (d.layers !== undefined) { // 이 층들의 꼭짓점에만 적용 (없으면 모든 층)
        need(Array.isArray(d.layers) && d.layers.length >= 1 && d.layers.length <= LIMIT.layers);
        need(d.layers.every((id) => typeof id === 'string' && layerIds.has(id)));
        out.layers = [...new Set(d.layers)];
      }
      deformers.push(out);
    }

    // 뼈대 모드에서 base 층이 표정 그림 대신 쓰는 그림 (2단계: 머리카락을 떼어 낸 몸 그림)
    let bases = null;
    if (raw.bases !== undefined) {
      need(isObj(raw.bases));
      bases = {};
      for (const [key, name] of Object.entries(raw.bases)) {
        need(BASE_KEYS.includes(key) && typeof name === 'string' && IMAGE_RE.test(name));
        bases[key] = base + name;
      }
    }

    return { version: 1, size, grid, regions, deformers, physics, layers, bases, usesPoint: deformers.some((d) => d.param === 'point') };
  }

  function cleanRig(raw, normal, extra) {
    try { return clean(raw, normal || null, extra || {}); } catch (_) { return null; }
  }

  // '#pose=angleZ:1,hairSway:-1' → { angleZ: 1, hairSway: -1 } (이름은 규칙대로, 값은 -1.5..1.5)
  function parsePose(text) {
    const out = {};
    for (const part of String(text || '').split(',')) {
      const [name, raw] = part.split(':');
      const v = Number(raw);
      if (NAME_RE.test(String(name).trim()) && raw !== undefined && raw.trim() !== '' && Number.isFinite(v)) out[name.trim()] = clamp(v, -PHYS_LIMIT, PHYS_LIMIT);
    }
    return out;
  }

  // ---------------------------------------------------------------- 2) 영역 무게 · 그물 · 휘기
  function segDist(px, py, ax, ay, bx, by) {
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 ? clamp01(((px - ax) * dx + (py - ay) * dy) / len2) : 0;
    return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
  }

  function insidePoly(pts, x, y) { // 짝수-홀수 규칙
    let inside = false;
    const n = pts.length / 2;
    for (let i = 0, j = n - 1; i < n; j = i++) {
      const xi = pts[2 * i]; const yi = pts[2 * i + 1]; const xj = pts[2 * j]; const yj = pts[2 * j + 1];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  // 영역의 무게 0..1: 안쪽 1, 바깥으로 feather 동안 smoothstep으로 0. '*'(또는 없음)는 어디나 1.
  function regionWeight(region, x, y) {
    if (!region || region === '*') return 1;
    if (region.kind === 'ellipse') {
      const [cx, cy, rx, ry] = region.c;
      const u = (x - cx) / rx;
      const v = (y - cy) / ry;
      const d = Math.hypot(u, v);
      if (d <= 1) return 1;
      if (!(region.feather > 0)) return 0;
      const dist = ((d - 1) * d) / Math.hypot(u / rx, v / ry); // 타원 바깥선까지의 거리(1차 근사)
      return 1 - smooth(dist / region.feather);
    }
    if (insidePoly(region.pts, x, y)) return 1;
    if (!(region.feather > 0)) return 0;
    const p = region.pts;
    const n = p.length / 2;
    let dist = Infinity;
    for (let i = 0, j = n - 1; i < n; j = i++) dist = Math.min(dist, segDist(x, y, p[2 * j], p[2 * j + 1], p[2 * i], p[2 * i + 1]));
    return 1 - smooth(dist / region.feather);
  }

  function falloffAt(f, x, y) { // from→to 방향 사영 비율(0..1로 자름)^power
    const dx = f.to[0] - f.from[0];
    const dy = f.to[1] - f.from[1];
    const t = clamp01(((x - f.from[0]) * dx + (y - f.from[1]) * dy) / (dx * dx + dy * dy));
    return Math.pow(t, f.power);
  }

  // 한 층의 그물. rect = 이 층이 뼈대 좌표에서 차지하는 자리 { x, y, w, h }.
  // opts: cols·rows(없으면 기본 그물과 같은 칸 크기), uv(그림 전체 자리, 없으면 rect), mask(영역 이름: 그 무게를 꼭짓점 알파로, 그물은 그 영역 둘레만 더 촘촘히), layer(층 id)
  // 무게는 '쉬는 자리'에서 한 번만 계산해 둔다 (휘어진 뒤 자리로 다시 계산하지 않는다).
  function buildGrid(rig, rect, opts = {}) {
    let { x, y, w, h } = rect;
    const uv = opts.uv || rect;
    const mask = opts.mask ? rig.regions[opts.mask] : null;
    if (mask) { // 마스크 영역 둘레만 (전신 눈 감은 그림도 눈 주변 작은 그물만 만든다)
      const [x0, y0, x1, y1] = mask.bbox;
      const nx0 = Math.max(x, x0); const ny0 = Math.max(y, y0); const nx1 = Math.min(x + w, x1); const ny1 = Math.min(y + h, y1);
      if (nx1 > nx0 && ny1 > ny0) { x = nx0; y = ny0; w = nx1 - nx0; h = ny1 - ny0; }
    }
    const cw = (mask ? 0.5 : 1) * (rig.size.w / rig.grid.cols);
    const ch = (mask ? 0.5 : 1) * (rig.size.h / rig.grid.rows);
    const cols = opts.cols || clamp(Math.ceil(w / Math.max(4, cw)), 1, 64);
    const rows = opts.rows || clamp(Math.ceil(h / Math.max(4, ch)), 1, 64);
    const n = (cols + 1) * (rows + 1);
    const layer = opts.layer || 'base';
    const rest = new Float32Array(n * 2);
    const uvs = new Float32Array(n * 2);
    const alpha = new Float32Array(n);
    const active = [];
    rig.deformers.forEach((d, i) => { if (!d.layers || d.layers.includes(layer)) active.push(i); });
    const wts = rig.deformers.map((_, i) => (active.includes(i) ? new Float32Array(n) : null));
    for (let r = 0; r <= rows; r++) {
      for (let c = 0; c <= cols; c++) {
        const v = r * (cols + 1) + c;
        const px = x + (w * c) / cols;
        const py = y + (h * r) / rows;
        rest[2 * v] = px; rest[2 * v + 1] = py;
        uvs[2 * v] = (px - uv.x) / uv.w; uvs[2 * v + 1] = (py - uv.y) / uv.h;
        alpha[v] = mask ? regionWeight(mask, px, py) : 1;
        for (const i of active) {
          const d = rig.deformers[i];
          let wt = regionWeight(d.region === '*' ? null : rig.regions[d.region], px, py);
          if (wt > 0 && d.falloff) wt *= falloffAt(d.falloff, px, py);
          wts[i][v] = wt;
        }
      }
    }
    const index = new Uint16Array(cols * rows * 6);
    let k = 0;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const a = r * (cols + 1) + c;
        const b = a + 1;
        const d = a + cols + 1;
        index[k++] = a; index[k++] = b; index[k++] = d; index[k++] = b; index[k++] = d + 1; index[k++] = d;
      }
    }
    return { cols, rows, n, rest, uv: uvs, alpha, w: wts, active, layer, rect: { x, y, w, h }, index };
  }

  // 그물 꼭짓점을 매개변수(params)대로 휜다: p = p + w·(T(p) − p), 적힌 순서대로 (나중 것은 이미 휜 자리에 적용).
  // rotate = pivot 둘레 k·값 도 (양수는 시계 방향, 화면 기준), shift = (kx·값, ky·값), scale = pivot 기준 1+kx·값, 1+ky·값.
  function deform(grid, rig, params, out = new Float32Array(grid.rest.length)) {
    const rest = grid.rest;
    const n = grid.n;
    for (let i = 0; i < rest.length; i++) out[i] = rest[i];
    for (const i of grid.active) {
      const d = rig.deformers[i];
      const val = params[d.param];
      if (!val) continue; // 0이면 아무것도 안 함 (NaN·undefined 포함)
      const w = grid.w[i];
      if (d.type === 'rotate') {
        const a = (d.k * val * Math.PI) / 180;
        const c = Math.cos(a); const s = Math.sin(a);
        const px = d.pivot[0]; const py = d.pivot[1];
        for (let v = 0; v < n; v++) {
          const wt = w[v];
          if (!wt) continue;
          const x = out[2 * v]; const y = out[2 * v + 1];
          const dx = x - px; const dy = y - py;
          out[2 * v] = x + wt * (px + dx * c - dy * s - x);
          out[2 * v + 1] = y + wt * (py + dx * s + dy * c - y);
        }
      } else if (d.type === 'shift') {
        const tx = d.kx * val; const ty = d.ky * val;
        for (let v = 0; v < n; v++) {
          const wt = w[v];
          if (!wt) continue;
          out[2 * v] += wt * tx; out[2 * v + 1] += wt * ty;
        }
      } else {
        const sx = 1 + d.kx * val; const sy = 1 + d.ky * val;
        const px = d.pivot[0]; const py = d.pivot[1];
        for (let v = 0; v < n; v++) {
          const wt = w[v];
          if (!wt) continue;
          const x = out[2 * v]; const y = out[2 * v + 1];
          out[2 * v] = x + wt * (px + (x - px) * sx - x);
          out[2 * v + 1] = y + wt * (py + (y - py) * sy - y);
        }
      }
    }
    return out;
  }

  // ---------------------------------------------------------------- 3) 스프링 물리
  // out 하나마다: 입력 가중합(+ 입력 속도 × 속도 가중치)을 목표로 x'' = stiffness·(목표 − x) − damping·x'. dt가 크면 잘게 쪼개 계산, 값은 -1.5..1.5.
  function makePhysics() { return { x: {}, v: {}, prev: {} }; }

  function resetPhysics(state, list) { for (const p of list) { state.x[p.out] = 0; state.v[p.out] = 0; } state.prev = {}; }

  function physicsTarget(p, params, prev, dt) {
    let target = 0;
    for (const [name, wt, vg] of p.in) {
      const val = fin(params[name]) ? params[name] : 0;
      target += wt * val;
      if (vg && dt > 0 && prev[name] !== undefined) target += (vg * (val - prev[name])) / dt;
    }
    return clamp(target, -PHYS_LIMIT, PHYS_LIMIT);
  }

  function stepPhysics(state, list, params, dt) {
    const d = fin(dt) ? clamp(dt, 0, 0.5) : 0;
    const steps = d > 0 ? Math.min(60, Math.ceil(d * 60)) : 0;
    const h = steps ? d / steps : 0;
    for (const p of list) {
      let x = fin(state.x[p.out]) ? state.x[p.out] : 0;
      let v = fin(state.v[p.out]) ? state.v[p.out] : 0;
      const target = physicsTarget(p, params, state.prev, d);
      for (let i = 0; i < steps; i++) {
        v += (p.stiffness * (target - x) - p.damping * v) * h;
        x += v * h;
        if (x > PHYS_LIMIT || x < -PHYS_LIMIT) { x = clamp(x, -PHYS_LIMIT, PHYS_LIMIT); v = 0; }
      }
      state.x[p.out] = x; state.v[p.out] = v;
      params[p.out] = x;
    }
    for (const p of list) for (const [name] of p.in) if (fin(params[name])) state.prev[name] = params[name];
  }

  // 멈춘 자세: 물리 out은 (자세에 적혀 있지 않으면) 입력이 그대로 있을 때의 자리
  function steadyPhysics(list, params) {
    for (const p of list) if (!hasOwn(params, p.out)) params[p.out] = physicsTarget(p, params, {}, 0);
  }

  // ---------------------------------------------------------------- 4) 움직임 조종
  // 뼈대마다 따로 적지 않고 엔진이 표준 매개변수를 직접 움직인다: 가만히(느린 잡음)·숨쉬기·바라보기·깜빡임·표정(폴짝·흔들림·고개 숙임)·손짓·말하기.
  // 시계와 난수는 밖에서 넣을 수 있다 (시험에서 가짜 시계·난수로 시간표를 확인).
  const TAU = Math.PI * 2;
  const wave = (s, a, pa, b, pb) => 0.6 * Math.sin((s * TAU) / a + pa) + 0.4 * Math.sin((s * TAU) / b + pb);
  // 가끔 멈춰 있는 순간: 0..1 (0이면 아주 잠깐 완전히 멈춘다). 계속 출렁이면 그림이 늘어나 보인다
  const rest = (s, period, phase) => smooth(0.5 + 0.9 * Math.sin((s * TAU) / period + phase));
  const pulse = (u, at, amp, len) => (u >= at ? amp * Math.exp(-(u - at) / len) : 0); // 착지 때 눌림

  function createMotion(opts = {}) {
    const clock = opts.now || (() => (typeof performance !== 'undefined' ? performance.now() : Date.now()));
    const rnd = opts.random || Math.random;
    const reduced = opts.reduced || (() => false);
    const P = { ...DEFAULTS };
    const t0 = clock();
    let last = t0;
    let mood = 'normal';
    let hop = null; let shake = null; let pointing = null; let talking = null; // { at, ms }
    let bow = 0;
    const look = { x: 0, y: 0, tx: 0, ty: 0, on: false };
    const blinkDelay = () => 2600 + rnd() * 3400; // 2.6~6초마다
    let nextBlink = t0 + blinkDelay();
    let blinks = []; // 진행 중이거나 곧 시작할 깜빡임의 시작 시각

    const running = (a, t) => (a && t - a.at < a.ms ? a : null);

    function setMood(name, instant = false, t = clock()) {
      if (!MOOD_NAMES.includes(name) || name === mood) return false;
      mood = name;
      blinks = [];
      if (!instant && !reduced()) { // 기쁨은 폴짝, 걱정은 흔들림
        if (name === 'happy') hop = { at: t, ms: 800 };
        else if (name === 'worried') shake = { at: t, ms: 700 };
      }
      return true;
    }

    // 손짓: 평소 얼굴일 때만 (기쁨·걱정은 폴짝·흔들림이 대신한다). 하면 true
    function point(ms = 1300, t = clock()) {
      if (reduced() || mood !== 'normal') return false;
      pointing = { at: t, ms };
      return true;
    }

    function talk(ms = 1500, t = clock()) {
      if (reduced()) return false;
      talking = { at: t, ms };
      return true;
    }

    // 바라보기: x·y는 -1..1 (화면 오른쪽·아래가 +), null이면 진행판을 떠난 것
    function lookAt(x, y) {
      if (x === null || x === undefined) { look.on = false; return; }
      look.on = true;
      look.tx = clamp(fin(x) ? x : 0, -1, 1);
      look.ty = clamp(fin(y) ? y : 0, -1, 1);
    }

    function update(t = clock()) {
      const dt = clamp((t - last) / 1000, 0, 0.1);
      last = t;
      if (reduced()) { // 효과 끔: 모두 0(눈은 뜸)으로 한 장만
        Object.assign(P, DEFAULTS);
        look.x = 0; look.y = 0; look.on = false; bow = 0; hop = null; shake = null; pointing = null; talking = null; blinks = [];
        return P;
      }
      const s = (t - t0) / 1000;
      // 가만히: 작고 느린 잡음(5~8초 주기)에 가끔 쉬는 순간. 매개변수로 angleX ±0.4, angleY ±0.3, angleZ ±0.25, bodyX ±0.2, bodyZ ±0.33
      let angleX = 0.4 * wave(s, 7.3, 0.4, 5.9, 2.1) * rest(s, 19, 0.9);
      let angleY = 0.3 * wave(s, 8.1, 1.3, 5.5, 0.2) * rest(s, 23, 2.4);
      let angleZ = 0.25 * wave(s, 7.1, 2.6, 5.3, 0.9) * rest(s, 17, 0.3);
      let bodyX = 0.2 * wave(s, 8.3, 0.7, 6.1, 3.0) * rest(s, 21, 1.7);
      let bodyZ = 0.33 * wave(s, 6.7, 1.7, 5.1, 0.3) * rest(s, 29, 3.9);
      let posY = 0;
      let squash = 0;

      // 바라보기: 가만히 움직임과 섞는다. 나가면 1초쯤에 걸쳐 돌아온다
      const k = 1 - Math.exp(-dt / (look.on ? 0.25 : 0.35));
      look.x += ((look.on ? look.tx : 0) - look.x) * k;
      look.y += ((look.on ? look.ty : 0) - look.y) * k;
      const mix = clamp01(Math.hypot(look.x, look.y));
      angleX = angleX * (1 - 0.7 * mix) + look.x * 0.6;
      angleY = angleY * (1 - 0.7 * mix) - look.y * 0.6; // 위를 보면 고개를 든다(+)
      angleZ += look.x * 0.25; // 포인터 쪽으로 아주 조금 갸웃

      // 고개 숙임(걱정): 부드럽게 -0.3까지
      bow += ((mood === 'worried' ? -0.3 : 0) - bow) * (1 - Math.exp(-dt / 0.3));
      angleY += bow;

      // 깜빡임: 눈 1→0(60ms) 유지(40ms) 0→1(90ms), 25%는 두 번 (평소 얼굴·손짓 아닐 때만)
      if (t >= nextBlink) {
        if (mood === 'normal' && !running(pointing, t)) {
          blinks.push(t);
          if (rnd() < 0.25) blinks.push(t + 260);
        }
        nextBlink = t + blinkDelay();
      }
      let closed = 0;
      blinks = blinks.filter((b) => t - b < 190);
      for (const b of blinks) {
        const u = t - b;
        if (u < 0) continue;
        closed = Math.max(closed, u < 60 ? u / 60 : u < 100 ? 1 : 1 - (u - 100) / 90);
      }

      // 기쁨 폴짝 (0.8초, 두 번 튄다: 큰 것 → 작은 것) · 걱정 흔들림 (0.7초 진동)
      const hopNow = running(hop, t);
      if (!hopNow) hop = null;
      else {
        const u = (t - hop.at) / hop.ms;
        const y = u < 0.4 ? Math.sin((Math.PI * u) / 0.4) : u < 0.8 ? 0.55 * Math.sin((Math.PI * (u - 0.4)) / 0.4) : 0;
        posY += y;
        squash += -0.5 * y + pulse(u, 0.4, 0.8, 0.05) + pulse(u, 0.8, 0.5, 0.05);
      }
      const shakeNow = running(shake, t);
      if (!shakeNow) shake = null;
      else {
        const u = (t - shake.at) / shake.ms;
        const tt = (u * shake.ms) / 1000;
        angleZ += 0.3 * Math.sin(TAU * 3.5 * tt) * (1 - u);
        bodyX += 0.8 * Math.sin(TAU * 3.5 * tt + 0.5) * (1 - u);
      }

      // 손짓: point 0→1→0 + 판 쪽(왼쪽)으로 기울기
      let pointEnv = 0;
      const pnow = running(pointing, t);
      if (!pnow) pointing = null;
      else {
        const u = clamp01((t - pointing.at) / pointing.ms);
        pointEnv = Math.min(smooth(u / 0.3), smooth((1 - u) / 0.3));
        bodyZ -= 0.7 * pointEnv;
        bodyX -= 0.25 * pointEnv;
      }

      // 말하기: 음절처럼 입을 여닫는다. 말하는 동안 0.12(다문 입)~1(벌림)을 오가고, 말하지 않을 때는 0 = 입 조각 없이 원래 그림 그대로.
      // 입 층은 show 범위로 고른다 (기본 하나: mouthOpen 0.04~0.42 다문 입 조각, 0.3~0.8 반쯤 벌린 조각, 그 밖은 원래 그림의 벌린 웃음)
      let mouth = 0;
      const tnow = running(talking, t);
      if (!tnow) talking = null;
      else {
        const tt = (t - talking.at) / 1000;
        const env = Math.min(1, tt / 0.12, (talking.ms / 1000 - tt) / 0.15);
        const shape = (0.5 + 0.5 * Math.sin(TAU * 4.6 * tt)) * (0.7 + 0.3 * Math.sin(TAU * 1.3 * tt + 0.7));
        mouth = clamp01(env) * (0.12 + 0.88 * shape);
      }

      P.angleX = clamp(angleX, -1, 1);
      P.angleY = clamp(angleY, -1, 1);
      P.angleZ = clamp(angleZ, -1, 1);
      P.bodyX = clamp(bodyX, -1, 1);
      P.bodyZ = clamp(bodyZ, -1, 1);
      P.posY = clamp(posY, -1, 1);
      P.squash = clamp(squash, -1, 1);
      P.breath = (1 - Math.cos((TAU * s) / 4.6)) / 2; // 4.6초 주기
      P.eyeOpen = 1 - closed;
      P.eyeX = clamp(look.x, -1, 1);
      P.eyeY = clamp(-look.y, -1, 1);
      P.mouthOpen = clamp01(mouth);
      P.point = pointEnv;
      return P;
    }

    return {
      params: P, update, setMood, point, talk, lookAt,
      get mood() { return mood; },
      isPointing: (t = clock()) => Boolean(running(pointing, t)),
    };
  }

  // ---------------------------------------------------------------- 5) WebGL 인형
  const VERT = 'attribute vec2 a_pos;attribute vec2 a_uv;attribute float a_a;uniform vec4 u_view;varying vec2 v_uv;varying float v_a;'
    + 'void main(){gl_Position=vec4(a_pos*u_view.xy+u_view.zw,0.0,1.0);v_uv=a_uv;v_a=a_a;}';
  const FRAG = 'precision mediump float;uniform sampler2D u_tex;uniform float u_alpha;varying vec2 v_uv;varying float v_a;'
    + 'void main(){gl_FragColor=texture2D(u_tex,v_uv)*(v_a*u_alpha);}';
  const FADE_S = 0.25; // 표정 바뀔 때 겹쳐 바뀌는 시간

  let glOk = null;
  function supported() {
    if (glOk !== null) return glOk;
    glOk = false;
    try {
      if (typeof document === 'undefined') return false;
      const gl = document.createElement('canvas').getContext('webgl', { premultipliedAlpha: true });
      glOk = Boolean(gl) && typeof gl.createProgram === 'function';
      const lose = gl && gl.getExtension('WEBGL_lose_context');
      if (lose) lose.loseContext();
    } catch (_) { glOk = false; }
    return glOk;
  }

  function shader(gl, type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || 'shader');
    return s;
  }

  // 층 보임 정도 0..1: show 범위 안에서 1, 가장자리 fade 동안 부드럽게
  function showAlpha(show, params) {
    if (!show) return 1;
    const v = fin(params[show.param]) ? params[show.param] : 0;
    return clamp01((v - show.min) / show.fade) * clamp01((show.max - v) / show.fade);
  }

  // host 안에 캔버스 인형을 만든다. cfg: { rig, box: {w,h}, normal: {x,y,h}(상자 좌표), images: {normal, happy, worried, point?}, pad(선택: 상자 둘레로 캔버스를 넓힐 여유) }
  // opts: { reduced: () => 효과 끔?, now, random }. WebGL을 못 쓰면 null.
  function create(host, cfg, opts = {}) {
    if (!supported()) return null;
    const rig = cfg.rig;
    const reduced = opts.reduced || (() => false);
    const canvas = document.createElement('canvas');
    canvas.className = 'bd-puppet';
    canvas.setAttribute('aria-hidden', 'true');
    let gl = null;
    try { gl = canvas.getContext('webgl', { premultipliedAlpha: true, alpha: true, antialias: false }); } catch (_) { gl = null; }
    if (!gl) return null;
    host.append(canvas);

    const motion = createMotion({ now: opts.now, random: opts.random, reduced });
    const phys = makePhysics();
    const imgs = {}; // 뼈대 모드에서 base가 쓰는 그림 (bases가 표정 그림을 대신한다, 없는 것은 건너뜀)
    for (const [key, src] of Object.entries({ ...cfg.images, ...(rig.bases || {}) })) if (typeof src === 'string' && src) imgs[key] = src;
    const pointImage = Boolean(imgs.point) && !rig.usesPoint; // 손짓 deformer가 없으면 손짓 그림으로 바꿔 보인다
    const order = [...rig.layers.filter((l) => l.under), ...rig.layers.filter((l) => !l.under)];
    const cell = [rig.size.w / rig.grid.cols, rig.size.h / rig.grid.rows];
    const s = cfg.normal.h / rig.size.h; // 뼈대 좌표 → 상자 좌표 배율
    const pad = fin(cfg.pad) ? clamp(cfg.pad, 0, 60) : 0; // 상자 밖으로 휘어 나가는 머리카락이 잘리지 않게 캔버스를 조금 넓힌다
    const bw = cfg.box.w + 2 * pad;
    const bh = cfg.box.h + 2 * pad;
    const view = [(2 * s) / bw, (-2 * s) / bh, (2 * (cfg.normal.x + pad)) / bw - 1, 1 - (2 * (cfg.normal.y + pad)) / bh];
    for (const [prop, v] of [['left', -pad / cfg.box.w], ['top', -pad / cfg.box.h], ['width', bw / cfg.box.w], ['height', bh / cfg.box.h]]) canvas.style.setProperty(prop, `${v * 100}%`);
    const head = (() => { // 바라보기 기준: head 영역의 가운데 (없으면 그림 위쪽)
      const r = rig.regions.head;
      if (!r) return [rig.size.w * 0.55, rig.size.h * 0.2];
      return r.kind === 'ellipse' ? [r.c[0], r.c[1]] : [(r.bbox[0] + r.bbox[2]) / 2, (r.bbox[1] + r.bbox[3]) / 2];
    })();

    let R = null; // GL 자원 (컨텍스트를 잃었다 되찾으면 새로 만든다)
    let dead = false;
    let lost = false;
    let active = false;
    let raf = 0;
    let lastT = 0;
    let pose = null;
    let rect = null;
    let mesh = null; // 마지막으로 그린 base의 휜 꼭짓점 (개발용 그물 보기)
    const fade = { from: 'normal', to: 'normal', t: 1 };
    const pics = new Map(); // 그림 주소 → { img, ok }
    const layers = new Map(); // 층 id → { def, grid, out }

    function initGL() {
      const prog = gl.createProgram();
      gl.attachShader(prog, shader(gl, gl.VERTEX_SHADER, VERT));
      gl.attachShader(prog, shader(gl, gl.FRAGMENT_SHADER, FRAG));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog) || 'link');
      R = {
        aPos: gl.getAttribLocation(prog, 'a_pos'), aUv: gl.getAttribLocation(prog, 'a_uv'), aA: gl.getAttribLocation(prog, 'a_a'),
        uView: gl.getUniformLocation(prog, 'u_view'), uTex: gl.getUniformLocation(prog, 'u_tex'), uAlpha: gl.getUniformLocation(prog, 'u_alpha'),
        tex: new Map(), buf: new Map(),
      };
      gl.useProgram(prog);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); // 곱해진 알파(premultiplied)
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
      gl.clearColor(0, 0, 0, 0);
      gl.uniform1i(R.uTex, 0);
      gl.uniform4f(R.uView, view[0], view[1], view[2], view[3]);
    }

    // ---- 그림
    function pic(src) {
      let p = pics.get(src);
      if (p) return p;
      p = { img: new Image(), ok: false };
      p.img.onload = () => { p.ok = true; onPic(src, p); kick(); };
      p.img.onerror = () => { console.warn(`인형: 그림을 못 읽었어요 ${src}`); };
      p.img.src = src;
      pics.set(src, p);
      return p;
    }

    function onPic(src, p) {
      const ratio = p.img.naturalWidth / p.img.naturalHeight;
      const isBase = Object.values(imgs).includes(src);
      if (isBase && Math.abs(ratio - rig.size.w / rig.size.h) > 0.01) console.warn(`인형: 그림 크기(${p.img.naturalWidth}×${p.img.naturalHeight})가 뼈대 size(${rig.size.w}×${rig.size.h})와 달라요 ${src}`);
    }

    function tex(src) {
      const p = pics.get(src);
      if (!p || !p.ok || !R) return null;
      let t = R.tex.get(src);
      if (!t) {
        t = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, t);
        gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, p.img);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        R.tex.set(src, t);
      }
      return t;
    }

    // ---- 층 그물 (base는 바로, 그림 층은 그림을 읽은 뒤 크기를 알고 나서)
    for (const def of rig.layers) layers.set(def.id, { def, grid: null, out: null });
    for (const [key, src] of Object.entries(imgs)) if (key !== 'point' || pointImage) pic(src); // 손짓 그림은 손짓 deformer가 없을 때만 쓰므로 그때만 읽는다
    for (const def of rig.layers) if (def.src) pic(def.src);

    function gridOf(ls) {
      if (ls.grid) return ls.grid;
      const def = ls.def;
      if (def.id === 'base') {
        ls.grid = buildGrid(rig, { x: 0, y: 0, w: rig.size.w, h: rig.size.h }, { cols: rig.grid.cols, rows: rig.grid.rows, layer: 'base' });
      } else {
        const p = pics.get(def.src);
        if (!p || !p.ok) return null;
        const rectL = { x: def.x, y: def.y, w: (def.h * p.img.naturalWidth) / p.img.naturalHeight, h: def.h };
        ls.grid = buildGrid(rig, rectL, { mask: def.mask, layer: def.id, uv: rectL, cell });
      }
      ls.out = new Float32Array(ls.grid.rest.length);
      return ls.grid;
    }

    function bufOf(ls) {
      let b = R.buf.get(ls.def.id);
      if (b) return b;
      const g = ls.grid;
      const make = (target, data, usage) => { const o = gl.createBuffer(); gl.bindBuffer(target, o); gl.bufferData(target, data, usage); return o; };
      b = {
        pos: make(gl.ARRAY_BUFFER, ls.out.byteLength, gl.DYNAMIC_DRAW), uv: make(gl.ARRAY_BUFFER, g.uv, gl.STATIC_DRAW),
        a: make(gl.ARRAY_BUFFER, g.alpha, gl.STATIC_DRAW), idx: make(gl.ELEMENT_ARRAY_BUFFER, g.index, gl.STATIC_DRAW),
      };
      R.buf.set(ls.def.id, b);
      return b;
    }

    // 층 하나를 (그림, 보임 정도) 목록대로 그린다
    function drawLayer(ls, list, params) {
      const g = gridOf(ls);
      if (!g) return;
      const b = bufOf(ls);
      deform(g, rig, params, ls.out);
      gl.bindBuffer(gl.ARRAY_BUFFER, b.pos);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, ls.out);
      gl.enableVertexAttribArray(R.aPos);
      gl.vertexAttribPointer(R.aPos, 2, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, b.uv);
      gl.enableVertexAttribArray(R.aUv);
      gl.vertexAttribPointer(R.aUv, 2, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, b.a);
      gl.enableVertexAttribArray(R.aA);
      gl.vertexAttribPointer(R.aA, 1, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, b.idx);
      for (const [t, a] of list) {
        gl.bindTexture(gl.TEXTURE_2D, t);
        gl.uniform1f(R.uAlpha, a);
        gl.drawElements(gl.TRIANGLES, g.index.length, gl.UNSIGNED_SHORT, 0);
      }
      if (ls.def.id === 'base') mesh = { cols: g.cols, rows: g.rows, pos: ls.out };
    }

    // ---- 크기 맞추기: 실제 픽셀 = 화면에 보이는 크기 × min(2, devicePixelRatio) (무대가 CSS로 늘거나 줄어도 또렷하게)
    function fit() {
      rect = canvas.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = Math.max(0, Math.round(rect.width * dpr));
      const h = Math.max(0, Math.round(rect.height * dpr));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, canvas.width, canvas.height);
    }

    function poseValues() {
      const p = { ...DEFAULTS, ...pose };
      steadyPhysics(rig.physics, p);
      return p;
    }

    function render(t) {
      if (!R || lost || !active) return;
      fit();
      if (canvas.width < 2 || canvas.height < 2) return;
      const dt = lastT ? clamp((t - lastT) / 1000, 0, 0.1) : 0;
      lastT = t;
      const calm = reduced();
      let params;
      if (pose) params = poseValues();
      else {
        params = motion.update(t);
        if (calm) { for (const p of rig.physics) params[p.out] = 0; resetPhysics(phys, rig.physics); } else stepPhysics(phys, rig.physics, params, dt);
      }
      // 어느 표정 그림을 base로 보일지 (손짓 deformer가 없으면 손짓 그림으로)
      const mood = motion.mood;
      const want = !pose && pointImage && motion.isPointing(t) ? 'point' : mood;
      if (want !== fade.to) { fade.from = fade.to; fade.to = want; fade.t = calm || pose ? 1 : 0; }
      if (fade.t < 1) fade.t = calm ? 1 : Math.min(1, fade.t + dt / FADE_S);

      gl.clear(gl.COLOR_BUFFER_BIT);
      for (const def of order) {
        if (def.moods && !def.moods.includes(mood)) continue;
        const ls = layers.get(def.id);
        if (def.id === 'base') {
          const tNew = tex(imgs[fade.to] || imgs.normal);
          const tOld = tex(imgs[fade.from] || imgs.normal);
          if (fade.t < 1 && tOld && tNew && tOld !== tNew) drawLayer(ls, [[tOld, 1], [tNew, smooth(fade.t)]], params);
          else if (tNew || tOld) drawLayer(ls, [[tNew || tOld, 1]], params);
          continue;
        }
        const a = showAlpha(def.show, params);
        const tx = a > 0.002 ? tex(def.src) : null;
        if (tx) drawLayer(ls, [[tx, a]], params);
      }
    }

    // ---- 돌리기: 보일 때만 requestAnimationFrame (판을 떠나거나 창이 숨으면 멈춤, 효과 끔이면 한 장만 그리고 멈춤)
    const loopOn = () => active && !document.hidden && !reduced() && !pose && host.isConnected && !lost;
    function tick(ts) {
      raf = 0;
      if (dead) return;
      render(ts);
      if (loopOn()) raf = requestAnimationFrame(tick);
    }
    function kick() { if (!dead && !raf && active && host.isConnected) raf = requestAnimationFrame(tick); }

    const onVisible = () => kick();
    const onLost = (e) => { e.preventDefault(); lost = true; };
    const onRestored = () => {
      try { initGL(); lost = false; kick(); } catch (err) { console.warn('인형: 그리기 되살리기 실패', err); }
    };
    let observer = null;
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('resize', onVisible);
    canvas.addEventListener('webglcontextlost', onLost);
    canvas.addEventListener('webglcontextrestored', onRestored);
    if (typeof MutationObserver !== 'undefined') { // 효과 스위치(html.calm)가 바뀌면 다시 돌리거나 멈춘다
      observer = new MutationObserver(onVisible);
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    }

    try { initGL(); } catch (err) {
      console.warn('인형: WebGL 준비 실패', err);
      dead = true;
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('resize', onVisible);
      if (observer) observer.disconnect();
      canvas.remove();
      return null;
    }

    return {
      canvas,
      // 표정 바꾸기: instant면 겹치지 않고 바로 (처음 만들 때)
      setMood(name, instant = false) {
        if (!motion.setMood(name, instant)) return;
        if (instant) { fade.from = name; fade.to = name; fade.t = 1; }
        kick();
      },
      point(ms = 1300) { const ok = motion.point(ms); kick(); return ok; },
      talk(ms = 1500) { const ok = motion.talk(ms); kick(); return ok; },
      // 진행판 위 포인터 (화면 좌표) → 머리·눈이 그쪽으로. null이면 나감
      lookAt(cx, cy) {
        if (cx === null || cx === undefined) { motion.lookAt(null); return; }
        if (!rect || !rect.width || reduced()) return;
        const hx = rect.left + (((head[0] * s + cfg.normal.x + pad) / bw) * rect.width);
        const hy = rect.top + (((head[1] * s + cfg.normal.y + pad) / bh) * rect.height);
        motion.lookAt((cx - hx) / (rect.width * 1.3), (cy - hy) / (rect.height * 1.1));
      },
      setActive(on) { active = Boolean(on); if (active) { lastT = 0; kick(); } },
      // 개발용: 값으로 멈춘 자세 (null이면 다시 저절로 움직임). 물리 out(hairSway 등)도 적을 수 있다
      setPose(values) { pose = values ? { ...values } : null; lastT = 0; kick(); },
      params: () => ({ ...(pose ? poseValues() : motion.params) }),
      debugMesh: () => mesh,
      destroy() {
        dead = true;
        if (raf) cancelAnimationFrame(raf);
        document.removeEventListener('visibilitychange', onVisible);
        window.removeEventListener('resize', onVisible);
        if (observer) observer.disconnect();
        canvas.removeEventListener('webglcontextlost', onLost);
        canvas.removeEventListener('webglcontextrestored', onRestored);
        const lose = gl.getExtension('WEBGL_lose_context');
        if (lose) lose.loseContext();
        canvas.remove();
      },
    };
  }

  // ---------------------------------------------------------------- 6) 개발용 화면 (#view=board&demo=rig): 영역 무게를 색으로 겹쳐 보이고, 매개변수 슬라이더로 자세를 잡는다
  // 서버에 아무것도 보내지 않는다. 글자는 textContent, 스타일은 CSSOM만 (CSP).
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function devView(root, cfg, opts = {}) {
    const rig = cfg.rig;
    const K = Math.min(1.7, 820 / cfg.box.h); // 상자 좌표 → 화면 배율
    const s = (cfg.normal.h / rig.size.h) * K; // 뼈대 좌표 → 화면 배율
    const ox = cfg.normal.x * K;
    const oy = cfg.normal.y * K;
    const wrap = el('div', 'bd-rig-demo');
    const stage = el('div', 'bd-rig-stage');
    stage.style.setProperty('width', `${Math.round(cfg.box.w * K)}px`);
    stage.style.setProperty('height', `${Math.round(cfg.box.h * K)}px`);
    const fig = el('div', 'bd-rig-fig');
    stage.append(fig);

    // 영역 색 (뼈대 좌표 → 낮은 해상도 2D 캔버스). '*'는 색을 안 칠한다
    const names = Object.keys(rig.regions);
    const hslToRgb = (hh) => { const f = (n) => { const k = (n + hh / 30) % 12; return 0.5 - 0.35 * Math.max(-1, Math.min(k - 3, 9 - k, 1)); }; return [f(0) * 255, f(8) * 255, f(4) * 255]; };
    const colors = names.map((_, i) => { const hue = (i * 137.5) % 360; return { rgb: hslToRgb(hue), css: `hsl(${Math.round(hue)}, 85%, 50%)` }; });
    const step = Math.max(2, Math.round(rig.size.h / 260));
    const wc = el('canvas', 'bd-rig-weights');
    wc.width = Math.ceil(rig.size.w / step);
    wc.height = Math.ceil(rig.size.h / step);
    wc.style.setProperty('left', `${Math.round(ox)}px`);
    wc.style.setProperty('top', `${Math.round(oy)}px`);
    wc.style.setProperty('width', `${Math.round(rig.size.w * s)}px`);
    wc.style.setProperty('height', `${Math.round(rig.size.h * s)}px`);
    const wctx = wc.getContext('2d');
    const img = wctx.createImageData(wc.width, wc.height);
    for (let y = 0; y < wc.height; y++) {
      for (let x = 0; x < wc.width; x++) {
        let r = 0; let g = 0; let b = 0; let sum = 0; let keep = 1;
        names.forEach((name, i) => { // 무게로 섞은 색, 진하기는 무게가 클수록
          const w = regionWeight(rig.regions[name], x * step + step / 2, y * step + step / 2);
          if (w <= 0.01) return;
          r += colors[i].rgb[0] * w; g += colors[i].rgb[1] * w; b += colors[i].rgb[2] * w; sum += w; keep *= 1 - 0.5 * w;
        });
        if (!sum) continue;
        const o = (y * wc.width + x) * 4;
        img.data[o] = r / sum; img.data[o + 1] = g / sum; img.data[o + 2] = b / sum; img.data[o + 3] = (1 - keep) * 255;
      }
    }
    wctx.putImageData(img, 0, 0);
    const want = new Set(String(opts.overlay || '').split(',')); // #overlay=regions,mesh: 처음부터 켤 겹침
    wc.hidden = !want.has('regions');

    // 그물 선 (휜 base 꼭짓점)
    const mc = el('canvas', 'bd-rig-mesh');
    mc.width = Math.round(cfg.box.w * K);
    mc.height = Math.round(cfg.box.h * K);
    mc.hidden = !want.has('mesh');
    const mctx = mc.getContext('2d');
    stage.append(wc, mc);

    const puppet = create(fig, cfg, { reduced: opts.reduced });
    const pose = { ...(opts.pose || {}) };
    const panel = el('div', 'bd-rig-panel');
    panel.append(el('h3', '', '뼈대 조절 (개발용)'));
    const drawMesh = () => {
      mctx.clearRect(0, 0, mc.width, mc.height);
      const m = puppet && puppet.debugMesh();
      if (mc.hidden || !m) return;
      mctx.strokeStyle = 'rgba(20, 20, 20, 0.45)';
      mctx.lineWidth = 1;
      const at = (c, r) => { const v = r * (m.cols + 1) + c; return [ox + m.pos[2 * v] * s, oy + m.pos[2 * v + 1] * s]; };
      mctx.beginPath();
      for (let r = 0; r <= m.rows; r++) for (let c = 0; c <= m.cols; c++) {
        const [x, y] = at(c, r);
        if (c < m.cols) { const [x2, y2] = at(c + 1, r); mctx.moveTo(x, y); mctx.lineTo(x2, y2); }
        if (r < m.rows) { const [x2, y2] = at(c, r + 1); mctx.moveTo(x, y); mctx.lineTo(x2, y2); }
      }
      mctx.stroke();
    };
    const apply = () => {
      if (puppet) puppet.setPose(pose);
      setTimeout(drawMesh, 80);
      setTimeout(drawMesh, 600);
    };
    const toggles = el('div', 'bd-rig-toggles');
    for (const [label, on, run] of [
      ['영역 색 보기', !wc.hidden, (v) => { wc.hidden = !v; }],
      ['그물 선 보기', !mc.hidden, (v) => { mc.hidden = !v; drawMesh(); }],
    ]) {
      const box = el('input');
      box.type = 'checkbox';
      box.checked = on;
      box.addEventListener('change', () => run(box.checked));
      const lab = el('label');
      lab.append(box, el('span', '', label));
      toggles.append(lab);
    }
    panel.append(toggles);

    const legend = el('ul', 'bd-rig-legend');
    names.forEach((name, i) => {
      const li = el('li');
      const chip = el('i');
      chip.style.setProperty('background', colors[i].css);
      li.append(chip, el('span', '', name));
      legend.append(li);
    });
    panel.append(legend);

    const sliders = el('div', 'bd-rig-sliders');
    const outs = rig.physics.map((p) => p.out);
    const setters = {};
    for (const name of [...STANDARD, ...outs]) {
      const [lo, hi] = outs.includes(name) ? [-PHYS_LIMIT, PHYS_LIMIT] : rangeOf(name);
      const row = el('label', 'bd-rig-row');
      const input = el('input');
      input.type = 'range';
      input.min = String(lo); input.max = String(hi); input.step = '0.01';
      const start = pose[name] !== undefined ? pose[name] : (DEFAULTS[name] || 0);
      input.value = String(start);
      const val = el('output', '', start.toFixed(2));
      input.addEventListener('input', () => { pose[name] = Number(input.value); val.textContent = Number(input.value).toFixed(2); apply(); });
      setters[name] = (v) => { input.value = String(v); val.textContent = Number(v).toFixed(2); };
      row.append(el('span', '', name), input, val);
      sliders.append(row);
    }
    panel.append(sliders);
    const buttons = el('div', 'bd-rig-buttons');
    const reset = el('button', '', '모두 처음으로');
    reset.type = 'button';
    reset.addEventListener('click', () => { for (const k of Object.keys(pose)) delete pose[k]; for (const [k, set] of Object.entries(setters)) set(DEFAULTS[k] || 0); apply(); });
    buttons.append(reset);
    panel.append(buttons);

    wrap.append(stage, panel);
    root.append(wrap);
    if (puppet) { puppet.setMood('normal', true); puppet.setActive(true); apply(); }
    return { puppet, wrap };
  }

  const logic = {
    STANDARD, DEFAULTS, cleanRig, parsePose, regionWeight, buildGrid, deform, makePhysics, stepPhysics, steadyPhysics, createMotion, showAlpha,
  };
  return { logic, supported, create, devView };
})();

if (typeof module !== 'undefined') module.exports = Puppet; // tools/dev/puppet_sim.js (node)
