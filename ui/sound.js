/* AI 스튜디오 — 효과음 (CEO 승인 2026-09-28)
 *
 * 소리 파일 없이 Web Audio로 그 자리에서 만든다 (도트 게임풍 짧은 소리: 네모파·세모파·잡음).
 * 기본은 꺼짐. 상단 바의 스피커 버튼으로 켜고 끄며, 이 브라우저에 기억한다 (localStorage studio.sound).
 * 브라우저는 사용자가 한 번 누른 뒤에만 소리를 낸다 — 켜는 버튼을 누르는 것이 그 한 번이다.
 * 같은 소리가 너무 자주 겹치지 않게 소리마다 최소 간격(GAP)을 둔다.
 */
'use strict';

const Sfx = (() => {
  const KEY = 'studio.sound';
  let on = false;
  try { on = localStorage.getItem(KEY) === 'on'; } catch (_) { on = false; }
  let ctx = null;
  let master = null;
  const last = {};
  const GAP = { sparkle: 160, notify: 400, pop: 100, drop: 90, flip: 120, warp: 260 };

  function audio() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
      master = ctx.createGain();
      master.gain.value = 0.35;
      master.connect(ctx.destination);
    }
    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    return ctx;
  }

  // 음 하나: freq에서 (to가 있으면 to까지 미끄러지며) dur초 동안, 짧게 커졌다가 사라진다
  function tone(freq, { at = 0, dur = 0.12, type = 'square', vol = 0.3, to = null } = {}) {
    const t0 = ctx.currentTime + at;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t0);
    if (to) o.frequency.exponentialRampToValueAtTime(to, t0 + dur);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(g);
    g.connect(master);
    o.start(t0);
    o.stop(t0 + dur + 0.02);
  }

  // 잡음 (종이·바람 소리): 거르는 주파수를 from → to로 옮긴다
  function noise({ at = 0, dur = 0.15, vol = 0.3, from = 800, to = 3000, q = 0.8, type = 'bandpass' } = {}) {
    const t0 = ctx.currentTime + at;
    const n = Math.max(1, Math.floor(ctx.sampleRate * dur));
    const buf = ctx.createBuffer(1, n, ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    const f = ctx.createBiquadFilter();
    f.type = type;
    f.Q.value = q;
    f.frequency.setValueAtTime(from, t0);
    f.frequency.exponentialRampToValueAtTime(to, t0 + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(vol, t0);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    src.connect(f);
    f.connect(g);
    g.connect(master);
    src.start(t0);
    src.stop(t0 + dur);
  }

  const SOUNDS = {
    stamp() { tone(120, { dur: 0.2, type: 'triangle', vol: 0.7, to: 50 }); noise({ dur: 0.09, vol: 0.5, from: 500, to: 150, type: 'lowpass' }); },
    sparkle() { [1568, 2093, 2637, 3136].forEach((f, i) => tone(f, { at: i * 0.05, dur: 0.12, vol: 0.1 })); },
    flip() { noise({ dur: 0.16, vol: 0.25, from: 1200, to: 4200 }); },
    page() { noise({ dur: 0.38, vol: 0.2, from: 600, to: 3600, q: 0.6 }); },
    whoosh() { noise({ dur: 0.5, vol: 0.22, from: 300, to: 2600, q: 1.2 }); },
    pop() { tone(880, { dur: 0.07, vol: 0.16, to: 1320 }); },
    drop() { tone(660, { dur: 0.09, vol: 0.14, to: 330 }); tone(196, { at: 0.08, dur: 0.06, type: 'triangle', vol: 0.3 }); },
    notify() { tone(1047, { dur: 0.09, vol: 0.13 }); tone(1397, { at: 0.08, dur: 0.14, vol: 0.13 }); },
    call() { tone(784, { dur: 0.1, vol: 0.14 }); tone(988, { at: 0.1, dur: 0.16, vol: 0.14 }); },
    cheer() { [523, 659, 784, 1047].forEach((f, i) => tone(f, { at: i * 0.09, dur: i === 3 ? 0.32 : 0.1, vol: 0.16 })); },
    oops() { tone(330, { dur: 0.14, vol: 0.16 }); tone(247, { at: 0.13, dur: 0.24, vol: 0.16 }); },
    alarm() {
      for (let i = 0; i < 3; i++) {
        tone(880, { at: i * 0.5, dur: 0.24, type: 'sawtooth', vol: 0.1, to: 660 });
        tone(660, { at: i * 0.5 + 0.25, dur: 0.24, type: 'sawtooth', vol: 0.1, to: 880 });
      }
    },
    // 소환 '뾰로롱': 빠르게 올라가는 반짝 음 + 바람
    warp() {
      [784, 1047, 1319, 1568, 2093].forEach((f, i) => tone(f, { at: i * 0.045, dur: 0.09, type: 'triangle', vol: 0.13, to: f * 1.06 }));
      noise({ at: 0.02, dur: 0.3, vol: 0.08, from: 1500, to: 6000, q: 1.5 });
    },
    meow() { tone(650, { dur: 0.12, type: 'triangle', vol: 0.22, to: 950 }); tone(950, { at: 0.1, dur: 0.3, type: 'triangle', vol: 0.22, to: 480 }); },
  };

  function play(name) {
    if (!on || !SOUNDS[name]) return;
    const now = performance.now();
    if (last[name] && now - last[name] < (GAP[name] || 60)) return;
    last[name] = now;
    if (!audio()) return;
    try { SOUNDS[name](); } catch (_) { /* 소리는 없어도 된다 */ }
  }

  function set(value) {
    on = Boolean(value);
    try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch (_) { /* 기억 못 해도 괜찮다 */ }
    if (on) play('pop');
  }

  return { play, set, enabled: () => on };
})();
