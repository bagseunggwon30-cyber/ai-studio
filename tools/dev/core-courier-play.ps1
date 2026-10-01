# 코어 쿠리어 해보기: 제품 저장소에 합쳐진(=결재로 병합된) 판을 임시 폴더에 꺼내 게임 창을 띄운다.
# 제품 저장소(projects/core-courier)는 읽기만 한다 — Godot가 만드는 .godot 폴더가 저장소에 생기지 않는다.
#
#   pwsh tools/dev/core-courier-play.ps1                # 지금 main (마지막으로 병합된 판)
#   pwsh tools/dev/core-courier-play.ps1 -Ref 735d55b   # 옛 판 (단계별로 비교해 볼 때)
#   -Wait : 게임 창을 닫을 때까지 기다린다 (기본은 창을 띄우고 바로 끝난다)
#
# 판마다 처음 한 번은 파일을 풀고 Godot가 그림 목록을 만드느라 10초쯤 걸리고, 다음부터는 바로 뜬다.
# 조작: 방향키/WASD 이동, Esc 일시정지, R 다시 시작. 90초 안에 파란 코어 5개를 모아 초록 출구로.
# 자동 점검(화면 없이)은 core-courier-smoke.ps1.
param([string]$Ref = 'HEAD', [switch]$Wait)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8   # 한글이 깨지지 않게
$OutputEncoding = [System.Text.Encoding]::UTF8
$root = (Resolve-Path "$PSScriptRoot/../..").Path
$repo = Join-Path $root 'projects/core-courier'
$toml = Get-Content (Join-Path $root 'studio.toml') -Raw -Encoding UTF8
$consoleExe = [regex]::Match($toml, "(?m)^godot[ ]*=[ ]*'([^']+)'").Groups[1].Value
$godot = $consoleExe -replace '_console[.]exe$', '.exe'   # 창이 뜨는 쪽 (검은 콘솔 창이 없는 판)
if (-not $consoleExe -or -not (Test-Path $consoleExe) -or -not (Test-Path $godot)) { throw "Godot를 찾지 못했습니다 (studio.toml [tools] godot): $consoleExe" }

$sha = git -C $repo rev-parse --short=7 $Ref 2>$null
if ($LASTEXITCODE -ne 0 -or -not $sha) { throw "제품 저장소에서 '$Ref' 판을 찾지 못했습니다." }
$sha = "$sha".Trim()
$title = (git -C $repo log -1 --format=%s $sha).Trim()
Write-Host "코어 쿠리어 $sha — $title"

$base = Join-Path $env:TEMP 'ais-cc-play'
$dir = Join-Path $base $sha
$ready = Join-Path $dir '.ready'
if (-not (Test-Path $ready)) {
    Write-Host '처음이라 준비하는 중입니다 (10초쯤 걸려요)…'
    if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
    New-Item -ItemType Directory $dir -Force | Out-Null
    $zip = Join-Path $base "$sha.zip"
    git -C $repo archive --format=zip -o $zip $sha
    if ($LASTEXITCODE -ne 0) { throw "git archive 실패: $sha" }
    Expand-Archive $zip -DestinationPath $dir -Force
    Remove-Item $zip
    & $consoleExe --headless --path $dir --import *> $null   # 클래스 목록(class_name)을 만든다
    if (-not (Test-Path (Join-Path $dir '.godot/global_script_class_cache.cfg'))) { throw 'Godot 준비(--import)에 실패했습니다.' }
    Set-Content -Path $ready -Value $sha
}
# 예전 판 폴더는 치운다 (그 판의 게임이 열려 있어 못 지우면 그대로 둔다)
Get-ChildItem $base -Directory | Where-Object { $_.Name -ne $sha } | ForEach-Object {
    try { Remove-Item $_.FullName -Recurse -Force -ErrorAction Stop } catch { }
}

Write-Host '게임 창을 엽니다.'
Write-Host '  방향키 또는 WASD = 움직이기 · Esc = 잠깐 멈춤 · R = 다시 시작'
Write-Host '  90초 안에 파란 코어 5개를 모아서 초록 출구로! 빨간 공은 피하세요.'
$p = Start-Process -FilePath $godot -ArgumentList @('--path', "`"$dir`"") -PassThru
if ($Wait) { $p.WaitForExit() }
