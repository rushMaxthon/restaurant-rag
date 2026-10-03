<#
.SYNOPSIS
  Installs the QuickBite print agent so a kitchen ticket prints with nobody
  signed in and no browser open.

.DESCRIPTION
  Copies the agent to C:\Program Files\QuickBitePrint, pairs it with the
  server using a code from the admin panel, and registers a Scheduled Task so
  it starts by itself and keeps running.

  A Scheduled Task rather than a Windows Service, and that is a decision
  rather than a shortcut: a service must answer the Windows service-control
  protocol, which plain node.exe does not, so a service needs a wrapper
  executable shipped alongside it. A task started with -AtStartup runs at boot
  as SYSTEM with no user signed in, which is the whole requirement, and it
  needs nothing extra.

  -AtLogon exists for one reason. A task at startup runs in Session 0, which
  has no user profile and therefore CANNOT see per-user installed printers. If
  the printer is attached by USB and goes through the Windows spooler, the
  agent has to run as the signed-in user instead. A network printer on its own
  IP has no such problem, so -AtStartup is the default.

.EXAMPLE
  # Network printer on its own IP - the normal case
  .\install.ps1 -Server https://orders.example.com/api -Code 123456

.EXAMPLE
  # USB printer through the Windows spooler
  .\install.ps1 -Server https://orders.example.com/api -Code 123456 -AtLogon
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [Parameter(Mandatory = $true)][string]$Code,

    # Only for a deployment serving several restaurants on one address. In
    # production each has its own subdomain and the URL carries it.
    [string]$StorefrontHost,

    # See the note above about Session 0.
    [switch]$AtLogon,

    # Install for this user only, with no Administrator rights.
    #
    # Not a lesser option so much as a different one. It writes to
    # %LOCALAPPDATA% and registers the task under the current account, so a
    # restaurant where nobody has the admin password can still install it -
    # and because it necessarily runs in a user session, it is also the mode
    # a USB printer needs. The trade is that tickets print only while that
    # user is signed in.
    [switch]$PerUser,

    [string]$InstallDir,
    [string]$TaskName = "QuickBitePrintAgent"
)

$ErrorActionPreference = "Stop"

if (-not $InstallDir) {
    $InstallDir = if ($PerUser) { "$env:LOCALAPPDATA\QuickBitePrint" } else { "$env:ProgramFiles\QuickBitePrint" }
}
# A per-user install necessarily runs in a session, so it is always at logon.
if ($PerUser) { $AtLogon = $true }

function Fail($message) {
    Write-Host ""
    Write-Host "  $message" -ForegroundColor Red
    Write-Host ""
    exit 1
}

function Step($message) {
    Write-Host "  $message" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "  QuickBite print agent" -ForegroundColor White
Write-Host "  ---------------------"
Write-Host ""

# --- 1. Administrator -------------------------------------------------------
# Needed to write to Program Files and to register a task that runs as SYSTEM.
$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $PerUser -and -not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail @"
This needs an Administrator PowerShell window (right-click PowerShell > Run as
administrator), so the agent can start at boot with nobody signed in.

Or install it for this user only, which needs no Administrator rights:

    .\install.ps1 -Server $Server -Code <a fresh code> -PerUser

Tickets then print only while this user is signed in.
"@
}

