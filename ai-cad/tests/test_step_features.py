from pathlib import Path
import sys

import pytest
from build123d import Box, Cylinder, Pos, export_step

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.inspect_step import inspect_step
from workflow.step_features import canonical_axis, group_cylinders


def cylinder(radius, start, end, point=(0, 0, 0), direction=(0, 0, 1), kind="hole"):
    return {"kind": kind, "radius": radius, "axis_point": list(point), "axis_dir": list(direction),
            "axis_range_bounds": [start, end]}


def test_axis_representation_is_canonical():
    a = canonical_axis([2, 3, 4], [0, 0, -2])
    b = canonical_axis([2, 3, 99], [0, 0, 1])
    assert a == b == ([2.0, 3.0, 0.0], [0.0, 0.0, 1.0])


def test_split_faces_and_counterbore_grouped():
    items = [cylinder(2, 0, 5), cylinder(2, 5, 10), cylinder(4, 10, 12),
             cylinder(5, 0, 10, point=(30, 0, 0), kind="boss")]
    result = group_cylinders(items)
    assert len(result) == 1
    assert result[0]["classification"] == "stepped"
    assert [s["diameter"] for s in result[0]["stages"]] == [4, 8]
    assert result[0]["evidence"]["concave_cylinder_faces"] == 3


def test_same_axis_disconnected_not_merged():
    result = group_cylinders([cylinder(2, 0, 4), cylinder(2, 6, 10)])
    assert len(result) == 2


def test_opposite_direction_and_shifted_axis():
    result = group_cylinders([cylinder(2, 0, 4, direction=(0, 0, 1)),
                              cylinder(2, 4, 8, point=(0, 0, 20), direction=(0, 0, -1)),
                              cylinder(2, 0, 4, point=(1, 0, 0))])
    assert len(result) == 2


@pytest.mark.parametrize("field,value", [("axis_tolerance_mm", -1), ("angle_tolerance_deg", float("nan")),
                                          ("interval_tolerance_mm", True), ("radius_tolerance_mm", -1)])
def test_bad_tolerance(field, value):
    args = {"axis_tolerance_mm": .01, "angle_tolerance_deg": .1,
            "interval_tolerance_mm": .01, "radius_tolerance_mm": .01, field: value}
    with pytest.raises(ValueError):
        group_cylinders([], **args)


def test_inspect_real_step_holes(tmp_path):
    part = Box(40, 30, 10) - Pos(-10, 0, -5) * Cylinder(2, 20) - Pos(10, 0, -5) * Cylinder(3, 20)
    path = tmp_path / "plate.step"
    export_step(part, path)
    report = inspect_step(path)
    assert report["concave_cylinder_face_count"] == 2
    assert report["hole_candidate_count"] == 2
    assert sorted(f["stages"][0]["diameter"] for f in report["hole_candidates"]) == [4, 6]
    assert all("螺纹" in f["limitations"] for f in report["hole_candidates"])
