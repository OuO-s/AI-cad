#Requires -Version 5.1
<#
.SYNOPSIS
  ai-cad 一键安装脚本（在新电脑上运行）
.DESCRIPTION
  在目标机上完成：
    1) Python 依赖（build123d / jsonschema / pytest，失败时提示离线 wheel 方案）
    2) Fusion MCP Addin 复制到 %APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\
    3) DSH 配置追加 mcp-fusion 补丁（幂等）
    4) ai-cad skill 安装到 %USERPROFILE%\.agents\skills\ai-cad\（自动写入本机 $CAD 路径）
  用法：在解包后的 ai-cad\deploy\ 目录里执行  .\install.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipPython,   # 跳过 pip 安装
    [switch]$SkipFusion,   # 跳过 Fusion 插件安装
    [switch]$SkipDsh,      # 跳过 DSH 配置
    [switch]$SkipSkill     # 跳过 skill 安装
)
$ErrorActionPreference = 'Stop'
$deployDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$cadRoot   = Split-Path -Parent $deployDir
Write-Host "== ai-cad 安装 | 管线根目录: $cadRoot ==" -ForegroundColor Cyan

# ---------- 1) Python 依赖 ----------
if (-not $SkipPython) {
    Write-Host "`n[1/4] Python 依赖..." -ForegroundColor Yellow
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { Write-Warning "未找到 python，请先安装 Python 3.10-3.12（64 位）后重试，或用 -SkipPython 跳过" }
    else {
        & python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
        if ($LASTEXITCODE -ne 0) { Write-Warning "Python 版本过低（需 >=3.10），跳过依赖安装" }
        else {
            & python -m pip install -r (Join-Path $deployDir 'requirements.txt')
            if ($LASTEXITCODE -ne 0) {
                $wf = Join-Path $cadRoot '.wheels-full'
                if (Test-Path (Join-Path $wf 'build123d-0.11.1-py3-none-any.whl')) {
                    Write-Host "  在线安装失败，改用离线 wheel 包($wf)..." -ForegroundColor Yellow
                    & python -m pip install --no-index --find-links $wf -r (Join-Path $deployDir 'requirements.txt')
                    if ($LASTEXITCODE -eq 0) { Write-Host "  Python 依赖 OK（离线）" -ForegroundColor Green }
                    else { Write-Warning "  离线安装也失败，检查 python/pip 环境" }
                } else {
                    Write-Warning "pip 在线安装失败且无离线 wheel 包(.wheels-full)。离线方案：`n  在有网机器上: python $cadRoot\scripts\download_wheels_full.py`n  把整个 .wheels-full 目录拷过来后:`n  pip install --no-index --find-links $cadRoot\.wheels-full -r $($deployDir)\requirements.txt"
                }
            } else { Write-Host "  Python 依赖 OK" -ForegroundColor Green }
        }
    }
} else { Write-Host "`n[1/4] 跳过 Python 依赖（-SkipPython）" -ForegroundColor DarkGray }

# ---------- 2) Fusion MCP Addin ----------
if (-not $SkipFusion) {
    Write-Host "`n[2/4] Fusion MCP Addin..." -ForegroundColor Yellow
    $src = Join-Path $cadRoot 'vendor\FusionMCPSample\Fusion MCP Addin'
    $dst = Join-Path $env:APPDATA 'Autodesk\Autodesk Fusion 360\API\AddIns\Fusion MCP Addin'
    if (-not (Test-Path $src)) { Write-Warning "源不存在: $src（vendor 副本缺失？）" }
    else {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
        if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
        # 排除 __pycache__
        Get-ChildItem -Recurse $src | Where-Object { $_.FullName -notmatch '__pycache__' } |
            ForEach-Object {
                $rel = $_.FullName.Substring($src.Length + 1)
                if ($_.PSIsContainer) { New-Item -ItemType Directory -Force -Path (Join-Path $dst $rel) | Out-Null }
                else {
                    $d = Join-Path $dst (Split-Path -Parent $rel); New-Item -ItemType Directory -Force -Path $d | Out-Null
                    Copy-Item $_.FullName (Join-Path $dst $rel) -Force
                }
            }
        Write-Host "  已安装到: $dst" -ForegroundColor Green
        Write-Host "  注意: 插件 manifest 为 runOnStartup，重启 Fusion 后自动加载并在 9100 端口监听"
    }
} else { Write-Host "`n[2/4] 跳过 Fusion 插件（-SkipFusion）" -ForegroundColor DarkGray }

