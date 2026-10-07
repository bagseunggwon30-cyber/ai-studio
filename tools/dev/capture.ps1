# 화면 캡처 (Edge 헤드리스, 1536x1024). 서버가 떠 있어야 한다.
#
#   pwsh tools/dev/capture.ps1 -Port 8793 -Prefix step5 -Names home,board,meeting
#
# 이름 → 주소: home(홈), board(진행판), media(이미지·영상 작업대), novelroom(소설 집필실), designroom(디자인 작업실), workbench(옛 노드 편집기),
# quests, inbox, meeting, diary, team, sheet, trophies, alerts, customize, skills, hire, finderq … (#open=… 팝업).
# 옛 도트 사무실 화면(main·stop·rest·blocked·call·warp·work·bodies·floor2 …)은 2026-10-06에 없앴다 — 그 주소를 붙여도 홈이 열린다.
# board(진행판 칸반), boardflip(진행판 보드를 뒤집은 채로 — 작업이 넘어갈 때 모습).
# media(이미지·영상 작업대 첫 화면). 상태별 캡처(그림 결과·영상 결과·만드는 중·확인 창·연결 창·처음 쓰는 모습)는 눌러 봐야 해서 node tools/dev/media_browser.cjs --shots 가 modern-media-*.png 로 남긴다.
# novelroom(소설 집필실 첫 화면) · designroom(디자인 작업실 첫 화면): 프로젝트가 있어야 볼만하므로 가짜 회사(fake-company.ps1)가 아니라 소설·디자인 예시 프로젝트가 든 연습용 서버
#   python tools/dev/rooms_fixture.py --port 8801 (끝나면 표준 입력에 stop) 주소로 찍는다: pwsh tools/dev/capture.ps1 -Port 8801 -Prefix check -Names novelroom,designroom.
#   눌러 봐야 하는 상태(원고 읽기·시작 버튼 펼침·새 작품 만들기 창·시안·그림 보기·프로젝트 없음 안내)는 node tools/dev/rooms_browser.cjs --shots 가 modern-novel-*.png · modern-design-*.png 로 남긴다.
# boardstates(가짜 작업으로 다섯 칸·막힘·결재·스킬이 모두 보이는 진행판), boardcalm(할 일 없음 초록 줄), boardlong(아주 긴 제목·이유), boardempty(작업 없음) — 개발용 주소 #boarddemo=… (서버에 아무것도 보내지 않음).
# rig(인형 뼈대 맞추기 화면: 큰 인형 + 매개변수 슬라이더), rigreg(영역 무게를 색으로 겹침), rigpose(#pose=angleZ:1,hairSway:-1 멈춘 자세).
# 캐릭터 뼈대(WebGL)를 찍으려면 소프트웨어 WebGL을 켜는 --enable-unsafe-swiftshader가 필요해 아래 옵션에 넣어 두었다.
# 두 캡처를 동시에 돌릴 때는 -ProfileName으로 브라우저 저장 폴더를 나눈다 (기본 ais-edge-profile을 같이 쓰면 충돌할 수 있다).
# 휴대폰 리모컨(/m): mstates(가짜 작업으로 결재함), minbox·mwork·morder·malerts(탭별), mdetail(작업 상세), mpair(짝짓기 화면) — 개발용 주소 /m#demo=… (서버에 아무것도 보내지 않음).
# 이 이름들은 390x844(화면 배율 2, 터치 기기)로 찍는다. Edge 헤드리스는 창이 500px보다 좁아지지 않아서, 이 이름만 CDP로 화면 크기를 흉내 낸다(node 필요). 찍는 동안 페이지 오류·콘솔 오류도 알려 준다.
# -FullPage를 붙이면 휴대폰 화면을 스크롤하지 않고 끝까지 한 장에 찍는다(검토용).
# 결과: docs/design/captures/<Prefix>-<이름>.png
param(
  [int]$Port = 8793,
  [string[]]$Names = @('home'),
  [string]$Prefix = 'capture',
  [int]$BudgetMs = 4000,
  [string]$ProfileName = 'ais-edge-profile',
  [switch]$FullPage
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw 'Microsoft Edge를 찾지 못했습니다.' }
$map = @{
  quests = '#open=quests'; inbox = '#open=inbox'; meeting = '#open=meeting'; diary = '#open=diary'; team = '#open=team'
  sheet = '#open=sheet'; trophies = '#open=trophies'; alerts = '#open=alerts'; customize = '#open=customize'
  skills = '#open=skills'; jobcard = '#open=jobcard'; grades = '#open=grades'; workshop = '#open=workshop'; mcp = '#open=mcp'; schedules = '#open=schedules'; remote = '#open=remote'
  taskcard = '#open=taskcard'; approval = '#open=approval'; skilldetail = '#open=skilldetail'; mcpdetail = '#open=mcpdetail'; hire = '#open=hire'; login = '#open=login'
  digest = '#open=digest&boarddemo=states'; finder = '#open=finder&boarddemo=states'; finderq = '#open=finder&boarddemo=states&q=솔'
  home = '#view=home'; homestates = '#view=home&boarddemo=states'; boardlist = '#view=board&boarddemo=states&mode=list'; boardgroup = '#view=board&boarddemo=states&group=1'; boardapproval = '#view=board&boarddemo=states&boardview=approval'
  board = '#view=board'; workbench = '#view=workbench'; boardflip = '#view=board&demo=boardflip'; media = '#view=media'
  novelroom = '#view=novel'; designroom = '#view=design'
  boardstates = '#view=board&boarddemo=states'; boardcalm = '#view=board&boarddemo=calm'; boardlong = '#view=board&boarddemo=long'; boardempty = '#view=board&boarddemo=empty'
  mstates = 'm#demo=states'; minbox = 'm#demo=states&tab=inbox'; mwork = 'm#demo=states&tab=work'; morder = 'm#demo=states&tab=order'; malerts = 'm#demo=states&tab=alerts'
  mdetail = 'm#demo=states&open=D101'; mpair = 'm#demo=pair'
  rig = '#view=board&demo=rig'; rigreg = '#view=board&demo=rig&overlay=regions'; rigpose = '#view=board&pose=angleZ:1,hairSway:-1'
}
# 짧은 경로의 임시 폴더를 쓴다 (Windows 경로 260자 제한)
$edgeProfile = Join-Path $env:TEMP $ProfileName
$common = @('--headless=new', '--disable-gpu', '--enable-unsafe-swiftshader', '--hide-scrollbars', '--no-first-run', "--user-data-dir=$edgeProfile", '--window-size=1536,1024', "--virtual-time-budget=$BudgetMs")
$phoneNames = @('mstates', 'minbox', 'mwork', 'morder', 'malerts', 'mdetail', 'mpair')
$phoneJobs = @()
$out = Join-Path $root 'docs\design\captures'
New-Item -ItemType Directory -Force $out | Out-Null
foreach ($n in $Names) {
  if (-not $map.ContainsKey($n)) { Write-Warning "모르는 이름: $n"; continue }
  if ($phoneNames -contains $n) { $phoneJobs += $n; continue } # 휴대폰 이름은 아래에서 따로 (CDP)
  $tmp = Join-Path $env:TEMP "ais-$Prefix-$n.png"
  Start-Process -FilePath $edge -ArgumentList ($common + @("--screenshot=$tmp", "http://127.0.0.1:$Port/$($map[$n])")) -Wait
  Move-Item $tmp (Join-Path $out "$Prefix-$n.png") -Force
  "$Prefix-$n.png"
}

