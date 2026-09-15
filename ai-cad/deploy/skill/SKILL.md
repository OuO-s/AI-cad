# AI CAD 建模（自然语言 → STEP）

你在 DeepSeek Harness 会话中充当 AI 意图解析层：把用户的自然语言零件描述转换为
CAD IR JSON，再驱动确定性管线产出 STEP。**你只产出 JSON，绝不直接写 build123d Python 代码。**

## 项目位置

- 管线根目录：`__CAD_ROOT__`（下称 `$CAD`）
- 每轮开始时先读：`$CAD\docs\IR_SPEC.md`（规范可能已更新）和 `$CAD\schemas\cad_ir.schema.json`

## 工作循环（严格按序执行）

1. **读规范**：IR_SPEC.md 的坐标系（Z 向上、mm）、特征语义、反模式六禁令、已知局限
2. **产 JSON**：写到 `$CAD\examples\<name>.json`
   - 用户没给的尺寸：取工程合理默认值，**全部假设列在 meta.description 里**
   - 螺纹孔：M2=Ø2.4、M3=Ø3.4、M4=Ø4.5（通径配合）；贯穿优先 `through: true`
   - 所有可调尺寸进 `parameters` 表（带 min/max），特征字段用 `{"param": "名"}` 引用
   - 派生尺寸（如 `base_depth/2 - t`）IR 不支持表达式：自己算好写字面量，并在
     meta.description 注明该字面量依赖哪些参数
   - 注意特征顺序：倒角/圆角要在后续叠加特征之前做，避免切到结合处
3. **校验**：`python $CAD\scripts\validate_ir.py $CAD\examples\<name>.json`
   （cwd 用 `$CAD`，加 `$env:PYTHONIOENCODING='utf-8'`）——结构+语义两层必须全过
4. **建模**：`python $CAD\scripts\build_ir.py $CAD\examples\<name>.json --keep-script`
5. **几何验证**：对照解析解核对体积/包围盒；实体数应为 1、valid=true；
   孔位不得切穿壁厚
6. **报告**：给出 STEP/STL 路径（`$CAD\output\<name>.step`）、关键尺寸、所做假设清单

## 修改既有模型（理解 + 叠加特征）

用户给 STEP 文件要改（打孔/加凸台/开槽等），走此循环，**不需要 Fusion**：

1. **体检**：`python $CAD\scripts\inspect_step.py <模型.step>` → 读
   `<模型>.inspect.json`：体积/包围盒/平面清单/圆柱面（自动分孔与凸台、轴向、
   轴点坐标、z 范围、M2–M6 螺纹底孔猜测）
2. **写修改 IR**：首个特征 `{"id": "base", "type": "import_step", "path": "<相对 IR JSON 目录的路径>"}`
   开启实体链，后续 hole/extrude/fillet/chamfer/boolean 照常 target 它
3. 校验/建模/验证同上；修改前后体积差可对照解析解核对；改完可再 inspect 复检
4. 参考实例：`$CAD\examples\phone_stand_modified.json`

边界：修改是"几何叠加"不是编辑特征树——原模型已有特征（如已打的孔径）不能直接改，
只能补钻/填补近似；斜孔、异形腔不支持。

## Fusion 活模型路线（按需）

用户要改"活在 Fusion 里的参数化模型"（改已有特征尺寸/草图/参数表）时走
FusionMCPSample（MCP，Fusion 需开启）：优先用已挂载的 `mcp__fusion__execute_api_script` /
`get_screenshot` 工具；**若本会话未挂载这些工具**，用 `$CAD\deploy\fusion_rpc.ps1`
直连 `http://localhost:9100/` 走 JSON-RPC（Initialize → tools/call）。
脚本约定与排障见 `$CAD\docs\FUSION_MCP.md`。
判定：给的是文件 → STEP 路线；模型开着且要动特征树 → Fusion 路线。

## 失败修正规则（重要）

- 校验失败 → 修 JSON 字段，重跑校验
- 执行失败 → 读 traceback，定位是哪个特征的哪个参数（坐标越界/半径大于边长/布尔为空），
  **修 JSON 重跑；禁止手工编辑生成的 Python 脚本**
- 几何异常（体积 0/多实体）→ 通常是孔位或尺寸矛盾，调参数重跑
- 用户要改模型 → 改 JSON 里的 `parameters` 或特征，重跑管线

## 生成器能力边界（产出 JSON 前必须自查）

- 支持：extrude（direction: normal/antinormal/symmetric × mode: add/subtract/intersect/new，
  含 target 链）、hole（贯穿/盲孔 Ø+center）、fillet、chamfer（edges: all/vertical/
  horizontal/top/bottom）、boolean（union/subtract/intersect）、
  **import_step**（导入既有 STEP 为根实体）
- 暂不支持：revolve、多轮廓单草图、数值表达式
- 单孔轴线沿 Z；孔中心必须在目标实体范围内

## 环境备忘

- Windows GBK 控制台：跑 python 前设 `$env:PYTHONIOENCODING='utf-8'`
- build123d 已装（0.11.1）；pip 网络若挂：用 `$CAD\scripts\download_wheels.py` 下 wheel
  到 `.wheels\` 后 `pip install --no-index --find-links .wheels <pkg>` 离线装
- 参考实例：`$CAD\examples\phone_stand.json`（L 形支架+M3 孔+倒角，完整参数化范例）、
  `$CAD\examples\phone_stand_modified.json`（import_step 修改既有模型范例）
