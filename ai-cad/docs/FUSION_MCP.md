# Fusion MCP 接入（AutodeskFusion360/FusionMCPSample）

## 架构

```
DSH (cordis.patch.yml: mcp-fusion 插件, streamable-http)
  → http://localhost:9100/   (Fusion MCP Addin 在 Fusion 进程内起的 HTTP MCP server)
    → execute_api_script / get_screenshot / get_api_documentation / get_best_practices
```

- Fusion 开启 → add-in（runOnStartup: true）自动加载，9100 就绪
- Fusion 关闭 → 什么都不运行；DSH 侧静默重试，无副作用

## 安装位置（本机实测，注意官方 README 的路径在这台机器上不对）

- 正确：`%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\Fusion MCP Addin\`
- 源码副本：`ai-cad\vendor\FusionMCPSample\`（git clone，更新时重新同步）

## DSH 配置

`C:\Users\Remilie\.dsh\profiles\web\cordis.patch.yml`：
serverName=fusion，streamable-http，toolCallTimeoutMs=180000，failOnStartupError=false。
工具以 `mcp__fusion__execute_api_script` 等名称挂到模型。配置热更新（HMR），
改 yml 触发断开重连。

## execute_api_script 脚本约定（重要）

- 必须定义 `def run(context):`，否则报 "Script does not have a run function"
- 用 `print()` 回传数据（出现在 result.content[0].text）
- 禁止 messageBox；不要捕获异常（让 Fusion 中止事务并回传错误位置）
- 修改文档前后各截一张图（get_screenshot）确认效果
- 查 API 用 get_api_documentation 或读 defs：
  `%APPDATA%\Autodesk\Autodesk Fusion 360\API\Python\defs\adsk`

## 验证记录（2026-09-15）

- initialize 握手 OK（serverInfo: Fusion MCP Server 1.0.0，tools 能力 true）
- execute_api_script OK：`{"doc_name": null, "design_active": false}`（当时无打开文档，符合预期）

## 与本地 STEP 管线的分工

- 改"STEP 文件"（不依赖 Fusion）：`scripts/inspect_step.py` + IR `import_step` 特征
- 改"活在 Fusion 里的参数化模型"（可编辑特征树/草图/参数）：走本 MCP，
  可改已有特征尺寸（这是 STEP 路线做不到的）
