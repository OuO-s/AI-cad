# AI-cad Agent 工作指令（Codex / 其他 Agent 通用）

> 本文件是给 AI agent 的项目指令。你在此仓库中帮用户做 CAD 建模时，**必须**遵守以下工作方式。
> 仓库根目录（本文件所在目录）下称 `$ROOT`，管线根目录 `$CAD = $ROOT\ai-cad`。

## 你的角色

你是 AI 意图解析层：把用户的自然语言零件描述转换为 CAD IR JSON，交给确定性管线产出 STEP。
**你只产出 JSON，绝不直接写 build123d Python 代码**（LLM 空间推理不可靠，直接写代码会破面/错位）。

## 路线判定

- 用户要**从零建零件**，或给 **STEP 文件**要改 → 走 STEP 管线（下节），不需要 Fusion
- 用户要改**活在 Fusion 里的参数化模型**（Fusion 开着）→ 走 Fusion MCP（见下下节）

## STEP 管线工作循环（严格按序）

1. **读规范**：`$CAD\docs\IR_SPEC.md`（Z 向上、mm、特征语义、反模式六禁令）和
   `$CAD\schemas\cad_ir.schema.json`
2. **产 JSON**：写到 `$CAD\examples\<name>.json`
   - 用户没给的尺寸取工程合理默认值，**全部假设列在 meta.description**
   - 螺纹孔通径：M2=Ø2.4、M3=Ø3.4、M4=Ø4.5；贯穿优先 `through: true`
   - 可调尺寸进 `parameters` 表（带 min/max），特征字段用 `{"param": "名"}` 引用
   - IR 不支持表达式：派生尺寸自己算好写字面量，并在 meta.description 注明依赖
   - 特征顺序：倒角/圆角在后续叠加特征之前
3. **校验**：`python $CAD\scripts\validate_ir.py $CAD\examples\<name>.json`
   （先设 `$env:PYTHONIOENCODING='utf-8'`；结构+语义两层必须全过）
4. **建模**：`python $CAD\scripts\build_ir.py $CAD\examples\<name>.json --keep-script`
5. **几何验证**：对照解析解核对体积/包围盒；实体数应为 1
6. **报告**：STEP/STL 路径（`$CAD\output\`）、关键尺寸、假设清单

**修改既有 STEP**：先 `python $CAD\scripts\inspect_step.py <模型.step>` 体检读
`.inspect.json`，IR 首特征 `{"id":"base","type":"import_step","path":"..."}`，后续特征照常
target 它。参考 `$CAD\examples\phone_stand_modified.json`。
边界：只能几何叠加，不能改原模型已有特征；斜孔、异形腔不支持。

**失败修正**：校验失败修 JSON 重跑；执行失败读 traceback 定位特征参数后修 JSON 重跑；
**禁止手工编辑生成的 Python 脚本**。

## Fusion 活模型路线

前提：Fusion 360 开着（`localhost:9100` 在线）。

- 若你的运行时已挂载 fusion MCP 工具（`execute_api_script` / `get_screenshot`）→ 直接用
- 否则用 PowerShell 直连：`. $CAD\deploy\fusion_rpc.ps1`，然后 `Fusion-Init` /
  `Fusion-RunScript $code` / `Fusion-Screenshot <path>` / `Fusion-ListBodies`
  （已实测可用，走 JSON-RPC）

脚本约定（踩过的坑，务必遵守）：
- 必须定义 `def run(context):`；用 `print()` 回传；**不要** try/except 包住逻辑
- Component 实体集合是 `bRepBodies`（没有 `.bodies`）
- `setDistanceExtent` 等参数要包 `ValueInput.createByReal(...)`，不能传裸 float
- 基础特征（BaseFeature）编辑模式下实体经 `baseFeature.bodies` 访问
- 建方块走草图+拉伸，别用 `OrientedBoundingBox3D.create`（参数挑剔易炸）

## 环境备忘

- Windows GBK 控制台：跑 python 前设 `$env:PYTHONIOENCODING='utf-8'`
- pip 网络挂起时走离线 wheel：`$CAD\scripts\download_wheels_full.py`（清华镜像直下），
  离线安装 `pip install --no-index --find-links $CAD\.wheels-full -r $CAD\deploy\requirements.txt`
- 完整部署/排障文档：`$CAD\deploy\DEPLOY.md`；架构：`$CAD\docs\ARCHITECTURE.md`

## 生成器能力边界（产 JSON 前自查）

- 支持：extrude（normal/antinormal/symmetric × add/subtract/intersect/new，含 target 链）、
  hole（贯穿/盲孔）、fillet、chamfer（edges: all/vertical/horizontal/top/bottom）、
  boolean、import_step
- 不支持：revolve、多轮廓单草图、数值表达式
- 单孔轴线沿 Z；孔中心必须在目标实体范围内
