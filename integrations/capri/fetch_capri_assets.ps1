# Capri's sprite sheets live in this project at assets\capri (the source of truth).
# This script (1) downloads them from capri-desktop if that folder is empty, or with -Force,
# and (2) syncs them into ViviPet's public\models\capri so the pet can load them.
# Edit or replace a sprite in assets\capri, re-run this, then rebuild ViviPet (npm run build:renderer).
#
# Art by Lachy (https://github.com/lachydotmcg/capri-desktop), PolyForm Noncommercial 1.0.0:
# personal / noncommercial use only; LICENSE.md and NOTICE.txt must stay with every copy.
#
# Usage: powershell -ExecutionPolicy Bypass -File fetch_capri_assets.ps1 [-ViviPet D:\AI\External\ViviPet] [-Force]
param([string]$ViviPet = 'D:\AI\External\ViviPet', [switch]$Force)

$ErrorActionPreference = 'Stop'
$commit = '3023fb45b3b40e7b379fbba609358753cea1d054'   # pinned capri-desktop revision
$base = "https://raw.githubusercontent.com/lachydotmcg/capri-desktop/$commit"
$assets = Resolve-Path (Join-Path $PSScriptRoot '..\..\assets') | Select-Object -ExpandProperty Path
$source = Join-Path $assets 'capri'
$sprites = 'idle', 'blink', 'grin', 'mouth', 'glitch', 'dangle', 'sleep', 'wake', 'dance', 'arrive'

New-Item -ItemType Directory -Force $source | Out-Null
if ($Force -or -not (Test-Path (Join-Path $source 'idle.png'))) {
    Write-Host "Downloading Capri sprites (capri-desktop $($commit.Substring(0, 7)))..."
    foreach ($name in $sprites) {
        Invoke-WebRequest -UseBasicParsing "$base/assets/sprites/$name.png" -OutFile (Join-Path $source "$name.png")
        Write-Host "  $name.png"
    }
    Invoke-WebRequest -UseBasicParsing "$base/LICENSE.md" -OutFile (Join-Path $source 'LICENSE.md')
    @"
Capri sprite sheets from https://github.com/lachydotmcg/capri-desktop (commit $commit).
Required Notice: Copyright 2026 Lachy (https://github.com/lachydotmcg)
Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE.md). Noncommercial use only.
"@ | Set-Content -Encoding utf8 (Join-Path $source 'NOTICE.txt')
} else {
    Write-Host "Using sprites already in $source"
}

$dest = Join-Path $ViviPet 'apps\desktop\public\models\capri'
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item (Join-Path $source '*') $dest -Force
Write-Host "Synced $source -> $dest. Rebuild ViviPet (npm run build:renderer in apps\desktop) to bundle them."
