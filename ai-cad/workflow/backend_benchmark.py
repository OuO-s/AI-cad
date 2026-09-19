"""固定几何样本的 build123d/CadQuery 可重复基准；不据库名预设结论。"""

import importlib
import importlib.metadata
import math
import statistics
import time


CASES = {
    "box": {"volume_mm3": 1000., "bbox_mm": [20., 10., 5.]},
    "four_hole_plate": {"volume_mm3": 100 * 80 * 4 - 4 * math.pi * 2 ** 2 * 4, "bbox_mm": [100., 80., 4.]},
    "open_shell": {"volume_mm3": 60 * 40 * 20 - 56 * 36 * 18, "bbox_mm": [60., 40., 20.]},
}


def _build123d(case):
    from build123d import Box, Cylinder, Pos
    if case == "box":
        return Box(20, 10, 5)
    if case == "four_hole_plate":
        shape = Box(100, 80, 4)
        for x in (-35, 35):
            for y in (-25, 25):
                shape = shape - Pos(x, y, -1) * Cylinder(2, 6)
        return shape
    if case == "open_shell":
        return Box(60, 40, 20) - Pos(0, 0, 1) * Box(56, 36, 18)
    raise ValueError("未知样本")


def _cadquery(case):
    import cadquery as cq
    if case == "box":
        return cq.Workplane("XY").box(20, 10, 5, centered=(True, True, False))
    if case == "four_hole_plate":
        return (cq.Workplane("XY").box(100, 80, 4, centered=(True, True, False))
                .faces(">Z").workplane().pushPoints([(-35, -25), (-35, 25), (35, -25), (35, 25)])
                .hole(4))
    if case == "open_shell":
        return (cq.Workplane("XY").box(60, 40, 20, centered=(True, True, False))
                .faces(">Z").shell(-2))
    raise ValueError("未知样本")


def _metrics(backend, shape):
    if backend == "build123d":
        box = shape.bounding_box()
        return float(shape.volume), [float(box.size.X), float(box.size.Y), float(box.size.Z)], bool(shape.is_valid)
    solid = shape.val()
    box = solid.BoundingBox()
    return float(solid.Volume()), [float(box.xlen), float(box.ylen), float(box.zlen)], bool(solid.isValid())


def benchmark_backend(backend, repeats=3):
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1 or repeats > 100:
        raise ValueError("repeats 必须是 1～100 的整数")
    package = "build123d" if backend == "build123d" else "cadquery" if backend == "cadquery" else None
    if package is None:
        raise ValueError("仅支持 build123d/cadquery")
    import_start = time.perf_counter()
    try:
        importlib.import_module(package)
    except ImportError as exc:
        return {"backend": backend, "status": "unavailable", "reason": str(exc), "cases": []}
    import_seconds = time.perf_counter() - import_start
    builder = _build123d if backend == "build123d" else _cadquery
    rows = []
    for name, expected in CASES.items():
        times, failures, last = [], [], None
        for _ in range(repeats):
            start = time.perf_counter()
            try:
                shape = builder(name)
                elapsed = time.perf_counter() - start
                last = _metrics(backend, shape)
                times.append(elapsed)
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
        row = {"case": name, "attempts": repeats, "successes": len(times), "failures": failures}
        if last:
            volume, bbox, valid = last
            row.update({"median_seconds": statistics.median(times), "min_seconds": min(times),
                        "volume_mm3": volume, "volume_error_mm3": volume - expected["volume_mm3"],
                        "bbox_mm": bbox, "bbox_error_mm": [a - b for a, b in zip(bbox, expected["bbox_mm"])],
                        "valid": valid})
        rows.append(row)
    return {"backend": backend, "status": "completed", "version": importlib.metadata.version(package),
            "import_seconds": import_seconds, "repeats": repeats, "cases": rows}


def benchmark_all(repeats=3):
    return {"scope": "固定规则几何的本机微基准；不代表复杂装配、交互体验或维护成本",
            "backends": [benchmark_backend(name, repeats) for name in ("build123d", "cadquery")]}
