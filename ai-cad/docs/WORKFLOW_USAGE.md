# 预览确认与分层交付：使用说明

## 已实现范围

保留 build123d，不需要更换 CAD 后端。CLI 支持样式草稿、尺寸依赖、独立构建目录和结果清单。Fusion 提供当前选择/草图读取、圆形/矩形预览、编辑后确认，以及已确认圆孔切削。

Fusion 首版自动写入只支持根组件上的平面，切削只支持独立加工圆。矩形和圈选标记可预览但不能自动切削；组件实例可以读取，但写入会明确拒绝。复杂实例定位、曲面/STL拟合、壳体厚度原特征修改、完整装配干涉、制造白名单导出和后端性能对比仍待后续开发。不能把本版本称作全部路线图完成。

## 离线 STEP 管线

在 `ai-cad` 目录执行：

```powershell
python scripts/build_ir.py examples/l_bracket.json --mode draft
python scripts/build_ir.py examples/l_bracket.json --mode final
python scripts/build_ir.py examples/l_bracket.json --stl --expected-solids 1
```

每次运行建立 `output/<run_id>/`，保存 STEP、可选 STL、`run.json`，失败保留日志摘要及脚本。成功时默认清理生成脚本，`--keep-script` 可保留。清单只在文件生成且基础几何检查通过后列入 artifacts；每次独立目录避免误交付同名旧模型。

`draft` 只省略 fillet/chamfer 并重定向后续特征目标，不改变孔位。仍作基础有效性检查；它不等于“零检查”，也不自动去掉用户的安装结构。`final` 保留全部特征。两种模式都不自动验证装配，清单的 `checks.assembly` 明确为 `not_checked`。需要后续装配验收后才能宣称可制造。

CLI 输入的参数可使用 `expression` 替代 `value`：

```json
{
  "lid_bottom": {"value": 98},
  "lid_thickness": {"value": 6, "min": 1, "max": 10},
  "lid_top": {"expression": "lid_bottom + lid_thickness"}
}
```

只支持数字、参数名、括号和四则运算；循环、调用、属性访问被拒绝。CLI 在进入原 IR Schema 前将表达式解析成数值；直接调用生成器或 `validate_ir.py` 时仍须传已解析的原 IR。这是输入扩展层，不是新版 IR Schema。单位仍由调用者按 mm、角度等字段语义一致提供。

## Fusion：读取用户标注

```powershell
. .\deploy\fusion_rpc.ps1
Fusion-Workflow @{ action = 'read_selection' }
Fusion-Workflow @{ action = 'read_annotations' }
```

优先读取选中的草图，否则读取可见草图；也可用 `sketch_token` 指定草图。返回圆径、局部坐标、基准方向、尺寸表达式、构造/投影属性和组件实例上下文。默认单位 mm；实例变换矩阵平移分量使用 Fusion 原生 cm，字段名为 `transform_cm`。

普通圈选圆不能自动解释成扩孔要求。计划中的 `role=locator` 是定位标记，`role=machining` 才是加工轮廓。

## Fusion：预览、确认与切孔

1. 用户选择目标平面，调用 `read_selection` 获得 `face_token`。
2. 建立计划，通过 `preview_change` 显示标记。坐标使用创建在该面上的 Fusion 草图坐标；返回实际原点/轴方向，不能等同于屏幕左右。
3. 用户查看或编辑 `AI_待确认_<id>` 草图，并明确加工深度及方向。
4. 仅在用户明确确认后调用 `confirm_change`，再调用 `apply_confirmed_change`。

```powershell
$plan = @{
  version = 1; units = 'mm'; mode = 'preview'
  target = @{face_token = '<read_selection返回的平面token>'}
  invariants = @()
  operations = @(@{
    id='H1'; type='circle'; role='machining'; source='proposed'
    x=10; y=10; diameter=4.9
  })
}
Fusion-Workflow @{ action='preview_change'; plan=$plan }
# 以下操作要在用户确认草图与深度后执行；不得自动设置 user_confirmed。
Fusion-Workflow @{ action='confirm_change'; task_id='<返回的task_id>'; user_confirmed=$true; depth_mm=-4 }
Fusion-Workflow @{ action='apply_confirmed_change'; task_id='<返回的task_id>' }
Fusion-Workflow @{ action='status'; task_id='<返回的task_id>' }
```

`depth_mm` 是沿草图法向的有符号切削长度；示例 -4 仅示范调用，不是推荐孔深。确认时重新读取用户修改后的圆径与坐标。非投影额外曲线、嵌套/重叠轮廓、角色变化和待定项会被拒绝。

确认记录绑定计划和局部几何快照。执行前重新核对；已成功执行的同一任务再次执行只返回状态。任务存于当前文档根组件属性，不导出标记。实体几何快照用于变化检测，并不承诺覆盖所有保持相同摘要的拓扑变化；复杂重建后应重新预览。

