# ==============================================================================
# STROKE // WINDOWS NON-ADMINISTRATOR USER INSTALLER (POWERSHELL)
# ==============================================================================
# Strictly adheres to Stroke Zero Administrator Policy:
# - Installs directly to per-user directory: $env:LOCALAPPDATA\Programs\Stroke
# - Application data stored in: $env:LOCALAPPDATA\Stroke
# - Models stored in: $env:LOCALAPPDATA\Stroke\Models
# - Version backups stored in: $env:LOCALAPPDATA\Stroke\Backups
# - Execution level: asInvoker (NEVER prompts UAC or requires elevation)
# ==============================================================================

$ErrorActionPreference = "Stop"

# Detect if running elevated and advise the user
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    Write-Warning "Stroke is executing in an elevated Administrator session."
    Write-Warning "Stroke is designed to operate strictly with standard user privileges."
    Write-Warning "Administrator rights are NOT required and NOT recommended."
}

$localAppData = $env:LOCALAPPDATA
if (-not $localAppData) {
    $localAppData = [System.IO.Path]::Combine($env:USERPROFILE, "AppData", "Local")
}

$installDir = [System.IO.Path]::Combine($localAppData, "Programs", "Stroke")
$appDataDir = [System.IO.Path]::Combine($localAppData, "Stroke")
$modelsDir = [System.IO.Path]::Combine($appDataDir, "Models")
$backupsDir = [System.IO.Path]::Combine($appDataDir, "Backups")
$downloadsDir = [System.IO.Path]::Combine($appDataDir, "Downloads")

Write-Host "=================================================================" -ForegroundColor Green
Write-Host " STROKE // USER-LEVEL DESKTOP INSTALLATION (WINDOWS)" -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Green
Write-Host "Installation Directory: $installDir"
Write-Host "Application Data:       $appDataDir"
Write-Host "Models Directory:       $modelsDir"
Write-Host "Backups Directory:      $backupsDir"
Write-Host "Administrator / UAC:    NOT REQUIRED (Standard User Execution)"
Write-Host "=================================================================" -ForegroundColor Green

# Ensure target directories exist
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
New-Item -ItemType Directory -Force -Path $appDataDir | Out-Null
New-Item -ItemType Directory -Force -Path $modelsDir | Out-Null
New-Item -ItemType Directory -Force -Path $backupsDir | Out-Null
New-Item -ItemType Directory -Force -Path $downloadsDir | Out-Null

# Create non-elevated user startup batch wrapper
$cmdWrapper = [System.IO.Path]::Combine($installDir, "stroke.cmd")
@"
@echo off
set "STROKE_APP_DATA=%LOCALAPPDATA%\Stroke"
set "STROKE_MODELS_DIR=%LOCALAPPDATA%\Stroke\Models"
set "STROKE_BACKUPS_DIR=%LOCALAPPDATA%\Stroke\Backups"
if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" "%~dp0main.py" %*
) else (
    python "%~dp0main.py" %*
)
"@ | Set-Content -Path $cmdWrapper -Encoding UTF8

# Add to user PATH if not present (does NOT touch system PATH)
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$installDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$installDir", "User")
    Write-Host "[OK] Added $installDir to per-user PATH environment variable." -ForegroundColor Cyan
}

Write-Host "[OK] Windows user installation completed cleanly with zero UAC elevation." -ForegroundColor Green
