"""管线 CLI：校验 IR → 生成脚本 → 沙箱执行 → 输出 STEP/STL。

用法：
    python scripts/build_ir.py examples/box_with_hole.json [--out output] [--keep-script]
"""

import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from validate_ir import validate_semantics  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

from generator.ir_codegen import generate_script  # noqa: E402
from sandbox.runner import execute  # noqa: E402
from workflow.plan import draft_ir, fingerprint  # noqa: E402
from workflow.expressions import resolve_parameters  # noqa: E402


def load_and_validate(ir_path: Path) -> dict:
    import json

    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    ir["parameters"] = resolve_parameters(ir.get("parameters", {}))
    name = ir.get("meta", {}).get("name", "")
    if not isinstance(name, str) or not re.fullmatch(r"[\w-]+", name) or name.upper() in {
        "CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]
    }:
        raise ValueError("模型名称不能包含路径或非法文件名字符")
    schema = json.loads((ROOT / "schemas" / "cad_ir.schema.json").read_text(encoding="utf-8"))
    structural = sorted(Draft202012Validator(schema).iter_errors(ir), key=lambda e: list(e.path))
    if structural:
        for err in structural:
            loc = "/".join(str(p) for p in err.path) or "<root>"
            print(f"[结构] {loc}: {err.message}")
        sys.exit(1)
    semantic = validate_semantics(ir, base_dir=ir_path.resolve().parent)
    if semantic:
        for msg in semantic:
            print(f"[语义] {msg}")
        sys.exit(2)
    return ir


def main() -> int:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="CAD IR → build123d → STEP 管线")
    parser.add_argument("ir", type=Path, help="CAD IR JSON 文件")
    parser.add_argument("--out", type=Path, default=ROOT / "output", help="输出目录")
    parser.add_argument("--keep-script", action="store_true", help="保留生成的 Python 脚本")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--stl", action="store_true", help="额外导出 STL；默认只导出 STEP")
    parser.add_argument("--expected-solids", type=int, default=1,
                        help="预期制造实体数，默认 1；多实体交付需明确指定")
    parser.add_argument("--mode", choices=("draft", "final"), default="final",
                        help="draft 省略倒角/圆角供看样式；final 保留全部特征")
    args = parser.parse_args()
    if args.expected_solids < 1:
        parser.error("--expected-solids 必须为正整数")

    started = time.perf_counter()
    ir = load_and_validate(args.ir)
    source_hash = fingerprint(ir)
    if args.mode == "draft":
        ir = draft_ir(ir)
    print(f"✅ IR 校验通过: {ir['meta']['name']} ({len(ir['features'])} 特征)")

    run_id = uuid.uuid4().hex
    out_dir = args.out.resolve() / run_id
    out_dir.mkdir(parents=True, exist_ok=False)
    name = ir["meta"]["name"]
    step_path = out_dir / f"{name}.step"
    stl_path = out_dir / f"{name}.stl"
    script_path = out_dir / f"{name}_gen.py"
    manifest_path = out_dir / "run.json"
    manifest = {"run_id": run_id, "status": "running", "mode": args.mode,
                "source_hash": source_hash, "artifacts": [],
                "checks": {"geometry": "pending", "assembly": "not_checked"}}

    def save_manifest():
        manifest["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        temp = manifest_path.with_suffix(".tmp")
        temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(manifest_path)

    save_manifest()

    try:
        code = generate_script(ir, step_path=str(step_path),
                               stl_path=str(stl_path) if args.stl else None,
                               base_dir=args.ir.resolve().parent,
                               expected_solids=args.expected_solids)
        script_path.write_text(code, encoding="utf-8")
        print(f"✅ 脚本已生成: {script_path}")
        result = execute(script_path, timeout_s=args.timeout, cwd=out_dir)
    except Exception as exc:
        manifest.update(status="failed", error=str(exc))
        save_manifest()
        raise
    if not result.ok:
        manifest.update(status="failed", error=result.summary(), metrics=result.metrics)
        manifest["checks"]["geometry"] = "failed_or_incomplete"
        save_manifest()
        print(f"❌ 执行失败: {result.summary()}")
        if result.stderr:
            print("--- stderr 尾部 ---")
            print("\n".join(result.stderr.strip().splitlines()[-15:]))
        return 1

    m = result.metrics or {}
    outputs = [step_path] + ([stl_path] if args.stl else [])
    if any(not p.is_file() or p.stat().st_size == 0 for p in outputs):
        manifest.update(status="failed", error="导出文件缺失或为空")
        save_manifest()
        return 1
    manifest.update(status="draft" if args.mode == "draft" else "geometry_passed",
                    metrics=m, artifacts=[str(p) for p in outputs])
    manifest["checks"]["geometry"] = "passed"
    save_manifest()
    print(f"交付清单: {manifest_path}")
    if args.mode == "draft":
        print("样式草稿：已省略倒角/圆角；不得视为最终制造版本。")
    print(f"✅ STEP: {step_path}")
    if args.stl:
        print(f"   STL : {stl_path}")
    print("   已通过基础几何检查；安装孔位、装配干涉等需按任务另行核对。")
    print(f"   体积={m.get('volume', 0):.2f} mm³  包围盒={m.get('bbox')}  "
          f"实体={m.get('solids')}  有效={m.get('valid')}")
    if not args.keep_script and "pytest" not in sys.modules:
        script_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
