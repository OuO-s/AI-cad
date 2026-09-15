# 架构设计

## 运行形态：与 DeepSeek Harness（DSH）组合

本平台的 AI 层有两条并存路径：

- **主路径（DSH）**：用户在 DSH 会话中直接下自然语言指令，DSH 读取 Schema 后产出
  CAD IR JSON 文件到工作区，调用管线脚本生成 STEP；执行失败的 traceback 直接回到
  DSH 会话，由 DSH 修改 JSON 重试——不需要单独构建自愈循环服务。
- **并存路径（Ollama）**：FastAPI 后端保留 `/generate` 接口，内部可接本地 Ollama
  模型做意图解析，使管线可脱离 DSH 独立运行（CLI / API 调用）。

## 管线总览

```
用户自然语言（经 DSH 会话，或 FastAPI + Ollama）
    │
    ▼
┌─────────────┐   JSON Schema 约束 + Few-shot + 反模式
│  LLM 意图解析 │ ────────────────────────────────┐
│ (DSH / Ollama)│                                │ (校验失败时
└─────────────┘                                 │  带 traceback
    │ CAD IR JSON                               │  重试/修正)
    ▼                                           │
┌─────────────┐                                 │
│ Schema 校验   │ ── 不合格 ──────────────────────┘
└─────────────┘
    │ 合法 JSON
    ▼
┌──────────────────┐
│ 确定性代码生成器    │  模板 + 几何计算，无 LLM 参与
│ (JSON → Python)  │
└──────────────────┘
    │ build123d 脚本
    ▼
┌──────────────────┐
│ 沙箱执行           │  AST 静态验证 + import 白名单 + 超时
└──────────────────┘
    │
    ├──▶ STEP 文件（B-Rep 精确实体，可导入 SolidWorks/Fusion 360 编辑）
    └──▶ STL/GLTF 预览网格（前端暂缓，先用本地查看器验证）
```

## 关键决策与理由

| 决策 | 理由 |
|------|------|
| LLM 输出 JSON 而非代码 | LLM 空间推理不可靠；JSON 可严格校验、可修正、可 diff |
| 生成器用模板而非 LLM | 确定性：同一 JSON 永远生成同一脚本，可单测、可审计 |
| DSH 作为主 AI 层 | 修正循环天然存在于会话中，无需自建 agent 服务 |
| 保留 Ollama 接口 | 管线可独立于 DSH 运行，便于集成到其他系统 |
| 前端暂缓 | 先跑通管线核心闭环，Three.js 预览等管线稳定后再做 |
| 几何内核只在后端 | build123d 依赖完整 OCCT；前端用 Replicad 只做轻量预览（可选） |
| 沙箱用子进程 + AST 验证 | 生成脚本理论上是安全的，但 LLM 修正循环可能引入任意文本，必须防御 |

## 模块职责

- `schemas/`：CAD IR JSON Schema，管线的"合同"，LLM 与生成器共同依赖
- `generator/`：纯函数式的 JSON → Python 翻译器，无副作用、无 IO
- `sandbox/`：脚本执行隔离层，负责安全验证与资源限制
- `llm/`：Ollama 客户端、Prompt 模板（并存路径用；DSH 路径复用同一套 Prompt 规范）
- `server/`：FastAPI 服务（独立运行形态），串联各模块
- `web/`：前端（暂缓；管线稳定后用 Vue 3 + Three.js + Monaco）
