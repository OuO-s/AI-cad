# Call Fusion MCP tools over plain JSON-RPC at http://localhost:9100/
# Usage: fusion_call.ps1 -ToolName execute_api_script -Arguments @{ script = (gc py.txt -raw) }
param(
    [Parameter(Mandatory=$true)][string]$ToolName,
    [Parameter(Mandatory=$true)][hashtable]$Arguments
)
$ErrorActionPreference = 'Stop'
$call = @{ jsonrpc='2.0'; id=1; method='tools/call'; params=@{ name=$ToolName; arguments=$Arguments } } | ConvertTo-Json -Depth 8
$r = Invoke-WebRequest -Uri 'http://localhost:9100/' -Method Post -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($call)) -UseBasicParsing
$obj = $r.Content | ConvertFrom-Json
if ($obj.error) { throw ($obj.error | ConvertTo-Json -Depth 8) }
if ($obj.result.isError) { throw (($obj.result.content | ConvertTo-Json -Depth 8)) }
$imgs = $obj.result.content | Where-Object { $_.type -eq 'image' }
if ($imgs) {
    $out = Join-Path $PSScriptRoot 'fusion_screenshot.png'
    [IO.File]::WriteAllBytes($out, [Convert]::FromBase64String(($imgs | Select-Object -First 1).data))
    Write-Output "saved: $out"
}
($obj.result.content | Where-Object { $_.type -eq 'text' } | ForEach-Object { $_.text }) -join "`n"
