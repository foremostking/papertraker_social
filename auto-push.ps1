$ErrorActionPreference = "SilentlyContinue"

$projectDir = 'd:\副业\2026\AI论文自动化工程\scholarpilot'
$branch = 'scholarpilot'
$remote = 'https://github.com/foremostking/papertraker_social.git'

Set-Location $projectDir

git add -A

$status = git status --short
if (-not $status) {
    exit 0
}

$commitMsg = "auto sync: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
git commit -m $commitMsg

git push origin $branch
if ($LASTEXITCODE -ne 0) {
    Start-Sleep -Seconds 10
    git push origin $branch
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Failed to push to $remote (branch: $branch) after retry."
        exit 1
    }
}