# ---------- 3) DSH 配置 ----------
if (-not $SkipDsh) {
    Write-Host "`n[3/4] DSH 配置（cordis.patch.yml）..." -ForegroundColor Yellow
    $patch = Join-Path $env:USERPROFILE '.dsh\profiles\web\cordis.patch.yml'
    $entry = @'

# Fusion MCP Addin（AutodeskFusion360/FusionMCPSample）在 Fusion 内监听 localhost:9100
- id: mcp-fusion
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: fusion
    transport: streamable-http
    url: http://localhost:9100/
    toolCallTimeoutMs: 180000
    failOnStartupError: false
    reconnect:
      enabled: true
      initialDelayMs: 2000
      maxDelayMs: 30000
      maxAttempts: 50
'@
    if (Test-Path $patch) {
        if (Select-String -Path $patch -Pattern 'id:\s*mcp-fusion' -Quiet) {
            Write-Host "  已存在 mcp-fusion 条目，跳过" -ForegroundColor Green
        } else {
            Add-Content -Path $patch -Encoding UTF8 -Value $entry
            Write-Host "  已追加 mcp-fusion 条目（DSH 配置热更新，自动重连）" -ForegroundColor Green
        }
    } else {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $patch) | Out-Null
        Set-Content -Path $patch -Encoding UTF8 -Value $entry.TrimStart("`r`n")
        Write-Host "  已创建: $patch" -ForegroundColor Green
    }
} else { Write-Host "`n[3/4] 跳过 DSH 配置（-SkipDsh）" -ForegroundColor DarkGray }

# ---------- 4) skill ----------
if (-not $SkipSkill) {
    Write-Host "`n[4/4] ai-cad skill..." -ForegroundColor Yellow
    $skillDir = Join-Path $env:USERPROFILE '.agents\skills\ai-cad'
    New-Item -ItemType Directory -Force -Path $skillDir | Out-Null
    $tpl = Get-Content (Join-Path $deployDir 'skill\SKILL.md') -Raw
    $tpl = $tpl.Replace('__CAD_ROOT__', $cadRoot)
    Set-Content -Path (Join-Path $skillDir 'SKILL.md') -Encoding UTF8 -Value $tpl
    Write-Host "  已安装: $skillDir\SKILL.md（\$CAD = $cadRoot）" -ForegroundColor Green
} else { Write-Host "`n[4/4] 跳过 skill（-SkipSkill）" -ForegroundColor DarkGray }

# ---------- 自检 ----------
Write-Host "`n== 自检 ==" -ForegroundColor Cyan
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python -c "import build123d, jsonschema; print('  python deps: OK')"
    if ($LASTEXITCODE -ne 0) { Write-Warning "  python deps: 缺失（见上方离线方案）" }
}
$env:PYTHONIOENCODING = 'utf-8'
Push-Location $cadRoot
& python scripts\build_ir.py examples\box_with_hole.json --out "$env:TEMP\ai-cad-selfcheck" | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "  管线自检: OK（STEP 已生成到 %TEMP%\ai-cad-selfcheck）" -ForegroundColor Green }
else { Write-Warning "  管线自检失败，检查上方输出" }
Pop-Location
if ((Test-NetConnection 127.0.0.1 -Port 9100 -InformationLevel Quiet -WarningAction SilentlyContinue)) {
    Write-Host "  Fusion MCP 9100 端口: 在线（Fusion 已开且插件已加载）" -ForegroundColor Green
} else {
    Write-Host "  Fusion MCP 9100 端口: 离线（正常——Fusion 没开时不监听）" -ForegroundColor DarkGray
}
Write-Host "`n安装流程结束。详细使用说明见 deploy\DEPLOY.md" -ForegroundColor Cyan
