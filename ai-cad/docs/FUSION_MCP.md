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

## 与本地 STEP 管线的分工（改模路线选择）

**核心结论：只有 Fusion MCP 路线能修改模型的"原特征"（已有孔径、草图尺寸、用户参数表、时间线）。
STEP 管线和网格手术都只能"几何叠加"（补钻、填补、加凸台），不能改原设计特征。**

三条路线对比：

| 路线 | 几何精度 | 能否改原特征 | 前置条件 | 典型用途 |
|------|---------|-------------|---------|---------|
| Fusion MCP（本文档） | 解析级（B-Rep） | **能**：改特征尺寸/草图/参数表，进时间线可回滚 | Fusion 开启 + addin 活着 + 模型是原生参数化 | 改"活"模型的原有特征尺寸 |
| STEP 管线（inspect_step + IR import_step） | 解析级（B-Rep） | 否，只能叠加 | 拿到 STEP 文件即可，可离线复现 | 给文件改实体：打孔/加凸台/开槽 |
| 网格手术（导出 STL + trimesh/manifold3d） | 0.01~0.3mm（采样近似） | 否 | 任意网格模型 | STL/导入网格特征的修改 |

触发逻辑（同时满足才走该路线）：

1. **MCP 路线**：模型正开在 Fusion 里 + 要动的是特征树（如"把 Ø3 孔改成 Ø4"）+ 模型有原生特征树。
   注意：导入的网格（基础网格特征）没有特征树，MCP 只能读不能改——此时落到路线 3。
   （本机实例：Go2_AC1 文档即网格模型，MCP 完成了读取/导出，修改走了网格手术。）
2. **STEP 路线**：用户给的是 STEP 文件（或明确要 B-Rep 级精度/CNC 级输出）。STEP 自带 mm 单位，
   无缩放歧义；圆柱面/孔位由 inspect_step 解析读出，修改体积可解析核对。
3. **网格路线**：模型只有 STL/网格形态。尺寸靠采样推断（射线+边界环），孔用多边形近似（48 边形），
   填充用体素灌浆（0.3mm 台阶，埋在孔内）——3D 打印够用，CNC 不建议。

已知坑（路线选择时的检查项）：

- **单位/缩放**：Fusion API 内部几何为 cm；STL 无单位，Fusion 导入默认按 cm 解析。实测出现过
  文档网格 10 倍放大、以及 STL 导入后 Fusion 显示 70cm（实为 70mm）的假象。改模前先核对
  已知尺寸（如"槽宽 4mm 配 M4"），必要时用"导入已知 mm 的 STEP 后比对包围盒"来标定。
- 网格路线的"孔深/沉槽"须用射线剖面探测，不能只看顶面边界环（会漏掉底部沉槽，实例见
  `scripts/modify_plate_mesh.py` 的体素灌浆方案）。
