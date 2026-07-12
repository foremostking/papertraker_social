# ScholarPilot Daily Auto-Push to GitHub
# Silent: skip when no changes, only log on push failure

$ProjectDir = Split-Path -Parent $PSScriptRoot
$Branch = "scholarpilot"
$LogFile = Join-Path $ProjectDir ".git\auto-push.log"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "$timestamp  $Message" | Out-File -FilePath $LogFile -Append -Encoding UTF8
}

try {
    Set-Location $ProjectDir
} catch {
    Write-Log "Cannot set location to $ProjectDir : $_"
    exit 1
}

# Stage all changes (.gitignore excludes .venv, .env, __pycache__, etc.)
# Use 2>$null to suppress git warnings (e.g. LF/CRLF) from stderr
git add -A 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Log "git add failed (exit code: $LASTEXITCODE)"
    exit 1
}

# Check for changes
$status = git status --short 2>$null
if ([string]::IsNullOrWhiteSpace($status)) {
    # No changes, exit silently
    exit 0
}

# Commit changes
$commitMsg = "auto sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
git commit -m $commitMsg 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Log "git commit failed (exit code: $LASTEXITCODE)"
    exit 1
}

# Push to remote
git push origin $Branch 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Log "Push OK: $commitMsg"
    exit 0
}

# First push failed, wait 10s and retry once
Write-Log "First push failed (exit code: $LASTEXITCODE), retrying in 10s..."
Start-Sleep -Seconds 10
git push origin $Branch 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Log "Retry push OK: $commitMsg"
    exit 0
}

# Retry also failed
Write-Log "Push FAILED after retry (exit code: $LASTEXITCODE): $commitMsg"
exit 1
