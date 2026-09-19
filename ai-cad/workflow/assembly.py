"""已定位 STEP 的装配检查与白名单交付；不推测安装位置、不改变输入几何。"""

import hashlib
import itertools
import io
import json
import math
from pathlib import Path
import re
import uuid


def number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{name} 必须为有限数值")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name} 超出范围")
    return value


def validate_assembly(plan):
    if plan.get("version") != 1 or plan.get("units") != "mm" or plan.get("frame") != "assembly_world":
        raise ValueError("需要 version=1、units=mm、frame=assembly_world；输入必须已在同一装配坐标系定位")
    parts = plan.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("parts 不能为空")
    ids = set()
    for part in parts:
        name = part.get("id", "")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) or name in ids:
            raise ValueError("零件 id 必须为唯一的小写安全标识")
        if name.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)], *[f"LPT{i}" for i in range(10)]}:
            raise ValueError("零件 id 是系统保留文件名")
        ids.add(name)
        if part.get("role") not in ("manufacturing", "reference"):
            raise ValueError("每个零件必须显式标记 manufacturing/reference")
        if not isinstance(part.get("path"), str) or not part["path"]:
            raise ValueError("每个零件必须指定 STEP 路径")
        if set(part) - {"id", "role", "path", "bounds_mm"}:
            raise ValueError("未知零件字段；不支持隐式变换或多实体按序号选择")
        bounds = part.get("bounds_mm")
        if bounds is not None:
            if not isinstance(bounds, list) or len(bounds) != 2 or any(not isinstance(v, list) or len(v) != 3 for v in bounds):
                raise ValueError("bounds_mm 必须是 [最小点, 最大点]")
            for axis in range(3):
                lo, hi = bounds[0][axis], bounds[1][axis]
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lo, hi)) or hi <= lo:
                    raise ValueError("bounds_mm 必须有限且各轴有正长度")
    exports = plan.get("exports")
    if not isinstance(exports, list) or not exports or any(not isinstance(x, str) for x in exports) or len(set(exports)) != len(exports):
        raise ValueError("必须指定非空、不重复的 exports 制造白名单")
    roles = {p["id"]: p["role"] for p in parts}
    if any(roles.get(x) != "manufacturing" for x in exports):
        raise ValueError("导出白名单包含参考包络或未知零件")
    number(plan.get("distance_tolerance_mm", 1e-6), "distance_tolerance_mm")
    number(plan.get("volume_tolerance_mm3", 1e-6), "volume_tolerance_mm3")
    number(plan.get("bounds_tolerance_mm", 1e-5), "bounds_tolerance_mm")
    checks = plan.get("checks", [])
    seen = set()
    if not isinstance(checks, list):
        raise ValueError("checks 必须为列表")
    for check in checks:
        pair = check.get("pair")
        if not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(x, str) or x not in ids for x in pair) or pair[0] == pair[1]:
            raise ValueError("检查必须引用两个不同的已知零件")
        key = tuple(sorted(pair))
        if key in seen:
            raise ValueError("不允许重复检查同一零件对")
        seen.add(key)
        number(check.get("min_clearance_mm", 0), "min_clearance_mm")
        if set(check) - {"pair", "min_clearance_mm"}:
            raise ValueError("未知检查字段")
    if set(plan) - {"version", "units", "frame", "parts", "exports", "checks", "distance_tolerance_mm", "volume_tolerance_mm3", "bounds_tolerance_mm"}:
        raise ValueError("未知装配字段，不能静默忽略检查约束")


def shape_metrics(shape):
    box = shape.bounding_box()
    bounds = [list(box.min), list(box.max)]
    volume = float(shape.volume)
    valid = bool(shape.is_valid)
    solids = len(shape.solids())
    if not valid or solids != 1 or not math.isfinite(volume) or volume <= 0:
        raise ValueError("每个输入 STEP 必须仅包含一个有效正体积实体")
    if any(not math.isfinite(x) for row in bounds for x in row) or any(bounds[1][i] <= bounds[0][i] for i in range(3)):
        raise ValueError("实体包围盒异常")
    return {"bounds_mm": bounds, "volume_mm3": volume, "solids": solids, "valid": valid}


