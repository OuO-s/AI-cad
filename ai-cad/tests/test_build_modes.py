"""CLI 草稿、表达式与失败清单的集成验收。"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_cli(tmp_path, ir, *flags):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(ir), encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/build_ir.py"), str(path),
                             "--out", str(tmp_path / "out"), *flags], capture_output=True,
                            text=True, encoding="utf-8", timeout=120)
    manifests = list((tmp_path / "out").glob("*/run.json"))
    return result, json.loads(manifests[0].read_text(encoding="utf-8")) if manifests else None


def box():
    return {"version": "1.0", "meta": {"name": "mode_test", "units": "mm"},
            "parameters": {"base": {"value": 4}, "height": {"expression": "base+2"}},
            "features": [{"id": "box", "type": "extrude", "mode": "new",
                          "distance": {"param": "height"},
                          "profile": {"shape": "rectangle", "length": 10, "width": 10}},
                         {"id": "round", "type": "fillet", "target": "box", "radius": 1}]}


def test_draft_omits_fillet_and_resolves_dimensions(tmp_path):
    result, manifest = run_cli(tmp_path, box(), "--mode", "draft")
    assert result.returncode == 0, result.stdout + result.stderr
    assert manifest["status"] == "draft"
    assert abs(manifest["metrics"]["volume"] - 600) < 1e-6
    assert manifest["checks"]["assembly"] == "not_checked"


def test_failed_build_has_no_deliverable_artifacts(tmp_path):
    result, manifest = run_cli(tmp_path, box(), "--expected-solids", "2")
    assert result.returncode != 0
    assert manifest["status"] == "failed"
    assert manifest["artifacts"] == []
    assert not list((tmp_path / "out").glob("*/*.step"))


def test_name_cannot_escape_output_directory(tmp_path):
    ir = box()
    ir["meta"]["name"] = "../escape"
    result, manifest = run_cli(tmp_path, ir)
    assert result.returncode != 0 and manifest is None
