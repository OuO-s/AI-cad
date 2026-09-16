# AI-cad：AI 参数化 CAD 建模环境

自然语言 → CAD IR JSON → 确定性 build123d 代码生成 → 沙箱执行 → 工业级 STEP。
外加 Fusion 360 MCP 接入，可直接编辑 Fusion 里的活模型（特征树/草图/参数）。

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

核心设计原则：**大模型只做意图解析，不直接生成几何代码**——LLM 输出必须是符合
`schemas/cad_ir.schema.json` 的 IR JSON，几何由确定性生成器产出，保证可复现、可校验。

---

## 🤖 AI 部署协议（如果你是 AI，用户让你部署本仓库，按此执行）

> 目标：在一台新的 Windows 电脑上把本环境完整装好。
> 前提：用户已装好 git 和 DSH（DeepSeek Harness）；Fusion 360 可选。

按顺序执行，每步失败按【失败处置】处理，不要跳步：

### 第 1 步：环境检查

```powershell
python --version          # 需要 3.10–3.12（64 位）
git --version
```

- `python` 不存在或版本不符 → 停止，告知用户先安装 Python 3.10–3.12（64 位，勾选 Add to PATH）。

### 第 2 步：克隆仓库

```powershell
git clone https://github.com/OuO-s/AI-cad.git <目标目录>
cd <目标目录>\ai-cad\deploy
```

### 第 3 步：运行安装脚本

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force   # 仅当前进程放行脚本
.\install.ps1
```

`install.ps1` 自动完成四件事（幂等，可重复运行）：
1. **Python 依赖**：先在线 `pip install`，失败自动切换离线 wheel 包（仓库 zip 自带
   `.wheels-full\`，59 wheel / 112MB，含 build123d+OCP 全依赖——但 `git clone` 不含它，
   见下方【离线环境】）
2. **Fusion MCP 插件** → `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\`
3. **DSH 配置**：追加 `mcp-fusion` 条目到 `~\.dsh\profiles\web\cordis.patch.yml`
4. **skill**：安装到 `~\.agents\skills\ai-cad\`（自动写入本机实际路径）

脚本末尾自带自检（跑一遍示例全管线 + 探测 9100 端口）。

【离线环境】git clone 得到的仓库**没有** `.wheels-full\`（体积原因未入库）。目标机没外网时：
在任意有网机器上 clone 后执行 `python scripts\download_wheels_full.py` 生成，把整个
`.wheels-full\` 目录拷到目标机的 `ai-cad\` 下，再运行 `install.ps1`（会自动用离线包装）。

### 第 4 步：验证安装

```powershell
cd <目标目录>\ai-cad
$env:PYTHONIOENCODING='utf-8'
python scripts\build_ir.py examples\box_with_hole.json --out $env:TEMP\ai-cad-verify
# 成功标志：输出体积等校验信息，%TEMP%\ai-cad-verify 下生成 .step/.stl
python -m pytest tests -v -p no:cacheprovider    # 可选：23 个几何单测应全绿
```

Fusion 相关验证（装了 Fusion 才做）：启动 Fusion → 实用程序→ADD-INS 确认
"Fusion MCP Addin" 已加载 → `Test-NetConnection 127.0.0.1 -Port 9100` 应为 True。

### 第 5 步：向用户报告

报告内容：各步成败、Python 版本、自检结果、离线包是否用到、Fusion 是否就绪。

【失败处置速查】详见 `ai-cad\deploy\DEPLOY.md` §5（8 条排障表）。
最常见：pip 网络挂起（走离线 wheel 方案）；中文乱码（`$env:PYTHONIOENCODING='utf-8'`）；
9100 离线（Fusion 没开，属正常）。

---

## 人类使用指南

| 场景 | 怎么做 |
|------|--------|
| 自然语言建零件 | 在 DSH 会话说需求（"建一个 80×50×8 底板，四角 M4 孔…"），skill 自动触发，产出 `output\*.step` |
| 修改既有 STEP | DSH 里给文件路径说要改什么（inspect_step 体检 + 特征叠加） |
| 改 Fusion 活模型 | 开着 Fusion 对 DSH 说（走 mcp__fusion__* 工具，或 `deploy\fusion_rpc.ps1` 直连兜底） |
| 部署到新电脑 | 见上方 AI 部署协议，或自己跑 `deploy\pack.ps1` + `install.ps1` |

深入阅读（都在 `ai-cad\docs\`）：
`IR_SPEC.md`（IR 规范与反模式）· `ARCHITECTURE.md`（架构）· `FUSION_MCP.md`（Fusion 接入）·
`DEVELOPMENT.md`（开发指南）· `TROUBLESHOOTING.md`（排障）· `deploy\DEPLOY.md`（部署详解）

## 仓库结构

```
├── README.md            # 本文件（含 AI 部署协议）
├── .gitignore
└── ai-cad/
    ├── deploy/          # 部署包：install/pack/uninstall.ps1、DEPLOY.md、fusion_rpc.ps1
    ├── docs/            # 设计文档
    ├── examples/        # IR JSON 实例（回归基准）
    ├── schemas/         # CAD IR JSON Schema（管线合同）
    ├── generator/       # 确定性代码生成器（JSON → build123d 脚本）
    ├── sandbox/         # AST 静态验证 + 子进程隔离执行
    ├── scripts/         # CLI：validate_ir / build_ir / inspect_step / download_wheels_full
    ├── tests/           # 23 个几何单测
    ├── vendor/          # FusionMCPSample（官方 Fusion MCP 参考实现源码）
    └── output/          # 生成物（不入库）
```