def pair_metrics(first, second):
    common = first.intersect(second)
    volume = sum(float(s.volume) for s in common) if common else 0.0
    distance = float(first.distance_to(second))
    number(volume, "交集体积")
    number(distance, "最小距离")
    return {"intersection_mm3": volume, "distance_mm": distance}


def deliver_assembly(plan, base_dir, output_dir):
    """所有声明检查通过才发布 STEP；未声明的零件对显式记为未检查。"""
    from build123d import export_step, import_step

    validate_assembly(plan)
    run_dir = Path(output_dir).resolve() / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=False)
    input_dir = run_dir / "inputs_not_for_manufacturing"
    input_dir.mkdir()
    report = {"run_id": run_dir.name, "status": "running", "artifacts": {}, "parts": {}, "checks": [],
              "plan": plan, "scope": "仅显式零件对、包围盒和静态几何；不验证插入路径、线缆、散热或强度"}

    def save():
        temp = run_dir / "run.json.tmp"
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temp.replace(run_dir / "run.json")

    save()
    try:
        shapes = {}
        sources = {}
        for part in plan["parts"]:
            path = (Path(base_dir) / part["path"]).resolve()
            if path.suffix.lower() not in (".step", ".stp"):
                raise ValueError("仅接受 STEP；STL 不能冒充精确实体")
            # 固化输入副本，避免导入过程中源文件变化；只从本次快照读取。
            data = path.read_bytes()
            snapshot = input_dir / (part["id"] + ".step")
            snapshot.write_bytes(data)
            shape = import_step(snapshot)
            metrics = shape_metrics(shape)
            expected = part.get("bounds_mm")
            if expected is not None and any(abs(metrics["bounds_mm"][i][j] - expected[i][j]) > plan.get("bounds_tolerance_mm", 1e-5) for i in range(2) for j in range(3)):
                raise ValueError(f"{part['id']} 固定包围盒约束不满足")
            sources[part["id"]] = hashlib.sha256(data).hexdigest()
            report["parts"][part["id"]] = {**metrics, "role": part["role"], "source": str(path), "sha256": sources[part["id"]]}
            shapes[part["id"]] = shape
        checked = set()
        for check in plan.get("checks", []):
            a, b = check["pair"]
            metrics = pair_metrics(shapes[a], shapes[b])
            passed = (metrics["intersection_mm3"] <= plan.get("volume_tolerance_mm3", 1e-6)
                      and metrics["distance_mm"] + plan.get("distance_tolerance_mm", 1e-6) >= check.get("min_clearance_mm", 0))
            report["checks"].append({**check, **metrics, "passed": passed})
            checked.add(tuple(sorted((a, b))))
        report["unchecked_pairs"] = [list(p) for p in itertools.combinations(sorted(shapes), 2) if p not in checked]
        if any(not c["passed"] for c in report["checks"]):
            raise ValueError("声明的干涉或间隙检查失败，不发布制造 STEP")
        artifacts = {}
        for name in plan["exports"]:
            path = run_dir / (name + ".step")
            # 由 Python 写文件，避免 OCCT 原生路径编码/长度限制。
            buffer = io.BytesIO()
            # 已强制单实体，不导出可能带空装配层级的导入 Compound 包装。
            solid = shapes[name].solids()[0]
            solid.label = name
            if not export_step(solid, buffer) or not buffer.getvalue():
                raise ValueError(f"{name} STEP 导出失败")
            path.write_bytes(buffer.getvalue())
            exported = shape_metrics(import_step(path))
            original = report["parts"][name]
            if abs(exported["volume_mm3"] - original["volume_mm3"]) > max(1e-6, original["volume_mm3"] * 1e-8):
                raise ValueError(f"{name} STEP 回读体积不一致")
            if any(abs(exported["bounds_mm"][i][j] - original["bounds_mm"][i][j]) > 1e-5 for i in range(2) for j in range(3)):
                raise ValueError(f"{name} STEP 回读位置或尺寸不一致")
            artifacts[name] = {"step": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        report["artifacts"] = artifacts
        report["status"] = "declared_checks_passed" if report["checks"] else "geometry_passed"
        report["assembly"] = "partial" if report["unchecked_pairs"] else ("declared_pairs_passed" if report["checks"] else "not_checked")
    except Exception as exc:
        report["status"] = "failed"
        report["artifacts"] = {}
        report["error"] = f"{type(exc).__name__}: {exc}"
    save()
    return run_dir / "run.json", report
