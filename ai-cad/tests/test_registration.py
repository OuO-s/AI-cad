"""对应点配准不能静默缩放、镜像或接受退化定位。"""

from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow.registration import rigid_registration


POINTS = np.array([[0, 0, 0], [10, 0, 0], [0, 20, 0], [0, 0, 30]])


def test_rotation_translation():
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    target = POINTS @ rotation.T + [35, 2, 8]
    report = rigid_registration(POINTS, target, .001)
    matrix = np.asarray(report["transform"])
    assert report["status"] == "within_tolerance"
    assert matrix[:3, :3] == pytest.approx(rotation, abs=1e-10)
    assert matrix[:3, 3] == pytest.approx([35, 2, 8])
    assert report["requires_placement_confirmation"]


@pytest.mark.parametrize("factor", [2, -1])
def test_scale_and_mirror_rejected(factor):
    target = POINTS.copy()
    target[:, 0] *= factor
    result = rigid_registration(POINTS, target, .01)
    assert result["status"] == "rejected"
    assert np.linalg.det(np.asarray(result["transform"])[:3, :3]) == pytest.approx(1)


def test_planar_mount_points():
    source = POINTS[:3]
    result = rigid_registration(source, source + [35, 0, 0], .001)
    assert result["status"] == "within_tolerance"


@pytest.mark.parametrize("points", [[], [[0, 0, 0]] * 3, [[0, 0, 0], [1, 0, 0], [2, 0, 0]],
                                     [[0, 0, 0], [1, 0, 0], [0, float("nan"), 0]]])
def test_degenerate_points(points):
    with pytest.raises(ValueError):
        rigid_registration(points, points, .01)


@pytest.mark.parametrize("tolerance", [0, -1, True, float("inf")])
def test_explicit_tolerance(tolerance):
    with pytest.raises(ValueError):
        rigid_registration(POINTS, POINTS, tolerance)


def test_noisy_point_rejected():
    target = POINTS.astype(float).copy()
    target[1, 1] += 1
    result = rigid_registration(POINTS, target, .01)
    assert result["status"] == "rejected"
    assert result["max_error_mm"] > .01
