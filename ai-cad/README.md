# AI CAD 建模平台

自然语言 → CAD IR JSON → 确定性 build123d 代码生成 → 工业级 STEP 文件

> **运行形态**：本项目与 DeepSeek Harness（DSH）组合运行。DSH 是主要的 AI 意图解析层；
> 同时后端保留 Ollama 接口，使管线可脱离 DSH 独立运行。
>
> **改模路线（按模型形态选，详见 `docs/FUSION_MCP.md` 的"改模路线选择"）**：
> - **改 STEP 文件**（Fusion 无需开启）：`scripts/inspect_step.py` 体检 → IR `import_step` 特征叠加修改。解析级精度，但只能"叠加"（补钻/填补/加凸台），**改不了原设计特征**。
> - **改 Fusion 里的活模型**：官方 FusionMCPSample（见 `docs/FUSION_MCP.md`）。**唯一能改"原特征"的路线**——已有孔径、草图尺寸、参数表、时间线。前提：模型有原生特征树；导入的网格（基础网格特征）没有特征树，MCP 只能读不能改。
> - **网格手术**（STL/导入网格的兜底）：导出网格后用 trimesh/manifold3d 布尔修改，精度 0.01~0.3mm，3D 打印够用，CNC 不建议。
> 注意单位坑：Fusion 内部几何为 cm、STL 无单位（Fusion 导入默认按 cm 解析），改模前先核对已知尺寸。

## 核心架构原则（不可违背）

1. **大模型只做意图解析，不直接生成几何代码**
   - LLM 输出必须是符合 `schemas/cad_ir.schema.json` 的 CAD IR JSON
   - 原因：LLM 在空间推理和坐标计算上不可靠，直接生成代码会导致破面、错位、布尔运算失败
   - 主要的 LLM 是 DSH 本身；Ollama 接口是并存的可选路径

2. **确定性代码生成器负责 JSON → build123d Python 脚本**
   - 生成器不依赖 LLM，使用预定义模板和几何计算逻辑
   - 每个 JSON 字段精确映射到 build123d API 调用
   - 处理：草图平面、拉伸方向、孔位坐标、布尔运算顺序、倒角/圆角参数

3. **Python 脚本必须在沙箱中执行**
   - 限制 import（只允许 build123d、math 等安全模块）
   - 阻止危险内置函数（eval、exec、open、`__import__` 等）
   - AST 静态验证 + 执行超时
   - 失败时捕获 traceback，可选择性回传 LLM 修正

4. **前端渲染与几何内核解耦**
   - 后端执行脚本导出 STEP + 预览网格（STL/GLTF）
   - 前端 Three.js 渲染预览网格，不运行几何内核
   - 最终 STEP 导出始终在后端完成

## 目录结构

```
ai-cad/
├── README.md               # 本文件
├── docs/
│   ├── ARCHITECTURE.md     # 架构设计（管线图、关键决策）
│   ├── ROADMAP.md          # 开发路线图与进度
│   ├── IR_SPEC.md          # CAD IR 规范（坐标系、特征语义、反模式、局限、修改既有模型工作流）
│   ├── FUSION_MCP.md       # Fusion MCP 接入（安装位置、脚本约定、与 STEP 管线分工）
│   ├── DSH_WORKFLOW.md     # DSH 意图解析工作循环
│   ├── MODULES.md          # 模块参考（文件职责、协议、设计不变量）
│   ├── DEVELOPMENT.md      # 开发指南（环境、测试、新增特征清单）
│   └── TROUBLESHOOTING.md  # 已知问题与排障手册
├── schemas/
│   └── cad_ir.schema.json  # CAD IR JSON Schema v1.0（管线合同）
├── examples/               # IR 实例（回归基准）+ 第一阶段手写脚本
│   ├── box_with_hole.json  #   最小教学例
│   ├── phone_stand.json    #   DSH 端到端首例（L 形支架+M3+倒角）
│   ├── phone_stand_modified.json  #   修改既有模型首例（import_step + 打孔 + 加凸台）
│   ├── l_bracket.json      #   skill 触发实例（用户迭代产物）
│   └── phase1_box_with_hole.py  # 第一阶段手写验证脚本
├── generator/
│   └── ir_codegen.py       # 确定性代码生成器（JSON → build123d 脚本）
├── sandbox/
│   └── runner.py           # AST 静态验证 + 子进程隔离执行
├── scripts/
│   ├── validate_ir.py      # 双层校验 CLI（结构 + 语义）
│   ├── build_ir.py         # 全管线 CLI（校验→生成→执行→STEP）
│   ├── download_wheels.py  # pip 网络故障绕行（离线 wheel 下载）
│   ├── inspect_step.py     # STEP 体检：导入任意 STEP → 拓扑/尺寸摘要 JSON（孔/凸台识别）
│   └── probe_api.py        # build123d API 探针（写生成器前验证假设）
├── vendor/
│   └── FusionMCPSample/    # Autodesk 官方 Fusion MCP 参考实现源码副本
├── tests/
│   └── test_generator.py   # 23 个几何单测（体积解析解/确定性/沙箱安全）
├── .wheels/                # pip 离线安装缓存（保留）
└── output/                 # 生成物：STEP / STL / 临时脚本（可删）
```

