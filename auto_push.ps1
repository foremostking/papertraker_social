$ErrorActionPreference = "SilentlyContinue"
$projectPath = "d:\副业\2026\AI论文自动化工程\scholarpilot"
$branch = "scholarpilot"

Set-Location $projectPath

git add -A 2>$null

$status = git status --short 2>$null
if ([string]::IsNullOrWhiteSpace($status)) {
    exit 0
}

$commitMsg = "auto sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
git commit -m $commitMsg 2>$null

$pushResult = git push origin $branch 2>&1
if ($LASTEXITCODE -ne 0) {
    Start-Sleep -Seconds 10
    $retryResult = git push origin $branch 2>&1
    if ($LASTEXITCODE -ne 0) {
        $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        Write-Output "[$timestamp] Push failed after retry."
        Write-Output $retryResult
        exit 1
    }
}
