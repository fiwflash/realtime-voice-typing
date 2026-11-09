# Build the single Windows installer with Inno Setup.
$ErrorActionPreference = "Stop"

$Root = Split-Path $PSScriptRoot -Parent
$IsccCandidates = @(
    "$env:LOCALAPPDATA\Programs\InnoSetup6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "ไม่พบ ISCC.exe — ติดตั้ง Inno Setup 6 หรือแก้ path ในสคริปต์นี้"
}

if (-not (Test-Path "$Root\dist\RealtimeVoiceTyping\RealtimeVoiceTyping.exe")) {
    throw "ยังไม่มี dist\RealtimeVoiceTyping — รัน packaging\build.ps1 ก่อน"
}

Push-Location $Root
try {
    Write-Host "Compiling installer with $Iscc"
    & $Iscc "packaging\installer.iss"
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }

    Get-ChildItem "release\RealtimeVoiceTyping-Setup-*.exe" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 |
        ForEach-Object { Write-Host ("Installer ready: {0} ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB)) }
}
finally {
    Pop-Location
}
