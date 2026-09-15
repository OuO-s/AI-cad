# 模块参考

管线各文件的职责、接口与协议。开发前先读本文，了解改动会影响哪里。

## 总览

```
用户自然语言（DSH skill: ai-cad）
        │
        ▼
examples/<name>.json          DSH 产出 CAD IR（受 docs/IR_SPEC.md 约束）
        │
        ▼
scripts/validate_ir.py        结构校验（JSON Schema）+ 语义校验
        │
        ▼
generator/ir_codegen.py       确定性翻译：IR → build123d Python 脚本
        │
        ▼
sandbox/runner.py             AST 静态验证 + 子进程隔离执行
        │
        ├──▶ output/<name>.step     B-Rep 精确实体（最终产物）
        ├──▶ output/<name>.stl      预览网格
        └──▶ ::METRICS:: stdout 行  几何指标（供验证/测试）
```

## 文件职责

### `schemas/cad_ir.schema.json`

管线的"合同"。结构层约束（字段存在性、类型、枚举）全部在这里；
**跨字段/跨特征的语义约束不在这里**（JSON Schema 表达不了），归语义校验器。

维护规则：字段变更 = 破坏性变更，必须同步更新 `validate_ir.py`、`ir_codegen.py`、
`docs/IR_SPEC.md` 和 skill 的能力边界段，并跑全量测试。

### `scripts/validate_ir.py` — 双层校验器

| 层 | 检查内容 | 退出码 |
|----|---------|--------|
| 结构 | JSON Schema（jsonschema Draft 2020-12） | 1 |
| 语义 | id 唯一且 snake_case；target/operands/depends_on 存在且在前；参数引用存在、默认值在 [min,max]；正值字段 > 0；hole depth/through 互斥；revolve 角度范围；sketch 不可作 target | 2 |

关键数据结构：
- `SOLID_PRODUCING` — 可作 target 的特征类型集合
- `POSITIVE_FIELDS` — 按特征类型列出必须为正的 (字段路径) 元组

CLI：`python scripts/validate_ir.py <ir.json>`

### `generator/ir_codegen.py` — 确定性代码生成器

核心入口：`generate_script(ir: dict, *, step_path: str, stl_path: str) -> str`

- **纯函数**：无 IO、无全局状态；同一 IR → 字节级相同输出（有单测锁定）
- `ParamResolver` — `{"param": "名"}` → Python 表达式（`P_<NAME>` 常量名或字面量）
- `EMITTERS` — 特征类型 → 翻译函数的分派表；新增特征类型在这里注册
- **实体链追踪**（`generate_script` 内）：`chain_of`（特征→根）、`var_root`（根→当前状态变量）。
  mode=new 开新链；带 target 的特征推进所在链；boolean 合并两条链。
  最终结果 = 唯一链的当前状态，或多链的 `Compound`
- 生成脚本的固定结构：`import json` → `from build123d import (...)` → 参数常量 →
  逐特征代码块 → `result = ...` → 导出 → `::METRICS::`

### `sandbox/runner.py` — 沙箱执行器

- `validate_ast(source) -> list[str]` — import 白名单 `{build123d, math, json}`、
  危险调用（eval/exec/open/getattr/…）、dunder 属性封锁
- `execute(script_path, *, timeout_s=120, cwd=None) -> RunResult` — AST 验证 →
  `python -I`（隔离模式）子进程执行 → 捕获输出
- `RunResult`：`ok / returncode / stdout / stderr / metrics / ast_errors / timed_out`
- CLI：`python -m sandbox.runner <script.py> [--timeout 120]`

### `scripts/build_ir.py` — 管线 CLI

一条命令串起全流程：校验（复用 validate_ir 的函数）→ 生成 → 沙箱执行 → 打印结果。
默认生成后删除脚本；`--keep-script` 保留（调试/审计用）。

### `scripts/download_wheels.py` — pip 网络故障绕行

用 urllib（走清华镜像 `/packages/` 直链）下载 wheel 到 `.wheels/`，之后
`pip install --no-index --find-links .wheels <pkg>` 离线安装。改下载列表：编辑 `PACKAGES`。

### `examples/` — IR 实例库

- `box_with_hole.json` — 最小教学例（也用于校验器正反向测试基准）
- `phone_stand.json` — DSH 端到端首例（L 形支架 + M3 孔 + 倒角）
- `l_bracket.json` — skill 触发实例（用户交互迭代产物）

### `tests/test_generator.py` — 几何单测

23 个用例：每特征类型至少 1 个体积解析解断言 + 确定性 + AST 安全 7 类。
运行方式见 DEVELOPMENT.md。

## 协议

### `::METRICS::` 输出协议

生成脚本最后一行输出，沙箱解析进 `RunResult.metrics`：

```json
{"volume": 47607.30, "bbox": [60.0, 40.0, 20.0], "solids": 1, "valid": true}
```

改这个格式 = 同步改 `ir_codegen.py` 尾部 + `runner.py` 解析 + 依赖它的测试。

### 退出码约定（validate_ir / build_ir 共用）

- `0` 成功；`1` 结构错误；`2` 语义错误；`3` 用法/环境错误
- build_ir 执行失败时输出 stderr 尾部 15 行供定位

## 设计不变量（改动时不可破坏）

1. **LLM 层永远不产出 Python 代码**——AI 的输出只能是 IR JSON
2. **生成器永远不"补充"几何意图**——JSON 里没有的不生成（倒角事件即为例证）
3. **生成器纯函数**——同输入同输出，禁止读环境/时间/随机数
4. **沙箱先验证后执行**——AST 不过，进程不启动
5. **失败修 JSON 不修脚本**——生成的脚本是派生物，永远可丢弃可再生
