"""无第三方网格库的 STL 安装平面与圆形边界候选提取。"""

import math
from pathlib import Path
import re
import struct

import numpy as np


def load_stl(path):
    data = Path(path).read_bytes()
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + count * 50:
            values = np.empty((count, 3, 3), dtype=float)
            for i in range(count):
                flat = struct.unpack_from("<12fH", data, 84 + i * 50)[3:12]
                values[i] = np.asarray(flat).reshape(3, 3)
            return values, "binary"
    text = data.decode("ascii", errors="strict")
    vertices = [[float(x), float(y), float(z)] for x, y, z in re.findall(
        r"\bvertex\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)", text)]
    if not vertices or len(vertices) % 3:
        raise ValueError("不是有效的二进制或 ASCII STL")
    return np.asarray(vertices, dtype=float).reshape(-1, 3, 3), "ascii"


def _basis(normal):
    helper = np.array([1., 0., 0.]) if abs(normal[0]) < .8 else np.array([0., 1., 0.])
    u = np.cross(normal, helper)
    u /= np.linalg.norm(u)
    return u, np.cross(normal, u)


def fit_circle(points_3d, normal):
    origin = points_3d.mean(axis=0)
    u, v = _basis(normal)
    points = np.column_stack(((points_3d - origin) @ u, (points_3d - origin) @ v))
    design = np.column_stack((2 * points[:, 0], 2 * points[:, 1], np.ones(len(points))))
    cx, cy, c = np.linalg.lstsq(design, np.sum(points ** 2, axis=1), rcond=None)[0]
    radius_sq = c + cx * cx + cy * cy
    if radius_sq <= 0:
        raise ValueError("圆拟合退化")
    radius = math.sqrt(radius_sq)
    distances = np.linalg.norm(points - [cx, cy], axis=1)
    residuals = np.abs(distances - radius)
    angles = np.sort(np.mod(np.arctan2(points[:, 1] - cy, points[:, 0] - cx), 2 * math.pi))
    gaps = np.diff(np.r_[angles, angles[0] + 2 * math.pi])
    coverage = 1 - float(gaps.max() / (2 * math.pi))
    center = origin + cx * u + cy * v
    return {"center_mm": center.tolist(), "diameter_mm": radius * 2,
            "rms_residual_mm": float(np.sqrt(np.mean(residuals ** 2))),
            "max_residual_mm": float(residuals.max()), "angular_coverage": coverage,
            "sample_count": len(points_3d)}


def _loops_from_triangles(triangles, vertex_tolerance):
    def key(point):
        return tuple(np.rint(point / vertex_tolerance).astype(np.int64))
    coordinates, counts = {}, {}
    for triangle in triangles:
        for a, b in ((triangle[0], triangle[1]), (triangle[1], triangle[2]), (triangle[2], triangle[0])):
            ka, kb = key(a), key(b)
            coordinates.setdefault(ka, a)
            coordinates.setdefault(kb, b)
            edge = tuple(sorted((ka, kb)))
            counts[edge] = counts.get(edge, 0) + 1
    adjacency = {}
    for (a, b), count in counts.items():
        if count == 1:
            adjacency.setdefault(a, []).append(b)
            adjacency.setdefault(b, []).append(a)
    if any(len(neighbors) != 2 for neighbors in adjacency.values()):
        return [], "non_manifold_or_open_planar_boundary"
    loops, remaining = [], set(adjacency)
    while remaining:
        start = min(remaining)
        loop, previous, current = [], None, start
        while True:
            loop.append(current)
            options = [x for x in adjacency[current] if x != previous]
            nxt = options[0]
            previous, current = current, nxt
            if current == start:
                break
            if current in loop or len(loop) > len(adjacency):
                return [], "invalid_boundary_cycle"
        remaining.difference_update(loop)
        loops.append(np.asarray([coordinates[p] for p in loop]))
    return loops, None


