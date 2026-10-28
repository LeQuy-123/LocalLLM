# Applies the companion changes (chibi character, chat box, Kokoro TTS, hotkey, reaction fixes)
# to a ViviPet checkout, configures its TTS for Kokoro, and builds it.
# Usage: powershell -ExecutionPolicy Bypass -File apply_patch.ps1 [-ViviPet D:\AI\External\ViviPet]
param([string]$ViviPet = 'D:\AI\External\ViviPet')

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$base = 'ffa2b9ffcb9e1b1dd0bebdd5db6d7c1dd0539d93'   # ViviPet commit the patch was made against

if (-not (Test-Path "$ViviPet\.git")) {
    git clone https://github.com/suntianc/ViviPet.git $ViviPet
}
Push-Location $ViviPet
try {
    if ((git rev-parse HEAD) -ne $base) { Write-Warning "ViviPet is not at $base; the patch may need manual merging." }
    git apply --check "$here\vivipet-companion.patch"
    if ($LASTEXITCODE -ne 0) { throw 'Patch does not apply (already applied, or ViviPet changed).' }
    git apply "$here\vivipet-companion.patch"
    Write-Host 'Patch applied.'

    # Capri's sprite sheets (third-party art, noncommercial license) are downloaded, not stored in this repo
    & (Join-Path $here '..\capri\fetch_capri_assets.ps1') -ViviPet $ViviPet

    Push-Location 'apps\desktop'
    npm install
    node node_modules\electron\install.js   # pnpm/npm sometimes skip Electron's binary download
    npm run build
    Pop-Location
} finally { Pop-Location }

# ViviPet reads its TTS settings from %APPDATA%\vivi-pet\tts-config.json
$cfgDir = Join-Path $env:APPDATA 'vivi-pet'
New-Item -ItemType Directory -Force $cfgDir | Out-Null
Copy-Item "$here\tts-config.json" (Join-Path $cfgDir 'tts-config.json') -Force
Write-Host "Kokoro TTS config written to $cfgDir\tts-config.json"