# 휴대폰 크기 캡처용 node 스크립트 (실행할 때 임시 파일로 쓴다). 화면 크기 흉내: Emulation.setDeviceMetricsOverride.
$phoneShotJs = @'
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
const [edge, port, outDir, prefix, profileName, full, ...jobs] = process.argv.slice(2);
const dbg = 9400 + Math.floor(Math.random() * 400);
const profile = path.join(os.tmpdir(), profileName);
const proc = spawn(edge, ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run', `--user-data-dir=${profile}`, `--remote-debugging-port=${dbg}`, '--window-size=500,1000', 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 60 && !target; i++) {
  try { target = (await (await fetch(`http://127.0.0.1:${dbg}/json`)).json()).find((t) => t.type === 'page'); } catch (_) { /* 기다림 */ }
  if (!target) await sleep(250);
}
if (!target) { console.error('Edge 화면에 연결하지 못했습니다.'); proc.kill(); process.exit(1); }
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => { ws.onopen = r; });
let seq = 0;
const waits = new Map();
const problems = [];
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && waits.has(d.id)) { waits.get(d.id)(d); waits.delete(d.id); return; }
  if (d.method === 'Runtime.exceptionThrown') problems.push('예외: ' + (d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text));
  else if (d.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(d.params.type)) problems.push('콘솔 ' + d.params.type + ': ' + d.params.args.map((a) => a.value ?? a.description ?? '').join(' '));
  else if (d.method === 'Log.entryAdded' && ['error', 'warning'].includes(d.params.entry.level)) problems.push('로그 ' + d.params.entry.level + ': ' + d.params.entry.text + ' ' + (d.params.entry.url || ''));
};
const send = (method, params = {}) => new Promise((res) => { const i = ++seq; waits.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');
await send('Runtime.enable');
await send('Log.enable');
const metrics = (height) => send('Emulation.setDeviceMetricsOverride', { width: 390, height, deviceScaleFactor: 2, mobile: true });
for (const job of jobs) {
  const at = job.indexOf('=');
  const name = job.slice(0, at);
  problems.length = 0;
  await metrics(844);
  await send('Page.navigate', { url: 'about:blank' }); // 같은 쪽에서 #뒤만 바뀌면 다시 안 읽으므로 비웠다가 간다
  await sleep(150);
  await send('Page.navigate', { url: `http://127.0.0.1:${port}/${job.slice(at + 1)}` });
  await sleep(1500);
  if (full === '1') {
    const r = await send('Runtime.evaluate', { expression: 'document.documentElement.scrollHeight', returnByValue: true });
    await metrics(Math.max(844, r.result.result.value));
    await sleep(300);
  }
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(outDir, `${prefix}-${name}.png`), Buffer.from(shot.result.data, 'base64'));
  console.log(`${prefix}-${name}.png` + (problems.length ? '  <-- 페이지 오류: ' + problems.join(' | ') : '  (페이지 오류 없음)'));
}
ws.close();
proc.kill();
await sleep(300);
try { fs.rmSync(profile, { recursive: true, force: true }); } catch (_) { /* 무시 */ }
process.exit(0);
'@
if ($phoneJobs.Count -gt 0) {
  $phoneScript = Join-Path $env:TEMP "ais-phone-shot-$Prefix.mjs"
  Set-Content -Path $phoneScript -Value $phoneShotJs -Encoding utf8
  $jobArgs = @($phoneJobs | ForEach-Object { "$_=$($map[$_])" })
  & node $phoneScript $edge $Port $out $Prefix "$ProfileName-cdp" $(if ($FullPage) { '1' } else { '0' }) @jobArgs
  Remove-Item $phoneScript -ErrorAction SilentlyContinue
}
