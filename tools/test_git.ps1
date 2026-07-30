$GitPath = "D:\Software\Git\cmd\git.exe"
$ProjectDir = "d:\副业\2026\AI论文自动化工程\scholarpilot"
Write-Host "GitPath=$GitPath"
Write-Host "ProjectDir=$ProjectDir"
& $GitPath -C $ProjectDir status --short
Write-Host "ExitCode=$LASTEXITCODE"
