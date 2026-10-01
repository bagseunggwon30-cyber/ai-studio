# 층 배경(본사 1층, 일하는 층 2층)을 Codex CLI(본인 ChatGPT 로그인, API 키 없음)로 뽑는다. (CEO 결정 2026-09-29: 본사 새로 그리기 + 층 늘리기)
#
#   pwsh tools/sprites/make_floors.ps1                  # 두 장 모두 (이미 있으면 건너뜀)
#   pwsh tools/sprites/make_floors.ps1 -Only f2 -Force
#   pwsh tools/sprites/make_floors.ps1 -Only f1 -Tag b  # 후보를 하나 더 (bg-office-f1-b.png)
#
# 결과: assets-raw/bg-office-f1.png, bg-office-f2.png. 고른 그림은 ui/assets/bg/로 복사하고 scene.js FLOORS의 자리를 잰다.
# 의자는 등받이가 보이게(뒤에서 본 모습) 그린다: 직원은 등을 보이며 앉고, 등받이 가림막이 몸 아래를 가린다.
param([string[]]$Only = @(), [switch]$Force, [string]$Tag = '')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
New-Item -ItemType Directory -Force (Join-Path $root 'assets-raw') | Out-Null

$codex = Get-ChildItem "$env:LOCALAPPDATA\OpenAI\Codex\bin" -Recurse -Filter codex.exe -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $codex) { throw 'Codex 앱의 codex.exe를 찾지 못했습니다.' }
$codexPath = $codex.FullName

$plate = @'
This is an EMPTY background plate for a cozy pixel-art management game (like Kairosoft games):
- No people, no animals, no text, letters or numbers anywhere. Every sign plate, paper, poster and screen is blank.
- All computer monitors are turned off (dark screens).
- The top 70 px and the bottom 130 px of the image are covered by game UI later: keep only wall or plain floor there, no important furniture.
- Every office chair is a black swivel chair seen from BEHIND: its backrest faces the viewer and the seat faces the desk, pulled out a little so a person could sit in it. All chairs look the same.
- Leave clear, empty floor aisles around the desks so characters can stand there.
'@

$floors = [ordered]@{
  f1 = @{
    Images = @('ui\assets\bg\office.png')
    Prompt = @"
Use your image generation tool in EDIT mode with the attached image as the input reference — keep the same crisp 16-bit pixel-art style, outline thickness, palette, warm daylight and 3/4 top-down camera angle. Output one new image, landscape 1536x1024.

Redraw this company headquarters office with a NEW, roomier layout:
1. Keep along the top wall: the two windows, the round wall clock, the cork quest board (empty, no notes) in the upper middle, and the glass-walled meeting room in the upper right with its round table, purple chairs and lavender rug.
2. Keep on the left wall: tall bookshelves and the small whiteboard (blank) with a blank wooden sign plate above it.
3. Work area in the middle-left: SIX identical wooden desks in TWO ROWS of THREE, every desk facing the top of the image (monitor on the far edge of the desk, keyboard, a mug or plant), a black office chair on the near side of each desk, low gray cubicle partitions between neighboring desks. Wide aisle between the two rows.
4. Right side under the meeting room: a long wooden trophy shelf with empty compartments and a blank sign plate.
5. Bottom right: a BIG lounge (much bigger than before) on a large soft rug: two purple beanbags, a green floor cushion, a small two-seat sofa, a round low coffee table, a coffee machine on a small cabinet, plants, and a blank sign plate. Leave open rug space in the middle.
6. Bottom left: the wooden stair railing going down.
$plate
"@
  }
  f2 = @{
    Images = @('ui\assets\bg\office.png')
    Prompt = @"
Use your image generation tool. The attached image is ONLY a style reference: match its crisp 16-bit pixel-art style, outline thickness, palette, warm daylight and 3/4 top-down camera angle. Do NOT redraw the attached room. Output one new image, landscape 1536x1024.

Draw the SECOND FLOOR of the same company: an open-plan work floor.
1. Top wall: a row of large windows with a city view, a round wall clock, a blank whiteboard, potted plants.
2. Work area covering the left two thirds: EIGHT identical wooden desks in TWO ROWS of FOUR, every desk facing the top of the image (monitor on the far edge of the desk, keyboard, a mug or small plant), a black office chair on the near side of each desk, low gray cubicle partitions between neighboring desks. Wide aisle between the two rows.
3. Right third: a lounge on a large soft rug: a small two-seat sofa, two beanbags (purple and green), a round low coffee table, a coffee machine and a water cooler, bookshelf, plants, and a blank wooden sign plate above it. Leave open rug space.
4. Bottom left: a staircase landing with a wooden railing going down.
$plate
"@
  }
}

$suffix = if ($Tag) { "-$Tag" } else { '' }
$jobs = foreach ($name in $floors.Keys) {
  if ($Only.Count -and $Only -notcontains $name) { continue }
  $target = Join-Path $root "assets-raw\bg-office-$name$suffix.png"
  if ((Test-Path $target) -and -not $Force) { Write-Host "건너뜀 (있음): $target"; continue }
  [pscustomobject]@{ Name = $name; Target = $target; Images = $floors[$name].Images; Prompt = $floors[$name].Prompt }
}

# 한 장에 1~3분. 동시에 그린다.
$jobs | ForEach-Object -ThrottleLimit 4 -Parallel {
  foreach ($k in 'OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', 'ANTHROPIC_API_KEY', 'AZURE_OPENAI_API_KEY', 'XAI_API_KEY') {
    [Environment]::SetEnvironmentVariable($k, $null, 'Process')
  }
  $job = $_
  $cliArgs = @('exec')
  foreach ($i in $job.Images) { $cliArgs += @('-i', $i) }
  $cliArgs += @('--json', '--ephemeral', '--ignore-user-config', '--skip-git-repo-check', '-s', 'read-only',
    '-C', $using:root, '-m', 'gpt-6-luna', '-c', 'model_reasoning_effort="low"')
  Push-Location $using:root
  try { $lines = $job.Prompt | & $using:codexPath @cliArgs 2>$null } finally { Pop-Location }
  $thread = ($lines | Select-String '"thread_id":"([^"]+)"' | Select-Object -First 1).Matches.Groups[1].Value
  # Codex가 "결과가 없다"고 답해도 파일은 저장돼 있을 때가 많다. 폴더를 직접 본다.
  $png = if ($thread) { Get-ChildItem "$env:USERPROFILE\.codex\generated_images\$thread" -Filter *.png -ErrorAction SilentlyContinue | Select-Object -First 1 }
  if ($png) {
    Copy-Item $png.FullName $job.Target -Force
    Write-Host "완료: $($job.Name) → $($job.Target)"
  } else {
    Write-Warning "실패: $($job.Name) (thread $thread) — 다시 돌리세요."
  }
}
