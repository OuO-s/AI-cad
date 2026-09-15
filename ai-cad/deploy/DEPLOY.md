# ai-cad 部署与使用文档

> 目标读者：要把这套"AI 参数化 CAD 环境"装到另一台电脑上的人。
> 装好后怎么用、坏了怎么查，也都在这份文档里。

---

## 1. 这套东西是什么

由两部分组成的一个 AI CAD 工作环境：

```
┌─────────────────────────────────────────────────────────────┐
│  DSH（DeepSeek Harness，AI 意图解析层）                       │
│    └─ skill "ai-cad"：把自然语言翻译成 CAD IR JSON            │
├──────────────────────┬──────────────────────────────────────┤
│  A. STEP 管线（离线） │  B. Fusion MCP（在线，需开 Fusion）    │
│  ai-cad/ 目录         │  Fusion MCP Addin 插件                │
│  IR JSON → 校验 →     │  Fusion 进程内 HTTP MCP server        │
│  build123d 代码生成 → │  监听 localhost:9100                  │
│  沙箱执行 → STEP/STL  │  可改"活模型"的特征树/草图/参数         │
└──────────────────────┴──────────────────────────────────────┘
```

- **A 路（STEP 管线）**：从零建零件、或对既有 STEP 文件做"体检+叠加特征"修改。
  不依赖 Fusion，产出可导入 SolidWorks/Fusion 的 STEP。
- **B 路（Fusion 活模型）**：模型开着、要改特征树里的参数/草图时用。
  这是 STEP 路线做不到的（STEP 已丢特征历史）。

## 2. 前置条件（目标机）

| 组件 | 要求 | 检查 |
|------|------|------|
| Windows | 10/11 x64 | — |
| Python | 3.10–3.12（64 位），`python` 在 PATH | `python --version` |
| Fusion 360 | 已登录可用（只有 B 路需要） | — |
| DSH | 已安装且可开 Web 会话（`pnpm`/node 环境随 DSH 自带） | 打开 DSH web |

网络受限环境：pip 装不上时用离线 wheel 方案（见 §5 排障 T1）。

## 3. 部署步骤

```powershell
# 源机上（一次）：
cd <本机>\ai-cad\deploy
.\pack.ps1                       # 出 ai-cad-deploy.zip 到桌面
# 拷贝 zip 到目标机任意目录，解压

# 目标机上：
cd <解压目录>\ai-cad\deploy
.\install.ps1                    # 全自动：Python 依赖 → Fusion 插件 → DSH 配置 → skill
```

`install.ps1` 做的四件事（均可单独跳过，见 `.\install.ps1 -?`）：

