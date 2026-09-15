# DSH 意图解析工作循环（第四阶段主路径）

本文档规定 DSH 作为 AI 意图解析层时，从用户自然语言到 CAD IR JSON 的标准流程。
每一步都必须执行，不得跳过。

## 工作循环

```
用户自然语言
   │
1│ 读取规范：docs/IR_SPEC.md + schemas/cad_ir.schema.json（每轮重读，规范可能更新）
   │
2│ 产出 IR JSON：写入 examples/<name>.json
   │    - 未给定的尺寸：用工程合理默认值，并在 meta.description 中列出全部假设
   │    - M3 螺丝孔通径默认 Ø3.4（细牙可 Ø3.5）；贯穿优先 through: true
   │    - 所有可调尺寸进 parameters 表（带 min/max），特征字段用 {"param": ...} 引用
   │    - 遵守 IR_SPEC 反模式六条禁令
   │
3│ 校验：python scripts/validate_ir.py examples/<name>.json   → 必须两层全过
   │
4│ 建模：python scripts/build_ir.py examples/<name>.json --keep-script
   │
5│ 几何验证（对照解析解或工程常识）：
   │    - 体积、包围盒、实体数=1、valid=true
   │    - 孔位在实体范围内、壁厚未被切穿（必要时在 JSON 里调整重跑）
   │
6│ 向用户报告：输出文件路径、关键尺寸、所做假设；人工确认后可导入 SolidWorks 验证
   │
└─ 失败时：读 traceback / 校验错误 → 修 JSON（不是改生成的 Python）→ 回到 3
```

## 失败修正规则

- **校验失败**：修 JSON 字段直到两层校验通过
- **执行失败**（traceback）：分析是哪个特征的哪个参数导致（坐标越界、半径大于边长、
  布尔结果为空等），修 JSON 后重跑；禁止手工编辑生成的 Python 脚本
- **几何异常**（体积为 0、多实体、破面）：通常是孔位/尺寸矛盾，调整参数重跑

## 与并存路径（Ollama）的关系

Ollama 路径复用同一套 Prompt 规范（IR_SPEC 的语义 + 反模式），实现于 `server/` + `llm/`
（待建）。两条路径产出的 JSON 都必须通过同一个 `scripts/validate_ir.py`，无一例外。

## 当前生成器能力边界（DSH 产出时必须遵守）

- 支持：extrude（direction/mode 全组合）、hole（贯穿/盲孔）、fillet、chamfer、boolean
- 暂不支持：revolve（OCCT 轴约束待处理）、草图布尔叠加（单轮廓单草图）
- sketch 单独特征目前不生成几何，轮廓一律内联在 extrude 里