`invariants` 目前用于记录和人工核对，不是通用约束求解器。首版切削明确限制 participantBodies 为目标实体，未实现任意自由文本约束自动验证。

RPC 同一主机协作进程使用互斥锁串行调用，单次请求默认超时180秒。超时后服务端可能仍在执行：先查询任务状态，不能直接重试写请求。此锁不能阻止用户在 Fusion 手动编辑或其他客户端绕过此封装。

## 测试

```powershell
python -m pytest tests -q
```

Fusion 实机验收需要拼接 `workflow/plan.py`、`workflow/fusion_adapter.py` 和 `scripts/fusion_workflow_smoke.py` 后交给 `Fusion-RunScript`。测试新建临时文档，完成后关闭且不保存并恢复原活动文档；覆盖预览、确认失效、按编辑后尺寸加工、幂等执行。不会在用户当前模型上试切。

## Fusion 半透明包络（第二批）

```powershell
Fusion-Workflow @{
  action='preview_envelopes'; units='mm'; frame='assembly_world'
  envelopes=@(@{id='A'; bounds_mm=@(@(4,27,2), @(114,137,72))})
}
Fusion-Workflow @{action='clear_envelopes'; task_id='<预览返回的task_id>'}
```

仅支持根装配坐标系轴对齐包围盒，以 30% 不透明度显示。坐标必须明确，不自动推测实例变换或安装面。包络是 Custom Graphics，不创建 BRep/打印实体，也不构成对位置的用户确认。清理只按本工具保存的任务标识删除图形，可重复调用，不删除其他草图/图形。API 和图形清理已在 Fusion 临时文档实测；尚无自动碰撞着色或文字标签。

## 已定位装配的校核与制造白名单（第二批）

`python scripts/deliver_assembly.py assembly.json --out output/assemblies`

输入 STEP 必须已经在同一装配坐标系中；每个文件恰好一个实体。工具不猜测原点、不按实体序号拆分文件、不自动移动模型。参考包络仍参与检查，但不得列入 `exports`。

```json
{
  "version": 1,
  "units": "mm",
  "frame": "assembly_world",
  "parts": [
    {"id": "lower", "role": "manufacturing", "path": "lower.step"},
    {"id": "lid", "role": "manufacturing", "path": "lid.step"},
    {"id": "module_a", "role": "reference", "path": "module_a.step"}
  ],
  "exports": ["lower", "lid"],
  "checks": [
    {"pair": ["lower", "lid"], "min_clearance_mm": 0},
    {"pair": ["lower", "module_a"], "min_clearance_mm": 0},
    {"pair": ["lid", "module_a"], "min_clearance_mm": 1}
  ]
}
```

示例的 1 mm 仅示范约束，不是通用推荐间隙。每对零件检查交集体积和最小距离；允许零间隙接触不等于允许实体重叠。可配置 `volume_tolerance_mm3`（默认 1e-6）、`distance_tolerance_mm`（默认 1e-6）。容差不是制造配合值。零件可加 `bounds_mm: [[xmin,ymin,zmin],[xmax,ymax,zmax]]`，按 `bounds_tolerance_mm`（默认 1e-5）检查固定外部尺寸/位置；这不是通用自由文本约束求解器。

导出不是只检查文件存在：每个制造 STEP 回读后核对有效单实体、体积和包围盒；失败不发布。回读校核保持原来的装配位置，不重新居中。

每次运行独立目录，`run.json` 记录输入 SHA256、实际检查值、未检查零件对 `unchecked_pairs`、制造制品白名单及文件 SHA256。只有 `artifacts` 中列出的文件才是交付件。`inputs_not_for_manufacturing/` 是原始输入快照，包含参考模块，仅用于追溯，严禁打包为制造文件。检查或导出失败时清单为空。没有声明零件对检查时仅报告几何通过；即使所有静态零件对通过，也不代表已校核装入路径、线缆、散热或强度。

## 对应点安装定位（第二批）

`python scripts/register_landmarks.py landmarks.json`

```json
{
  "units": "mm",
  "source_mm": [[0,0,0],[70,0,0],[0,70,0]],
  "target_mm": [[35,0,0],[105,0,0],[35,70,0]],
  "tolerance_mm": 0.05
}
```

源点、目标点须由用户明确对应，至少三个不共线点。返回 4×4 刚体变换，使用列向量约定 `target = transform @ source`，以及逐点误差、RMS、最大残差。超出容差返回 `rejected` 和非零退出码；禁止缩放或镜像。容差必须按实际精度要求指定。共面点可用，但无法识别用户把对称孔对应关系选反的意图错误，所以始终要求位置确认。

这是数值配准工具，不直接写入 Fusion、不自动识别 STL 孔、不恢复网格丢失的精确曲面；草图/选点读取和模型移动仍需通过明确的确认流程衔接。

## 数据与发布约定

交付代码分支保留原 `master`，不强推、不自动合并。不提交当前选择 token、临时模型、输出 STEP/F3D、草图快照或用户项目的未授权文件。使用记录输出保持在本地。
