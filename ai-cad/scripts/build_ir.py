"""管线 CLI：校验 IR → 生成脚本 → 沙箱执行 → 输出 STEP/STL。

用法：
    python scripts/build_ir.py examples/box_with_hole.json [--out output] [--keep-script]
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from validate_ir import validate_semantics  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

from generator.ir_codegen import generate_script  # noqa: E402
from sandbox.runner import execute  # noqa: E402


def load_and_validate(ir_path: Path) -> dict:
    import json

    ir = json.loads(ir_path.read_text(encoding="utf-8"))
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
    args = parser.parse_args()

    ir = load_and_validate(args.ir)
    print(f"✅ IR 校验通过: {ir['meta']['name']} ({len(ir['features'])} 特征)")

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    name = ir["meta"]["name"]
    step_path = out_dir / f"{name}.step"
    stl_path = out_dir / f"{name}.stl"
    script_path = out_dir / f"{name}_gen.py"

    code = generate_script(ir, step_path=str(step_path), stl_path=str(stl_path),
                           base_dir=args.ir.resolve().parent)
    script_path.write_text(code, encoding="utf-8")
    print(f"✅ 脚本已生成: {script_path}")

    result = execute(script_path, timeout_s=args.timeout, cwd=out_dir)
    if not result.ok:
        print(f"❌ 执行失败: {result.summary()}")
        if result.stderr:
            print("--- stderr 尾部 ---")
            print("\n".join(result.stderr.strip().splitlines()[-15:]))
        return 1

    m = result.metrics or {}
    print(f"✅ STEP: {step_path}")
    print(f"   STL : {stl_path}")
    print(f"   体积={m.get('volume', 0):.2f} mm³  包围盒={m.get('bbox')}  "
          f"实体={m.get('solids')}  有效={m.get('valid')}")
    if not args.keep_script and "pytest" not in sys.modules:
        script_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
