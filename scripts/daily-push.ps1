$ErrorActionPreference = 'Continue'

$projectDir = 'd:\副业\2026\AI论文自动化工程\scholarpilot'
$branch = 'scholarpilot'

Set-Location $projectDir

git add -A 2>$null
$status = git status --short

if ([string]::IsNullOrWhiteSpace($status)) {
    exit 0
}

$commitMsg = "auto sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
git commit -m $commitMsg 2>$null

$pushed = $false
git push origin $branch 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    $pushed = $true
}

if (-not $pushed) {
    Start-Sleep -Seconds 10
    git push origin $branch 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $time = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        Write-Error "[$time] ScholarPilot push failed. git push exit code: $LASTEXITCODE"
        exit 1
    }
}