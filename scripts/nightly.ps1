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
$env:PYTHONUNBUFFERED = "1"
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
$log = Join-Path $logDir "$day.log"
$utf8 = New-Object Text.UTF8Encoding $false

function Write-Log([string]$text) {
    [IO.File]::AppendAllText($log, "$text`r`n", $utf8)
}

# A program's output and errors, appended to the log as bytes (cmd's redirection does not re-encode).
# Returns its exit code; throws on failure unless -NoThrow.
function Invoke-Logged([string]$what, [string]$exe, [string[]]$arguments, [switch]$NoThrow) {
    $quoted = ($arguments | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join " "
    Write-Log "> $what"
    cmd.exe /d /c "`"$exe`" $quoted >> `"$log`" 2>&1"
    $code = $LASTEXITCODE
    if ($code -ne 0 -and -not $NoThrow) { throw "$what failed (exit $code)" }
    return $code
}

function Invoke-Pipeline([string[]]$arguments) {
    $null = Invoke-Logged "pipeline $($arguments -join ' ')" $uv (@("run", "--quiet", "--python", "3.12", "python", "-m", "pipeline") + $arguments)
}

try {
    Write-Log "nightly: $(Get-Date -Format o), branch $Branch, push $($Push.IsPresent)"
    if (-not (Test-Path $Worktree)) {
        Invoke-Logged "git worktree add" $git @("-C", $Repo, "worktree", "add", "--detach", $Worktree) | Out-Null
    }
    Set-Location $Worktree
    Invoke-Logged "git fetch" $git @("fetch", "-q", "origin") | Out-Null
    Invoke-Logged "git checkout" $git @("checkout", "-q", "--detach", "--force", "origin/$Branch") | Out-Null
    $env:CAR_RESEARCH_DB = Join-Path $Worktree "data\car-research.sqlite"
    Invoke-Pipeline @("nightly")
    Invoke-Pipeline @("raw-status")

    if (-not $Push) {
        Write-Log "compared with main's snapshot (new = this build, old = main):"
        Invoke-Logged "compare" $uv @("run", "--quiet", "--python", "3.12", "python", "scripts/compare_snapshots.py", "web/public/data", "git:origin/main") | Out-Null
        Write-Log "nightly: done $(Get-Date -Format o)"
        return
    }

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        & $git add -- web/public/data docs/deal-comparison.md
        & $git diff --cached --quiet
        if ($LASTEXITCODE -eq 0) { Write-Log "nothing changed"; break }
        Invoke-Logged "git commit" $git @("-c", "user.name=car-research nightly", "-c", "user.email=nightly@car-research.local",
                                          "commit", "-q", "-m", "data: nightly build $day") | Out-Null
        if ((Invoke-Logged "git push" $git @("push", "-q", "origin", "HEAD:main") -NoThrow) -eq 0) { Write-Log "pushed"; break }
        if ($attempt -eq 3) { throw "main kept moving; tonight's snapshot was not pushed" }
        # main moved while we scraped: take it as it now is and build again from the raws (no new fetching).
        Write-Log "main moved; building again on it (attempt $attempt)"
        Invoke-Logged "git fetch" $git @("fetch", "-q", "origin") | Out-Null
        Invoke-Logged "git checkout" $git @("checkout", "-q", "--detach", "--force", "origin/main") | Out-Null
        Invoke-Pipeline @("build", "--deal-table", "docs/deal-comparison.md")
    }
    Write-Log "nightly: done $(Get-Date -Format o)"
}
catch {
    Write-Log "nightly: FAILED: $_"
    throw
}
