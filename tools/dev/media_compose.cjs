'use strict';
// 만들어 둔 영상 컷들을 이어붙여 자막·마지막 안내 화면이 있는 하나의 광고 영상(MP4, 소리 없음)으로 만든다.
//   node tools/dev/media_compose.cjs <스토리보드.json> [서버 주소=http://127.0.0.1:8765/]
// 스토리보드(JSON):
//   { "output": "output/ad/ad.mp4", "xfade": 0.6, "size": [1280, 720],
//     "clips": [ { "run": "W…", "node": "b", "captions": [ { "text": "…", "from": 0.4, "to": 4.8 } ] }, … ],
//     "endcard": { "title": "…", "subtitle": "…", "contact": "…", "note": "…", "seconds": 3 } }
// 서버가 내주는 산출물 주소(/api/workbench/runs/<run>/artifacts/<node>/0)를 같은 출처로 재생해 캔버스에 그리고, 브라우저(Edge)의 MediaRecorder로 녹화한다.
// 읽기만 한다 — Grok을 부르지 않고 서버 데이터를 바꾸지 않는다. 녹화는 실제 재생 시간만큼 걸린다.
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const fs = require('fs');
const path = require('path');

const boardFile = process.argv[2];
const base = (process.argv[3] || 'http://127.0.0.1:8765/').replace(/\/?$/, '/');
if (!boardFile) { console.error('스토리보드 JSON 경로가 필요해요.'); process.exit(2); }
const board = JSON.parse(fs.readFileSync(boardFile, 'utf-8'));
const outFile = path.resolve(board.output || 'output/ad/ad.mp4');
fs.mkdirSync(path.dirname(outFile), { recursive: true });

