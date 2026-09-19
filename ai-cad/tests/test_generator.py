"""第三阶段单元测试：生成器 + 沙箱 + 几何有效性。

运行：
    python -m pytest tests/test_generator.py -v
几何断言基于解析解（体积/包围盒/实体数），每个特征类型至少一个用例。
"""

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generator.ir_codegen import generate_script  # noqa: E402
from sandbox.runner import execute, validate_ast  # noqa: E402

OUT = ROOT / "output" / "tests"
OUT.mkdir(parents=True, exist_ok=True)

BOX = {"shape": "rectangle", "length": 60, "width": 40}


def build(ir, name, *, timeout=120.0):
    """生成 + 沙箱执行，返回 (RunResult, 脚本路径)。"""
    script = OUT / f"{name}_gen.py"
    script.write_text(
        generate_script(ir, step_path=str(OUT / f"{name}.step"), stl_path=str(OUT / f"{name}.stl")),
        encoding="utf-8",
    )
    return execute(script, timeout_s=timeout, cwd=OUT), script


def base_ir(features, name="test_part", params=None):
    return {
        "version": "1.0",
        "meta": {"name": name, "units": "mm"},
        "parameters": params or {},
        "features": features,
    }


# ── extrude ────────────────────────────────────────────────

def test_extrude_box():
    ir = base_ir([{"id": "box", "type": "extrude", "profile": BOX, "plane_spec": {"plane": "XY"},
                   "distance": 20, "mode": "new"}])
    r, _ = build(ir, "t_extrude")
    assert r.ok, r.summary()
    assert r.metrics["volume"] == pytest.approx(60 * 40 * 20, abs=1e-6)
    assert r.metrics["bbox"] == pytest.approx([60, 40, 20])
    assert r.metrics["solids"] == 1 and r.metrics["valid"]


def test_extrude_antinormal():
    ir = base_ir([{"id": "box", "type": "extrude", "profile": BOX, "plane_spec": {"plane": "XY"},
                   "distance": 20, "direction": "antinormal", "mode": "new"}])
    r, _ = build(ir, "t_antinorm")
    assert r.ok, r.summary()
    assert r.metrics["volume"] == pytest.approx(48000, abs=1e-6)


def test_extrude_symmetric():
    ir = base_ir([{"id": "box", "type": "extrude", "profile": BOX, "plane_spec": {"plane": "XY"},
                   "distance": 20, "direction": "symmetric", "mode": "new"}])
    r, _ = build(ir, "t_symm")
    assert r.ok, r.summary()
    assert r.metrics["volume"] == pytest.approx(48000, abs=1e-6)


def test_extrude_offset_plane_and_centered_profile():
    ir = base_ir([{"id": "box", "type": "extrude",
                   "profile": {"shape": "rectangle", "length": 10, "width": 10, "center": {"x": 5, "y": 0}},
                   "plane_spec": {"plane": "XY", "offset": 5}, "distance": 3, "mode": "new"}])
    r, _ = build(ir, "t_offset")
    assert r.ok, r.summary()
    assert r.metrics["volume"] == pytest.approx(300, abs=1e-4)
    assert r.metrics["bbox"][2] == pytest.approx(3)


def test_parameters_flow_into_geometry():
    ir = base_ir(
        [{"id": "box", "type": "extrude",
          "profile": {"shape": "rectangle", "length": {"param": "L"}, "width": {"param": "W"}},
          "plane_spec": {"plane": "XY"}, "distance": {"param": "H"}, "mode": "new"}],
        params={"L": {"value": 50}, "W": {"value": 30}, "H": {"value": 10}},
    )
    r, _ = build(ir, "t_params")
    assert r.ok, r.summary()
    assert r.metrics["volume"] == pytest.approx(50 * 30 * 10, abs=1e-6)