# --- 2. What to install -----------------------------------------------------
#
# Two shapes, and the first needs nothing on the PC at all.
#
# `QuickBitePrintAgent.exe` is a Node single-executable: the whole runtime is
# inside it, so a restaurant copies one file and nothing else. That is what
# ships, and it is why there is no "install Node first" step for the person
# doing this in a kitchen at 4pm.
#
# `agent.cjs` beside a Node install is the developer shape, and the fallback
# if the .exe is missing from the folder.
$root = Split-Path -Parent $PSScriptRoot
$exe = @(
    (Join-Path $PSScriptRoot "QuickBitePrintAgent.exe"),
    (Join-Path $root "release\QuickBitePrintAgent.exe"),
    (Join-Path $root "build\QuickBitePrintAgent.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

if ($exe) {
    Copy-Item -LiteralPath $exe -Destination (Join-Path $InstallDir "QuickBitePrintAgent.exe") -Force
    $launcher = Join-Path $InstallDir "QuickBitePrintAgent.exe"
    $launchArgs = ""
    Step "Installed (self-contained) to $InstallDir"
} else {
    $bundle = Join-Path $root "dist\agent.cjs"
    if (-not (Test-Path $bundle)) {
        Fail @"
Nothing to install: neither QuickBitePrintAgent.exe nor dist\agent.cjs is in
this folder.

If you are building from source: npm install && npm run build && npm run package
"@
    }
    $node = (Get-Command node -ErrorAction SilentlyContinue).Source
    if (-not $node) {
        foreach ($candidate in @("$env:ProgramFiles\nodejs\node.exe", "${env:ProgramFiles(x86)}\nodejs\node.exe")) {
            if (Test-Path $candidate) { $node = $candidate; break }
        }
    }
    if (-not $node) {
        Fail @"
This folder has only the developer build (dist\agent.cjs), which needs Node.js.

Either use the packaged QuickBitePrintAgent.exe, or install Node LTS from
https://nodejs.org (the .msi, all defaults) and run this again.
"@
    }
    Copy-Item -LiteralPath $bundle -Destination (Join-Path $InstallDir "agent.cjs") -Force
    $launcher = $node
    $launchArgs = """$(Join-Path $InstallDir 'agent.cjs')"" "
    Step "Installed (needs Node at $node) to $InstallDir"
}

# --- 4. Pair ----------------------------------------------------------------
# Before the task is registered, so a wrong code fails here - where somebody
# is watching - rather than silently at the next boot.
$pairArgs = @()
if ($launchArgs) { $pairArgs += (Join-Path $InstallDir "agent.cjs") }
$pairArgs += @("pair", "--server", $Server, "--code", $Code)
if ($StorefrontHost) { $pairArgs += @("--storefront-host", $StorefrontHost) }

Step "Pairing with $Server ..."
& $launcher @pairArgs
if ($LASTEXITCODE -ne 0) {
    Fail "Pairing failed. Codes last ten minutes - generate a fresh one from the Printers page and try again."
}

# --- 5. The task ------------------------------------------------------------
# Deleted first so re-running the installer is an upgrade rather than an error.
#
# `Get-ScheduledTask` rather than `schtasks /Query`, and that is not a style
# choice. Under `$ErrorActionPreference = "Stop"` Windows PowerShell wraps a
# native command's stderr in an ErrorRecord, so `schtasks` reporting "cannot
# find the file specified" for a task that does not exist yet - which is the
# normal case on a first install - aborted the installer after it had already
# copied the files and paired. A cmdlet with -ErrorAction SilentlyContinue
# answers the question without that.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Step "Replacing the existing task"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute $launcher -Argument "$($launchArgs)run" -WorkingDirectory $InstallDir

if ($PerUser) {
    # The current account only, which is what makes this work without
    # elevation: registering a task for yourself needs no privilege.
    $me = $identity.Identity.Name
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
    $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive
    $where = "at logon for $me only"
} elseif ($AtLogon) {
    # As the signed-in user, so the Windows spooler's per-user printers are
    # visible. Someone has to be logged in for tickets to print.
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principal = New-ScheduledTaskPrincipal -GroupId "BUILTIN\Users" -RunLevel Highest
    $where = "at logon, as the signed-in user (needed for USB printers)"
} else {
    # As SYSTEM at boot: no login required, which is the point.
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $where = "at startup, with no login needed"
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

# -ExecutionTimeLimit 0 means "never kill it": the default is three days, and
# an agent silently terminated on day four is the kind of failure that gets
# blamed on the printer. -RestartCount with a one-minute interval is what
# brings it back if it ever does exit. -MultipleInstances IgnoreNew so a
# restart cannot leave two agents racing for the same queue.

# Registered, then VERIFIED, and the verification is not a formality.
#
# `Register-ScheduledTask` and `Start-ScheduledTask` raise CIM errors that do
# not terminate the script even under `$ErrorActionPreference = "Stop"`. So
# this printed "registered", "Started" and "Done" after both had failed with
# Access denied - meaning a restaurant would reboot, nothing would print, and
# the person who installed it would have no reason to suspect the install. An
# installer that cannot confirm what it did must say so.
try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings `
        -Description "Prints kitchen tickets for new orders." -ErrorAction Stop | Out-Null
} catch {
    Fail @"
The agent is installed and paired, but Windows would not register the
background task: $($_.Exception.Message)

Everything else is done, so finish it from an Administrator PowerShell window:

    cd $PSScriptRoot
    .\install.ps1 -Server $Server -Code <a fresh code>

Until then the agent can be run by hand, and will print normally:

    "$launcher" $($launchArgs)run --console
"@
}

if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    Fail "The task '$TaskName' did not register, and Windows reported no reason. Try an Administrator PowerShell window."
}
Step "Scheduled task '$TaskName' registered: $where"

try {
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
} catch {
    Fail "The task registered but would not start: $($_.Exception.Message)"
}

# Started is not the same as running. A task whose action is wrong goes
# straight back to Ready, and the only way to know is to look.
Start-Sleep -Seconds 2
$state = (Get-ScheduledTask -TaskName $TaskName).State
if ($state -eq "Running") {
    Step "Running"
} else {
    Write-Host "  The task is '$state' rather than Running." -ForegroundColor Yellow
    Write-Host "  Check $(Join-Path $env:ProgramData 'QuickBitePrint\agent.log') for why." -ForegroundColor Yellow
}

$dataDir = Join-Path $env:ProgramData "QuickBitePrint"
Write-Host ""
Write-Host "  Done." -ForegroundColor Green
Write-Host ""
Write-Host "  Log      $dataDir\agent.log"
Write-Host "  Config   $dataDir\config.json"
Write-Host ""
Write-Host "  Next: open the admin panel, press Test print, and watch the printer."
Write-Host "  If nothing comes out, the log file above says why."
Write-Host ""
