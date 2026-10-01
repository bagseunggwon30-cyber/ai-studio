# 가짜 실행기(--fake)로 화면 흐름을 확인하기 위한 회사 사본.
#
#   pwsh tools/dev/fake-company.ps1 -Reset          # 사본을 새로 만든다 (제품 저장소는 git clone)
#   pwsh tools/dev/fake-company.ps1                 # 코드·화면·설정만 사본에 다시 복사한다 (데이터는 유지)
#   pwsh tools/dev/fake-company.ps1 -Serve -Port 8793   # 복사한 뒤 사본에서 serve --fake 실행 (Ctrl+C로 종료)
#
# 왜 사본인가: --fake로 결재하면 가짜 변경이 제품 저장소 main에 병합된다. 진짜 회사 폴더에서는 쓰지 않는다.
# 사본 위치: %TEMP%\ais-fake (짧은 경로 — Windows 경로 260자 제한 때문)
# -Name ais-fake2: 다른 창에서 이미 사본 회사가 돌고 있을 때 따로 쓰는 두 번째 사본
param([switch]$Reset, [switch]$Serve, [int]$Port = 8793, [string]$Name = 'ais-fake')
$ErrorActionPreference = 'Stop'
$src = (Resolve-Path "$PSScriptRoot\..\..").Path
$dst = Join-Path $env:TEMP $Name

if ($Reset -and (Test-Path $dst)) { Remove-Item -LiteralPath $dst -Recurse -Force }
if (-not (Test-Path $dst)) {
  New-Item -ItemType Directory -Force $dst | Out-Null
  foreach ($d in 'company', 'trusted') { Copy-Item (Join-Path $src $d) (Join-Path $dst $d) -Recurse }
  New-Item -ItemType Directory -Force (Join-Path $dst 'projects') | Out-Null
  foreach ($p in Get-ChildItem (Join-Path $src 'projects') -Directory) {
    git clone -q --no-hardlinks $p.FullName (Join-Path $dst "projects\$($p.Name)")
  }
  "사본을 만들었습니다: $dst"
}
# assets-raw: 의상·캐릭터 제조실이 원본 그림을 참고로 쓴다
foreach ($d in 'studio', 'ui', 'tools\sprites', 'assets-raw') {
  robocopy (Join-Path $src $d) (Join-Path $dst $d) /MIR /NFL /NDL /NJH /NJS /NP /XD __pycache__ .godot | Out-Null
}
Copy-Item (Join-Path $src 'studio.toml'), (Join-Path $src 'studio.py') $dst -Force
"코드·화면·설정을 복사했습니다."

if ($Serve) {
  Set-Location $dst
  python studio.py --root $dst --data (Join-Path $dst 'data') serve --fake --no-browser --port $Port
}
