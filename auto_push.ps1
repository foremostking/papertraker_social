$ErrorActionPreference = "SilentlyContinue"

Set-Location 'd:\副业\2026\AI论文自动化工程\scholarpilot'

git add -A
$status = git status --short

if (-not $status) {
    exit 0
}

git commit -m "auto sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"

$pushResult = git push origin scholarpilot 2>&1

if ($LASTEXITCODE -ne 0) {
    Start-Sleep -Seconds 10
    $pushResult = git push origin scholarpilot 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Git push failed: $pushResult"
        exit 1
    }
}

exit 0
