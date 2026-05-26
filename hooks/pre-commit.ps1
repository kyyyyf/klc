# klc pre-commit hook — PowerShell port.
#
# Install (klc cloned as subdir `klc-fw/` of the project):
#   Copy-Item klc-fw/hooks/pre-commit.ps1 .git/hooks/pre-commit.ps1
#   Copy-Item klc-fw/hooks/pre-commit.sample-cmd .git/hooks/pre-commit
#
# Install (klc elsewhere): set $env:KLC_FRAMEWORK_ROOT before commit.
#
# Runs consistency_check.py over every ticket that has staged files
# inside .klc/tickets/. Passes when no violations are reported.

$ErrorActionPreference = 'Stop'

$repoRoot = (git rev-parse --show-toplevel) 2>$null
if (-not $repoRoot) { $repoRoot = (Get-Location).Path }
$env:PROJECT_ROOT = $repoRoot

$fw = $env:KLC_FRAMEWORK_ROOT
if ($fw -and (Test-Path (Join-Path $fw 'scripts\klc'))) {
    # use it
} else {
    $fw = $null
    Get-ChildItem -Directory -Path $repoRoot | ForEach-Object {
        $cand = Join-Path $_.FullName 'scripts\klc'
        if (-not $fw -and (Test-Path $cand)) {
            $fw = $_.FullName
        }
    }
}

if (-not $fw) {
    Write-Error "pre-commit: klc repo not found; set KLC_FRAMEWORK_ROOT or clone klc as a subdirectory of the project"
    exit 0
}

$staged = (git diff --cached --name-only --diff-filter=ACM) |
          Where-Object { $_ -like '.klc/tickets/*' }
if (-not $staged) { exit 0 }

$tickets = $staged |
           ForEach-Object { ($_ -split '/')[2] } |
           Sort-Object -Unique

$failed = 0
foreach ($t in $tickets) {
    if ($t -eq 'archive') { continue }
    & python (Join-Path $fw 'core\skills\consistency_check.py') --ticket $t
    if ($LASTEXITCODE -ne 0) { $failed = 1 }
}

exit $failed
