# 소품(C1)·아이콘(C2)·창 틀(C3) 시트를 Codex CLI(본인 ChatGPT 로그인, API 키 없음)로 뽑는다.
#
#   pwsh tools/sprites/make_ui_sheets.ps1                 # 세 장 모두 (이미 있으면 건너뜀)
#   pwsh tools/sprites/make_ui_sheets.ps1 -Only props -Force
#
# 결과: assets-raw/props.png, icons.png, panels.png (asset-prompts.md C1~C3)
# 다음: make_ui_assets.gd로 칸마다 잘라 ui/assets/ui/에 둔다.
# 첨부 그림은 '그림체 참고'로만 쓴다 (첨부 장면을 다시 그리지 말라고 분명히 적는다).
param([string[]]$Only = @(), [switch]$Force)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
New-Item -ItemType Directory -Force (Join-Path $root 'assets-raw') | Out-Null

$codex = Get-ChildItem "$env:LOCALAPPDATA\OpenAI\Codex\bin" -Recurse -Filter codex.exe -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $codex) { throw 'Codex 앱의 codex.exe를 찾지 못했습니다.' }
$codexPath = $codex.FullName

$style = 'Use your image generation tool. The attached image is ONLY a style reference: match its crisp 16-bit pixel-art style, outline thickness, palette and warm lighting. Do NOT redraw the attached scene. Output one new image, landscape 1536x1024.'

$sheets = [ordered]@{
  props  = @{
    Images = @('docs\design\01-main-office.webp')
    Prompt = @"
$style

Draw a sprite sheet of 16 small game props in a 4x4 grid of equal cells on a flat, solid, pure magenta background (#FF00FF). Each prop is centered in its cell with plenty of empty magenta space around it. No text or letters anywhere, no shadows on the background, no grid lines, no frames around the cells.
Row 1 (flat front views of a monitor SCREEN only, no bezel stand): 1) colorful lines of code on a dark navy screen; 2) a white document with blue text lines; 3) a small bar chart on a white screen; 4) a dark screen with a white pause symbol.
Row 2: 5) small gold trophy cup on a wooden base; 6) purple game cartridge with an empty cream label area; 7) small wooden picture frame holding a blank white paper; 8) calico cat curled up asleep on a round purple cushion.
Row 3: 9) round red wax seal; 10) round purple wax seal; 11) round gold wax seal; 12) red alarm beacon lamp, lit and glowing, on a small gray base.
Row 4: 13) blank yellow square sticky note with a red pushpin at the top center; 14) the same in green; 15) the same in pink; 16) the same in lavender.
"@
  }
  icons  = @{
    Images = @('docs\design\01-main-office.webp')
    Prompt = @"
$style

Draw a sheet of 16 pixel-art UI icons in a 4x4 grid of equal cells on a flat, solid, pure magenta background (#FF00FF). Every icon is centered in its cell, all icons the same size (about half of the cell), with a bold dark plum (#2E2B3D) outline and flat cream (#F6F0E4) and lavender (#7F77DD) fills with small highlights, like the top bar and bottom round buttons of the attached image. No text or letters, no shadows on the background, no grid lines.
Row 1: 1) studio logo: lavender rounded square with a small cream mark of two dots joined by a line; 2) yellow lightning bolt; 3) cream envelope; 4) cream bell.
Row 2: 5) round red stop button with a white square in the middle; 6) cream rolled scroll (quest list); 7) group of three people (employees); 8) open book.
Row 3: 9) white paper-plane send arrow inside a lavender circle; 10) green circle with a white check mark; 11) amber circle with a white exclamation mark; 12) chain link.
Row 4: 13) document page with lines; 14) shield with a check mark; 15) folder; 16) archive box.
"@
  }
  panels = @{
    Images = @('docs\design\03-approval.webp', 'docs\design\02-quest-board.webp')
    Prompt = @"
$style

Draw seven separate blank UI panel objects on a flat, solid, pure magenta background (#FF00FF), loosely arranged in a grid with clear magenta gaps between them. Every panel is completely blank: no text, no icons, no writing, no drawings on it. No shadows on the background, no grid lines.
1) parchment paper card with a silver paper clip at the top left; 2) cork board in a wooden frame with four empty colored header strips across the top (gray, blue, yellow, green); 3) wooden clipboard holding a blank cream sheet; 4) open brown leather journal lying flat with two blank cream pages; 5) empty wooden letter tray; 6) wooden shelf unit with 2x3 empty compartments; 7) small white speech bubble with a dark outline and a tail pointing down.
"@
  }
}

$jobs = foreach ($name in $sheets.Keys) {
  if ($Only.Count -and $Only -notcontains $name) { continue }
  $target = Join-Path $root "assets-raw\$name.png"
  if ((Test-Path $target) -and -not $Force) { Write-Host "건너뜀 (있음): $target"; continue }
  [pscustomobject]@{ Name = $name; Target = $target; Images = $sheets[$name].Images; Prompt = $sheets[$name].Prompt }
}

# 한 장에 1~2분. 세 장을 동시에 그린다.
$jobs | ForEach-Object -ThrottleLimit 3 -Parallel {
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