## 快速开始

工作流改进与分阶段验收见 [修改计划](docs/WORKFLOW_IMPROVEMENT_PLAN.md)，已实现功能与调用方式见 [工作流使用说明](docs/WORKFLOW_USAGE.md)。Fusion 首版已支持标注预览确认与根组件平面圆孔切削，复杂装配/网格拟合仍待开发。

```bash
pip install build123d jsonschema pytest
python -m pytest tests -v -p no:cacheprovider     # 回归测试（Windows 记得设 PYTHONIOENCODING=utf-8）
python scripts/build_ir.py examples/l_bracket.json # 全管线出 STEP
python scripts/inspect_step.py output/<run_id>/l_bracket.step # 用本次清单中的实际路径替换
```

产出：`output/<run_id>/l_bracket.step` 与 `run.json`（每次独立目录；原生 B-Rep，可导入 SolidWorks / Fusion 360 编辑）。

默认只导出 STEP；需要 STL 时增加 `--stl`。默认要求一个制造实体，多实体需显式指定 `--expected-solids N`。导出前会检查几何有效性、有限正体积/包围盒与实体数量；安装孔位和装配干涉仍需按任务核对。`--mode draft` 可省略圆角/倒角先看样式，最终用 `--mode final` 完整生成。

```bash
python scripts/build_ir.py examples/l_bracket.json --stl
python -m pytest tests/test_delivery.py tests/test_generator.py -q
```

## 我该读哪份文档？

| 你想… | 读 |
|-------|-----|
| 用自然语言建个零件 | 直接在 DSH 会话说需求（skill `ai-cad` 自动触发）；流程见 `docs/DSH_WORKFLOW.md` |
| 修改/加工既有 STEP 模型 | `docs/IR_SPEC.md` 的"既有模型的理解 + 修改工作流"一节 |
| 让 AI 直接操作 Fusion 改活模型（**唯一能改原特征**：孔径/草图/参数表） | `docs/FUSION_MCP.md`（Fusion 需开启 + 模型须有特征树；含三路线对比与触发逻辑） |
| 理解管线怎么运转 | `docs/ARCHITECTURE.md` → `docs/MODULES.md` |
| 写/改 IR JSON | `docs/IR_SPEC.md`（含反模式六禁令） |
| 改代码、加特征类型 | `docs/DEVELOPMENT.md`（新增特征七步清单） |
| 踩到环境坑了 | `docs/TROUBLESHOOTING.md` |
| 查进度/待办 | `docs/ROADMAP.md` |

## 触发方式

skill 安装于 `C:\Users\Remilie\.agents\skills\ai-cad\`，DSH 会话中说
"建一个 XX 零件"之类的话即可触发；改 skill 内容直接编辑该目录的 SKILL.md。

## 参考项目

| 项目 | 参考价值 |
|------|---------|
| build123d-mcp | 如何为 AI Agent 封装 build123d 的 CAD 操作工具 |
| CadCore | Agentic 管线、自愈循环、沙箱执行设计 |
| AI-CAD-Creator | OCCT 栈的 CAD IR JSON Schema 设计 |
| text-to-cad | LLM + build123d + STEP 的集成工作流 |
| HiCAD | 架构思想（双阶段建模、Prompt 分层、沙箱执行），不参考 JSCAD 实现（见 ../HiCAD） |
