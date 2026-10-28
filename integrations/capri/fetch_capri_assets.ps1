# Downloads Capri's sprite sheets from capri-desktop (by Lachy, https://github.com/lachydotmcg/capri-desktop)
# into ViviPet's public/models/capri folder, together with the project's license.
#
# The art is NOT stored in this repo. It is licensed under PolyForm Noncommercial 1.0.0:
# personal / noncommercial use only, and the license + Required Notice must travel with any copy.
#
# Usage: powershell -ExecutionPolicy Bypass -File fetch_capri_assets.ps1 [-ViviPet D:\AI\External\ViviPet]
param([string]$ViviPet = 'D:\AI\External\ViviPet')

$ErrorActionPreference = 'Stop'
$commit = '3023fb45b3b40e7b379fbba609358753cea1d054'   # pinned capri-desktop revision
$base = "https://raw.githubusercontent.com/lachydotmcg/capri-desktop/$commit"
$dest = Join-Path $ViviPet 'apps\desktop\public\models\capri'
$sprites = 'idle', 'blink', 'grin', 'mouth', 'glitch', 'dangle', 'sleep', 'wake', 'dance', 'arrive'

New-Item -ItemType Directory -Force $dest | Out-Null
foreach ($name in $sprites) {
    Invoke-WebRequest -UseBasicParsing "$base/assets/sprites/$name.png" -OutFile (Join-Path $dest "$name.png")
    Write-Host "  $name.png"
}
Invoke-WebRequest -UseBasicParsing "$base/LICENSE.md" -OutFile (Join-Path $dest 'LICENSE.md')
@"
Capri sprite sheets from https://github.com/lachydotmcg/capri-desktop (commit $commit).
Required Notice: Copyright 2026 Lachy (https://github.com/lachydotmcg)
Licensed under the PolyForm Noncommercial License 1.0.0 (see LICENSE.md). Noncommercial use only.
"@ | Set-Content -Encoding utf8 (Join-Path $dest 'NOTICE.txt')

Write-Host "Capri assets installed to $dest. Rebuild ViviPet (npm run build in apps\desktop) to bundle them."