def test_extrude_point_list_polygon():
    """任意点列多边形：直角三角形 (0,0)-(30,0)-(0,20)，面积 300。"""
    ir = base_ir([{"id": "tri", "type": "extrude",
                   "profile": {"shape": "polygon",
                               "points": [{"x": 0, "y": 0}, {"x": {"param": "a"}, "y": 0}, {"x": 0, "y": 20}]},
                   "plane_spec": {"plane": "XZ"}, "distance": {"param": "t"},
                   "direction": "symmetric", "mode": "new"}],
                 name="t_points", params={"a": {"value": 30}, "t": {"value": 10}})
    r, _ = build(ir, "t_points")
    assert r.ok, r.summary()
    assert r.metrics["volume"] == pytest.approx(0.5 * 30 * 20 * 10, rel=1e-9)
    assert r.metrics["bbox"] == pytest.approx([30, 10, 20])
    assert r.metrics["solids"] == 1 and r.metrics["valid"]


# ── hole ───────────────────────────────────────────────────

def test_hole_through():
    ir = base_ir([
        {"id": "box", "type": "extrude", "profile": BOX, "plane_spec": {"plane": "XY"},
         "distance": 20, "mode": "new"},
        {"id": "hole", "type": "hole", "diameter": 5, "center": {"x": 15, "y": 10, "z": 10},
         "through": True, "target": "box"},
    ])
    r, _ = build(ir, "t_hole_through")
    assert r.ok, r.summary()
    expected = 60 * 40 * 20 - math.pi * 2.5 ** 2 * 20
    assert r.metrics["volume"] == pytest.approx(expected, rel=1e-6)
    assert r.metrics["solids"] == 1


def test_hole_blind():
    ir = base_ir([
        {"id": "box", "type": "extrude", "profile": BOX, "plane_spec": {"plane": "XY"},
         "distance": 20, "mode": "new"},
        {"id": "hole", "type": "hole", "diameter": 5, "center": {"x": 15, "y": 10, "z": 20},
         "depth": 8, "target": "box"},
    ])
    r, _ = build(ir, "t_hole_blind")
    assert r.ok, r.summary()
    expected = 60 * 40 * 20 - math.pi * 2.5 ** 2 * 8
    assert r.metrics["volume"] == pytest.approx(expected, rel=1e-6)


# ── fillet / chamfer ──────────────────────────────────────

def test_fillet_reduces_volume():
    ir = base_ir([
        {"id": "box", "type": "extrude", "profile": {"shape": "rectangle", "length": 30, "width": 30},
         "plane_spec": {"plane": "XY"}, "distance": 10, "mode": "new"},
        {"id": "f", "type": "fillet", "radius": 2, "target": "box", "edges": "all"},
    ])
    r, _ = build(ir, "t_fillet")
    assert r.ok, r.summary()
    assert r.metrics["volume"] < 30 * 30 * 10
    assert r.metrics["valid"]


def test_chamfer_reduces_volume():
    ir = base_ir([
        {"id": "box", "type": "extrude", "profile": {"shape": "rectangle", "length": 30, "width": 30},
         "plane_spec": {"plane": "XY"}, "distance": 10, "mode": "new"},
        {"id": "c", "type": "chamfer", "distance": 2, "target": "box", "edges": "vertical"},
    ])
    r, _ = build(ir, "t_chamfer")
    assert r.ok, r.summary()
    # 4 条竖直边各切去 2*2*10/2 = 20 mm³
    assert r.metrics["volume"] == pytest.approx(30 * 30 * 10 - 4 * 20, rel=1e-6)


def test_edge_selector_top():
    ir = base_ir([
        {"id": "box", "type": "extrude", "profile": {"shape": "rectangle", "length": 30, "width": 30},
         "plane_spec": {"plane": "XY"}, "distance": 10, "mode": "new"},
        {"id": "f", "type": "fillet", "radius": 2, "target": "box", "edges": "top"},
    ])
    r, _ = build(ir, "t_top")
    assert r.ok, r.summary()
    assert r.metrics["volume"] < 30 * 30 * 10
    # 只圆角顶面 4 条边，体积减少量应显著小于全边圆角
    assert r.metrics["volume"] > 8000


# ── boolean ───────────────────────────────────────────────

