#Requires -Version 5.1
<#
.SYNOPSIS
  在源机上打包 ai-cad 部署 zip（剔除生成物/缓存），拷到目标机解压后运行 deploy\install.ps1
#>
[CmdletBinding()]
param(
    [string]$OutZip = "$env:USERPROFILE\Desktop\ai-cad-deploy.zip"
)
$ErrorActionPreference = 'Stop'
$deployDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$cadRoot   = Split-Path -Parent $deployDir

$exclude = @('__pycache__', '.pytest_cache', 'output', 'pytest-cache-files-*')
$files = Get-ChildItem -Recurse -File $cadRoot -ErrorAction SilentlyContinue | Where-Object {
    $rel = $_.FullName.Substring($cadRoot.Length + 1)
    -not ($exclude | Where-Object { $rel -like "*$_*" })
}
Write-Host "打包 $($files.Count) 个文件 → $OutZip"
if (Test-Path $OutZip) { Remove-Item $OutZip }
$files | Compress-Archive -DestinationPath $OutZip
Write-Host "完成: $OutZip（$([math]::Round((Get-Item $OutZip).Length/1MB,1)) MB）"
Write-Host "目标机步骤: 解压任意目录 → 进入 deploy\ → .\install.ps1"
