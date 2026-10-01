# 코어 쿠리어 자동 확인 (화면 없이). 제품 저장소에 커밋된 판을 임시 폴더에 꺼내 Godot로 돌린다 — 제품 저장소는 건드리지 않는다.
#
#   pwsh tools/dev/core-courier-smoke.ps1            # 지금 main
#   pwsh tools/dev/core-courier-smoke.ps1 -Ref 8de477d
#
# 하는 일: 씬을 띄워 이동·방 안에서만 움직임·일시정지(Esc)·코어 줍기·출구 승리·재시작(R)·적 피격과 무적 깜빡임·시간 초과 패배를 확인한다.
# 규칙 검사(신뢰 테스트 8개)와는 별개다: 그쪽은 RunState만 보고, 이쪽은 씬·HUD·입력이 이어졌는지 본다. 종료 코드 = 실패한 개수.
# 스크립트 본문은 tools/dev/core_courier_smoke.gd. 게임을 바꾸면(노드 이름·HUD 글자) 여기 확인도 같이 고친다.
param([string]$Ref = 'HEAD')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8   # Godot가 내보내는 UTF-8 한글이 깨지지 않게
$OutputEncoding = [System.Text.Encoding]::UTF8
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$repo = Join-Path $root 'projects\core-courier'
$toml = Get-Content (Join-Path $root 'studio.toml') -Raw -Encoding UTF8
$godot = [regex]::Match($toml, "(?m)^godot\s*=\s*'([^']+)'").Groups[1].Value
if (-not $godot -or -not (Test-Path $godot)) { throw "Godot를 찾지 못했습니다 (studio.toml [tools] godot): $godot" }

$tmp = Join-Path $env:TEMP 'ais-cc-smoke'
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory $tmp | Out-Null
$zip = Join-Path $env:TEMP 'ais-cc-smoke.zip'
git -C $repo archive --format=zip -o $zip $Ref
if ($LASTEXITCODE -ne 0) { throw "git archive 실패: $Ref" }
Expand-Archive $zip -DestinationPath $tmp -Force
Remove-Item $zip
Copy-Item (Join-Path $PSScriptRoot 'core_courier_smoke.gd') (Join-Path $tmp 'smoke.gd')

& $godot --headless --path $tmp --import *> $null   # 클래스 목록(class_name)을 만든다
& $godot --headless --path $tmp --script res://smoke.gd 2>&1 | ForEach-Object { $_ -replace "$([char]27)\[[0-9;]*m", '' }
exit $LASTEXITCODE
