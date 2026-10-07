/* AI 스튜디오 — 직원 꾸미기 그리기 (모습 세트·머리색·옷 색)
 *
 * - 모습 세트(옷·체형·머리 모양·안경·소품·표정, 꾸미기 공방): 그림이 따로 있다 (<직원>@<세트>.<동작>.strip.png, portraits@<세트>.png).
 * - 머리색·옷 색: tools/sprites/make_masks.gd가 만든 표시(.mask.png, 빨강 = 머리, 초록 = 옷)가 있는 픽셀만
 *   부분 평균 색(parts.json) 대비 비율을 지키며 새 색으로 칠한다. 음영이 그대로 남는다.
 * - 몸 조절 막대(키·머리 크기·체격·어깨·가슴·허리·골반·머리 숱): 색을 칠한 다음 부위별로 그 자리에서 고친다 (아래 '몸 조절').
 *   예전의 '그림 통째로 늘리기'는 없앴다. 크게 바꾸려면 꾸미기 공방에서 새로 그린다.
 * 결과는 캐시한다. 선택지와 색 값은 서버의 look_options(studio/company.py)에서 온다.
 * - 그림 목록(index.json)·색 통계(parts.json)는 두 곳에서 합쳐 읽는다: 배포 그림 /assets/sprites/ 와 승인해서 설치한 그림
 *   /assets/custom/ (실행 데이터 폴더 data/assets). 설치한 항목은 dir("custom/sprites/")을 달고 온다.
 * - 얼굴 그림 열 구성은 '지금 화면에 걸린 그림'을 따른다 (합친 그림이 준비되기 전에는 기본 4열, 새 직원 얼굴은 비워 둔다).
 */
'use strict';