(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(base + '#view=home');
  await page.waitForFunction(() => typeof Data !== 'undefined' && Data.loaded, null, { timeout: 60000 });
  const result = await page.evaluate(async (board) => {
    const [W, H] = board.size || [1280, 720];
    const xf = board.xfade ?? 0.6;
    const clips = board.clips.map((c) => ({ ...c, url: c.url || `/api/workbench/runs/${c.run}/artifacts/${c.node || 'b'}/0` }));
    // 컷마다 영상 준비 (소리 끔, 처음부터 끝까지 한 번만 재생)
    for (const clip of clips) {
      const v = document.createElement('video');
      v.muted = true; v.playsInline = true; v.preload = 'auto'; v.src = clip.url;
      await new Promise((resolve, reject) => { v.onloadeddata = resolve; v.onerror = () => reject(new Error('재생 불가: ' + clip.url)); });
      clip.video = v; clip.len = v.duration;
    }
    let at = 0;
    for (const [i, clip] of clips.entries()) { clip.start = at; at += clip.len - (i < clips.length - 1 ? xf : 0); }
    const end = board.endcard || null;
    const total = at + (end ? 0 : 0);
    const canvas = document.createElement('canvas'); canvas.width = W; canvas.height = H;
    document.body.append(canvas);
    const ctx = canvas.getContext('2d');
    const type = ['video/mp4;codecs=avc1.42E01E', 'video/mp4', 'video/webm;codecs=vp9'].find((t) => MediaRecorder.isTypeSupported(t));
    const recorder = new MediaRecorder(canvas.captureStream(30), { mimeType: type, videoBitsPerSecond: 6000000 });
    const chunks = []; recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    const stopped = new Promise((resolve) => { recorder.onstop = resolve; });

    function plate(text, alpha, y, size) {
      ctx.save(); ctx.globalAlpha = alpha;
      ctx.font = `700 ${size}px "Malgun Gothic", "Segoe UI", sans-serif`;
      const w = ctx.measureText(text).width, padX = 34, padY = 18, h = size + padY * 2, x = (W - w) / 2 - padX;
      ctx.fillStyle = 'rgba(10, 14, 22, 0.55)';
      ctx.beginPath(); ctx.roundRect(x, y - h / 2, w + padX * 2, h, 18); ctx.fill();
      ctx.fillStyle = '#fff'; ctx.textBaseline = 'middle'; ctx.textAlign = 'center';
      ctx.fillText(text, W / 2, y + 2); ctx.restore();
    }
    function line(text, alpha, y, size, color = '#fff') {
      ctx.save(); ctx.globalAlpha = alpha; ctx.font = `700 ${size}px "Malgun Gothic", "Segoe UI", sans-serif`;
      ctx.fillStyle = color; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, W / 2, y); ctx.restore();
    }
    const ramp = (t, a, b, f = 0.35) => Math.max(0, Math.min(1, Math.min((t - a) / f, (b - t) / f)));

    recorder.start(500);
    const t0 = performance.now();
    const endSeconds = end ? (end.seconds || 3) : 0;
    const last = clips[clips.length - 1];
    await new Promise((resolve) => {
      const started = new Set();
      function frame() {
        const t = (performance.now() - t0) / 1000;
        for (const [i, clip] of clips.entries()) if (!started.has(i) && t >= clip.start) { started.add(i); clip.video.currentTime = 0; clip.video.play(); }
        ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
        for (const [i, clip] of clips.entries()) {
          if (!started.has(i)) continue;
          const alpha = i === 0 ? 1 : Math.min(1, (t - clip.start) / xf);
          ctx.globalAlpha = alpha; ctx.drawImage(clip.video, 0, 0, W, H); ctx.globalAlpha = 1;
        }
        for (const clip of clips) {
          if (!started.has(clips.indexOf(clip))) continue;
          const local = t - clip.start;
          for (const cap of clip.captions || []) { const a = ramp(local, cap.from, cap.to); if (a > 0) plate(cap.text, a, H - 96, 40); }
        }
        if (end) {
          const local = t - (last.start + last.len - endSeconds);
          if (local > 0) {
            const a = Math.min(1, local / 0.8);
            ctx.save(); ctx.globalAlpha = a * 0.62; ctx.fillStyle = '#0b1220'; ctx.fillRect(0, 0, W, H); ctx.restore();
            line(end.title, a, H * 0.40, 66);
            if (end.subtitle) line(end.subtitle, Math.min(1, Math.max(0, (local - 0.4) / 0.6)), H * 0.40 + 78, 38, '#9be7ff');
            if (end.contact) line(end.contact, Math.min(1, Math.max(0, (local - 0.8) / 0.6)), H * 0.40 + 138, 30);
            if (end.note) line(end.note, a, H - 40, 20, 'rgba(255,255,255,.75)');
          }
        }
        if (t >= last.start + last.len + (end ? 0.2 : 0.1) || t > total + 6) return resolve();
        requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    });
    recorder.stop(); await stopped;
    const blob = new Blob(chunks, { type });
    const buffer = new Uint8Array(await blob.arrayBuffer());
    window.__composed = buffer;
    return { type, bytes: buffer.length, seconds: Math.round((performance.now() - t0) / 100) / 10, clips: clips.map((c) => ({ url: c.url, len: Math.round(c.len * 100) / 100, start: Math.round(c.start * 100) / 100 })) };
  }, board);
  // 큰 파일은 조각으로 가져온다
  const fd = fs.openSync(outFile, 'w');
  for (let pos = 0; pos < result.bytes; pos += 3 * 1024 * 1024) {
    const part = await page.evaluate(([from, to]) => {
      let s = ''; const view = window.__composed.subarray(from, to);
      for (let i = 0; i < view.length; i += 0x8000) s += String.fromCharCode.apply(null, view.subarray(i, i + 0x8000));
      return btoa(s);
    }, [pos, Math.min(result.bytes, pos + 3 * 1024 * 1024)]);
    fs.writeSync(fd, Buffer.from(part, 'base64'));
  }
  fs.closeSync(fd);
  console.log(JSON.stringify({ output: outFile, ...result, errors }));
  await browser.close();
})().catch((e) => { console.error(e.message); process.exit(1); });
