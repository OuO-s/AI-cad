"""沙箱执行器：AST 静态验证 + 子进程隔离执行生成的 build123d 脚本。

安全层：
1. AST 静态验证
   - import 白名单：build123d / math / json
   - 禁止危险调用：eval、exec、compile、open、__import__、input、breakpoint、
     getattr/setattr/delattr、globals/locals/vars
   - 禁止 dunder 属性访问（obj.__class__ 等）
2. 子进程执行
   - python -I（隔离模式：忽略 PYTHONPATH / 用户 site）
   - 硬超时，超时杀进程
   - 捕获 stdout/stderr；解析 ::METRICS:: 行
"""

from __future__ import annotations

import ast
import json
import math
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_IMPORTS = {"build123d", "math", "json"}

FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "open", "__import__", "input", "breakpoint",
    "getattr", "setattr", "delattr", "globals", "locals", "vars", "exit", "quit",
}

FORBIDDEN_MODULE_MEMBERS = {
    "os", "sys", "subprocess", "shutil", "pathlib", "socket", "ctypes",
    "importlib", "builtins", "pickle", "multiprocessing", "threading",
}


@dataclass
class RunResult:
    ok: bool
    returncode: int
    stdout: str = ""
    stderr: str = ""
    metrics: dict | None = None
    ast_errors: list[str] = field(default_factory=list)
    timed_out: bool = False

    def summary(self) -> str:
        if self.ast_errors:
            return "AST 拒绝: " + "; ".join(self.ast_errors)
        if self.timed_out:
            return "执行超时"
        if self.ok:
            return f"成功 volume={self.metrics['volume']:.2f}" if self.metrics else "成功（无几何指标）"
        return f"失败 exit={self.returncode}: {self.stderr.strip().splitlines()[-1] if self.stderr.strip() else '无输出'}"


class SandboxViolation(Exception):
    pass


# ── AST 静态验证 ───────────────────────────────────────────

def validate_ast(source: str) -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"语法错误: {e}"]

    for node in ast.walk(tree):
        # import 白名单
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    errors.append(f"第 {node.lineno} 行: 禁止 import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level:  # 相对导入
                errors.append(f"第 {node.lineno} 行: 禁止相对导入")
            elif root not in ALLOWED_IMPORTS:
                errors.append(f"第 {node.lineno} 行: 禁止 from {node.module} import")
        # 危险调用
        elif isinstance(node, ast.Call):
            fn = node.func
            name = None
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
                if isinstance(fn.value, ast.Name) and fn.value.id in FORBIDDEN_MODULE_MEMBERS:
                    errors.append(f"第 {node.lineno} 行: 禁止访问 {fn.value.id}.{fn.attr}")
            if name in FORBIDDEN_CALLS:
                errors.append(f"第 {node.lineno} 行: 禁止调用 {name}()")
        # dunder 属性
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                errors.append(f"第 {node.lineno} 行: 禁止 dunder 属性 .{node.attr}")
    return errors


# ── 子进程执行 ─────────────────────────────────────────────

def run_script(script_path: Path, *, timeout_s: float = 120.0, cwd: Path | None = None) -> RunResult:
    script_path = Path(script_path)
    proc = subprocess.run(
        [sys.executable, "-I", str(script_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        cwd=str(cwd or script_path.parent),
    )
    result = RunResult(
        ok=proc.returncode == 0,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("::METRICS::"):
            try:
                result.metrics = json.loads(line[len("::METRICS::"):])
            except json.JSONDecodeError:
                pass
            break
    if result.ok:
        reason = metrics_error(result.metrics)
        if reason:
            result.ok = False
            result.stderr += "\n几何检查失败：" + reason
    return result


def metrics_error(metrics: dict | None) -> str | None:
    """退出码为零仍需有可信的基础几何指标；不代表已验证装配。"""
    if not isinstance(metrics, dict):
        return "缺少几何指标"
    if metrics.get("valid") is not True:
        return "实体有效性未通过"
    solids = metrics.get("solids")
    if isinstance(solids, bool) or not isinstance(solids, int) or solids < 1:
        return "没有有效实体数量"
    bbox = metrics.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 3:
        return "包围盒格式错误"
    values = [metrics.get("volume")] + bbox
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) and v > 0 for v in values):
        return "体积或包围盒必须为有限正数"
    return None


def execute(script_path: Path, *, timeout_s: float = 120.0, cwd: Path | None = None,
            skip_ast: bool = False) -> RunResult:
    """完整沙箱管线：AST 验证 → 子进程执行。"""
    source = Path(script_path).read_text(encoding="utf-8")
    if not skip_ast:
        errors = validate_ast(source)
        if errors:
            return RunResult(ok=False, returncode=-1, ast_errors=errors)
    try:
        return run_script(script_path, timeout_s=timeout_s, cwd=cwd)
    except subprocess.TimeoutExpired:
        return RunResult(ok=False, returncode=-1, timed_out=True)


if __name__ == "__main__":
    import argparse

    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="沙箱执行 build123d 脚本")
    parser.add_argument("script", type=Path)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    r = execute(args.script, timeout_s=args.timeout)
    print(r.summary())
    if r.metrics:
        print(json.dumps(r.metrics, indent=2))
    sys.exit(0 if r.ok else 1)