def inspect_stl_interface(path, units, plane_angle_tolerance_deg=1.0, plane_offset_tolerance_mm=0.05,
                          vertex_tolerance_mm=1e-4, circle_max_residual_mm=0.1,
                          circle_min_coverage=0.8, circle_min_samples=8):
    if units != "mm":
        raise ValueError("STL 不含可靠单位；必须由用户明确指定 units=mm，其他单位请先显式转换")
    numeric = [plane_angle_tolerance_deg, plane_offset_tolerance_mm, vertex_tolerance_mm,
               circle_max_residual_mm, circle_min_coverage]
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0 for x in numeric):
        raise ValueError("拟合容差必须为正的有限数值")
    if not isinstance(circle_min_samples, int) or isinstance(circle_min_samples, bool) or circle_min_samples < 3:
        raise ValueError("circle_min_samples 至少为 3")
    triangles, encoding = load_stl(path)
    edges_a = triangles[:, 1] - triangles[:, 0]
    edges_b = triangles[:, 2] - triangles[:, 0]
    crosses = np.cross(edges_a, edges_b)
    double_area = np.linalg.norm(crosses, axis=1)
    valid = np.isfinite(triangles).all(axis=(1, 2)) & (double_area > 1e-12)
    rejected = int((~valid).sum())
    triangles, crosses, double_area = triangles[valid], crosses[valid], double_area[valid]
    if len(triangles) == 0:
        raise ValueError("STL 没有非退化三角形")
    normals = crosses / double_area[:, None]
    # 方向规范化，仅用于把同一几何平面的反向三角形归组。
    canonical = normals.copy()
    flip = ((canonical[:, 0] < -1e-12) |
            ((np.abs(canonical[:, 0]) <= 1e-12) & (canonical[:, 1] < -1e-12)) |
            ((np.abs(canonical[:, :2]).max(axis=1) <= 1e-12) & (canonical[:, 2] < 0)))
    canonical[flip] *= -1
    centroids = triangles.mean(axis=1)
    offsets = np.sum(canonical * centroids, axis=1)
    cos_limit = math.cos(math.radians(plane_angle_tolerance_deg))
    clusters = []
    for i in range(len(triangles)):
        match = next((c for c in clusters if float(c["normal"] @ canonical[i]) >= cos_limit
                      and abs(c["offset"] - offsets[i]) <= plane_offset_tolerance_mm), None)
        if match is None:
            match = {"normal": canonical[i].copy(), "offset": float(offsets[i]), "indices": [], "area": 0.}
            clusters.append(match)
        match["indices"].append(i)
        match["area"] += float(double_area[i] / 2)
    cluster = max(clusters, key=lambda c: c["area"])
    selected = triangles[cluster["indices"]]
    loops, boundary_error = _loops_from_triangles(selected, vertex_tolerance_mm)
    circles, rejected_loops = [], []
    for index, loop in enumerate(loops):
        result = fit_circle(loop, cluster["normal"])
        accepted = (result["sample_count"] >= circle_min_samples
                    and result["max_residual_mm"] <= circle_max_residual_mm
                    and result["angular_coverage"] >= circle_min_coverage)
        (circles if accepted else rejected_loops).append({"loop_index": index, **result})
    bounds = [triangles.reshape(-1, 3).min(axis=0).tolist(), triangles.reshape(-1, 3).max(axis=0).tolist()]
    return {"file": str(path), "units": "mm", "encoding": encoding, "triangle_count": len(triangles),
            "degenerate_triangles_rejected": rejected, "bounds_mm": bounds,
            "installation_plane_candidate": {"normal": cluster["normal"].tolist(), "offset_mm": cluster["offset"],
                                             "triangle_count": len(selected), "area_mm2": cluster["area"]},
            "circle_candidates": circles, "rejected_boundary_loops": rejected_loops,
            "boundary_error": boundary_error,
            "thresholds": {"plane_angle_tolerance_deg": plane_angle_tolerance_deg,
                           "plane_offset_tolerance_mm": plane_offset_tolerance_mm,
                           "vertex_tolerance_mm": vertex_tolerance_mm,
                           "circle_max_residual_mm": circle_max_residual_mm,
                           "circle_min_coverage": circle_min_coverage, "circle_min_samples": circle_min_samples},
            "requires_user_confirmation": True,
            "limitations": ["STL 单位来自用户声明，文件本身通常不携带可靠单位", "安装面按最大共面三角形面积选择，可能不是用户意图的安装面",
                            "圆形边界是网格拟合候选，不能恢复原 CAD 精度、螺纹或孔加工语义"]}
