$ErrorActionPreference = "Stop"

Write-Host "Installing SkillGod..." -ForegroundColor Cyan

$installDir = "$env:USERPROFILE\.skillgod\bin"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null

$sgRoot = Split-Path -Parent $PSScriptRoot
$binary = Join-Path $sgRoot "sg.exe"

if (-not (Test-Path $binary)) {
    Write-Host "Building binary..." -ForegroundColor Yellow
    Push-Location (Join-Path $sgRoot "cli")
    go build -o ..\sg.exe .
    Pop-Location
}

Copy-Item $binary (Join-Path $installDir "sg.exe") -Force
Write-Host "Installed to $installDir\sg.exe" -ForegroundColor Green

# Add to PATH if not already there
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$installDir*") {
    [Environment]::SetEnvironmentVariable(
        "PATH",
        "$userPath;$installDir",
        "User"
    )
    Write-Host "Added to PATH (restart terminal to use 'sg' globally)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Run: sg init" -ForegroundColor Cyan
Write-Host "Then restart your IDE." -ForegroundColor Cyan