const Looks = (() => {
  const BASE = '/assets/';
  let index = {};
  let parts = {};
  let options = { hair: [], outfit: [], kinds: [], styles: {} };
  const images = {}; // url → HTMLImageElement (불러오는 중이면 Promise)
  const failed = {}; // url → 실패한 시각. 연결이 끊겼을 때 매 프레임 다시 부르지 않게 잠깐 쉰다
  const RETRY_MS = 5000;
  const cache = new Map(); // key → canvas | dataURL
  const DEFAULT = { style: 'base', hair: 'base', outfit: 'base' };

  function load(url) {
    if (images[url]) return images[url];
    if (failed[url] && Date.now() - failed[url] < RETRY_MS) return Promise.resolve(null);
    images[url] = new Promise((resolve) => {
      const img = new Image();
      img.onload = () => { images[url] = img; delete failed[url]; resolve(img); };
      img.onerror = () => { images[url] = null; failed[url] = Date.now(); resolve(null); };
      img.src = url;
    });
    return images[url];
  }

  // 배포 목록과 설치한 목록을 합쳐 읽는다 (같은 키는 설치한 것이 이긴다). 어느 한쪽이라도 못 읽으면 null (지금 목록을 그대로 둔다).
  async function getMerged(name) {
    const read = async (url) => {
      try {
        const data = await (await fetch(url, { cache: 'no-store' })).json();
        return data && typeof data === 'object' ? data : null;
      } catch (_) {
        return null;
      }
    };
    const [base, custom] = await Promise.all([read(`${BASE}sprites/${name}`), read(`${BASE}custom/${name}`)]);
    return base && custom ? { ...base, ...custom } : null;
  }

  function loadIndex() { return getMerged('index.json'); }

  async function init(spriteIndex) {
    index = spriteIndex || {};
    parts = (await getMerged('parts.json')) || parts;
  }

  // 띠·표시 그림 주소: 배포 그림은 sprites/, 설치한 그림은 항목의 dir (custom/sprites/)
  function stripUrl(meta, file) { return `${BASE}${meta.dir || 'sprites/'}${file}`; }

  function setOptions(value) { if (value) options = value; }
  function getOptions() { return options; }
  // 예전에 저장한 키·체격 글자 값('tall' 등)은 버린다. 막대 값은 범위 안의 정수로.
  function norm(look) {
    const l = look || {};
    return { style: l.style || DEFAULT.style, hair: l.hair || DEFAULT.hair, outfit: l.outfit || DEFAULT.outfit, ...bodyOf(l) };
  }

  // 이 직원이 고를 수 있는 세트인지 (그림이 없으면 기본)
  function who(id, look) {
    const style = norm(look).style;
    return style !== 'base' && index[`${id}@${style}.step`] ? `${id}@${style}` : id;
  }

  function colorOf(list, key) {
    const item = (list || []).find((o) => o.key === key);
    return item && item.color ? hexToHsv(item.color) : null;
  }

  // 띠 하나를 꾸미기대로 칠하고(색) 몸을 조절한(막대) 그림과 그 meta. 준비가 안 됐으면 원본 그림(또는 null)을 주고 뒤에서 만든다.
  // 몸 조절을 하면 프레임 크기·anchor가 바뀌므로 Stills.still은 여기서 받은 meta로 그린다.
  function strip(id, action, look, onReady) {
    const w = who(id, look);
    const meta = index[`${w}.${action}`] || index[`${id}.${action}`];
    if (!meta) return { meta: null, image: null };
    const l = norm(look);
    const painted = paint(w, id, meta, l, onReady);
    const b = bodyOf(l);
    if (!painted.ready || !bodyOn(b)) return { meta, image: painted.image };
    const key = `${meta.file}|${l.hair}|${l.outfit}|${bodyKey(b)}`;
    const done = cache.get(key);
    if (done && done.image) return done;
    if (!done) {
      cache.set(key, 'pending');
      const maskP = b.hair_volume && meta.mask ? load(stripUrl(meta, meta.mask)) : Promise.resolve(null);
      maskP.then((mask) => setTimeout(() => { // 그리기 틈에 (한 프레임을 오래 막지 않게)
        try {
          cache.set(key, reshape(painted.image, mask, meta, action, b, standHeight(w, id, meta)));
        } catch (_) {
          cache.delete(key);
          return;
        }
        if (onReady) onReady();
      }, 0));
    }
    return { meta, image: painted.image };
  }

  // 색까지 칠한 띠: { image, ready } (ready = 이 꾸미기대로 다 칠해졌다)
  function paint(w, id, meta, l, onReady) {
    const hair = colorOf(options.hair, l.hair);
    const outfit = colorOf(options.outfit, l.outfit);
    const src = stripUrl(meta, meta.file);
    const base = images[src] instanceof HTMLImageElement ? images[src] : null;
    // 준비되면 다시 그리게 알린다. 실패했을 때는 알리지 않는다 (알리면 곧바로 또 불러서 끝없이 돈다)
    if (!base) load(src).then((img) => { if (img && onReady) onReady(); });
    if ((!hair && !outfit) || !meta.mask) return { image: base, ready: Boolean(base) };
    const key = `${meta.file}|${l.hair}|${l.outfit}`;
    const done = cache.get(key);
    if (done instanceof HTMLCanvasElement) return { image: done, ready: true };
    if (!done) {
      cache.set(key, 'pending');
      Promise.all([load(src), load(stripUrl(meta, meta.mask))]).then(([img, mask]) => {
        if (!img || !mask) {
          cache.delete(key); // 못 불렀으면 다음에 다시 (그동안은 원본 그림으로 그린다)
          return;
        }
        cache.set(key, recolor(img, mask, parts[w] || parts[id] || {}, hair, outfit));
        if (onReady) onReady();
      });
    }
    return { image: base, ready: false };
  }

  // 부위 선을 잴 '서 있는 키': 같은 모습의 서 있는 띠(step) 높이
  function standHeight(w, id, meta) {
    const step = index[`${w}.step`] || index[`${id}.step`];
    return (step && step.contentHeight) || meta.contentHeight || meta.frameHeight;
  }


  // 얼굴 아틀라스 (열 = 직원, 기본 4명: hana, sol, clo, luna + 새 직원). 직원마다 세트와 색이 다를 수 있어 열마다 따로 칠해 붙인다.
  // 얼굴 그림은 서버의 faces 목록으로 찾는다: 기본 4명 한 장, 세트 한 장(여러 명), 의상실에서 만든 한 사람짜리 옷.
  //
  // 열 구성은 두 가지를 따로 센다 (처음 열 때 새 직원이 있으면 합친 그림이 준비되기까지 1~2초 걸리는데, 그동안 칸이 어긋나지 않게):
  //   FACE_COLS = 앞으로 만들 그림의 구성 (기본 4명 + 새 직원, app.js가 setFaceCols로 맞춘다)
  //   shown     = 지금 화면(#stage)에 걸린 그림의 구성. 처음에는 기본 portraits.png(4열)이고, 합친 그림이 걸리면(commitFaces) 바뀐다.
  // 얼굴 위치(--fx)와 --face-cols는 shown을 따른다: 아직 그림에 없는 새 직원 얼굴은 그동안 비워 두고(숨김), 합친 그림이 걸리는 순간
  // 열 구성·--face-cols·모든 얼굴의 --fx가 한꺼번에 바뀐다.
  const BASE_FACES = ['hana', 'sol', 'clo', 'luna'];
  let FACE_COLS = BASE_FACES.slice();
  let shown = BASE_FACES.slice();

  function setFaceCols(ids) {
    const extra = (ids || []).filter((id) => !BASE_FACES.includes(id));
    const next = [...BASE_FACES, ...extra];
    if (next.join('|') !== FACE_COLS.join('|')) { FACE_COLS = next; cache.clear(); }
    return FACE_COLS.length;
  }
  // 얼굴 그림(아틀라스)에서 이 사람 칸의 가로 위치 (CSS background-position %). 그 그림에 없는 사람은 null.
  function xIn(ids, id) {
    const i = ids.indexOf(id);
    return i < 0 ? null : ids.length > 1 ? `${(i / (ids.length - 1)) * 100}%` : '0%';
  }
  function faceX(id) { return xIn(shown, id); }

  // 얼굴 요소(.face.<직원>)는 --fx를 인라인이 아니라 이 규칙에서 받는다: 열 구성이 바뀌면 규칙만 고쳐 이미 그려진 얼굴도 함께 바뀐다.
  // 스타일 속성·인라인 <style>은 CSP가 막지만, CSSOM으로 규칙을 만들고 고치는 것은 된다.
  let faceSheet = null;
  const faceRules = new Map(); // 직원 → CSSStyleRule

  function faceRule(id) {
    if (!faceSheet) {
      try {
        faceSheet = new CSSStyleSheet();
        document.adoptedStyleSheets = [...document.adoptedStyleSheets, faceSheet]; // 나중에 온 시트가 popups.css의 기본 규칙을 덮는다
      } catch (_) {
        faceSheet = [...document.styleSheets].reverse().find((sh) => { try { return Boolean(sh.cssRules); } catch (e) { return false; } });
      }
    }
    let rule = faceRules.get(id);
    if (!rule) {
      faceSheet.insertRule(`.face.${CSS.escape(id)} {}`, faceSheet.cssRules.length);
      rule = faceSheet.cssRules[faceSheet.cssRules.length - 1];
      faceRules.set(id, rule);
    }
    return rule;
  }

  // 모든 직원(기본 4명 + 새 직원)의 얼굴 규칙을 지금 걸린 그림(shown)에 맞춘다. 아직 그림에 없는 직원은 숨긴다.
  function syncFaces(teamIds) {
    for (const id of new Set([...BASE_FACES, ...(teamIds || [])])) {
      const x = faceX(id);
      const rule = faceRule(id);
      if (x === null) {
        rule.style.setProperty('visibility', 'hidden');
      } else {
        rule.style.setProperty('--fx', x);
        rule.style.setProperty('visibility', 'visible');
      }
    }
  }

  // 합친 얼굴 그림이 #stage에 걸렸다: 그 그림의 열 구성(ids)으로 바꾼다 (app.js가 --portraits·--face-cols와 함께 부른다)
  function commitFaces(ids) {
    shown = (ids || BASE_FACES).slice();
    syncFaces(FACE_COLS);
  }

  // 꾸미기 미리보기처럼 잠깐 쓰는 얼굴 요소에 직접 넣을 값 (그 그림 하나의 열 구성을 따른다)
  function faceStyle(res, id) {
    return { '--portraits': res.url ? `url("${res.url}")` : 'url("/assets/portraits.png")', '--face-cols': String(res.ids.length),
      '--fx': xIn(res.ids, id) || '0%', visibility: 'visible' };
  }

  function faceSource(id, look, col, count) {
    const faces = options.faces || {};
    return faces[who(id, look)] || faces[id] || { file: 'portraits.png', col, cols: count };
  }

  // 아틀라스 그림 주소는 blob: 로 만든다. 열이 6개쯤 되면 data: 주소가 2MiB(브라우저의 CSS 값 한도)를 넘어 --portraits가 조용히 무시된다.
  // strip 캐시(cache)와 따로 둔다: setFaceCols의 cache.clear()가 지워도 화면이 붙잡은 주소는 살아 있어야 하고, 밀려날 때만 revoke한다.
  const ATLAS_MAX = 16;
  const atlases = new Map();  // 열 구성 키 → blob 주소 (오래 안 쓴 것부터)
  const building = new Map(); // 키 → 만드는 중인 Promise (같은 키를 두 번 만들어 주소가 새지 않게)
  let pinned = null;          // 화면(#stage)이 쓰는 아틀라스 키: 밀려나도 없애지 않는다

  function trimAtlases(keep) {
    for (const [k, url] of atlases) {
      if (atlases.size <= ATLAS_MAX) break;
      if (k === keep || k === pinned) continue;
      URL.revokeObjectURL(url);
      atlases.delete(k);
    }
  }

  // pin: 화면 바탕(#stage --portraits)에 쓸 아틀라스면 true (꾸미기 미리보기처럼 잠깐 쓰는 것은 false)
  // 결과: { url, ids } — ids는 그 그림의 열 구성, url이 null이면 기본 portraits.png (기본 4명 그대로일 때). 그림을 못 불렀으면 null.
  async function portraits(looksById, pin = false) {
    const cols = FACE_COLS.slice(); // 만드는 동안 직원이 바뀌어도 이 구성대로 끝까지 만든다
    const key = cols.map((id) => { const l = norm(looksById[id]); return `${who(id, l)}:${l.hair}:${l.outfit}`; }).join('|');
    const plain = cols.length === BASE_FACES.length
      && cols.every((id) => { const l = norm(looksById[id]); return who(id, l) === id && l.hair === 'base' && l.outfit === 'base'; });
    if (plain) {
      if (pin) pinned = null;
      return { url: null, ids: cols };
    }
    let url = atlases.get(key);
    if (url) {
      atlases.delete(key); // 다시 썼으니 가장 새것으로
    } else {
      if (!building.has(key)) building.set(key, buildAtlas(cols, looksById).finally(() => building.delete(key)));
      url = await building.get(key);
      if (!url) return null; // 그림을 못 불렀다: 캐시하지 않고 다음에 다시 만든다
    }
    atlases.set(key, url);
    if (pin) pinned = key;
    trimAtlases(key);
    return { url, ids: cols };
  }

  async function buildAtlas(cols, looksById) {
    let out = null;
    for (const [col, id] of cols.entries()) {
      const l = norm(looksById[id]);
      const src = faceSource(id, l, col, cols.length);
      const [img, mask] = await Promise.all([load(`${BASE}${src.file}`), load(`${BASE}${src.file.replace(/\.png$/, '.mask.png')}`)]);
      if (!img) continue;
      const cw = img.naturalWidth / src.cols;
      if (!out) {
        out = document.createElement('canvas');
        out.width = cw * cols.length;
        out.height = img.naturalHeight;
      }
      const cell = document.createElement('canvas');
      cell.width = cw;
      cell.height = img.naturalHeight;
      cell.getContext('2d').drawImage(img, src.col * cw, 0, cw, img.naturalHeight, 0, 0, cw, img.naturalHeight);
      let piece = cell;
      const hair = colorOf(options.hair, l.hair);
      const outfit = colorOf(options.outfit, l.outfit);
      if ((hair || outfit) && mask) {
        const m = document.createElement('canvas');
        m.width = cw;
        m.height = img.naturalHeight;
        m.getContext('2d').drawImage(mask, src.col * cw, 0, cw, img.naturalHeight, 0, 0, cw, img.naturalHeight);
        piece = recolor(cell, m, parts[`${who(id, l)}:face`] || {}, hair, outfit);
      }
      out.getContext('2d').drawImage(piece, col * cw, 0);
    }
    if (!out) return null;
    const blob = await new Promise((resolve) => out.toBlob(resolve, 'image/png'));
    return blob ? URL.createObjectURL(blob) : null;
  }

  // ---------------------------------------------------------------- 몸 조절 (막대, CEO 요청 2026-09-29)
  // 게임 캐릭터 만들기처럼 부위별로 그 자리에서 고친다 (사용량 없음). 예전의 '그림 통째로 늘리기'가 아니다.
  // 막대 정의·범위는 서버(company.BODY_SLIDERS)가 준다. 한 단계 크기는 여기 BODY_STEP (자연스러운 범위로 고정).
  // 부위 선은 '서 있는 키'(같은 모습의 step 띠 높이, Hs)로 잰다 — 큰 머리·긴 머리카락 때문에 알파 폭으로는 목이 안 보인다:
  //   서 있는 자세: 발끝에서 Hs의 비율로 목 .60 · 어깨 .55 · 가슴 .48 · 허리 .40 · 엉덩이 .30 (그 아래가 다리)
  //   앉은 자세(work·rest·frozen): 머리 꼭대기에서 목 = 위 + .40Hs, 그 아래는 서 있을 때와 같은 간격
  // 여러 프레임인 동작은 첫 프레임의 선을 같이 써서 흔들리지 않게 한다.
  const BODY_KEYS = ['height', 'head', 'build', 'shoulders', 'chest', 'waist', 'hips', 'hair_volume'];
  const BODY_STEP = { height: 0.05, head: 0.05, build: 0.04, shoulders: 0.05, chest: 0.03, waist: 0.05, hips: 0.05, hair_volume: 0.03 };
  const BODY_RANGE = { height: [-2, 2], head: [-2, 2], build: [-2, 2], shoulders: [-2, 2], chest: [0, 2], waist: [-2, 2], hips: [-2, 2], hair_volume: [0, 2] };
  const SEATED = new Set(['work', 'rest', 'frozen']);
  const BACK = new Set(['work', 'frozen']);        // 뒤에서 본 모습: 가슴은 그대로
  const SIDE = new Set(['step', 'walk', 'rest']);  // 옆모습: 가슴은 바라보는 쪽으로 살짝
  const LINES = { neck: 0.60, shoulders: 0.55, chest: 0.48, waist: 0.40, hips: 0.30 }; // 서 있는 자세, 발끝에서 Hs 비율
  const BAND = 0.06; // 부위 띠의 반폭 (Hs 비율, 삼각 가중)

  function bodyOf(look) {
    const out = {};
    const defs = Object.fromEntries((options.body || []).map((d) => [d.key, [d.min, d.max]]));
    for (const k of BODY_KEYS) {
      const [lo, hi] = defs[k] || BODY_RANGE[k];
      const n = Math.trunc(Number((look || {})[k]) || 0);
      out[k] = Math.max(lo, Math.min(hi, n));
    }
    return out;
  }
  const bodyOn = (b) => BODY_KEYS.some((k) => b[k]);
  const bodyKey = (b) => BODY_KEYS.map((k) => b[k]).join(',');

  // 한 프레임의 줄마다 불투명한 왼쪽·오른쪽 끝 (빈 줄은 -1). alpha(x, y)는 그 프레임 안 좌표의 알파.
  function frameProfile(alpha, fw, fh) {
    const left = new Int16Array(fh).fill(-1);
    const right = new Int16Array(fh).fill(-1);
    for (let y = 0; y < fh; y++) {
      for (let x = 0; x < fw; x++) if (alpha(x, y) > 127) { left[y] = x; break; }
      if (left[y] < 0) continue;
      for (let x = fw - 1; x >= 0; x--) if (alpha(x, y) > 127) { right[y] = x; break; }
    }
    return { left, right };
  }

  // 몸 조절 계획 (캔버스 없이 계산만 — tools/dev/body_sim.js가 점검한다).
  // 돌려주는 것: 부위 선(y), 몸 가운데 cx, 줄마다 가로 배율 sx[y] = [왼쪽, 오른쪽], 머리 배율 head, 다리 배율 legs,
  // 머리 숱 배율 hair, 새 프레임 크기(fw2·fh2)와 늘어난 폭 여백 margin, 다리·머리가 늘어난 높이 legsDelta·headDelta.
  function bodyPlan(profile, fw, fh, b, action, facing, Hs) {
    const { left, right } = profile;
    let top = -1;
    let bottom = -1;
    for (let y = 0; y < fh; y++) if (left[y] >= 0) { if (top < 0) top = y; bottom = y; }
    if (top < 0) return null;
    const H = Hs > 0 ? Hs : bottom - top;
    const seated = SEATED.has(action);
    const at = {};
    if (seated) {
      const neck = top + 0.40 * H;
      for (const [k, f] of Object.entries(LINES)) at[k] = Math.min(bottom, neck + (LINES.neck - f) * H);
    } else {
      for (const [k, f] of Object.entries(LINES)) at[k] = bottom - f * H;
    }
    const neck = Math.max(top, Math.round(at.neck));
    // 몸 가운데: 어깨~엉덩이 줄의 좌우 끝 가운데를 평균 (팔이 한쪽으로 나와도 크게 흔들리지 않게)
    let sum = 0;
    let cnt = 0;
    for (let y = Math.round(at.shoulders); y <= Math.round(at.hips); y++) {
      if (y >= 0 && y < fh && left[y] >= 0) { sum += (left[y] + right[y]) / 2; cnt++; }
    }
    const cx = cnt ? sum / cnt : fw / 2;
    const tri = (y, c) => Math.max(0, 1 - Math.abs(y - c) / (BAND * H));
    const front = facing === 'left' ? 0 : 1; // 옆모습에서 앞쪽 (0 = 왼쪽, 1 = 오른쪽)
    const clampS = (s) => Math.max(0.8, Math.min(1.25, s));
    const sx = new Array(fh);
    let maxS = 1;
    for (let y = 0; y < fh; y++) {
      if (y <= neck) { sx[y] = [1, 1]; continue; }
      let s = 1 + b.build * BODY_STEP.build
        + b.shoulders * BODY_STEP.shoulders * tri(y, at.shoulders)
        + b.waist * BODY_STEP.waist * tri(y, at.waist)
        + b.hips * BODY_STEP.hips * tri(y, at.hips);
      const pair = [s, s];
      if (!BACK.has(action) && b.chest) {
        const c = BODY_STEP.chest * b.chest * tri(y, at.chest);
        if (SIDE.has(action)) pair[front] += 2 * c; // 옆모습: 앞쪽 반만 (전체 폭으로 치면 같은 크기)
        else { pair[0] += c; pair[1] += c; }
      }
      sx[y] = [clampS(pair[0]), clampS(pair[1])];
      maxS = Math.max(maxS, sx[y][0], sx[y][1]);
    }
    const head = clampS(1 + b.head * BODY_STEP.head);
    const hair = 1 + b.hair_volume * BODY_STEP.hair_volume;
    const legs = seated ? 1 : clampS(1 + b.height * BODY_STEP.height);
    const hips = Math.min(bottom, Math.max(neck, Math.round(at.hips)));
    const legsDelta = Math.round((bottom - hips) * (legs - 1));
    const headDelta = Math.round((neck - top) * (head - 1));
    const margin = Math.ceil((fw * (Math.max(maxS, head * hair) - 1)) / 2) + 2;
    return {
      top, bottom, neck, hips, lines: at, cx, sx, head, hair, legs, legsDelta, headDelta, margin,
      fw2: fw + 2 * margin, fh2: Math.max(1, fh + legsDelta + headDelta),
    };
  }

  // 몸 조절한 띠 (새 캔버스 + 바뀐 meta 복사본). img = 색까지 칠한 띠, mask = 머리 숱을 쓸 때만 (빨강 = 머리).
  function reshape(img, mask, meta, action, b, Hs) {
    const n = meta.frames || 1;
    const fw = meta.frameWidth;
    const fh = meta.frameHeight;
    const src = document.createElement('canvas');
    src.width = fw * n;
    src.height = fh;
    const sctx = src.getContext('2d', { willReadFrequently: true });
    sctx.drawImage(img, 0, 0);
    const data = sctx.getImageData(0, 0, fw, fh).data; // 첫 프레임으로 선을 잰다
    const plan = bodyPlan(frameProfile((x, y) => data[(y * fw + x) * 4 + 3], fw, fh), fw, fh, b, action, meta.facing, Hs);
    if (!plan) return { meta, image: img };
    // 머리 숱: 머리 표시가 있는 픽셀만 모은 층 (색을 칠한 그림에서)
    let hairLayer = null;
    if (mask && plan.hair > 1) {
      hairLayer = document.createElement('canvas');
      hairLayer.width = fw * n;
      hairLayer.height = fh;
      const hctx = hairLayer.getContext('2d', { willReadFrequently: true });
      hctx.drawImage(mask, 0, 0);
      const m = hctx.getImageData(0, 0, fw * n, fh);
      const px = sctx.getImageData(0, 0, fw * n, fh);
      for (let i = 0; i < m.data.length; i += 4) {
        const keep = m.data[i] > 127 && m.data[i + 3] > 0;
        m.data[i] = px.data[i];
        m.data[i + 1] = px.data[i + 1];
        m.data[i + 2] = px.data[i + 2];
        m.data[i + 3] = keep ? px.data[i + 3] : 0;
      }
      hctx.putImageData(m, 0, 0);
    }
    const { fw2, fh2, margin, cx, sx, neck, hips, bottom, top, legs, headDelta, head, hair } = plan;
    const out = document.createElement('canvas');
    out.width = fw2 * n;
    out.height = fh2;
    const ctx = out.getContext('2d');
    ctx.imageSmoothingEnabled = true;
    const cxL = Math.max(1, Math.min(fw - 1, Math.round(cx))); // 정수 칸에 맞춰 번지지 않게
    // 한 줄: 몸 가운데 기준으로 왼쪽·오른쪽을 따로 늘리거나 줄인다.
    // 왼쪽 반은 가운데를 1칸 넘겨 그려서, 두 반쪽이 만나는 곳에 가는 틈(세로 줄)이 생기지 않게 한다.
    const row = (k, sy, dy, [sl, sr]) => {
      const ox = k * fw2 + margin + cxL;
      ctx.drawImage(src, k * fw, sy, cxL + 1, 1, ox - cxL * sl, dy, (cxL + 1) * sl, 1);
      ctx.drawImage(src, k * fw + cxL, sy, fw - cxL, 1, ox, dy, (fw - cxL) * sr, 1);
    };
    // 세로 배치 (새 프레임은 shift만큼 커진다, 발끝은 바닥에 그대로):
    //   발끝 아래 여백: y + shift / 다리: 발끝에서 위로 legs배 / 몸통(목 아래~엉덩이): y + headDelta / 머리: 목 선(neck + headDelta)을 바닥으로 head배
    const shift = fh2 - fh;
    const feetOut = bottom + shift;
    const hh = neck - top + 1;
    for (let k = 0; k < n; k++) {
      for (let y = bottom + 1; y < fh; y++) row(k, y, y + shift, sx[y]);
      for (let d = feetOut; d > hips + headDelta; d--) {
        const y = Math.max(hips + 1, Math.min(bottom, Math.round(bottom - (feetOut - d) / legs)));
        row(k, y, d, sx[y]);
      }
      for (let y = neck + 1; y <= hips; y++) row(k, y, y + headDelta, sx[y]);
      const neckOut = neck + headDelta;
      const place = (layer, s) => ctx.drawImage(layer, k * fw, top, fw, hh,
        k * fw2 + margin + cxL - cxL * s, neckOut + 1 - hh * s, fw * s, hh * s);
      if (hairLayer) place(hairLayer, head * hair); // 머리 숱: 머리카락만 한 겹 뒤에 조금 크게
      place(src, head);
    }
    const meta2 = {
      ...meta, frameWidth: fw2, frameHeight: fh2,
      anchor: { x: (meta.anchor ? meta.anchor.x : fw / 2) + margin, y: (meta.anchor ? meta.anchor.y : fh) + shift },
      contentHeight: (meta.contentHeight || fh) + shift,
      grown: shift, // 몸 조절로 늘어난(줄면 음수) 높이: 미리보기(Stills.still)가 원래 배율을 지키게
    };
    return { meta: meta2, image: out };
  }

  // ---------------------------------------------------------------- 색 계산
  function recolor(img, mask, stats, hair, outfit) {
    const w = img.naturalWidth || img.width;
    const h = img.naturalHeight || img.height;
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const px = ctx.getImageData(0, 0, w, h);
    const mc = document.createElement('canvas');
    mc.width = w;
    mc.height = h;
    const mctx = mc.getContext('2d', { willReadFrequently: true });
    mctx.drawImage(mask, 0, 0);
    const m = mctx.getImageData(0, 0, w, h).data;
    const d = px.data;
    const hs = stats.hair || { s: 0.5, v: 0.5 };
    const os = stats.outfit || { s: 0.5, v: 0.5 };
    for (let i = 0; i < d.length; i += 4) {
      if (!m[i + 3] || !d[i + 3]) continue;
      const target = m[i] > 127 ? hair : m[i + 1] > 127 ? outfit : null;
      if (!target) continue;
      const mean = m[i] > 127 ? hs : os;
      const [, s, v] = rgbToHsv(d[i], d[i + 1], d[i + 2]);
      // 원래 부분 평균 대비 비율을 새 색에 옮긴다 (밝은 곳은 밝게, 그늘은 그늘로)
      const ns = clamp(target[1] * (s / Math.max(mean.s, 0.08)), 0, 1);
      const nv = clamp(target[2] * (v / Math.max(mean.v, 0.08)), 0, 1);
      const [r, g, b] = hsvToRgb(target[0], ns, nv);
      d[i] = r;
      d[i + 1] = g;
      d[i + 2] = b;
    }
    ctx.putImageData(px, 0, 0);
    return c;
  }

  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));

  function hexToHsv(hex) {
    const n = parseInt(hex.slice(1), 16);
    return rgbToHsv((n >> 16) & 255, (n >> 8) & 255, n & 255);
  }

  function rgbToHsv(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    const d = max - min;
    let h = 0;
    if (d) {
      if (max === r) h = ((g - b) / d) % 6;
      else if (max === g) h = (b - r) / d + 2;
      else h = (r - g) / d + 4;
      h *= 60;
      if (h < 0) h += 360;
    }
    return [h, max ? d / max : 0, max];
  }

  function hsvToRgb(h, s, v) {
    const c = v * s;
    const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
    const m = v - c;
    const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
    return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
  }

  function colorable(id) { return (options.colorable || BASE_FACES).includes(id); }

  return {
    init, loadIndex, setOptions, getOptions, norm, strip, portraits, who, setFaceCols, faceX, syncFaces, commitFaces, faceStyle, colorable, DEFAULT,
    BODY_KEYS, bodyOf, bodyPlan, frameProfile, // 몸 조절 (bodyPlan·frameProfile은 tools/dev/body_sim.js 점검용)
  };
})();
