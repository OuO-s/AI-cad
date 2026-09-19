# AI-cad Agent 工作指令（Codex / 其他 Agent 通用）

> 本文件是给 AI agent 的项目指令。你在此仓库中帮用户做 CAD 建模时，**必须**遵守以下工作方式。
> 仓库根目录（本文件所在目录）下称 `$ROOT`，管线根目录 `$CAD = $ROOT\ai-cad`。

## 你的角色

你是 AI 意图解析层：把用户的自然语言零件描述转换为 CAD IR JSON，交给确定性管线产出 STEP。
**你只产出 JSON，绝不直接写 build123d Python 代码**（LLM 空间推理不可靠，直接写代码会破面/错位）。

## 路线判定

- 用户要**从零建零件**，或给 **STEP 文件**要改 → 走 STEP 管线（下节），不需要 Fusion
- 用户要改**活在 Fusion 里的参数化模型**（Fusion 开着）→ 走 Fusion MCP（见下下节）

## 需求、预览和交付约定

- 新项目先复用已知偏好，只询问缺少且影响结果的信息：本轮是位置预览、样式草稿还是最终交付；参考对象；不可改变的尺寸/结构。
- 默认中文、简洁沟通、按需读取模型。默认仅交付 STEP；用户明确要求时才增加 STL/F3D/截图等文件。
- 安装位置、修改对象或关键尺寸不明确时，Fusion 路线先创建独立的待确认草图/临时图形，标注编号、拟定位置和待定尺寸；用户确认前不得对正式实体切孔、融合或移动。
- 已有明确草图、尺寸和修改授权时直接执行，不重复确认。用户修改预览后重新读取相关几何；参考对象或相关尺寸变化会使受影响的旧确认失效。
- 区分“定位标记”（圈选对象）和“加工轮廓”（实际制造尺寸），不能把圈选圆的直径自动当作孔径。
- 不按实体集合序号确定目标身份。结合文档、组件实例路径、选择对象、实体引用与几何校核；引用失效时重新绑定，不静默选用相似对象。
- 加厚需明确固定外形/内部空间/接合面及增厚方向。涉及其他尺寸的联动必须提前说明；不得声称它们不变。
- 快速模式可延后完整干涉、细节圆角等检查，但保留目标、单位、坐标和操作范围检查。没有执行的检查应明确标为未验证。
- 常规修改仅检查受影响区域；最终交付核对关键尺寸、安装接口、受影响的干涉及制造实体导出清单。单实体且有效不等于装配正确。
- 不添加未要求的安装脚、支架、底座等结构；缺失的关键安装信息通过标注确认，不以“合理默认值”代替用户决策。
- 优化项目基础设施时允许修改生成器、校验器和测试；仍禁止手工编辑生成的零件 Python 脚本。详细开发计划见 `ai-cad/docs/WORKFLOW_IMPROVEMENT_PLAN.md`。
- 已实现工具调用与能力边界见 `ai-cad/docs/WORKFLOW_USAGE.md`。Fusion 优先使用 `Fusion-Workflow` 读取/预览/确认，不绕过失效检查。`user_confirmed=true` 必须来自用户明确确认，不能由 agent 自行批准。
- 离线快速样式使用 `--mode draft`（省略倒角/圆角）；最终生成使用 `--mode final`。每次构建在独立 run_id 目录，交付引用本次 `run.json` 的 artifacts；未通过装配检查不得声称可装配。

## STEP 管线工作循环（严格按序）

1. **读规范**：`$CAD\docs\IR_SPEC.md`（Z 向上、mm、特征语义、反模式六禁令）和
   `$CAD\schemas\cad_ir.schema.json`
2. **产 JSON**：写到 `$CAD\examples\<name>.json`
   - 非关键尺寸可取合理默认值，**全部假设列在 meta.description**；安装位置、配合尺寸按上节确认
   - M2=Ø2.4、M3=Ø3.4、M4=Ø4.5 仅为可调整的螺钉间隙孔初值，不是螺纹底孔或所有工艺的标准值；贯穿优先 `through: true`
   - 可调尺寸进 `parameters` 表（带 min/max），特征字段用 `{"param": "名"}` 引用
   - IR 不支持表达式：派生尺寸自己算好写字面量，并在 meta.description 注明依赖
   - 特征顺序：倒角/圆角在后续叠加特征之前
3. **校验**：`python $CAD\scripts\validate_ir.py $CAD\examples\<name>.json`
   （先设 `$env:PYTHONIOENCODING='utf-8'`；结构+语义两层必须全过）
4. **建模**：`python $CAD\scripts\build_ir.py $CAD\examples\<name>.json --keep-script`
5. **几何验证**：导出前检查有效性、有限正体积和包围盒；默认实体数应为 1，多实体必须显式指定 `--expected-solids N`。按任务增加接口/干涉检查。
6. **报告**：默认 STEP 路径（`$CAD\output\`）、关键尺寸、假设清单；仅指定 `--stl` 时附加 STL

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
