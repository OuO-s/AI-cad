"""装配检查必须抓住碰撞、包络误导出和未检查范围。"""

import copy
import json
from pathlib import Path
import sys

import pytest
from build123d import Box, Compound, Pos, export_step, import_step

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow.assembly import deliver_assembly, pair_metrics, validate_assembly


def plan():
    return {"version": 1, "units": "mm", "frame": "assembly_world",
            "parts": [{"id": "shell", "role": "manufacturing", "path": "shell.step"},
                      {"id": "module", "role": "reference", "path": "module.step"}],
            "exports": ["shell"], "checks": [{"pair": ["shell", "module"], "min_clearance_mm": 2}]}


@pytest.mark.parametrize("offset,volume,distance", [(0, 1000, 0), (5, 500, 0), (10, 0, 0), (12, 0, 2)])
def test_pair_metrics(offset, volume, distance):
    result = pair_metrics(Box(10, 10, 10), Pos(offset, 0, 0) * Box(10, 10, 10))
    assert result["intersection_mm3"] == pytest.approx(volume)
    assert result["distance_mm"] == pytest.approx(distance)


@pytest.mark.parametrize("change", [
    {"exports": ["module"]}, {"exports": ["missing"]}, {"exports": ["shell", "shell"]},
    {"frame": "local"}, {"units": "cm"}, {"distance_tolerance_mm": float("nan")},
    {"checks": [{"pair": ["shell", "shell"]}]},
    {"checks": [{"pair": ["shell", "module"], "min_clearance_mm": -1}]},
    {"checks": [{"pair": ["shell", "module"], "min_clearance_mm": True}]},
    {"checks": [{"pair": ["shell", "module"], "allow_interference": True}]},
    {"ignored_invariant": "must not change"},
])
def test_bad_plan(change):
    with pytest.raises(ValueError):
        validate_assembly({**plan(), **change})


def inputs(tmp_path, offset=12):
    export_step(Box(10, 10, 10), tmp_path / "shell.step")
    export_step(Pos(offset, 0, 0) * Box(10, 10, 10), tmp_path / "module.step")


def test_white_list_and_repeat(tmp_path):
    inputs(tmp_path)
    first, result = deliver_assembly(plan(), tmp_path, tmp_path / "out")
    second, _ = deliver_assembly(plan(), tmp_path, tmp_path / "out")
    assert first != second
    assert result["status"] == "declared_checks_passed"
    assert result["assembly"] == "declared_pairs_passed"
    assert set(result["artifacts"]) == {"shell"}
    delivered = import_step(result["artifacts"]["shell"]["step"])
    assert delivered.volume == pytest.approx(1000)
    assert list(delivered.bounding_box().min) == pytest.approx([-5, -5, -5])
    assert not (first.parent / "module.step").exists()
    assert json.loads(first.read_text(encoding="utf-8")) == result


@pytest.mark.parametrize("offset", [0, 5, 10, 11])
def test_interference_or_insufficient_clearance_blocks_export(tmp_path, offset):
    inputs(tmp_path, offset)
    manifest, result = deliver_assembly(plan(), tmp_path, tmp_path / "out")
    assert result["status"] == "failed"
    assert result["artifacts"] == {}
    assert result["checks"][0]["passed"] is False
    assert not (manifest.parent / "shell.step").exists()


def test_partial_coverage(tmp_path):
    inputs(tmp_path)
    p = plan()
    p["checks"] = []
    _, result = deliver_assembly(p, tmp_path, tmp_path / "out")
    assert result["status"] == "geometry_passed"
    assert result["assembly"] == "partial"
    assert result["unchecked_pairs"] == [["module", "shell"]]


def test_invariant_and_multisolid_rejected(tmp_path):
    inputs(tmp_path)
    p = plan()
    p["parts"][0]["bounds_mm"] = [[0, 0, 0], [10, 10, 10]]
    _, result = deliver_assembly(p, tmp_path, tmp_path / "out")
    assert result["status"] == "failed"
    assert "包围盒" in result["error"]
    export_step(Compound(children=[Box(10, 10, 10), Pos(30, 0, 0) * Box(10, 10, 10)]), tmp_path / "shell.step")
    _, result = deliver_assembly(plan(), tmp_path, tmp_path / "out")
    assert result["status"] == "failed"
    assert "一个" in result["error"]


def test_unknown_transform_and_reserved_name():
    p = copy.deepcopy(plan())
    p["parts"][0]["transform"] = [35, 0, 0]
    with pytest.raises(ValueError, match="变换"):
        validate_assembly(p)
    p = plan()
    p["parts"][0]["id"] = "con"
    with pytest.raises(ValueError, match="保留"):
        validate_assembly(p)


def test_failed_export_does_not_publish(tmp_path, monkeypatch):
    inputs(tmp_path)
    monkeypatch.setattr("build123d.export_step", lambda *args, **kwargs: False)
    manifest, result = deliver_assembly(plan(), tmp_path, tmp_path / "out")
    assert result["status"] == "failed"
    assert result["artifacts"] == {}
    assert json.loads(manifest.read_text(encoding="utf-8"))["artifacts"] == {}


def test_cli_manifest(tmp_path):
    import subprocess
    inputs(tmp_path)
    source = tmp_path / "assembly.json"
    source.write_text(json.dumps(plan()), encoding="utf-8")
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" / "deliver_assembly.py"),
               str(source), "--out", str(tmp_path / "out")]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr + result.stdout
    response = json.loads(result.stdout)
    assert response["status"] == "declared_checks_passed"
    assert Path(response["manifest"]).is_file()
