"""CAD IR 语义校验器

在 JSON Schema 结构校验之上，检查跨字段/跨特征约束：
  1. id 唯一且符合命名规范
  2. target / operands / depends_on 引用的特征存在且出现在之前（拓扑序）
  3. 参数引用存在、默认值在 [min, max] 内
  4. 正值字段解析后 > 0（distance / diameter / radius / 边长 / 半径等）
  5. hole 的 depth 与 through 二选一
  6. revolve 角度 0 < angle <= 360
  7. sketch 特征不可作为 target

用法：
    python scripts/validate_ir.py examples/box_with_hole.json

退出码：0 = 通过；1 = 结构错误；2 = 语义错误。
"""

import json
import re
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    print("缺少依赖 jsonschema，请先: pip install jsonschema", file=sys.stderr)
    sys.exit(3)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "cad_ir.schema.json"

SOLID_PRODUCING = {"extrude", "revolve", "boolean", "hole", "fillet", "chamfer", "import_step"}

# (特征类型, 字段路径) -> 必须解析为正数的数值字段
POSITIVE_FIELDS = {
    "extrude": [("distance",), ("profile", "length"), ("profile", "width"), ("profile", "diameter"), ("profile", "circumscribed_radius")],
    "revolve": [("profile", "length"), ("profile", "width"), ("profile", "diameter"), ("profile", "circumscribed_radius")],
    "hole": [("diameter",), ("depth",)],
    "fillet": [("radius",)],
    "chamfer": [("distance",)],
}


class SemanticError(Exception):
    pass


def resolve_value(node, params, where):
    """数值或 {param: name} -> (数值, 是否为参数引用)"""
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return node, False
    if isinstance(node, dict) and "param" in node:
        name = node["param"]
        if name not in params:
            raise SemanticError(f"{where}: 引用了不存在的参数 '{name}'")
        return params[name]["value"], True
    raise SemanticError(f"{where}: 既不是数值也不是参数引用: {node!r}")


def check_positive(feature, params):
    ftype = feature["type"]
    fid = feature["id"]
    for path in POSITIVE_FIELDS.get(ftype, []):
        node = feature
        for key in path[:-1]:
            node = node.get(key, {})
        key = path[-1]
        if isinstance(node, dict) and key in node:
            value, _ = resolve_value(node[key], params, f"{fid}.{key}")
            if value <= 0:
                raise SemanticError(f"{fid}.{key} 必须为正数，解析得到 {value}")


def validate_semantics(ir, base_dir=None):
    errors = []
    params = ir.get("parameters", {})
    features = ir.get("features", [])
    base_dir = Path(base_dir) if base_dir else None

    # 参数表自身范围检查
    for name, p in params.items():
        v, lo, hi = p["value"], p.get("min"), p.get("max")
        if lo is not None and v < lo:
            errors.append(f"参数 {name}: 默认值 {v} 小于 min {lo}")
        if hi is not None and v > hi:
            errors.append(f"参数 {name}: 默认值 {v} 大于 max {hi}")

    seen_ids = {}
    for idx, feat in enumerate(features):
        fid = feat["id"]
        where = f"features[{idx}] (id={fid})"

        if not re.fullmatch(r"[a-z][a-z0-9_]*", fid):
            errors.append(f"{where}: id 必须是 snake_case，得到 '{fid}'")
        if fid in seen_ids:
            errors.append(f"{where}: id 与 features[{seen_ids[fid]}] 重复")
        seen_ids[fid] = idx

        ftype = feat["type"]
        if ftype in ("revolve", "sketch"):
            errors.append(f"{where}: 当前生成器不支持独立 {ftype} 特征")

        # 引用存在且在前
        for ref in feat.get("depends_on", []):
            if ref not in seen_ids or seen_ids[ref] >= idx:
                errors.append(f"{where}: depends_on 引用 '{ref}' 不存在或未在前文出现")

        target = feat.get("target")
        if target is not None:
            if target not in seen_ids or seen_ids[target] >= idx:
                errors.append(f"{where}: target '{target}' 不存在或未在前文出现")
            elif features[seen_ids[target]]["type"] not in SOLID_PRODUCING:
                errors.append(f"{where}: target '{target}' 是 {features[seen_ids[target]]['type']}，不是实体特征")

        if ftype == "boolean":
            ops = feat["operands"]
            for op in ops:
                if op not in seen_ids or seen_ids[op] >= idx:
                    errors.append(f"{where}: 操作数 '{op}' 不存在或未在前文出现")

        # mode=add/subtract/intersect 时必须有 target
        mode = feat.get("mode", "add")
        if ftype in ("extrude", "revolve") and mode in ("add", "subtract", "intersect") and target is None:
            errors.append(f"{where}: mode={mode} 需要指定 target")

        # import_step: 路径存在性
        if ftype == "import_step":
            raw = feat.get("path", "")
            p = Path(raw)
            if not p.is_absolute() and base_dir is not None:
                p = base_dir / p
            if not p.is_file():
                errors.append(f"{where}: import_step 路径不存在: '{raw}'（相对路径以 IR JSON 所在目录为基准）")

        # hole: depth 与 through 二选一
        if ftype == "hole":
            has_depth, has_through = "depth" in feat, bool(feat.get("through"))
            if has_depth and has_through:
                errors.append(f"{where}: depth 与 through 互斥，只能二选一")
            if not has_depth and not has_through:
                errors.append(f"{where}: 必须指定 depth（盲孔）或 through: true（贯穿）")

        # polygon 轮廓合法性：正多边形需 sides+半径（结构层已保证二选一），
        # 任意点列多边形至少 3 个顶点
        prof = feat.get("profile")
        if isinstance(prof, dict) and prof.get("shape") == "polygon" and "points" in prof:
            if len(prof["points"]) < 3:
                errors.append(f"{where}: profile.points 至少需要 3 个顶点，得到 {len(prof['points'])}")

        # revolve 角度范围
        if ftype == "revolve" and "angle" in feat:
            angle, _ = resolve_value(feat["angle"], params, f"{fid}.angle")
            if not (0 < angle <= 360):
                errors.append(f"{where}: angle 必须满足 0 < angle <= 360，得到 {angle}")

        try:
            check_positive(feat, params)
        except SemanticError as e:
            errors.append(str(e))

    return errors


def main():
    if len(sys.argv) != 2:
        print("用法: python scripts/validate_ir.py <ir.json>", file=sys.stderr)
        sys.exit(3)

    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ir_path = Path(sys.argv[1])
    if not ir_path.is_file():
        print(f"文件不存在: {ir_path}", file=sys.stderr)
        sys.exit(3)

    ir = json.loads(ir_path.read_text(encoding="utf-8"))

    # 第一层：结构校验
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    structural = sorted(Draft202012Validator(schema).iter_errors(ir), key=lambda e: list(e.path))
    if structural:
        for err in structural:
            loc = "/".join(str(p) for p in err.path) or "<root>"
            print(f"[结构] {loc}: {err.message}")
        sys.exit(1)
    print("✅ 结构校验通过 (JSON Schema)")

    # 第二层：语义校验
    semantic = validate_semantics(ir, base_dir=ir_path.resolve().parent)
    if semantic:
        for msg in semantic:
            print(f"[语义] {msg}")
        sys.exit(2)
    print("✅ 语义校验通过 (依赖/参数/正值/互斥)")

    n = len(ir["features"])
    print(f"特征数: {n}，类型: {[f['type'] for f in ir['features']]}")


if __name__ == "__main__":
    main()
