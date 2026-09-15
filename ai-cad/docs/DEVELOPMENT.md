# 开发指南

环境搭建、测试、以及最重要的：**如何给管线新增一个特征类型**。

## 环境搭建

```bash
# 1. Python 3.12+（开发环境为 3.12.6）
python --version

# 2. 几何内核（正常网络）
pip install build123d
#    pip 挂了 → 见 docs/TROUBLESHOOTING.md「pip 网络故障」节

# 3. 校验与测试依赖
pip install jsonschema pytest
```

验证安装：

```powershell
$env:PYTHONIOENCODING='utf-8'
python examples\phase1_box_with_hole.py        # 应输出 ✅ 第一阶段最小闭环验证通过
python -m pytest tests -v -p no:cacheprovider  # 应 23 passed
```

**Windows 必读**：所有 python 命令前设 `$env:PYTHONIOENCODING='utf-8'`（GBK 控制台
打不出 ³/✅ 等字符，详见 TROUBLESHOOTING.md）。

## 运行测试

```powershell
cd D:\AI\project\Company\AImodeling\ai-cad
$env:PYTHONIOENCODING='utf-8'
python -m pytest tests\test_generator.py -v -p no:cacheprovider
```

- **必须加 `-p no:cacheprovider`**：沙箱下 pytest 缓存目录写不进去
- **测试不能用 pytest 的 tmp_path fixture**（同因）；用 `tests/` 里自带的 `output/tests/` 目录
- 每个用例都会真跑一次 build123d（子进程），全套约 95 秒；调试单特征用
  `python -m pytest tests\test_generator.py -k hole -v` 过滤

## 端到端冒烟

```powershell
python scripts\validate_ir.py examples\box_with_hole.json   # 双层校验
python scripts\build_ir.py examples\l_bracket.json          # 全管线 → STEP
```

STEP 验证要点：重新导入体积一致、单实体、文件含 `ADVANCED_BREP_SHAPE_REPRESENTATION`
与 `MANIFOLD_SOLID_BREP`（见 examples/phase1_box_with_hole.py 尾部断言）。

---

## 如何新增一个特征类型（以 revolve 为例的完整清单）

新增特征 = 动 6 个地方 + 1 个文档。按序：

### 1. 探针先行（写代码前验证 API 假设）

在 `scripts/probe_api.py` 加探针或在临时脚本里验证 build123d 0.11.1 的实际行为。
revolve 的教训：**OCCT 要求旋转轴必须位于轮廓平面内**，这直接决定 IR 字段设计
（要么约束 axis 与 plane_spec 的关系，要么生成器里自动构造合规平面）。

### 2. 扩 Schema（`schemas/cad_ir.schema.json`）

- `feature.properties` 加该类型的专属字段（联合属性集模式，带 `[type]` 标注说明）
- `feature.allOf` 加 if/then 分支：该 type 时 required 哪些字段
- 数值字段用 `numberOrParam` / `positiveNumberOrParam`，复用 `$defs`

### 3. 扩语义校验（`scripts/validate_ir.py`）

Schema 表达不了的跨字段规则：互斥、范围换算后的检查、target 类型合法性。
加入 `POSITIVE_FIELDS` / `SOLID_PRODUCING`（如适用）或新增检查函数。

### 4. 扩生成器（`generator/ir_codegen.py`）

- 写 `_emit_<type>(feat, res, used) -> list[str]`，返回脚本行
- 注册进 `EMITTERS` 分派表和 `SUPPORTED_FEATURES`
- 需要的新 import 名加进 `_IMPORT_POOL`（按用途分键）
- 若引入新的实体产生方式，检查 `generate_script` 的链追踪逻辑是否要更新
  （boolean 当年引入时需要合并链）

### 5. 加单测（`tests/test_generator.py`）

至少 3 个用例：
- 体积解析解断言（手算期望值，`pytest.approx(..., rel=1e-6)`）
- 边界情况（如 revolve 360° vs 部分角）
- 与其他特征的组合（链追踪）

### 6. 更新文档与 skill

- `docs/IR_SPEC.md`：特征语义速查表加一行 + 已知局限里删掉该项
- `docs/MODULES.md`：EMITTERS 说明如变了要同步
- **skill 能力边界**：`C:\Users\Remilie\.agents\skills\ai-cad\SKILL.md` 的
  "生成器能力边界"段——不改这个，DSH 以后还会当它不支持

### 7. 全量回归

```powershell
python -m pytest tests -v -p no:cacheprovider     # 全绿
python scripts\build_ir.py examples\<每个example>.json  # 全部通过
```

## 目录级注意事项

| 目录 | 说明 |
|------|------|
| `output/` | 生成物（STEP/STL/临时脚本），可整体删除，git 应忽略 |
| `.wheels/` | pip 离线安装缓存，保留（网络故障时救命） |
| `output/tests/` | 测试产物目录，勿删（测试依赖） |
| `examples/` | IR 实例 = 回归基准，改一个要过一遍 build_ir |

## 关键技术备忘

- build123d 用**代数模式**（`extrude(Rectangle(...), amount=...)`），不是 builder 模式
  （`with BuildPart()`）。两种别混
- 贯穿孔模板：圆柱以目标包围盒中心为轴心、长度取包围盒三边和 × 2，保证穿透且与
  用户给的 z 无关（确定性）
- 盲孔语义：从 center 起沿 **-Z** 钻 depth 深（`align=(C,C,MAX)`）
- 边选择器实现在 `_edge_selector`：all/vertical(=filter_by(Axis.Z))/
  horizontal(=filter_by(Plane.XY))/top/bottom(=faces().sort_by(Axis.Z)[±])
- 生成脚本的参数以 `P_<NAME>` 常量出现在顶部；IR 的 snake_case 参数名直接大写化
