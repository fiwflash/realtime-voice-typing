# Build the PyInstaller onedir application.
$ErrorActionPreference = "Stop"

$Root = Split-Path $PSScriptRoot -Parent
Push-Location $Root
try {
    Write-Host "Building RealtimeVoiceTyping with PyInstaller..."
    python -m PyInstaller --noconfirm --clean "packaging\realtime_voice_typing.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    $size = (Get-ChildItem "dist\RealtimeVoiceTyping" -Recurse -File | Measure-Object Length -Sum).Sum
    Write-Host ("Build ready: dist\RealtimeVoiceTyping ({0:N1} MB)" -f ($size / 1MB))
}
finally {
    Pop-Location
}
