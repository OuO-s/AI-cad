from pathlib import Path
import struct
import sys

import pytest
from build123d import Box, Cylinder, Pos, export_stl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow.stl_interface import inspect_stl_interface, load_stl


def plate_with_holes():
    return Box(100, 80, 4) - Pos(-25, 0, -2) * Cylinder(3, 8) - Pos(25, 0, -2) * Cylinder(4, 8)


def test_real_stl_plane_and_holes(tmp_path):
    path = tmp_path / "plate.stl"
    export_stl(plate_with_holes(), path, angular_tolerance=.05)
    report = inspect_stl_interface(path, "mm", circle_max_residual_mm=.15)
    assert report["triangle_count"] > 0
    assert report["installation_plane_candidate"]["area_mm2"] > 7000
    diameters = sorted(c["diameter_mm"] for c in report["circle_candidates"])
    assert diameters == pytest.approx([6, 8], abs=.15)
    assert report["requires_user_confirmation"]
    assert report["rejected_boundary_loops"]  # 外矩形不是圆孔。


def test_units_are_never_guessed(tmp_path):
    path = tmp_path / "plate.stl"
    export_stl(plate_with_holes(), path)
    with pytest.raises(ValueError, match="单位"):
        inspect_stl_interface(path, "inch")


def test_ascii_loader(tmp_path):
    path = tmp_path / "one.stl"
    path.write_text("solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid x\n", encoding="ascii")
    triangles, encoding = load_stl(path)
    assert encoding == "ascii"
    assert triangles.shape == (1, 3, 3)


def test_invalid_binary_length_not_accepted(tmp_path):
    path = tmp_path / "bad.stl"
    path.write_bytes(b"x" * 80 + struct.pack("<I", 2) + b"x" * 50)
    with pytest.raises((ValueError, UnicodeDecodeError)):
        load_stl(path)


@pytest.mark.parametrize("kwargs", [{"vertex_tolerance_mm": 0}, {"circle_max_residual_mm": float("nan")},
                                    {"circle_min_samples": True}, {"circle_min_samples": 2}])
def test_bad_thresholds(tmp_path, kwargs):
    path = tmp_path / "plate.stl"
    export_stl(plate_with_holes(), path)
    with pytest.raises(ValueError):
        inspect_stl_interface(path, "mm", **kwargs)