1. **Python 依赖**：`pip install -r requirements.txt`（build123d / jsonschema / pytest）
2. **Fusion 插件**：把 `vendor\FusionMCPSample\Fusion MCP Addin` 复制到
   `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\`（manifest 为 runOnStartup，
   重启 Fusion 后自动加载，9100 端口监听）
3. **DSH 配置**：向 `~\.dsh\profiles\web\cordis.patch.yml` 追加 `mcp-fusion` 补丁条目
   （幂等；配置热更新，Fusion 开着时会自动挂上 `mcp__fusion__*` 工具）
4. **skill**：`deploy\skill\SKILL.md`（含 `__CAD_ROOT__` 占位符）→ 写入实际路径后装到
   `~\.agents\skills\ai-cad\SKILL.md`

安装脚本末尾自带**自检**：跑一遍 `examples\box_with_hole.json` 全管线 + 探测 9100 端口。

卸载：`.\uninstall.ps1`（只清各处安装项，不动项目目录）。

## 4. 装好后怎么用

### 4.1 自然语言建零件（A 路，最常用）

打开 DSH 会话直接说人话，例如：

> "建一个 80×50×8 的底板，四角 M4 安装孔，孔位离边 8mm，边缘倒 2mm 圆角"

skill 会自动触发，流程：DSH 产 `examples\<name>.json` → `validate_ir.py` 校验 →
`build_ir.py` 建模 → 产出 `output\<name>.step / .stl`，并报告关键尺寸与假设清单。
改尺寸 = 改 JSON 里的 `parameters` 重跑，不碰代码。

### 4.2 修改既有 STEP（A 路）

> "在这个支架上中间加个 Ø20 的凸台，再钻个 M3 通孔"

`inspect_step.py` 体检 → IR 首特征 `import_step` → 叠加 hole/extrude/boolean →
`build_ir.py`。参考 `examples\phone_stand_modified.json`。

### 4.3 改 Fusion 里的活模型（B 路）

前提：Fusion 开着、模型已打开（9100 在线）。

- **首选**：DSH 会话里已挂载 `mcp__fusion__execute_api_script` / `mcp__fusion__get_screenshot`
  工具（由 cordis.patch.yml 的 mcp-fusion 条目挂载），DSH 会直接调用。
- **兜底**（工具未挂载/直接脚本操作）：

  ```powershell
  . .\fusion_rpc.ps1
  Fusion-Init                       # 握手，应返回 Fusion MCP Server 1.0.0
  Fusion-ListBodies                 # 列出全文档实体+世界坐标包围盒
  $code = @'
  import adsk.core, adsk.fusion
  def run(context):
      # ... 这里写 Fusion API 操作，print() 回传结果
  '@
  Fusion-RunScript $code
  Fusion-Screenshot D:\tmp\after.png
  ```

脚本约定（踩过的坑，务必遵守）：
- 必须定义 `def run(context):`；用 `print()` 回传；**不要** try/except 包住逻辑
  （异常要传回 Fusion 中止事务，防止半成品状态）
- Component 的实体集合是 `bRepBodies`（没有 `.bodies`）
- `setDistanceExtent` 等 API 参数要包 `ValueInput.createByReal(...)`，不能传裸 float
- 改基础特征（BaseFeature）里的实体：`baseFeature.startEdit()` 后经
  `baseFeature.bodies` 访问，改完 `finishEdit()`
- `OrientedBoundingBox3D.create` 对参数挑剔，建方块建议直接走草图+拉伸路线

实例：把文档中 `Copper_Chimney` 阶梯圆柱改为阶梯方柱（13/9/15/11 边长，高度分段
8/138/5/7），全程走 B 路，体积解析解核对一致。

## 5. 排障速查

| # | 症状 | 处置 |
|---|------|------|
| T1 | pip 装不上（无外网/代理） | 部署 zip 默认**已内置** `.wheels-full\`（59 个 wheel ≈112MB，含 build123d+OCP 全依赖，`pack.ps1 -NoWheels` 可剔除）；`install.ps1` 在线失败会自动切换离线安装。手动命令：`pip install --no-index --find-links <解压目录>\ai-cad\.wheels-full -r deploy\requirements.txt`。重新生成 wheel 包：`python scripts\download_wheels_full.py`（走清华镜像，绕开会挂起的 pip 网络栈） |
| T2 | 中文输出乱码 | 执行前 `$env:PYTHONIOENCODING='utf-8'`（GBK 控制台） |
| T3 | 9100 离线但 Fusion 开着 | Fusion 实用程序→ADD-INS 里手动加载 `%APPDATA%\...\AddIns\Fusion MCP Addin`；确认 `.manifest` 内 `runOnStartup` |
| T4 | DSH 没挂出 mcp__fusion__* 工具 | 属正常设计：Fusion 没开时静默重试。确认 `cordis.patch.yml` 里有 mcp-fusion 条目；等重连或重启 DSH；急需就用 §4.3 的 fusion_rpc.ps1 直连 |
| T5 | IR 校验失败 | 看 `validate_ir.py` 双层报错（结构=JSON Schema / 语义=坐标、半径、孔位），修 JSON 重跑；禁改生成脚本 |
| T6 | 建出多实体/体积 0 | 通常孔位切穿壁或尺寸矛盾，查 parameters 里 min/max |
| T7 | build123d 导入失败 | 版本需 ≥0.11；OCP 依赖随 build123d 装（cadquery-ocp-novtk） |
| T8 | Fusion 脚本半途失败 | 事务会回滚，重跑修正后的完整脚本即可；勿手动"续"半截状态 |

更多见 `docs\TROUBLESHOOTING.md` 与 `docs\FUSION_MCP.md`。

## 6. 目录里各文档的入口

| 想干什么 | 看 |
|---------|-----|
| 部署/卸载/打包 | 本文件 + `deploy\*.ps1` |
| 从零建模流程细节 | `docs\DSH_WORKFLOW.md`、`docs\IR_SPEC.md` |
| 改 STEP 的工作流 | `docs\IR_SPEC.md` "既有模型的理解+修改"一节 |
| Fusion MCP 细节 | `docs\FUSION_MCP.md` |
| 管线架构/开发 | `docs\ARCHITECTURE.md`、`docs\DEVELOPMENT.md` |
