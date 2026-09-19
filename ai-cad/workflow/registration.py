"""显式对应点的刚体配准；禁止缩放、镜像和自动猜测点对应关系。"""

import numpy as np


def points_mm(values):
    points = np.asarray(values, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError("至少需要三个有限三维点，单位 mm")
    centered = points - points.mean(axis=0)
    singular = np.linalg.svd(centered, compute_uv=False)
    if singular[0] == 0 or singular[1] <= singular[0] * 1e-8:
        raise ValueError("点集重合、共线或近共线，不能唯一确定姿态")
    return points


def rigid_registration(source_mm, target_mm, tolerance_mm):
    """返回列向量约定 target = R @ source + t，坐标不经自动单位换算。"""
    if isinstance(tolerance_mm, bool) or not isinstance(tolerance_mm, (int, float)) or not np.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise ValueError("必须明确给出正的配准最大残差容差（mm）")
    source, target = points_mm(source_mm), points_mm(target_mm)
    if source.shape != target.shape:
        raise ValueError("源点和目标点数量必须相同，按顺序一一对应")
    source_center, target_center = source.mean(axis=0), target.mean(axis=0)
    u, _, vt = np.linalg.svd((source - source_center).T @ (target - target_center))
    correction = np.eye(3)
    correction[2, 2] = 1 if np.linalg.det(vt.T @ u.T) > 0 else -1
    rotation = vt.T @ correction @ u.T
    translation = target_center - rotation @ source_center
    residuals = np.linalg.norm(source @ rotation.T + translation - target, axis=1)
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = translation
    accepted = bool(np.max(residuals) <= tolerance_mm)
    return {"units": "mm", "convention": "target_column = transform @ source_column",
            "transform": matrix.tolist(), "residuals_mm": residuals.tolist(),
            "rms_mm": float(np.sqrt(np.mean(residuals ** 2))), "max_error_mm": float(np.max(residuals)),
            "tolerance_mm": tolerance_mm, "status": "within_tolerance" if accepted else "rejected",
            "requires_placement_confirmation": True,
            "scope": "仅匹配用户指定的对应点；不确认装配意图，不恢复 STL 精确曲面，不修改模型"}
