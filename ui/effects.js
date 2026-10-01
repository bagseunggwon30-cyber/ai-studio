/* AI 스튜디오 — 효과 (SPEC 5단계: 도장, 반짝임, 종이 넘김, 카드 날아가기)
 *
 * 모두 Web Animations API(element.animate)와 CSS 클래스로만 움직인다 (CSP: style 속성 없이 CSSOM만).
 * 효과를 끄면 움직임 없이 결과만 바로 보여 준다. 켜고 끄기는 상단 바의 효과 스위치(CEO 결정, 2026-09-28):
 * 한 번도 누르지 않았으면 운영체제의 '동작 줄이기'(Windows '애니메이션 효과')를 따르고, 누르면 그 값을 이 브라우저에 기억한다.
 * 꺼져 있으면 <html class="calm">이 되어 style.css가 CSS 애니메이션도 모두 멈춘다.
 * 좌표는 효과를 붙일 부모 요소 기준 px (본사·팝업 모두 1536×1024 캔버스 안이라 확대 배율과 무관).
 */
'use strict';

const Fx = (() => {
  const KEY = 'studio.motion'; // 'on' | 'off' | 없음(운영체제 설정을 따름)
  const media = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  let pref = null;
  try { pref = localStorage.getItem(KEY); } catch (_) { pref = null; }

  const reduced = () => (pref === 'on' ? false : pref === 'off' ? true : Boolean(media && media.matches));
  const wait = (ms) => new Promise((r) => setTimeout(r, reduced() ? 0 : ms));

  function applyCalm() { document.documentElement.classList.toggle('calm', reduced()); }

  // 효과 스위치: on = 움직이기. 저장을 못 해도(사생활 보호 창 등) 이번에 연 동안은 따른다.
  function setMotion(on) {
    pref = on ? 'on' : 'off';
    try { localStorage.setItem(KEY, pref); } catch (_) { /* 기억 못 해도 괜찮다 */ }
    applyCalm();
  }

  applyCalm();
  if (media && media.addEventListener) media.addEventListener('change', applyCalm);

  function done(anim) { return anim && anim.finished ? anim.finished.catch(() => {}) : Promise.resolve(); }

  function animate(el, frames, opts) {
    if (reduced() || !el || !el.animate) return null;
    return el.animate(frames, opts);
  }

  // ---------------------------------------------------------------- 반짝임
  // parent 안의 (x, y)에서 별(또는 점)이 사방으로 튄다. 끝나면 스스로 지운다.
  // sound: 별이면 반짝 소리 (다른 소리와 함께 쓸 때는 false)
  function sparkle(parent, x, y, { count = 10, spread = 70, colors = ['#ffd84a', '#fff6c2', '#ffffff'], shape = 'star', size = 18, sound = true } = {}) {
    if (shape === 'star' && sound) Sfx.play('sparkle'); // 소리는 효과를 꺼도 난다 (소리 스위치를 따로 둔다)
    if (reduced() || !parent) return;
    for (let i = 0; i < count; i++) {
      const s = document.createElement('span');
      s.className = `spark ${shape}`;
      const angle = (Math.PI * 2 * i) / count + Math.random() * 0.6;
      const dist = spread * (0.55 + Math.random() * 0.6);
      s.style.left = `${x}px`;
      s.style.top = `${y}px`;
      s.style.setProperty('--dx', `${Math.cos(angle) * dist}px`);
      s.style.setProperty('--dy', `${Math.sin(angle) * dist - 10}px`);
      s.style.setProperty('--c', colors[i % colors.length]);
      s.style.setProperty('--size', `${size * (0.6 + Math.random() * 0.7)}px`);
      s.style.setProperty('--d', `${Math.round(Math.random() * 120)}ms`);
      s.addEventListener('animationend', () => s.remove());
      parent.appendChild(s);
    }
  }

  // ---------------------------------------------------------------- 도장
  // 도장(버튼)을 들어 올렸다가 종이에 쾅 찍는다. 찍히는 순간 잉크 자국·종이 흔들림·잉크 방울.
  // tilt: 도구가 CSS에서 기울어 있는 각도 (결재 도장 -10도, 보통 버튼 0도)
  async function stamp(tool, paper, { text = '승인', x = 380, y = 520, color = 'red', tilt = -10 } = {}) {
    const r = `rotate(${tilt}deg)`;
    const lift = animate(tool, [
      { transform: `${r} translateY(0) scale(1)` },
      { transform: `${r} translateY(-46px) scale(1.1)`, offset: 0.45 },
      { transform: `${r} translateY(8px) scale(0.9)`, offset: 0.75 },
      { transform: `${r} translateY(0) scale(1)` },
    ], { duration: 520, easing: 'cubic-bezier(.3,0,.5,1)' });
    await wait(390); // 찍히는 순간
    Sfx.play('stamp');
    const ink = inkMark(paper, text, x, y, color);
    animate(paper, [
      { transform: 'translate(0, 0)' }, { transform: 'translate(-5px, 3px)' }, { transform: 'translate(4px, -2px)' },
      { transform: 'translate(-2px, 1px)' }, { transform: 'translate(0, 0)' },
    ], { duration: 240 });
    sparkle(paper, x, y, { count: 12, spread: 90, colors: color === 'red' ? ['#d6333b', '#e5484d', '#b8323a'] : ['#7f77dd', '#5a51b8'], shape: 'dot', size: 12 });
    await done(lift);
    return ink;
  }

  function inkMark(paper, text, x, y, color = 'red') {
    const ink = document.createElement('span');
    ink.className = `ink-stamp ${color}`;
    ink.style.left = `${x}px`;
    ink.style.top = `${y}px`;
    const inner = document.createElement('span');
    inner.textContent = text;
    ink.appendChild(inner);
    paper.appendChild(ink);
    animate(ink, [
      { transform: 'translate(-50%, -50%) rotate(-14deg) scale(1.5)', opacity: 0 },
      { transform: 'translate(-50%, -50%) rotate(-14deg) scale(0.95)', opacity: 0.95, offset: 0.6 },
      { transform: 'translate(-50%, -50%) rotate(-14deg) scale(1)', opacity: 0.9 },
    ], { duration: 260, easing: 'ease-out' });
    return ink;
  }

  // ---------------------------------------------------------------- 종이 뒤집기
  // el을 90도까지 돌려 옆으로 세운 뒤 swap()으로 내용을 바꾸고, 새 요소(getNew())를 -90도에서 0도로 돌린다.
  async function flip(el, swap, getNew) {
    Sfx.play('flip');
    const persp = 'perspective(1600px)';
    // forwards: 다 돌린 뒤 swap()까지 옆으로 선 채로 둔다 (한 프레임 원래대로 보이는 깜빡임 방지)
    await done(animate(el, [{ transform: `${persp} rotateY(0deg)` }, { transform: `${persp} rotateY(90deg)` }],
      { duration: 200, easing: 'ease-in', fill: 'forwards' }));
    swap();
    const next = getNew();
    await done(animate(next, [{ transform: `${persp} rotateY(-90deg)` }, { transform: `${persp} rotateY(0deg)` }],
      { duration: 240, easing: 'ease-out' }));
  }

  // ---------------------------------------------------------------- 책장 넘기기
  // book 안의 왼쪽·오른쪽 쪽(leftSel, rightSel)을 넘긴다. swap()이 book의 내용을 새 날짜로 바꾼다.
  // 앞으로(next): 오른쪽 쪽이 등을 축으로 왼쪽으로 넘어가며, 뒷면에 새 왼쪽 쪽이 보인다.
  async function pageTurn(getBook, leftSel, rightSel, forward, swap) {
    Sfx.play('page');
    const book = getBook();
    if (reduced() || !book) { swap(); return; }
    const oldLeft = book.querySelector(leftSel);
    const oldRight = book.querySelector(rightSel);
    const snap = (node) => {
      const c = node.cloneNode(true);
      c.setAttribute('aria-hidden', 'true');
      c.querySelectorAll('button').forEach((b) => b.setAttribute('tabindex', '-1'));
      return c;
    };
    const box = (node) => ({ left: node.offsetLeft, top: node.offsetTop, width: node.offsetWidth, height: node.offsetHeight });
    const L = box(oldLeft);
    const R = box(oldRight);
    const keepOld = snap(forward ? oldLeft : oldRight); // 넘어가는 동안 반대쪽은 옛 쪽을 그대로 보여 준다
    const front = snap(forward ? oldRight : oldLeft);
    swap();
    const nb = getBook();
    const back = snap(nb.querySelector(forward ? leftSel : rightSel));

    const layer = document.createElement('div');
    layer.className = 'turn-layer';
    const place = (node, b) => {
      node.classList.add('turn-part');
      node.style.left = `${b.left}px`;
      node.style.top = `${b.top}px`;
      node.style.width = `${b.width}px`;
      node.style.height = `${b.height}px`;
    };
    place(keepOld, forward ? L : R);
    const leaf = document.createElement('div');
    leaf.className = `turn-leaf ${forward ? 'fwd' : 'back'}`;
    place(leaf, forward ? R : L);
    front.classList.add('turn-face', 'front');
    back.classList.add('turn-face', 'back');
    leaf.append(front, back);
    layer.append(keepOld, leaf);
    nb.appendChild(layer);
    const to = forward ? -180 : 180;
    await done(leaf.animate([
      { transform: 'perspective(2400px) rotateY(0deg)' },
      { transform: `perspective(2400px) rotateY(${to}deg)` },
    ], { duration: 650, easing: 'cubic-bezier(.45,.05,.35,1)' }));
    layer.remove();
  }

  // ---------------------------------------------------------------- 카드 날아가기
  // 고른 카드가 (tx, ty)(캔버스 좌표)로 날아간다. 안 고른 카드는 흐려지며 내려간다.
  async function flyCards(stage, cards, rest, tx, ty) {
    Sfx.play('whoosh');
    if (reduced()) return;
    const sr = stage.getBoundingClientRect();
    const k = sr.width / 1536;
    const anims = cards.map((card, i) => {
      const r = card.getBoundingClientRect();
      const cx = (r.left + r.width / 2 - sr.left) / k;
      const cy = (r.top + r.height / 2 - sr.top) / k;
      const dx = tx - cx;
      const dy = ty - cy;
      card.classList.add('flying');
      return card.animate([
        { transform: 'translate(0, 0) perspective(500px) rotateX(10deg) rotate(0deg) scale(1)', opacity: 1 },
        { transform: `translate(${dx * 0.35}px, ${dy * 0.35 - 90}px) perspective(500px) rotateX(0deg) rotate(-10deg) scale(0.85)`, opacity: 1, offset: 0.4 },
        { transform: `translate(${dx}px, ${dy}px) perspective(500px) rotateX(0deg) rotate(8deg) scale(0.2)`, opacity: 0.15 },
      ], { duration: 900, delay: i * 120, easing: 'cubic-bezier(.4,0,.6,1)', fill: 'forwards' });
    });
    rest.forEach((card) => card.animate([{ opacity: 1 }, { opacity: 0.25, transform: 'translateY(24px) perspective(500px) rotateX(10deg)' }],
      { duration: 500, fill: 'forwards' }));
    await Promise.all(anims.map(done));
  }

  // ---------------------------------------------------------------- 작은 것들
  function pop(el, cls = 'pop-in') {
    Sfx.play('pop');
    if (reduced() || !el) return;
    el.classList.remove(cls);
    void el.offsetWidth;
    el.classList.add(cls);
    el.addEventListener('animationend', () => el.classList.remove(cls), { once: true });
  }

  return { reduced, setMotion, wait, animate, sparkle, stamp, inkMark, flip, pageTurn, flyCards, pop };
})();
