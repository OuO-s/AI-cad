# CAD IR 规范（v1.0）

本文档是 `schemas/cad_ir.schema.json` 的语义说明，也是 **DSH / LLM 产出 CAD IR JSON 时必须遵循的规范**。

## 坐标系与单位

- 右手直角坐标系，**Z 轴向上**，单位 **mm**（当前唯一支持单位）
- 基准面：`XY`（法向 +Z，顶视）、`XZ`（法向 -Y，前视）、`YZ`（法向 +X，右视）
- 草图局部坐标：`u` 对应基准面内第一轴、`v` 对应第二轴；`plane.offset` 沿法向平移，`plane.rotation` 在面内逆时针旋转（度）

## 执行模型

1. `features` 数组顺序即执行顺序（**拓扑序：被依赖者必须出现在前**）
2. 每个特征有唯一 `id`（snake_case），后续特征通过 `target` / `operands` / `depends_on` 引用
3. 实体产生型特征：`extrude`、`revolve`、`boolean`（它们的 id 代表"当前实体状态"）
4. 修改型特征：`hole`、`fillet`、`chamfer`（引用 target，产生新的实体状态，id 同样成为可引用名）
5. `sketch` 单独成特征仅用于复用；`extrude`/`revolve` 也可内联 `profile` + `plane_spec`

## 参数化

- `parameters` 表定义命名变量（含默认值、可选 min/max）
- 数值字段可用 `{"param": "名字"}` 引用变量；生成器在生成 Python 前先做参数替换
- 语义校验器负责检查：引用存在、min <= value <= max、正值约束（distance/diameter/radius/sides 的边长等解析后必须 > 0）

## 特征语义速查

| 类型 | 必填字段 | 语义 |
|------|---------|------|
| `sketch` | profile, plane_spec | 在基准面上定义轮廓（rectangle / circle / polygon） |
| `extrude` | profile, distance | 拉伸轮廓并与 target 做布尔（mode 默认 add；direction 默认 normal） |
| `revolve` | profile, axis | 轮廓绕轴旋转（angle 默认 360）并与 target 布尔 |
| `hole` | diameter, center | 从 center 沿方向去除圆柱；`through: true` 贯穿，`depth` 为盲孔深度，二选一 |
| `fillet` | radius, target | 在选定边加圆角（edges 默认 all） |
| `chamfer` | distance, target | 对称 45° 倒角（edges 默认 all） |
| `boolean` | operation, operands | operands[0] 与 operands[1] 的 union / subtract / intersect |
| `import_step` | path | 导入既有 STEP 文件作为根实体；path 相对 IR JSON 所在目录或绝对路径，后续特征可 target 它 |

## 既有模型的"理解 + 修改"工作流

1. **体检**：`python scripts/inspect_step.py <model.step>` → 产出 `<model>.inspect.json`
   （体积/包围盒/面统计/圆柱面清单，以及按共轴和连续区间聚类的候选孔；不猜测螺纹）
2. **DSH 读报告**，据此确定修改位置的坐标与尺寸
3. **写修改 IR**：首个特征用 `import_step` 导入原模型，后续叠加 hole/extrude/fillet/chamfer/boolean
4. 校验 + 建模流程同新建模型；体积变化可与解析解核对

## 边选择器（edgeSelector）

- `all` / `vertical`（竖直边）/ `horizontal`（水平边）/ `top`（顶面边）/ `bottom`（底面边）
- `{"indices": [...]}` 按生成器确定性边排序，**脆弱，尽量避免**；优先用枚举选择器

## 反模式（LLM 产出 JSON 时的禁令）

1. **禁止凭空猜测关键尺寸**：用户没给的尺寸用合理默认值并在 meta.description 里注明假设
2. **禁止自相矛盾**：孔中心必须落在实体范围内；布尔 subtract 的 operand 必须已存在
3. **禁止跳过依赖**：target/operands/depends_on 引用的 id 必须在前文出现且真实存在
4. **禁止无界值**：所有直径/半径/距离 > 0；revolve 角度 0 < angle <= 360；polygon 边数 3–64
5. **禁止在 IR 中写代码**：IR 里只能有 JSON 数据，任何 Python/表达式字符串都是非法的
6. **贯穿优先**：孔默认 `through: true`，除非用户明确要求盲孔深度

## 校验分层

| 层 | 负责者 | 检查内容 |
|----|--------|---------|
| 结构校验 | JSON Schema（`jsonschema` 库） | 字段存在性、类型、枚举、模式 |
| 语义校验 | `scripts/validate_ir.py` | id 唯一、依赖存在且有序、参数引用存在与范围、正值约束、hole depth/through 互斥 |
| 几何校验 | 第三阶段沙箱执行后 | 体积 > 0、单实体、is_valid、包围盒 |

## 已知局限（v1.0）

- **无数值表达式**：字段只能是字面量或 `{"param": ...}` 引用，不能写 `base_depth / 2 - t`。
  需要派生尺寸时，DSH 先在心中算好再写字面量，并在 meta.description 注明该值依赖哪些参数
  （改参数时需同步换算）。表达式支持列入 v1.1 候选。
- **revolve 未支持**：OCCT 要求旋转轴位于轮廓平面内，生成器尚未实现该约束（第三阶段备忘）
- **单轮廓单草图**：一个 extrude 只含一个 profile；复杂截面用多个 extrude + boolean 组合

## 示例

见 `examples/box_with_hole.json`：第一阶段带孔盒子的 IR 表达。
`examples/phone_stand.json`：DSH 端到端产出的 L 形手机支架（含 M3 通孔、倒角）。
`examples/phone_stand_modified.json`：**修改既有模型**范例——导入 phone_stand.step，
打中央 Ø8 通孔、底板加 Ø10×3 凸台（体积与解析解 39774.8 mm³ 吻合）。
