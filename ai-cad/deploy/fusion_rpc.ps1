#Requires -Version 5.1
<#
.SYNOPSIS
  Fusion MCP 直连工具：当 DSH 会话未挂载 mcp__fusion__* 工具时，
  直接对 Fusion 插件的 HTTP MCP 端点（localhost:9100）走 JSON-RPC。
  本文件的调用路线已在真实会话中验证（Fusion MCP Server 1.0.0，streamable-http）。
.USAGE
  . .\fusion_rpc.ps1          # dot-source 导入函数
  Fusion-Init                 # 握手（每次新会话一次即可；本服务器无 session id 要求）
  Fusion-RunScript $code      # 执行 API 脚本（Fusion 内 Python，约定见下）
  Fusion-Screenshot out.png   # 截图存盘
.CONVENTIONS
  脚本约定（与 docs/FUSION_MCP.md 一致）：
    - 必须定义 def run(context):
    - 用 print() 回传数据；禁止 messageBox；不要捕获异常（让 Fusion 回传错误位置）
    - Component 的实体集合是 bRepBodies（不是 bodies）
    - setDistanceExtent 等需要 ValueInput（不能传裸 float）
    - 基础特征（BaseFeature）编辑模式下实体经 baseFeature.bodies 访问
#>

$script:FusionMcpUrl = 'http://127.0.0.1:9100/'
$script:FusionHeaders = @{ Accept = 'application/json, text/event-stream' }

function Fusion-TestPort {
    <# 检查 Fusion MCP 是否在线（Fusion 没开时为离线属正常） #>
    return (Test-NetConnection 127.0.0.1 -Port 9100 -InformationLevel Quiet -WarningAction SilentlyContinue)
}

function Fusion-Init {
    <# initialize 握手；返回 serverInfo #>
    $init = @{ jsonrpc = '2.0'; id = 1; method = 'initialize'
               params = @{ protocolVersion = '2024-11-05'; capabilities = @{}
                           clientInfo = @{ name = 'dsh-fusion-rpc'; version = '1.0' } } }
    $body = $init | ConvertTo-Json -Depth 5
    $r = Invoke-WebRequest -Uri $script:FusionMcpUrl -Method Post -ContentType 'application/json' `
         -Headers $script:FusionHeaders -Body $body -UseBasicParsing
    ($r.Content | ConvertFrom-Json).result.serverInfo
}

function Fusion-Call {
    param([Parameter(Mandatory)][string]$Tool, [hashtable]$Arguments = @{})
    <# tools/call 原始调用；返回 result（isError=true 时抛出文本） #>
    $payload = @{ jsonrpc = '2.0'; id = 2; method = 'tools/call'
                  params = @{ name = $Tool; arguments = $Arguments } } | ConvertTo-Json -Depth 8
    $r = Invoke-WebRequest -Uri $script:FusionMcpUrl -Method Post -ContentType 'application/json' `
         -Headers $script:FusionHeaders -Body $payload -UseBasicParsing
    $j = $r.Content | ConvertFrom-Json
    if ($j.result.isError) { throw "Fusion 工具执行失败:`n$($j.result.content[0].text)" }
    return $j.result
}

function Fusion-RunScript {
    param([Parameter(Mandatory)][string]$Code)
    <# execute_api_script：执行 Fusion 内 Python 脚本，返回 stdout 文本 #>
    $res = Fusion-Call 'execute_api_script' @{ script = $Code }
    $text = ($res.content | Where-Object { $_.type -eq 'text' } | ForEach-Object { $_.text }) -join "`n"
    # 脚本抛异常时 Fusion 会把 traceback 混在 RuntimeError 里返回且 isError=false，
    # 这里探测并抛给调用者
    if ($text -match 'Traceback \(most recent call last\)') { throw "脚本执行异常:`n$text" }
    return $text
}

function Fusion-Screenshot {
    param([Parameter(Mandatory)][string]$Path)
    <# get_screenshot：截图并保存为 png #>
    $res = Fusion-Call 'get_screenshot' @{}
    $img = $res.content | Where-Object { $_.type -eq 'image' } | Select-Object -First 1
    if (-not $img) { throw '截图返回中无图像数据' }
    [IO.File]::WriteAllBytes($Path, [Convert]::FromBase64String($img.data))
    Write-Host "截图已保存: $Path"
}

# ---- 示例：列出当前文档全部实体（含子装配，世界坐标包围盒） ----
function Fusion-ListBodies {
    $code = @'
import adsk.core, adsk.fusion
def run(context):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    def walk(occ, path):
        comp = occ.component if occ else root
        for body in comp.bRepBodies:
            bb = body.boundingBox
            if occ is None:
                print('BODY|{}|X[{:.3f},{:.3f}]|Y[{:.3f},{:.3f}]|Z[{:.3f},{:.3f}]|vol={:.3f}'.format(
                    body.name, bb.minPoint.x, bb.maxPoint.x, bb.minPoint.y, bb.maxPoint.y, bb.minPoint.z, bb.maxPoint.z, body.volume))
            else:
                mat = occ.transform2
                pts = []
                for xi in (bb.minPoint.x, bb.maxPoint.x):
                    for yi in (bb.minPoint.y, bb.maxPoint.y):
                        for zi in (bb.minPoint.z, bb.maxPoint.z):
                            p = adsk.core.Point3D.create(xi, yi, zi)
                            p.transformBy(mat)
                            pts.append(p)
                xs=[p.x for p in pts]; ys=[p.y for p in pts]; zs=[p.z for p in pts]
                print('BODY|{}|X[{:.3f},{:.3f}]|Y[{:.3f},{:.3f}]|Z[{:.3f},{:.3f}]|vol={:.3f}'.format(
                    path + '/' + body.name, min(xs),max(xs),min(ys),max(ys),min(zs),max(zs), body.volume))
        for sub in comp.occurrences:
            walk(sub, path + '/' + sub.name)
    walk(None, '(root)')
'@
    return Fusion-RunScript $code
}
