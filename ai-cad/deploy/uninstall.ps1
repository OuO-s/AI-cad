#Requires -Version 5.1
<#
.SYNOPSIS
  ai-cad 卸载脚本（只清理散落在本机各处的安装项，不删 ai-cad 项目目录本身）
#>
[CmdletBinding()]
param(
    [switch]$KeepDsh   # 保留 DSH 的 mcp-fusion 补丁条目
)
$ErrorActionPreference = 'Stop'

# 1) Fusion 插件
$addin = Join-Path $env:APPDATA 'Autodesk\Autodesk Fusion 360\API\AddIns\Fusion MCP Addin'
if (Test-Path $addin) { Remove-Item -Recurse -Force $addin; Write-Host "已删除 Fusion 插件: $addin" }
else { Write-Host "Fusion 插件不存在，跳过" }

# 2) skill
$skill = Join-Path $env:USERPROFILE '.agents\skills\ai-cad'
if (Test-Path $skill) { Remove-Item -Recurse -Force $skill; Write-Host "已删除 skill: $skill" }
else { Write-Host "skill 不存在，跳过" }

# 3) DSH 补丁条目（去掉 mcp-fusion 块；手工确认更稳妥时用 -KeepDsh）
if (-not $KeepDsh) {
    $patch = Join-Path $env:USERPROFILE '.dsh\profiles\web\cordis.patch.yml'
    if (Test-Path $patch) {
        $lines = Get-Content $patch
        if ($lines -match 'id:\s*mcp-fusion') {
            # 删除从注释行到该条目块末尾（下一个顶格 '- ' 或文件尾）
            $out = New-Object System.Collections.Generic.List[string]
            $skip = $false
            for ($i = 0; $i -lt $lines.Count; $i++) {
                $l = $lines[$i]
                if ($l -match 'id:\s*mcp-fusion') { $skip = $true; continue }
                if ($skip) {
                    if ($l -match '^(- |#|---)' -or $l -match '^\S') { $skip = $false } else { continue }
                }
                # 吃掉紧邻上方的关联注释
                if (-not $skip -and $out.Count -gt 0 -and $l -match '^\s*#\s*Fusion MCP Addin' ) { $out.RemoveAt($out.Count - 1); continue }
                $out.Add($l)
            }
            Set-Content -Path $patch -Encoding UTF8 -Value ($out -join "`r`n")
            Write-Host "已从 DSH 补丁中移除 mcp-fusion 条目: $patch（建议手工复核）"
        } else { Write-Host "DSH 补丁中无 mcp-fusion 条目，跳过" }
    }
}
# 4) Python 包可选卸载：pip uninstall build123d cadquery-ocp-novtk jsonschema
Write-Host "Python 包未卸载；如需: pip uninstall build123d cadquery-ocp-novtk cadquery-ocp-proxy jsonschema"
