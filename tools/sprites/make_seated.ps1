# 앉은 자세(타자 A·B, 긴급 정지 때 놀람)를 '뒤에서 본 모습'으로 다시 그린다 (CEO 요청 2026-09-29: 의자에 앉아 일하는 도트 개선).
# Codex CLI(본인 ChatGPT 로그인, API 키 없음)로 기존 동작 시트를 EDIT 모드로 넣고 1·2·6번 칸만 바꾸게 한다.
#
#   pwsh tools/sprites/make_seated.ps1                       # 기본 옷 4명 (이미 있으면 건너뜀)
#   pwsh tools/sprites/make_seated.ps1 -Set summer           # 의상 세트
#   pwsh tools/sprites/make_seated.ps1 -Only sol -Force
#
# 결과(후보): assets-raw/seated/<base|세트>/char-<직원>.png
# 다음: 눈으로 확인한 뒤 compose_cells.gd로 1·2·6번 칸만 원래 시트(assets-raw/char-<직원>.png 등)에 옮기고 make_strips → make_masks.
# 새 본사 배경(make_floors.ps1)의 의자는 등받이가 보이게 그렸다: 직원은 그 의자에 등을 보이며 앉고, 등받이 가림막이 몸 아래를 가린다.
param([string]$Set = '', [string[]]$Only = @(), [switch]$Force)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$cfg = Get-Content "$PSScriptRoot\look-sets.json" -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
$name = if ($Set) { $Set } else { 'base' }
$out = Join-Path $root "assets-raw\seated\$name"
New-Item -ItemType Directory -Force $out | Out-Null

$codex = Get-ChildItem "$env:LOCALAPPDATA\OpenAI\Codex\bin" -Recurse -Filter codex.exe -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $codex) { throw 'Codex 앱의 codex.exe를 찾지 못했습니다.' }
$codexPath = $codex.FullName

# 앉았을 때 바라보는 쪽 (sheets.json facing과 같게)
$side = @{ hana = 'right'; sol = 'left'; clo = 'right'; luna = 'left' }

$jobs = @()
foreach ($c in $cfg.characters.Keys) {
  if ($Only.Count -and $Only -notcontains $c) { continue }
  $who = $cfg.characters[$c]
  $s = $side[$c]
  $sheet = if ($Set) { "assets-raw\looks\$Set\char-$c.png" } else { "assets-raw\char-$c.png" }
  if (-not (Test-Path (Join-Path $root $sheet))) { Write-Warning "${c}: 시트가 없습니다 ($sheet)"; continue }
  $target = Join-Path $out "char-$c.png"
  if ((Test-Path $target) -and -not $Force) { Write-Host "건너뜀 (있음): $target"; continue }
  $prompt = @"
Use your image generation tool in EDIT mode with the attached image as the input reference. It is the sprite sheet of our game character ${who}: a 4x2 grid of 8 equal cells (cells 1-4 on the top row, 5-8 on the bottom row). Keep the exact same character design, face, hair, clothes, colors, body proportions and SIZE, the same crisp 16-bit pixel-art style and outline, the same grid, and the same flat solid pure magenta (#FF00FF) background. Output one new image, landscape 1536x1024.

Keep cells 3, 4, 5, 7 and 8 exactly as they are.
Redraw ONLY cells 1, 2 and 6: the character sitting at a computer desk, seen from BEHIND and a little from the $s side (a 3/4 back view from the same high 3/4 top-down camera as a management game), so we see the back of the head, the back and shoulders, and a little of the $s cheek and ear. Draw only the character: no chair, no desk, no computer (they are in the background). Sit upright as on an office chair, hips at the bottom of the figure, legs forward under the desk and hidden behind the body.
1. typing on a keyboard in front of the body, both elbows bent forward, frame A
2. the same, frame B: hands and head moved slightly, for a 2-frame typing loop
6. sitting the same way, but turning the head and shoulders back toward the viewer over the $s shoulder, surprised face, both hands raised (a frozen, surprised pose)
The seated figure is about two thirds as tall as the standing figure in cell 4, with the same head size. Center each figure in its cell, same position in cells 1 and 2. No shadows, no floor, no text, no grid lines, no effects.
"@
  $jobs += [pscustomobject]@{ Name = $c; Target = $target; Images = @($sheet); Prompt = $prompt }
}

# 한 장에 1~3분. 네 장을 동시에 그린다.
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
  $png = if ($thread) { Get-ChildItem "$env:USERPROFILE\.codex\generated_images\$thread" -Filter *.png -ErrorAction SilentlyContinue | Select-Object -First 1 }
  if ($png) {
    Copy-Item $png.FullName $job.Target -Force
    Write-Host "완료: $($job.Name) → $($job.Target)"
  } else {
    Write-Warning "실패: $($job.Name) (thread $thread) — 다시 돌리세요."
  }
}
