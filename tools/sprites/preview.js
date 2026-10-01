'use strict';
// make_strips.gd가 만든 띠를 캐릭터별로 모아, 같은 배율로 캔버스에 넘겨 재생한다.
const SCALE = 0.6;
const grid = document.getElementById('grid');
const byCharacter = {};
for (const meta of Object.values(STRIPS)) (byCharacter[meta.character] ||= []).push(meta);

const players = [];
for (const [character, list] of Object.entries(byCharacter)) {
  const section = document.createElement('section');
  const title = document.createElement('h2');
  title.textContent = character;
  const row = document.createElement('div');
  row.className = 'row';
  for (const meta of list) {
    const fig = document.createElement('figure');
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(meta.frameWidth * SCALE);
    canvas.height = Math.round(meta.frameHeight * SCALE);
    const cap = document.createElement('figcaption');
    cap.textContent = `${meta.action} · ${meta.frames}프레임` + (meta.loop ? ` · ${meta.fps}fps` : '') + (meta.seam ? ` · 이음새 ${meta.seam}` : '');
    fig.append(canvas, cap);
    row.append(fig);
    const img = new Image();
    img.src = BASE + meta.file;
    players.push({ meta, canvas, ctx: canvas.getContext('2d'), img });
  }
  section.append(title, row);
  grid.append(section);
}

const start = performance.now();
function draw(now) {
  for (const p of players) {
    if (!p.img.complete || !p.img.naturalWidth) continue;
    const m = p.meta;
    const frame = m.frames > 1 ? Math.floor(((now - start) / 1000) * m.fps) % m.frames : 0;
    p.ctx.clearRect(0, 0, p.canvas.width, p.canvas.height);
    p.ctx.drawImage(p.img, frame * m.frameWidth, 0, m.frameWidth, m.frameHeight, 0, 0, p.canvas.width, p.canvas.height);
  }
  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);

document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-bg]');
  if (b) document.body.dataset.bg = b.dataset.bg;
});
