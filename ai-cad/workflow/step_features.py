"""把解析 STEP 圆柱面聚类为可追溯的候选孔特征。"""

import math


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(v):
    length = math.sqrt(_dot(v, v))
    if not math.isfinite(length) or length == 0:
        raise ValueError("圆柱轴方向无效")
    return [x / length for x in v]


def canonical_axis(point, direction):
    """轴线用单位方向和距原点最近点表示，消除轴点与正反方向歧义。"""
    d = _norm(direction)
    for value in d:
        if abs(value) > 1e-12:
            if value < 0:
                d = [-x for x in d]
            break
    projection = _dot(point, d)
    closest = [point[i] - projection * d[i] for i in range(3)]
    return closest, d


def _line_error(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def group_cylinders(cylinders, axis_tolerance_mm=0.01, angle_tolerance_deg=0.1,
                    interval_tolerance_mm=0.01, radius_tolerance_mm=0.01):
    """仅聚类凹圆柱面；区间不连续则不合并，避免同轴但分离的孔被误认。"""
    tolerances = (axis_tolerance_mm, angle_tolerance_deg, interval_tolerance_mm, radius_tolerance_mm)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in tolerances):
        raise ValueError("聚类容差必须为非负有限数值")
    candidates = []
    for index, item in enumerate(cylinders):
        if item.get("kind") != "hole":
            continue
        point, direction = canonical_axis(item["axis_point"], item["axis_dir"])
        interval = [float(x) for x in item["axis_range_bounds"]]
        if len(interval) != 2 or not all(math.isfinite(x) for x in interval) or interval[1] < interval[0]:
            raise ValueError("圆柱轴向区间无效")
        candidates.append({"face_index": index, "axis_point": point, "axis_dir": direction,
                           "interval": interval, "radius": float(item["radius"])})
    # 先按共轴分桶，再按轴向相接区间分组；角度用 |dot|，但方向已规范化。
    buckets = []
    cos_limit = math.cos(math.radians(angle_tolerance_deg))
    for item in candidates:
        bucket = next((b for b in buckets if _dot(b["axis_dir"], item["axis_dir"]) >= cos_limit
                       and _line_error(b["axis_point"], item["axis_point"]) <= axis_tolerance_mm), None)
        if bucket is None:
            bucket = {"axis_point": item["axis_point"], "axis_dir": item["axis_dir"], "faces": []}
            buckets.append(bucket)
        bucket["faces"].append(item)
    features = []
    for bucket in buckets:
        faces = sorted(bucket["faces"], key=lambda x: (x["interval"][0], x["interval"][1], x["radius"]))
        groups = []
        for face in faces:
            matches = [g for g in groups if face["interval"][0] <= g["end"] + interval_tolerance_mm
                       and face["interval"][1] >= g["start"] - interval_tolerance_mm]
            if not matches:
                groups.append({"start": face["interval"][0], "end": face["interval"][1], "faces": [face]})
            else:
                group = matches[0]
                group["start"] = min(group["start"], face["interval"][0])
                group["end"] = max(group["end"], face["interval"][1])
                group["faces"].append(face)
                for extra in matches[1:]:
                    group["start"] = min(group["start"], extra["start"])
                    group["end"] = max(group["end"], extra["end"])
                    group["faces"].extend(extra["faces"])
                    groups.remove(extra)
        for group in groups:
            stages = []
            for face in sorted(group["faces"], key=lambda x: (x["radius"], x["interval"])):
                stage = next((s for s in stages if abs(s["radius"] - face["radius"]) <= radius_tolerance_mm), None)
                if stage is None:
                    stage = {"radius": face["radius"], "diameter": face["radius"] * 2,
                             "axis_ranges": [], "face_indices": []}
                    stages.append(stage)
                stage["axis_ranges"].append(face["interval"])
                stage["face_indices"].append(face["face_index"])
            features.append({"kind": "hole_candidate", "axis_point": bucket["axis_point"],
                             "axis_dir": bucket["axis_dir"], "axis_range": [group["start"], group["end"]],
                             "stages": stages, "classification": "simple" if len(stages) == 1 else "stepped",
                             "evidence": {"concave_cylinder_faces": sum(len(s["face_indices"]) for s in stages),
                                          "coaxial": True, "axially_connected_by_bounds": True},
                             "limitations": "候选孔基于解析凹圆柱面及区间连续性；不证明贯穿、螺纹、可达性或制造意图"})
    features.sort(key=lambda f: (f["axis_point"], f["axis_range"], f["stages"][0]["radius"]))
    return features
