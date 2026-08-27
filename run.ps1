# One command, from a cold PowerShell prompt to a finished Short.
#
#   .\run.ps1 "ATM은 어떻게 지폐를 셀까?"
#   .\run.ps1 --setup --project-root D:/shorts-projects
#   .\run.ps1 --doctor
#   .\run.ps1 --probe
#   .\run.ps1 --script-only "김치는 어떻게 발효될까?"
#   .\run.ps1 --resume third
#
# The PowerShell twin of run.sh. It exists because every "just run one command"
# in this repository was a bash command, and PowerShell is where the work is
# actually being done -- `/c/Users/...` is Git Bash syntax that PowerShell reads
# as C:\c\Users\..., and `./run.sh` does not run here at all.
#
# Both the bash spellings (--setup) and the PowerShell ones (-Setup) are
# accepted, because switching shells should not mean relearning the flags.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Write-Step($m) { Write-Host "-- $m" -ForegroundColor DarkGray }
function Write-Ok($m)   { Write-Host "ok $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "!! $m" -ForegroundColor Yellow }
function Write-Fail($m) { Write-Host "stop $m" -ForegroundColor Red; exit 1 }

# -- arguments --------------------------------------------------------------
# Parsed by hand rather than with a param() block so that --setup and -Setup
# both work.
$Mode = "run"
$Topic = ""
$Resume = ""
$SetupArgs = @()
$i = 0
while ($i -lt $args.Count) {
    $a = [string]$args[$i]
    switch -Regex ($a) {
        '^--?setup$'        { $Mode = "setup";  $i++ }
        '^--?doctor$'       { $Mode = "doctor"; $i++ }
        '^--?probe$'        { $Mode = "probe";  $i++ }
        '^--?script-?only$' { $Mode = "script"; $i++ }
        '^--?resume$'       { $Resume = [string]$args[$i + 1]; $i += 2 }
        '^--?project-?root$' { $SetupArgs += @("--project-root", [string]$args[$i + 1]); $i += 2 }
        '^--?font$'         { $SetupArgs += @("--font", [string]$args[$i + 1]); $i += 2 }
        '^--?force$'        { $SetupArgs += "--force"; $i++ }
        '^--?h(elp)?$'      { Get-Content $PSCommandPath -TotalCount 8 | ForEach-Object { $_ -replace '^# ?', '' }; exit 0 }
        default             { $Topic = $a; $i++ }
    }
}

# -- python -----------------------------------------------------------------
$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Step "creating the virtualenv (first run only, takes a minute)"
    $launcher = $null
    foreach ($candidate in @("py", "python3", "python")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) { $launcher = $candidate; break }
    }
    if (-not $launcher) {
        Write-Fail "no Python found. Install it with:  winget install Python.Python.3.12"
    }
    if ($launcher -eq "py") { & py -3.12 -m venv .venv } else { & $launcher -m venv .venv }
    if (-not (Test-Path $VenvPython)) { Write-Fail "could not create .venv" }
}

& $VenvPython -c "import shorts_factory" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Step "installing dependencies (first run only)"
    & $VenvPython -m pip install --quiet --upgrade pip
    & $VenvPython -m pip install --quiet -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { Write-Fail "dependency install failed; the output above says why" }
}
Write-Ok "python ready"

# -- the modes that stop before the pipeline --------------------------------
if ($Mode -eq "setup")  { & $VenvPython scripts\setup_local.py @SetupArgs; exit $LASTEXITCODE }
if ($Mode -eq "doctor") { & $VenvPython scripts\doctor.py;                 exit $LASTEXITCODE }
if ($Mode -eq "probe")  {
    Write-Step "one fal call, so a wrong field name costs a clip and not a run"
    & $VenvPython scripts\probe_fal.py
    exit $LASTEXITCODE
}

if (-not $Resume -and -not $Topic) {
    Write-Fail 'give me a topic:  .\run.ps1 "ATM은 어떻게 지폐를 셀까?"'
}

# -- environment ------------------------------------------------------------
# Checked before anything is billed: every one of these has failed a real run
# once -- a missing key, a stripped ffmpeg, a mock provider left switched on.
Write-Step "checking ffmpeg, keys and providers"
& $VenvPython scripts\doctor.py
if ($LASTEXITCODE -ne 0) { Write-Fail "the check above failed. Fix what it names, then run this again." }

# -- the run ----------------------------------------------------------------
if ($Resume) {
    Write-Step "resuming $Resume"
    & $VenvPython -m shorts_factory resume $Resume
} elseif ($Mode -eq "script") {
    Write-Step "writing the script only -- nothing here is billed beyond research and the writer"
    & $VenvPython -m shorts_factory create $Topic --until write
} else {
    Write-Step "full run -- you get one look at the script before anything expensive happens"
    & $VenvPython -m shorts_factory create $Topic
}
$Status = $LASTEXITCODE

Write-Host ""
if ($Status -eq 0) {
    Write-Ok "done. The output path is printed above."
} else {
    Write-Host "the run stopped. Nothing already paid for is lost -- to carry on:"
    Write-Host "    .\run.ps1 --resume <project>"
}
exit $Status
