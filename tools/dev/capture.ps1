# 화면 캡처 (Edge 헤드리스, 1536x1024). 서버가 떠 있어야 한다.
#
#   pwsh tools/dev/capture.ps1 -Port 8793 -Prefix step5 -Names main,quests,meeting
#
# 이름 → 주소: main(본사), stop(#demo=stop 긴급 정지 자세), rest/blocked/call/warp/work(#demo=… 자세 고정, warp = 소환 중간),
# floor2/floor2rest(2층, 일하는 자세·쉬는 자세), bodies/bodieswork(몸 막대 비교: 선 자세·앉은 자세),
# quests, inbox, meeting, diary, team, sheet, trophies, alerts, customize, skills (#open=… 팝업).
# board(진행판 칸반), boardflip(진행판 보드를 뒤집은 채로 — 작업이 넘어갈 때 모습).
# boardstates(가짜 작업으로 다섯 칸·막힘·결재·스킬이 모두 보이는 진행판), boardcalm(할 일 없음 초록 줄), boardlong(아주 긴 제목·이유), boardempty(작업 없음) — 개발용 주소 #boarddemo=… (서버에 아무것도 보내지 않음).
# rig(인형 뼈대 맞추기 화면: 큰 인형 + 매개변수 슬라이더), rigreg(영역 무게를 색으로 겹침), rigpose(#pose=angleZ:1,hairSway:-1 멈춘 자세).
# 캐릭터 뼈대(WebGL)를 찍으려면 소프트웨어 WebGL을 켜는 --enable-unsafe-swiftshader가 필요해 아래 옵션에 넣어 두었다.
# 두 캡처를 동시에 돌릴 때는 -ProfileName으로 브라우저 저장 폴더를 나눈다 (기본 ais-edge-profile을 같이 쓰면 충돌할 수 있다).
# 결과: docs/design/captures/<Prefix>-<이름>.png
param(
  [int]$Port = 8793,
  [string[]]$Names = @('main'),
  [string]$Prefix = 'capture',
  [int]$BudgetMs = 4000,
  [string]$ProfileName = 'ais-edge-profile'
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw 'Microsoft Edge를 찾지 못했습니다.' }
$map = @{
  main = '#view=office'; stop = '#demo=stop'; rest = '#demo=rest'; blocked = '#demo=blocked'; call = '#demo=call'; warp = '#demo=warp'; work = '#demo=work'
  bodies = '#demo=bodies'; bodieswork = '#demo=bodieswork'; floor2 = '#floor=2&demo=crowd'; floor2rest = '#floor=2&demo=crowdrest'
  quests = '#open=quests'; inbox = '#open=inbox'; meeting = '#open=meeting'; diary = '#open=diary'; team = '#open=team'
  sheet = '#open=sheet'; trophies = '#open=trophies'; alerts = '#open=alerts'; customize = '#open=customize'
  skills = '#open=skills'; jobcard = '#open=jobcard'; grades = '#open=grades'; workshop = '#open=workshop'; mcp = '#open=mcp'; schedules = '#open=schedules'; remote = '#open=remote'
  board = '#view=board'; boardflip = '#view=board&demo=boardflip'
  boardstates = '#view=board&boarddemo=states'; boardcalm = '#view=board&boarddemo=calm'; boardlong = '#view=board&boarddemo=long'; boardempty = '#view=board&boarddemo=empty'
  rig = '#view=board&demo=rig'; rigreg = '#view=board&demo=rig&overlay=regions'; rigpose = '#view=board&pose=angleZ:1,hairSway:-1'
}
# 짧은 경로의 임시 폴더를 쓴다 (Windows 경로 260자 제한)
$edgeProfile = Join-Path $env:TEMP $ProfileName
$common = @('--headless=new', '--disable-gpu', '--enable-unsafe-swiftshader', '--hide-scrollbars', '--no-first-run', "--user-data-dir=$edgeProfile", '--window-size=1536,1024', "--virtual-time-budget=$BudgetMs")
$out = Join-Path $root 'docs\design\captures'
New-Item -ItemType Directory -Force $out | Out-Null
foreach ($n in $Names) {
  if (-not $map.ContainsKey($n)) { Write-Warning "모르는 이름: $n"; continue }
  $tmp = Join-Path $env:TEMP "ais-$Prefix-$n.png"
  Start-Process -FilePath $edge -ArgumentList ($common + @("--screenshot=$tmp", "http://127.0.0.1:$Port/$($map[$n])")) -Wait
  Move-Item $tmp (Join-Path $out "$Prefix-$n.png") -Force
  "$Prefix-$n.png"
}
