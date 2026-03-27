param(
  [Parameter(Mandatory=$true)]
  [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

$src = Join-Path $PSScriptRoot 'src'
if (-not (Test-Path $src)) {
  throw "Source dir not found: $src"
}

$targetSrc = Join-Path $TargetDir 'src'
if (-not (Test-Path $targetSrc)) {
  throw "Target src dir not found: $targetSrc (did you run npx @grafana/create-plugin?)"
}

Copy-Item -Recurse -Force $src\* $targetSrc
Write-Host "Copied plugin sources to $targetSrc"
