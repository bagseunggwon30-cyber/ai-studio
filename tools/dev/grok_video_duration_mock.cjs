// Offline media verification. Cached Edge only; no HTTP server or supplier calls.
const fs = require('fs');
const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const root = path.resolve(__dirname, '../..');
const fixture = path.join(root, 'tests/fixtures/mock-video-10s.webm');
const out = path.join(root, 'output/grok-video-duration');
let browser;
(async () => {
  fs.mkdirSync(out, { recursive: true });
  browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  const page = await browser.newPage();
  let bytes;
  if (!fs.existsSync(fixture)) {
    const encoded = await page.evaluate(async () => {
      const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 180;
      const ctx = canvas.getContext('2d'); ctx.fillStyle = '#fff8d7'; ctx.fillRect(0, 0, 320, 180);
      ctx.fillStyle = '#304b40'; ctx.font = '24px sans-serif'; ctx.fillText('MOCK 10-second clip', 20, 65);
      const stream = canvas.captureStream(5);
      const recorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8' });
      const chunks = []; recorder.ondataavailable = e => chunks.push(e.data);
      const stopped = new Promise(resolve => { recorder.onstop = resolve; }); recorder.start();
      let tick = 0; const timer = setInterval(() => { ctx.fillStyle = '#fff8d7'; ctx.fillRect(0, 100, 320, 80); ctx.fillStyle = '#304b40'; ctx.fillText(String(++tick), 140, 140); }, 200);
      await new Promise(resolve => setTimeout(resolve, 10200)); clearInterval(timer); recorder.stop(); await stopped;
      stream.getTracks().forEach(t => t.stop());
      return btoa(Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer()), c => String.fromCharCode(c)).join(''));
    });
    bytes = Buffer.from(encoded, 'base64');
    fs.mkdirSync(path.dirname(fixture), { recursive: true });
    fs.writeFileSync(fixture + '.tmp', bytes); fs.renameSync(fixture + '.tmp', fixture);
  } else bytes = fs.readFileSync(fixture);
  const report = await page.evaluate(async encoded => {
    const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
    const video = document.createElement('video'); video.controls = true;
    const url = URL.createObjectURL(new Blob([bytes], { type: 'video/webm' })); video.src = url; document.body.append(video);
    await new Promise((resolve, reject) => { video.onloadedmetadata = resolve; video.onerror = reject; });
    if (!Number.isFinite(video.duration)) {
      await new Promise(resolve => { video.onseeked = resolve; video.currentTime = 1e9; });
    }
    const duration = video.duration; video.currentTime = 0; await video.play();
    await new Promise(resolve => setTimeout(resolve, 300)); video.pause();
    const result = { simulation: true, requested_duration: 10, decoded_duration: duration, width: video.videoWidth, height: video.videoHeight, played: video.currentTime > 0, real_supplier_calls: 0, http_servers_started: 0 };
    URL.revokeObjectURL(url); return result;
  }, bytes.toString('base64'));
  if (!report.played || report.width !== 320 || Math.abs(report.decoded_duration - 10) > .3) throw new Error('Invalid 10-second mock: ' + JSON.stringify(report));
  await page.screenshot({ path: path.join(out, 'mock-video-10s.png') });
  fs.writeFileSync(path.join(out, 'media-report.json'), JSON.stringify(report, null, 2));
  process.stdout.write(JSON.stringify(report));
})().catch(e => { process.stderr.write(e.stack); process.exitCode = 1; }).finally(async () => { if (browser) await browser.close(); });
