# 开发路线图与进度

工作方式：每次只做一件事；每步可测试可验证；先手写再自动化；不过度设计。

运行形态：与 DSH 组合（主 AI 层），Ollama 接口并存，前端暂缓。

## 第一阶段：跑通最小闭环 ✅（自动化验证已完成）

- [x] 初始化项目结构与文档
- [x] 安装 build123d（0.11.1 + cadquery-ocp 7.9.3）
- [x] 手写脚本：BuildPart 创建带孔盒子，导出 STEP
- [x] 验证 STEP 文件有效性：重新导入体积 47607.30 mm³ 一致、1 实体、有效、
      STEP 内含 `ADVANCED_BREP_SHAPE_REPRESENTATION` + `MANIFOLD_SOLID_BREP`（原生 B-Rep，非网格转储）
- [ ] （人工）确认 STEP 导入 SolidWorks/Fusion 360 后是可编辑实体

环境备注（详细排障见 `TROUBLESHOOTING.md`）：
- 系统字体 `mstmc.ttf` 损坏 → build123d `text.py` 已打补丁，**升级 build123d 后需重打**
- 运行 python 一律先设 `PYTHONIOENCODING=utf-8`（Windows GBK）
- pip 网络挂 → `scripts/download_wheels.py` + `.wheels/` 离线装
- pytest 沙箱限制 → `-p no:cacheprovider`、不用 tmp_path

## 第二阶段：设计 CAD IR JSON Schema ✅

- [x] 定义 `schemas/cad_ir.schema.json`（v1.0，union 属性集 + if/then 按类型约束）
- [x] 特征类型：sketch（矩形/圆/多边形）、extrude、revolve、hole、fillet、chamfer、boolean
- [x] 每特征含：id、type、专属字段、depends_on/target/operands 依赖、数组即执行顺序
- [x] 参数化变量表（`parameters` + `{"param": ...}` 引用，供前端滑块与生成器替换）
- [x] `docs/IR_SPEC.md`：坐标系规范、执行模型、边选择器、反模式禁令（LLM 产出规范）
- [x] `scripts/validate_ir.py`：结构（JSON Schema）+ 语义（依赖/参数/正值/互斥）双层校验
- [x] `examples/box_with_hole.json`：第一阶段盒子的 IR 表达，正反向测试通过（6 类错误全拦截）

## 第三阶段：手写确定性代码生成器 ✅

- [x] `generator/ir_codegen.py`：纯函数 JSON → build123d 脚本，支持 extrude（含
      direction/mode/target 链）、hole（贯穿/盲孔）、fillet、chamfer（含 5 种边选择器）、
      boolean（含链合并追踪）；revolve 推迟（OCCT 要求轴在轮廓平面内，需专门探针）
- [x] `sandbox/runner.py`：AST 静态验证（import 白名单 build123d/math/json、危险调用、
      dunder 属性）+ 子进程隔离执行（`python -I`、硬超时、traceback 捕获、::METRICS:: 解析）
- [x] `scripts/build_ir.py` 管线 CLI：校验 → 生成 → 沙箱执行 → STEP/STL
- [x] 端到端验证：`examples/box_with_hole.json` → 体积 47607.30 mm³，与第一阶段手写脚本一致
- [x] `tests/test_generator.py`：23 个用例全通过（体积解析解、包围盒、实体数、确定性、
      AST 拒绝 7 类恶意脚本）
- 备忘：pytest 也可通过 `.wheels/` 离线装；沙箱内跑 pytest 需 `-p no:cacheprovider`
  且不能用 tmp_path（临时目录受限），测试自带输出目录

## 第四阶段：AI 意图解析接入 ✅（DSH 主路径完成，Ollama 并存路径待建）

- [x] `docs/DSH_WORKFLOW.md`：DSH 意图解析的标准工作循环（读规范→产 JSON→校验→建模
      →几何验证→报告假设；失败修 JSON 不改脚本）
- [x] 端到端实战：「带 M3 螺丝孔的手机支架」→ `examples/phone_stand.json`
      （L 形支架：底板 80×40×5 + 背板 80×5×60 + 2×M3 通孔 Ø3.4 + 顶边倒角 1）
- [x] 几何验证：体积 39790.54 mm³（与解析解 39880 − 倒角 − 孔一致）、单实体、有效、
      STEP 含 ADVANCED_BREP / MANIFOLD_SOLID_BREP
- [x] 发现并记录 IR v1.0 局限：无数值表达式（派生尺寸需 DSH 换算后写字面量并注明）
- [ ] Ollama 并存路径：`server/` + `llm/`，Prompt 复用 IR_SPEC 语义与反模式
- [x] 沉淀为 DSH skill（2026-09-15）：`C:\Users\Remilie\.agents\skills\ai-cad\SKILL.md`，
      触发条件=自然语言零件建模请求；已在会话技能目录中生效
- [ ] 人工确认：STEP 导入 SolidWorks / Fusion 360 检查可编辑特征历史

## 第五阶段：前端渲染与交互（暂缓，管线稳定后启动）

- [ ] 后端导出 STEP + 预览网格
- [ ] Three.js 渲染预览
- [ ] Monaco 代码编辑器（查看/修改生成脚本）
- [ ] 参数化滑块（调整 JSON 尺寸变量）
- [ ] 质量评分与一键优化
