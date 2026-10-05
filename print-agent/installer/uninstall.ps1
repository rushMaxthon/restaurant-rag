<#
.SYNOPSIS
  Removes the QuickBite print agent.

.DESCRIPTION
  Stops and deletes the Scheduled Task and removes the program files.

  The configuration and log under C:\ProgramData\QuickBitePrint are KEPT by
  default, and that is deliberate: the log is the only record of why a ticket
  did not print, and uninstalling is often the first thing somebody tries when
  diagnosing. -Purge removes them too, which also forgets the pairing - the
  agent must then be paired again with a fresh code.
#>

[CmdletBinding()]
param(
    [string]$InstallDir = "$env:ProgramFiles\QuickBitePrint",
    [string]$TaskName = "QuickBitePrintAgent",
    [switch]$Purge
)

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "  Run this from an Administrator PowerShell window." -ForegroundColor Red
    exit 1
}

# Cmdlets rather than `schtasks`: under ErrorActionPreference = Stop, a native
# command writing to stderr becomes a terminating error, and "no such task" is
# the normal case here.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "  Removed the scheduled task '$TaskName'" -ForegroundColor Cyan
} else {
    Write-Host "  No scheduled task '$TaskName' was registered" -ForegroundColor DarkGray
}

if (Test-Path $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
    Write-Host "  Removed $InstallDir" -ForegroundColor Cyan
}

$dataDir = Join-Path $env:ProgramData "QuickBitePrint"
if ($Purge) {
    if (Test-Path $dataDir) {
        Remove-Item -LiteralPath $dataDir -Recurse -Force
        Write-Host "  Removed $dataDir (pairing forgotten)" -ForegroundColor Cyan
    }
} elseif (Test-Path $dataDir) {
    Write-Host "  Kept $dataDir - the log and the pairing. Use -Purge to remove them." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "  Done." -ForegroundColor Green
Write-Host ""
