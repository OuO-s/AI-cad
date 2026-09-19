"""确定性 CAD IR → build123d Python 代码生成器

架构原则：
- 纯函数，无 LLM、无副作用、无 IO：同一份合法 IR 永远生成字节级相同的脚本
- 每个 IR 字段精确映射到 build123d 代数模式 API 调用
- 支持特征：extrude / hole / fillet / chamfer / boolean（revolve 下一增量）
- 参数表生成为脚本顶部常量（P_<NAME>），保持脚本可读可改

用法：
    from generator.ir_codegen import generate_script
    code = generate_script(ir, step_path="out/x.step", stl_path="out/x.stl")
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

SUPPORTED_FEATURES = {"extrude", "hole", "fillet", "chamfer", "boolean", "import_step"}
SOLID_PRODUCING = {"extrude", "hole", "fillet", "chamfer", "boolean"}

PLANE_EXPR = {"XY": "Plane.XY", "XZ": "Plane.XZ", "YZ": "Plane.YZ"}
AXIS_EXPR = {"X": "Axis.X", "Y": "Axis.Y", "Z": "Axis.Z"}

# 需要从 build123d 导入的名字（按需收集，最终排序去重）
_IMPORT_POOL = {
    "plane": ["Plane"],
    "axis": ["Axis"],
    "pos": ["Pos"],
    "profile_rect": ["Rectangle"],
    "profile_circle": ["Circle"],
    "profile_polygon": ["RegularPolygon"],
    "profile_polygon_points": ["Polygon"],
    "extrude": ["extrude"],
    "hole": ["Cylinder", "Align"],
    "fillet": ["fillet"],
    "chamfer": ["chamfer"],
    "compound": ["Compound"],
    "import_step": ["import_step"],
    "export": ["export_step", "export_stl"],
    "edge_select": [],  # filter_by/sort_by 是方法，无需导入
}


class CodegenError(Exception):
    """IR 无法翻译（语义校验应在上游拦截，此处兜底）。"""


# ── 参数解析 ────────────────────────────────────────────────

class ParamResolver:
    """把 {"param": name} 解析为 Python 表达式（常量名或字面量）。"""

    def __init__(self, params: dict[str, Any]):
        self.params = params

    def expr(self, node: Any, where: str) -> str:
        if isinstance(node, bool):
            raise CodegenError(f"{where}: 不支持布尔值出现在数值字段")
        if isinstance(node, (int, float)):
            return repr(float(node)) if isinstance(node, float) else repr(node)
        if isinstance(node, dict) and "param" in node:
            name = node["param"]
            if name not in self.params:
                raise CodegenError(f"{where}: 未知参数 '{name}'")
            return f"P_{name.upper()}"
        raise CodegenError(f"{where}: 非法数值节点 {node!r}")

    def value(self, node: Any, where: str) -> float:
        """解析为纯数值（测试/内部计算用）。"""
        e = self.expr(node, where)
        try:
            return float(e) if not e.startswith("P_") else float(self.params[e[2:].lower()]["value"])
        except (KeyError, ValueError):
            return float("nan")


# ── 表达式片段 ─────────────────────────────────────────────

def _plane_expr(plane_spec: dict, res: ParamResolver, used: set[str]) -> str:
    used.add("plane")
    expr = PLANE_EXPR[plane_spec["plane"]]
    if plane_spec.get("rotation"):
        used.add("axis")
        rot = res.expr(plane_spec["rotation"], "plane_spec.rotation")
        expr = f"{expr}.rotated((0.0, 0.0, {rot}))"
    if "offset" in plane_spec and plane_spec["offset"] not in (0, 0.0):
        off = res.expr(plane_spec["offset"], "plane_spec.offset")
        expr = f"{expr}.offset({off})"
    return expr


def _profile_expr(profile: dict, res: ParamResolver, used: set[str]) -> str:
    shape = profile["shape"]
    center = profile.get("center")
    where = f"profile({shape})"

    if shape == "rectangle":
        used.add("profile_rect")
        core = f"Rectangle({res.expr(profile['length'], where + '.length')}, {res.expr(profile['width'], where + '.width')})"
    elif shape == "circle":
        used.add("profile_circle")
        d = res.expr(profile["diameter"], where + ".diameter")
        core = f"Circle({d} / 2.0)"
    elif shape == "polygon":
        if "points" in profile:
            used.add("profile_polygon_points")
            pts = ", ".join(
                f"({res.expr(p['x'], where + '.points.x')}, {res.expr(p['y'], where + '.points.y')})"
                for p in profile["points"]
            )
            core = f"Polygon({pts})"
        else:
            used.add("profile_polygon")
            r = res.expr(profile["circumscribed_radius"], where + ".circumscribed_radius")
            n = int(profile["sides"])
            core = f"RegularPolygon({r}, {n})"
        if profile.get("rotation"):
            used.add("axis")
            core = f"{core}.rotate(Axis.Z, {res.expr(profile['rotation'], where + '.rotation')})"
    else:
        raise CodegenError(f"不支持的轮廓形状: {shape}")

    if center and any(center.get(k) not in (0, 0.0) for k in ("x", "y")):
        used.add("pos")
        u = res.expr(center["x"], where + ".center.x")
        v = res.expr(center["y"], where + ".center.y")
        core = f"Pos({u}, {v}, 0.0) * {core}"
    return core


def _sketch_expr(profile: dict, plane_spec: dict, res: ParamResolver, used: set[str]) -> str:
    """草图表达式：平面 × 轮廓（平面在左，先应用平面变换再画轮廓）。"""
    prof = _profile_expr(profile, res, used)
    if plane_spec.get("plane") != "XY" or plane_spec.get("offset", 0) or plane_spec.get("rotation"):
        plane = _plane_expr(plane_spec, res, used)
        return f"({plane}) * {prof}"
    return prof


def _edge_selector(solid_var: str, selector: Any, used: set[str]) -> str:
    if selector is None or selector == "all":
        return f"{solid_var}.edges()"
    if selector == "vertical":
        used.add("axis")
        return f"{solid_var}.edges().filter_by(Axis.Z)"
    if selector == "horizontal":
        used.add("plane")
        return f"{solid_var}.edges().filter_by(Plane.XY)"
    if selector == "top":
        used.add("axis")
        return f"{solid_var}.faces().sort_by(Axis.Z)[-1].edges()"
    if selector == "bottom":
        used.add("axis")
        return f"{solid_var}.faces().sort_by(Axis.Z)[0].edges()"
    if isinstance(selector, dict) and "indices" in selector:
        picks = [f"{solid_var}.edges()[{i}]" for i in selector["indices"]]
        return "[" + ", ".join(picks) + "]"
    raise CodegenError(f"非法边选择器: {selector!r}")


def _var(feature_id: str, prefix: str = "s_") -> str:
    return f"{prefix}{feature_id}"


# ── 特征翻译 ────────────────────────────────────────────────

def _emit_extrude(feat: dict, res: ParamResolver, used: set[str]) -> list[str]:
    used.add("extrude")
    fid = feat["id"]
    lines = []
    sk = f"_sk_{fid}"
    lines.append(f"{sk} = {_sketch_expr(feat['profile'], feat.get('plane_spec', {'plane': 'XY'}), res, used)}")

    distance = res.expr(feat["distance"], f"{fid}.distance")
    direction = feat.get("direction", "normal")
    if direction == "normal":
        amount = distance
        extra = ""
    elif direction == "antinormal":
        amount = f"-({distance})"
        extra = ""
    else:  # symmetric
        amount = f"({distance}) / 2.0"
        extra = ", both=True"

    mode = feat.get("mode", "add")
    new_var = _var(fid)

    if mode == "new":
        lines.append(f"{new_var} = extrude({sk}, amount={amount}{extra})")
        return lines

    target = feat.get("target")
    if not target:
        raise CodegenError(f"{fid}: mode={mode} 缺少 target")
    op = {"add": "+", "subtract": "-", "intersect": "&"}[mode]
    tmp = f"_x_{fid}"
    lines.append(f"{tmp} = extrude({sk}, amount={amount}{extra})")
    lines.append(f"{new_var} = {_var(target)} {op} {tmp}")
    return lines


def _emit_hole(feat: dict, res: ParamResolver, used: set[str]) -> list[str]:
    used.update({"hole", "pos"})
    fid = feat["id"]
    target = feat.get("target")
    if not target:
        raise CodegenError(f"{fid}: hole 缺少 target")
    tvar = _var(target)
    d = res.expr(feat["diameter"], f"{fid}.diameter")
    c = feat["center"]
    x = res.expr(c["x"], f"{fid}.center.x")
    y = res.expr(c["y"], f"{fid}.center.y")
    z = res.expr(c["z"], f"{fid}.center.z")

    if feat.get("through"):
        # 贯穿：圆柱以目标包围盒中心为轴心，长度取包围盒对角线 2 倍，保证穿透
        return [
            f"_bb_{fid} = {tvar}.bounding_box()",
            f"_cz_{fid} = (_bb_{fid}.min.Z + _bb_{fid}.max.Z) / 2.0",
            f"_cl_{fid} = (_bb_{fid}.size.X + _bb_{fid}.size.Y + _bb_{fid}.size.Z) * 2.0",
            f"s_{fid} = {tvar} - Pos({x}, {y}, _cz_{fid}) * Cylinder({d} / 2.0, _cl_{fid})",
        ]

    if "depth" not in feat:
        raise CodegenError(f"{fid}: hole 需要 depth（盲孔）或 through: true")
    depth = res.expr(feat["depth"], f"{fid}.depth")
    # 盲孔：从 center 起沿 -Z 钻 depth 深（align MAX 使圆柱向 z- 延伸）
    return [
        f"s_{fid} = {tvar} - Pos({x}, {y}, {z}) * Cylinder({d} / 2.0, {depth}, align=(Align.CENTER, Align.CENTER, Align.MAX))",
    ]


def _emit_fillet(feat: dict, res: ParamResolver, used: set[str]) -> list[str]:
    used.add("fillet")
    fid = feat["id"]
    target = feat.get("target")
    if not target:
        raise CodegenError(f"{fid}: fillet 缺少 target")
    edges = _edge_selector(_var(target), feat.get("edges"), used)
    r = res.expr(feat["radius"], f"{fid}.radius")
    return [f"s_{fid} = fillet({edges}, radius={r})"]


def _emit_chamfer(feat: dict, res: ParamResolver, used: set[str]) -> list[str]:
    used.add("chamfer")
    fid = feat["id"]
    target = feat.get("target")
    if not target:
        raise CodegenError(f"{fid}: chamfer 缺少 target")
    edges = _edge_selector(_var(target), feat.get("edges"), used)
    d = res.expr(feat["distance"], f"{fid}.distance")
    return [f"s_{fid} = chamfer({edges}, length={d})"]


def _emit_import_step(feat: dict, res: ParamResolver, used: set[str], base_dir: Path | None) -> list[str]:
    used.add("import_step")
    fid = feat["id"]
    p = Path(feat["path"])
    if not p.is_absolute() and base_dir is not None:
        p = base_dir / p
    p = p.resolve()
    return [
        f"# 导入现有模型: {feat['path']}",
        f"s_{fid} = import_step({str(p)!r})",
    ]


def _emit_boolean(feat: dict, res: ParamResolver, used: set[str]) -> list[str]:
    fid = feat["id"]
    op = {"union": "+", "subtract": "-", "intersect": "&"}[feat["operation"]]
    a, b = (_var(t) for t in feat["operands"])
    return [f"s_{fid} = {a} {op} {b}"]


EMITTERS = {
    "extrude": _emit_extrude,
    "hole": _emit_hole,
    "fillet": _emit_fillet,
    "chamfer": _emit_chamfer,
    "boolean": _emit_boolean,
}


# ── 主入口 ─────────────────────────────────────────────────

def generate_script(ir: dict, *, step_path: str, stl_path: str | None = None,
                    base_dir=None, expected_solids: int = 1) -> str:
    """把合法 CAD IR 翻译为可直接执行的 build123d 脚本文本。

    base_dir: IR JSON 所在目录（Path 或 str），用于解析 import_step 的相对路径。
    """
    if isinstance(expected_solids, bool) or not isinstance(expected_solids, int) or expected_solids < 1:
        raise CodegenError("expected_solids 必须为正整数")
    base_dir = base_dir if isinstance(base_dir, Path) or base_dir is None else Path(base_dir)
    res = ParamResolver(ir.get("parameters", {}))
    used: set[str] = set()
    body: list[str] = []

    # 链追踪：root_id -> 当前状态变量名（每个 mode=new 的特征开启一条实体链；
    # hole/fillet/chamfer/extrude(target)/boolean 都是对某条链的推进或合并）
    chain_of: dict[str, str] = {}   # 特征id -> 其所属 root 的 id
    root_of: dict[str, str] = {}    # 状态变量名 -> root id（用变量名做键，boolean 合并时改写）
    var_root: dict[str, str] = {}   # root id -> 当前状态变量名

    def root_chain(target_fid: str) -> str:
        if target_fid not in chain_of:
            raise CodegenError(f"target '{target_fid}' 不在任何实体链上")
        return chain_of[target_fid]

    for feat in ir["features"]:
        ftype = feat["type"]
        fid = feat["id"]
        if ftype == "sketch":
            continue
        if ftype not in EMITTERS and ftype != "import_step":
            raise CodegenError(
                f"{fid}: 特征类型 '{ftype}' 尚未支持（本生成器支持 {sorted(SUPPORTED_FEATURES)}）"
            )
        body.append(f"# feature: {fid} ({ftype})")
        if ftype == "import_step":
            body.extend(_emit_import_step(feat, res, used, base_dir))
        else:
            body.extend(EMITTERS[ftype](feat, res, used))
        body.append("")

        new_var = _var(fid)
        if ftype == "import_step" or (ftype == "extrude" and feat.get("mode", "add") == "new"):
            chain_of[fid] = fid
            var_root[fid] = new_var
        elif ftype == "boolean":
            roots = [root_chain(t) for t in feat["operands"]]
            merged = roots[0]
            for r in set(roots[1:]):
                if r != merged:
                    if r in var_root:
                        del var_root[r]
                    for k, v in list(chain_of.items()):
                        if v == r:
                            chain_of[k] = merged
            chain_of[fid] = merged
            var_root[merged] = new_var
        else:
            target = feat.get("target")
            if target:
                root = root_chain(target)
                chain_of[fid] = root
                var_root[root] = new_var
            elif ftype in ("extrude", "revolve"):
                # add/subtract/intersect 无 target 已被语义校验拦截，兜底
                raise CodegenError(f"{fid}: 缺少 target")

    if not var_root:
        raise CodegenError("IR 中没有产生实体的特征")

    # 结果收集：单链用当前状态；多链合成 Compound
    used.add("export")
    states = [var_root[r] for r in var_root]
    if len(states) == 1:
        final_lines = [f"result = {states[0]}"]
    else:
        used.add("compound")
        final_lines = [f"result = Compound(children=[{', '.join(states)}])"]

    final_lines += [
        "",
        "_bb = result.bounding_box()",
        "_metrics = {",
        "    'volume': result.volume,",
        "    'bbox': [_bb.size.X, _bb.size.Y, _bb.size.Z],",
        "    'solids': len(result.solids()),",
        "    'valid': bool(result.is_valid),",
        "}",
        "print('::METRICS::' + json.dumps(_metrics))",
        "if not _metrics['valid']:",
        "    raise ValueError('几何检查失败：实体无效，未导出')",
        f"if _metrics['solids'] != {expected_solids!r}:",
        "    raise ValueError('几何检查失败：实体数量与预期不符，未导出')",
        "if not all(math.isfinite(v) and v > 0 for v in [_metrics['volume']] + _metrics['bbox']):",
        "    raise ValueError('几何检查失败：体积或包围盒异常，未导出')",
        f"if not export_step(result, {step_path!r}):",
        "    raise RuntimeError('STEP 导出失败')",
    ]
    if stl_path is not None:
        final_lines += [
            f"if not export_stl(result, {stl_path!r}, tolerance=0.1, angular_tolerance=0.3):",
            "    raise RuntimeError('STL 导出失败')",
        ]

    imports = sorted({n for key in used for n in _IMPORT_POOL.get(key, [])})
    if stl_path is None:
        imports.remove("export_stl")
    import_lines = ["import json", "import math", "", "from build123d import (", *[f"    {n}," for n in imports], ")", ""]

    header = [f"# 由 ai-cad 确定性生成器自动生成，来自 {ir['meta']['name']}.json — 请勿手工编辑",
              "# 生成器版本: 1.1 (extrude/hole/fillet/chamfer/boolean/import_step)", ""]
    if ir.get("parameters"):
        header += ["# ── 参数表（与 IR parameters 对应）──"]
        header += [f"P_{name.upper()} = {float(p['value'])!r}" for name, p in ir["parameters"].items()]
        header.append("")

    return "\n".join(import_lines + header + body + final_lines) + "\n"
