$ErrorActionPreference = "Stop"

$projectDir = "d:\副业\2026\AI论文自动化工程\scholarpilot"
$branch = "scholarpilot"

Set-Location $projectDir

git add -A

$changes = git status --short

if ([string]::IsNullOrWhiteSpace($changes)) {
    exit 0
}

$commitMsg = "auto sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
git commit -m $commitMsg

$pushed = $false
try {
    git push origin $branch 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $pushed = $true }
} catch {}

if (-not $pushed) {
    Start-Sleep -Seconds 10
    try {
        git push origin $branch 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $pushed = $true }
    } catch {}
}

if (-not $pushed) {
    Write-Error "Git push failed for commit: $commitMsg"
    exit 1
}
