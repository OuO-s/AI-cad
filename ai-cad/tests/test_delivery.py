"""交付回归：基础几何失败不能导出，STL 按需，多实体需明确指定。"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generator.ir_codegen import generate_script
from sandbox.runner import execute, metrics_error


def box_ir(two=False):
    features = [{"id": "a", "type": "extrude", "mode": "new", "distance": 5,
                 "profile": {"shape": "rectangle", "length": 10, "width": 10}}]
    if two:
        features.append({"id": "b", "type": "extrude", "mode": "new", "distance": 5,
                         "profile": {"shape": "rectangle", "length": 10, "width": 10,
                                     "center": {"x": 30, "y": 0}}})
    return {"version": "1.0", "meta": {"name": "delivery", "units": "mm"},
            "features": features}


@pytest.mark.parametrize("override", [
    {"valid": False}, {"valid": 1}, {"solids": 0}, {"volume": float("nan")},
    {"volume": float("inf")}, {"volume": -1}, {"bbox": [10, 10, 0]},
    {"bbox": [10]}, {"solids": True},
])
def test_reject_bad_metrics(override):
    metrics = {"volume": 500, "bbox": [10, 10, 5], "solids": 1, "valid": True}
    assert metrics_error(metrics) is None
    assert metrics_error({**metrics, **override})


def test_zero_exit_without_metrics_is_failure(tmp_path):
    script = tmp_path / "no_metrics.py"
    script.write_text("print('done')\n", encoding="utf-8")
    result = execute(script)
    assert result.returncode == 0
    assert not result.ok
    assert "缺少几何指标" in result.summary()


def test_zero_exit_with_invalid_metrics_is_failure(tmp_path):
    script = tmp_path / "invalid_metrics.py"
    metrics = {"volume": 500, "bbox": [10, 10, 5], "solids": 1, "valid": False}
    script.write_text("print(" + repr("::METRICS::" + json.dumps(metrics)) + ")\n", encoding="utf-8")
    result = execute(script)
    assert result.returncode == 0
    assert not result.ok
    assert "实体有效性未通过" in result.summary()


def test_default_step_only(tmp_path):
    script = tmp_path / "model.py"
    step = tmp_path / "model.step"
    code = generate_script(box_ir(), step_path=str(step))
    assert "export_stl" not in code
    script.write_text(code, encoding="utf-8")
    result = execute(script)
    assert result.ok, result.summary()
    assert step.stat().st_size > 0
    assert not list(tmp_path.glob("*.stl"))


def test_solid_count_blocks_export_and_preserves_old_file(tmp_path):
    script = tmp_path / "model.py"
    step = tmp_path / "model.step"
    step.write_text("previous output", encoding="utf-8")
    script.write_text(generate_script(box_ir(two=True), step_path=str(step)), encoding="utf-8")
    result = execute(script)
    assert not result.ok
    assert result.metrics["solids"] == 2
    assert step.read_text(encoding="utf-8") == "previous output"


def test_explicit_multi_solid_and_stl(tmp_path):
    script = tmp_path / "model.py"
    step, stl = tmp_path / "model.step", tmp_path / "model.stl"
    script.write_text(generate_script(box_ir(two=True), step_path=str(step),
                                     stl_path=str(stl), expected_solids=2), encoding="utf-8")
    result = execute(script)
    assert result.ok, result.summary()
    assert result.metrics["solids"] == 2
    assert step.stat().st_size > 0 and stl.stat().st_size > 0


def test_cli_default_and_explicit_stl(tmp_path):
    ir = tmp_path / "input.json"
    ir.write_text(json.dumps(box_ir()), encoding="utf-8")
    command = [sys.executable, str(ROOT / "scripts" / "build_ir.py"), str(ir),
               "--out", str(tmp_path / "out")]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(list((tmp_path / "out").glob("*/delivery.step"))) == 1
    assert not list((tmp_path / "out").glob("*/delivery.stl"))
    result = subprocess.run(command + ["--stl"], capture_output=True, text=True,
                            encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(list((tmp_path / "out").glob("*/delivery.stl"))) == 1
    assert len(list((tmp_path / "out").glob("*/delivery.step"))) == 2
    manifests = [json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "out").glob("*/run.json")]
    assert all(m["status"] == "geometry_passed" for m in manifests)
    assert all(m["checks"]["assembly"] == "not_checked" for m in manifests)