def test_boolean_union():
    ir = base_ir([
        {"id": "a", "type": "extrude", "profile": {"shape": "rectangle", "length": 20, "width": 20},
         "plane_spec": {"plane": "XY"}, "distance": 5, "mode": "new"},
        {"id": "b", "type": "extrude",
         "profile": {"shape": "rectangle", "length": 20, "width": 20, "center": {"x": 10, "y": 10}},
         "plane_spec": {"plane": "XY"}, "distance": 5, "mode": "new"},
        {"id": "u", "type": "boolean", "operation": "union", "operands": ["a", "b"]},
    ])
    r, _ = build(ir, "t_union")
    assert r.ok, r.summary()
    assert r.metrics["volume"] == pytest.approx(20 * 20 * 5 + 20 * 20 * 5 - 10 * 10 * 5, rel=1e-6)
    assert r.metrics["solids"] == 1


def test_boolean_intersect_and_chain():
    ir = base_ir([
        {"id": "a", "type": "extrude", "profile": {"shape": "rectangle", "length": 20, "width": 20},
         "plane_spec": {"plane": "XY"}, "distance": 5, "mode": "new"},
        {"id": "b", "type": "extrude",
         "profile": {"shape": "rectangle", "length": 20, "width": 20, "center": {"x": 10, "y": 10}},
         "plane_spec": {"plane": "XY"}, "distance": 5, "mode": "new"},
        {"id": "i", "type": "boolean", "operation": "intersect", "operands": ["a", "b"]},
        # 布尔之后继续在链上打孔，验证链追踪（孔放在相交区域 0..10 的中心）
        {"id": "hole", "type": "hole", "diameter": 4, "center": {"x": 5, "y": 5, "z": 2.5},
         "through": True, "target": "i"},
    ])
    r, _ = build(ir, "t_intersect")
    assert r.ok, r.summary()
    expected = 10 * 10 * 5 - math.pi * 4 * 5
    assert r.metrics["volume"] == pytest.approx(expected, rel=1e-6)


def test_extrude_subtract_mode():
    ir = base_ir([
        {"id": "a", "type": "extrude", "profile": {"shape": "rectangle", "length": 20, "width": 20},
         "plane_spec": {"plane": "XY"}, "distance": 5, "mode": "new"},
        {"id": "cut", "type": "extrude",
         "profile": {"shape": "circle", "diameter": 10, "center": {"x": 0, "y": 0}},
         "plane_spec": {"plane": "XY"}, "distance": 5, "mode": "subtract", "target": "a"},
    ])
    r, _ = build(ir, "t_subtract")
    assert r.ok, r.summary()
    assert r.metrics["volume"] == pytest.approx(20 * 20 * 5 - math.pi * 25 * 5, rel=1e-6)


# ── 确定性 ─────────────────────────────────────────────────

def test_deterministic_output():
    ir = base_ir([{"id": "box", "type": "extrude", "profile": BOX, "plane_spec": {"plane": "XY"},
                   "distance": 20, "mode": "new"}])
    a = generate_script(ir, step_path="x.step", stl_path="x.stl")
    b = generate_script(ir, step_path="x.step", stl_path="x.stl")
    assert a == b


# ── 沙箱安全 ──────────────────────────────────────────────

@pytest.mark.parametrize("evil,expect_reject", [
    ("import os\n", True),
    ("from subprocess import run\n", True),
    ("eval('1+1')\n", True),
    ("open('x.txt')\n", True),
    ("__import__('os')\n", True),
    ("x = (1).__class__\n", True),
    ("import build123d\n", False),
    ("import json\nimport math\n", False),
])
def test_ast_validation(evil, expect_reject):
    errors = validate_ast(evil)
    assert bool(errors) == expect_reject, f"{evil!r} -> {errors}"


def test_sandbox_blocks_bad_script():
    script = OUT / "evil_gen.py"
    script.write_text("import build123d\nimport os\nos.system('echo hacked')\n", encoding="utf-8")
    r = execute(script)
    assert not r.ok
    assert r.ast_errors  # 被 AST 层拒绝，根本没执行
