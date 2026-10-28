# Starts the whole companion stack: Ollama (brain) -> Kokoro (voice) -> ViviPet (body) -> Companion (mind)
# Usage:  powershell -ExecutionPolicy Bypass -File D:\AI\Companion\start_companion.ps1 [-NoScreen] [-Console]
param([switch]$NoScreen, [switch]$Console)

$ErrorActionPreference = 'Continue'
$Kokoro  = 'D:\AI\External\Kokoro-FastAPI'
$ViviPet = 'D:\AI\External\ViviPet\apps\desktop'
$Root    = $PSScriptRoot

function Test-Url($url) {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $url | Out-Null; return $true } catch { return $false }
}
function Wait-Url($url, $name, $seconds) {
    for ($i = 0; $i -lt $seconds; $i++) { if (Test-Url $url) { Write-Host "  $name ready"; return } ; Start-Sleep 1 }
    Write-Warning "$name did not come up at $url"
}

Write-Host '[1/4] Ollama'
if (-not (Test-Url 'http://127.0.0.1:11434/api/tags')) {
    Start-Process 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
    Wait-Url 'http://127.0.0.1:11434/api/tags' 'Ollama' 30
} else { Write-Host '  already running' }

Write-Host '[2/4] Kokoro TTS'
if (-not (Test-Url 'http://127.0.0.1:8880/v1/audio/voices')) {
    # hidden, with output logged so crashes can be diagnosed
    Start-Process "$Root\run_kokoro_logged.bat" -WorkingDirectory $Kokoro -WindowStyle Hidden
    Wait-Url 'http://127.0.0.1:8880/v1/audio/voices' 'Kokoro' 180
} else { Write-Host '  already running' }

Write-Host '[3/4] ViviPet'
if (-not (Test-Url 'http://127.0.0.1:18765/health')) {
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue   # set by VS Code terminals; breaks Electron
    if (-not (Test-Path "$ViviPet\dist\main\main.js")) { Push-Location $ViviPet; npm run build; Pop-Location }
    Start-Process "$ViviPet\node_modules\.bin\electron.cmd" -ArgumentList '.' -WorkingDirectory $ViviPet -WindowStyle Hidden
    Wait-Url 'http://127.0.0.1:18765/health' 'ViviPet' 40
} else { Write-Host '  already running' }

Write-Host '[4/4] Companion brain'
$py = "$Root\.venv\Scripts\python.exe"
$extra = @(); if ($NoScreen) { $extra += '--no-screen' }
if ($Console) {
    & $py "$Root\main.py" @extra          # interactive: type to chat in this window
} else {
    Start-Process $py -ArgumentList (@("`"$Root\main.py`"", '--headless') + $extra) -WorkingDirectory $Root -WindowStyle Hidden
    Wait-Url 'http://127.0.0.1:18800/health' 'Companion' 30
    Write-Host "`nAll up. Double-click the pet or press Ctrl+Shift+Space to chat. Log: $Root\data\companion.log"
}
