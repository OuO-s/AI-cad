"""STEP 模型体检：导入任意 STEP → 提取拓扑/尺寸摘要 JSON，供 LLM 理解现有模型。

输出报告包含：
  - 实体数 / 体积 / 包围盒 / 有效性
  - 圆柱面清单（半径、轴向、轴位置、孔/凸台判定、z 范围）——孔位识别的核心
  - 平面清单（面积、法向、中心，按面积降序）
  - 其他曲面（圆锥/球/环面等）计数

用法：
    python scripts/inspect_step.py <model.step> [--out report.json]

判定原理：
  孔（凹圆柱面）：实体外法向在面中心处指向圆柱轴（dot(normal, radial) < 0）
  凸台（凸圆柱面）：外法向背离轴（dot > 0）
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from build123d import GeomType, import_step


def _vec3(v) -> list[float]:
    """build123d Vector / gp_Pnt/gp_Dir → [x, y, z]"""
    try:
        return [round(float(v.X), 4), round(float(v.Y), 4), round(float(v.Z), 4)]
    except TypeError:
        return [round(float(v.X()), 4), round(float(v.Y()), 4), round(float(v.Z()), 4)]


def _axis_dominant(d: list[float]) -> str:
    ax, ay, az = abs(d[0]), abs(d[1]), abs(d[2])
    if ax > 0.9:
        return "X"
    if ay > 0.9:
        return "Y"
    if az > 0.9:
        return "Z"
    return "oblique"


def inspect_step(path: Path) -> dict:
    shape = import_step(str(path))
    solids = shape.solids()
    bb = shape.bounding_box()

    report = {
        "file": str(path),
        "solids": len(solids),
        "valid": bool(shape.is_valid),
        "volume_mm3": round(shape.volume, 3),
        "bbox": {
            "min": [round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)],
            "max": [round(bb.max.X, 3), round(bb.max.Y, 3), round(bb.max.Z, 3)],
            "size": [round(bb.size.X, 3), round(bb.size.Y, 3), round(bb.size.Z, 3)],
        },
        "edges_total": len(shape.edges()),
        "faces_by_type": {},
        "cylinders": [],
        "planes": [],
    }

    for face in shape.faces():
        gt = face.geom_type
        name = gt.name if hasattr(gt, "name") else str(gt)
        report["faces_by_type"][name] = report["faces_by_type"].get(name, 0) + 1

        if gt == GeomType.CYLINDER:
            try:
                cyl = face.geom_adaptor().Cylinder()
                axis = cyl.Axis()
                loc = axis.Location()
                direction = axis.Direction()
                radius = cyl.Radius()
            except Exception:
                continue  # 退化圆柱面，跳过

            center = face.center()
            normal = face.normal_at(center)
            radial = (center.X - loc.X(), center.Y - loc.Y(), center.Z - loc.Z())
            dot = normal.X * radial[0] + normal.Y * radial[1] + normal.Z * radial[2]
            kind = "hole" if dot < 0 else "boss"

            fbb = face.bounding_box()
            report["cylinders"].append({
                "kind": kind,
                "radius": round(radius, 3),
                "diameter": round(radius * 2, 3),
                "axis_dir": _vec3(direction),
                "axis_dominant": _axis_dominant(_vec3(direction)),
                "axis_point": _vec3(loc),
                "face_center": _vec3(center),
                "z_range": [round(fbb.min.Z, 3), round(fbb.max.Z, 3)],
                "area": round(face.area, 3),
            })

        elif gt == GeomType.PLANE:
            center = face.center()
            try:
                normal = face.normal_at(center)
            except Exception:
                normal = None
            report["planes"].append({
                "area": round(face.area, 3),
                "normal": _vec3(normal) if normal else None,
                "center": _vec3(center),
            })

    # 排序：圆柱按半径升序（孔通常小）、平面按面积降序
    report["cylinders"].sort(key=lambda c: (c["kind"], c["radius"]))
    report["planes"].sort(key=lambda p: -p["area"])
    holes = [c for c in report["cylinders"] if c["kind"] == "hole"]
    report["hole_count"] = len(holes)
    # 常见螺纹底孔提示（通径配合：M2=2.4 M3=3.4 M4=4.5 M5=5.5 M6=6.6）
    thread_map = {2.4: "M2", 3.4: "M3", 4.5: "M4", 5.5: "M5", 6.6: "M6"}
    for h in holes:
        h["likely_thread"] = thread_map.get(round(h["diameter"], 1))
    return report


def human_summary(report: dict) -> str:
    b = report["bbox"]
    lines = [
        f"文件: {report['file']}",
        f"实体数: {report['solids']}  有效: {report['valid']}  体积: {report['volume_mm3']:.1f} mm³",
        f"包围盒: {b['size'][0]} × {b['size'][1]} × {b['size'][2]} mm"
        f" (min {b['min']} → max {b['max']})",
        f"面统计: {report['faces_by_type']}  边总数: {report['edges_total']}",
        f"圆柱面: {len(report['cylinders'])} 个（孔 {report['hole_count']} / 凸台 "
        f"{len(report['cylinders']) - report['hole_count']}）",
    ]
    for h in report["cylinders"]:
        if h["kind"] == "hole":
            t = f" ≈{h['likely_thread']}" if h.get("likely_thread") else ""
            lines.append(
                f"  孔 Ø{h['diameter']}{t} 轴向{h['axis_dominant']} "
                f"轴点{h['axis_point']} z∈[{h['z_range'][0]}, {h['z_range'][1]}]"
            )
    lines.append(f"平面: {len(report['planes'])} 个（前 5 按面积）")
    for p in report["planes"][:5]:
        lines.append(f"  面 {p['area']:.1f} mm² 法向{p['normal']} 中心{p['center']}")
    return "\n".join(lines)


def main() -> int:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="STEP 模型体检：提取拓扑/尺寸摘要")
    parser.add_argument("step", type=Path, help="STEP 文件路径")
    parser.add_argument("--out", type=Path, default=None, help="报告 JSON 输出路径（默认 <name>.inspect.json）")
    args = parser.parse_args()

    if not args.step.is_file():
        print(f"文件不存在: {args.step}", file=sys.stderr)
        return 3

    report = inspect_step(args.step)
    out = args.out or args.step.with_suffix(".inspect.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(human_summary(report))
    print(f"\n完整报告已写入: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
