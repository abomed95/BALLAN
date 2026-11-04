# Installe find-skills, arena et harvey-sales pour Claude Code (Windows, niveau utilisateur).
# Usage : placer ce script a cote des .zip, puis : powershell -ExecutionPolicy Bypass -File installer-skills.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$dest = Join-Path $HOME ".claude\skills"; New-Item -ItemType Directory -Force $dest | Out-Null
Write-Host "1/3 find-skills"; npx -y skills add https://github.com/vercel-labs/skills --skill find-skills -g -y
foreach ($s in "arena","harvey-sales") {
  Write-Host "-> $s"; $p = Join-Path $dest $s; if (Test-Path $p) { Remove-Item -Recurse -Force $p }
  Expand-Archive -Force "$s.zip" $dest
}
Get-ChildItem $dest
