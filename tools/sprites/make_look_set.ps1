# 의상 세트 그림을 Codex CLI(본인 ChatGPT 로그인, API 키 없음)로 뽑는다.
#
#   pwsh tools/sprites/make_look_set.ps1 -Set summer -Step sheets     # 직원별 동작 시트 4장
#   pwsh tools/sprites/make_look_set.ps1 -Set summer -Step walks      # 걷기 4장 (새 동작 시트를 옷 참고로 씀)
#   pwsh tools/sprites/make_look_set.ps1 -Set summer -Step portraits  # 얼굴 12장 한 장
#
# 결과: assets-raw/looks/<세트>/char-<직원>.png, walk-<직원>.png, portraits.png (이미 있으면 건너뜀, -Force로 다시)
# 다음: make_strips.gd, make_portraits.gd, make_masks.gd를 차례로 돌린다 (asset-prompts.md).
param(
  [Parameter(Mandatory)][string]$Set,
  [ValidateSet('sheets', 'walks', 'portraits')][string]$Step = 'sheets',
  [string[]]$Only = @(),
  [switch]$Force
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$cfg = Get-Content "$PSScriptRoot\look-sets.json" -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
if (-not $cfg.sets.ContainsKey($Set)) { throw "look-sets.json에 '$Set' 세트가 없습니다." }
$def = $cfg.sets[$Set]
$out = Join-Path $root "assets-raw\looks\$Set"
New-Item -ItemType Directory -Force $out | Out-Null

# Codex CLI: 데스크톱 앱 번들 중 가장 새 것 (npm 판은 GPT-6 모델을 못 쓴다)
$codex = Get-ChildItem "$env:LOCALAPPDATA\OpenAI\Codex\bin" -Recurse -Filter codex.exe -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $codex) { throw 'Codex 앱의 codex.exe를 찾지 못했습니다.' }
$codexPath = $codex.FullName

$jobs = @()
foreach ($c in $cfg.characters.Keys) {
  if ($Only.Count -and $Only -notcontains $c) { continue }
  $who = $cfg.characters[$c]
  $outfit = $def.outfits[$c]
  if ($Step -eq 'sheets') {
    $target = Join-Path $out "char-$c.png"
    $images = @("assets-raw\char-$c.png")
    $prompt = @"
Use your image generation tool in EDIT mode with the attached image as the input reference. It is the sprite sheet of our game character $who. Keep the exact same 4x2 grid layout, the same 8 poses in the same cells, the same size and position of the character in every cell, the same face, hair, body proportions and crisp 16-bit pixel-art style, and the same flat solid pure magenta (#FF00FF) background. Output one new image, landscape 1536x1024.

Change ONLY the clothes, in all 8 cells: $outfit.
Everything else stays identical. No text, no shadows, no floor, no grid lines, no effects.
"@
  } elseif ($Step -eq 'walks') {
    $target = Join-Path $out "walk-$c.png"
    $sheet = "assets-raw\looks\$Set\char-$c.png"
    if (-not (Test-Path (Join-Path $root $sheet))) { Write-Warning "${c}: 먼저 -Step sheets를 돌리세요."; continue }
    $images = @("assets-raw\walk-$c.png", $sheet)
    $prompt = @"
Use your image generation tool in EDIT mode with the FIRST attached image as the input reference. It is the 4-frame walk cycle of our game character $who. Keep the exact same 4 frames in one row, the same poses, positions, sizes, face, hair and crisp 16-bit pixel-art style, and the same flat solid pure magenta (#FF00FF) background. Output one new image, landscape 1536x1024.

Change ONLY the clothes in all 4 frames so they match the outfit worn in the SECOND attached image: $outfit.
No text, no shadows, no ground line, no grid lines, no motion marks.
"@
  } else {
    continue
  }
  if ((Test-Path $target) -and -not $Force) { Write-Host "건너뜀 (있음): $target"; continue }
  $jobs += [pscustomobject]@{ Name = $c; Target = $target; Images = $images; Prompt = $prompt }
}

if ($Step -eq 'portraits') {
  $target = Join-Path $out 'portraits.png'
  $sheets = $cfg.characters.Keys | ForEach-Object { "assets-raw\looks\$Set\char-$_.png" } | Where-Object { Test-Path (Join-Path $root $_) }
  $lines = ($cfg.characters.Keys | ForEach-Object { "- $($cfg.characters[$_]): $($def.outfits[$_])" }) -join "`n"
  $prompt = @"
Use your image generation tool in EDIT mode with the FIRST attached image as the input reference. It is a sheet of bust portraits: 4 columns (one character each) x 3 rows (normal, happy, worried). Keep the exact same grid, the same faces, expressions, hair, sizes, framing and crisp 16-bit pixel-art style, and the same flat solid pure magenta (#FF00FF) background. Output one new image, landscape 1536x1024.

Change ONLY the clothes visible at the shoulders so each character wears their new outfit (the other attached images show them):
$lines
No text, no frames, no shadows, no grid lines.
"@
  if (-not (Test-Path $target) -or $Force) {
    $jobs += [pscustomobject]@{ Name = 'portraits'; Target = $target; Images = @('assets-raw\portraits.png') + $sheets; Prompt = $prompt }
  }
}

# 한 번에 최대 4장씩 동시에 그린다 (한 장에 1~2분).
$jobs | ForEach-Object -ThrottleLimit 4 -Parallel {
  foreach ($k in 'OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', 'ANTHROPIC_API_KEY', 'AZURE_OPENAI_API_KEY') {
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
