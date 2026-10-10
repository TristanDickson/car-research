<#
The laptop's nightly job. Task Scheduler runs it (scripts/install-nightly.ps1 registers it).

It runs in a worktree of its own, so it never touches a working tree anyone edits:
fetch, check out origin/<Branch>, then `python -m pipeline nightly` (new committed history
into the raw store, scrape every live source into it, build from scratch, write the
snapshot and the deal table).

  -Push     commit the snapshot and the deal table and push them to main, which deploys
            the site. Without it nothing is pushed: the snapshot is compared with main's
            and the comparison goes in the log. That is the side-by-side mode, while the
            GitHub nightly still runs.

The log of each run is <raw store>\logs\nightly\<date>.log.
Windows PowerShell 5.1 syntax, so it runs on any Windows without PowerShell 7.
#>
param(
    [string]$Branch = "main",
    [switch]$Push,
    [string]$Repo = (Join-Path $env:USERPROFILE "car-research"),
    [string]$Worktree = (Join-Path $env:USERPROFILE "car-research-nightly")
)
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
if (-not $env:CAR_RESEARCH_RAW) { $env:CAR_RESEARCH_RAW = [Environment]::GetEnvironmentVariable("CAR_RESEARCH_RAW", "User") }
if (-not $env:CAR_RESEARCH_RAW) { throw "CAR_RESEARCH_RAW is not set: it names the raw store folder" }
$git = (Get-Command git).Source
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
# pdftotext reads Hyundai's PDF guides; Git for Windows ships one.
$gitBin = "C:\Program Files\Git\mingw64\bin"
if ((Test-Path (Join-Path $gitBin "pdftotext.exe")) -and ($env:Path -notlike "*$gitBin*")) { $env:Path = "$env:Path;$gitBin" }

$day = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
$logDir = Join-Path $env:CAR_RESEARCH_RAW "logs\nightly"
New-Item -ItemType Directory -Force $logDir | Out-Null
Start-Transcript -Path (Join-Path $logDir "$day.log") -Append | Out-Null

function Invoke-Checked([string]$what, [scriptblock]$block) {
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

function Invoke-Pipeline([string[]]$arguments) {
    Invoke-Checked "pipeline $($arguments -join ' ')" { & $uv run --quiet --python 3.12 python -m pipeline @arguments }
}

try {
    Write-Output "nightly: $(Get-Date -Format o), branch $Branch, push $($Push.IsPresent)"
    if (-not (Test-Path $Worktree)) {
        Invoke-Checked "git worktree add" { & $git -C $Repo worktree add --detach $Worktree }
    }
    Set-Location $Worktree
    Invoke-Checked "git fetch" { & $git fetch -q origin }
    Invoke-Checked "git checkout" { & $git checkout -q --detach --force "origin/$Branch" }
    $env:CAR_RESEARCH_DB = Join-Path $Worktree "data\car-research.sqlite"
    Invoke-Pipeline @("nightly")
    Invoke-Pipeline @("raw-status")

    if (-not $Push) {
        Write-Output "compared with main's snapshot (new = this build, old = main):"
        Invoke-Checked "compare" { & $uv run --quiet --python 3.12 python scripts/compare_snapshots.py web/public/data git:origin/main }
        return
    }

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        & $git add -- web/public/data docs/deal-comparison.md
        & $git diff --cached --quiet
        if ($LASTEXITCODE -eq 0) { Write-Output "nothing changed"; break }
        Invoke-Checked "git commit" { & $git -c user.name="car-research nightly" -c user.email="nightly@car-research.local" commit -q -m "data: nightly build $day" }
        & $git push -q origin HEAD:main
        if ($LASTEXITCODE -eq 0) { Write-Output "pushed"; break }
        if ($attempt -eq 3) { throw "main kept moving; tonight's snapshot was not pushed" }
        # main moved while we scraped: take it as it now is and build again from the raws (no new fetching).
        Write-Output "main moved; building again on it (attempt $attempt)"
        Invoke-Checked "git fetch" { & $git fetch -q origin }
        Invoke-Checked "git checkout" { & $git checkout -q --detach --force origin/main }
        Invoke-Pipeline @("build", "--deal-table", "docs/deal-comparison.md")
    }
}
finally {
    Stop-Transcript | Out-Null
}
