<#
Register the laptop's nightly job with Task Scheduler (task "car-research nightly").

  .\scripts\install-nightly.ps1 -Branch main -Push     the job after the switch-over: build and push to main
  .\scripts\install-nightly.ps1 -Branch <branch>       side by side: build, compare with main, push nothing

It creates the job's own worktree (%USERPROFILE%\car-research-nightly) if missing and runs
that worktree's scripts/nightly.ps1, which checks out origin/<Branch> before every run.
The job runs daily at -At (local time), wakes the laptop for it, catches up as soon as it
can after a missed start (the laptop was off or asleep), and stops after four hours. It
runs as you, only while you are logged on, so it needs no stored password.
Remove it with: Unregister-ScheduledTask -TaskName "car-research nightly"
#>
param(
    [string]$Branch = "main",
    [switch]$Push,
    [string]$At = "03:17"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$worktree = Join-Path $env:USERPROFILE "car-research-nightly"
git -C $repo fetch -q origin
if (-not (Test-Path $worktree)) {
    git -C $repo worktree add --detach $worktree "origin/$Branch"
    if ($LASTEXITCODE -ne 0) { throw "git worktree add failed" }
}
$script = Join-Path $worktree "scripts\nightly.ps1"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Branch $Branch"
if ($Push) { $arguments += " -Push" }
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $worktree
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$description = "car-research: scrape every live source into the raw store, build from scratch, " + $(if ($Push) { "push the snapshot to main." } else { "compare with main (pushes nothing)." })
Register-ScheduledTask -TaskName "car-research nightly" -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description $description -Force | Out-Null
Get-ScheduledTask -TaskName "car-research nightly" | Select-Object TaskName, State, @{n = "Runs"; e = { $arguments } }
