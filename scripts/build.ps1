# Cross-compile Digital Canvas for every supported target into dist\.
# Needs Go 1.26+ on PATH; no C compiler required.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

$version = $env:VERSION
if (-not $version) {
    $version = (git describe --tags --always --dirty 2>$null)
    if (-not $version) { $version = 'dev' }
}
New-Item -ItemType Directory -Force dist | Out-Null

$targets = @(
    @{ os = 'linux';   arch = 'arm64'; arm = '' },
    @{ os = 'linux';   arch = 'arm';   arm = '7' },
    @{ os = 'linux';   arch = 'arm';   arm = '6' },
    @{ os = 'linux';   arch = 'amd64'; arm = '' },
    @{ os = 'windows'; arch = 'amd64'; arm = '' }
)
foreach ($t in $targets) {
    $suffix = if ($t.arm) { "v$($t.arm)" } else { '' }
    $out = "dist/digitalcanvas-$($t.os)-$($t.arch)$suffix"
    if ($t.os -eq 'windows') { $out += '.exe' }
    $env:CGO_ENABLED = '0'; $env:GOOS = $t.os; $env:GOARCH = $t.arch; $env:GOARM = $t.arm
    go build -trimpath -ldflags "-s -w -X main.version=$version" -o $out ./cmd/digitalcanvas
    if ($LASTEXITCODE -ne 0) { throw "build failed for $out" }
    '{0,-42} {1:N1} MB' -f $out, ((Get-Item $out).Length / 1MB)
}
Remove-Item Env:GOOS, Env:GOARCH, Env:GOARM, Env:CGO_ENABLED -ErrorAction SilentlyContinue
