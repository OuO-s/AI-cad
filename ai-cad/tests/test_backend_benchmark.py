from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow.backend_benchmark import CASES, benchmark_backend


def test_build123d_benchmark_geometry():
    result = benchmark_backend("build123d", repeats=1)
    assert result["status"] == "completed"
    assert {row["case"] for row in result["cases"]} == set(CASES)
    for row in result["cases"]:
        assert row["successes"] == 1
        assert not row["failures"]
        assert row["valid"]
        assert row["volume_error_mm3"] == pytest.approx(0, abs=1e-5)
        assert row["bbox_error_mm"] == pytest.approx([0, 0, 0], abs=1e-7)


def test_cadquery_is_measured_or_explicitly_unavailable():
    result = benchmark_backend("cadquery", repeats=1)
    assert result["status"] in ("completed", "unavailable")
    if result["status"] == "unavailable":
        assert result["reason"]


@pytest.mark.parametrize("repeats", [0, 101, True])
def test_bad_repeats(repeats):
    with pytest.raises(ValueError):
        benchmark_backend("build123d", repeats)


def test_unknown_backend():
    with pytest.raises(ValueError):
        benchmark_backend("freecad", 1)
