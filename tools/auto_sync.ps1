# ScholarPilot Daily Auto-Sync Script
# Silent: skip when no changes, only log on push failure
# Uses SSH protocol (remote set to git@github.com:...)

# Derive project dir from script location (avoids Chinese path encoding issues)
$ProjectDir = Split-Path -Parent $PSScriptRoot
$GitPath = "D:\Software\Git\cmd\git.exe"
$LogFile = Join-Path $ProjectDir ".scholar\sync.log"
$Remote = "origin"
$Branch = "scholarpilot"

# Ensure SSH can find keys in non-interactive (scheduled task) context
$env:HOME = $env:USERPROFILE

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] [$Level] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
}

# Ensure log directory exists
$LogDir = Split-Path $LogFile -Parent
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# 1. git add -A
& $GitPath -C $ProjectDir add -A 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Log "git add -A failed (exit=$LASTEXITCODE)" "ERROR"
    exit 1
}

# 2. Check for changes
$status = & $GitPath -C $ProjectDir status --short 2>&1
if ([string]::IsNullOrWhiteSpace($status)) {
    # No changes, silent exit
    exit 0
}

# 3. Commit changes
$commitMsg = "auto sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
& $GitPath -C $ProjectDir commit -m "$commitMsg" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Log "git commit failed (exit=$LASTEXITCODE)" "ERROR"
    exit 1
}

# 4. Push to remote
& $GitPath -C $ProjectDir push $Remote $Branch 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Log "Push OK: $commitMsg" "INFO"
    exit 0
}

# 5. Push failed, wait 10s and retry once
Start-Sleep -Seconds 10
& $GitPath -C $ProjectDir push $Remote $Branch 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Log "Push FAILED after retry (exit=$LASTEXITCODE): $commitMsg" "ERROR"
    exit 1
} else {
    Write-Log "Retry push OK: $commitMsg" "INFO"
}
