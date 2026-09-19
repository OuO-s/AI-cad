"""需求歧义、确认失效、快速模式及依赖表达式回归。"""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workflow.plan import validate_plan, questions, confirm, require_confirmation, draft_ir
from workflow.expressions import resolve_parameters


def plan():
    return {"version": 1, "units": "mm", "mode": "preview", "target": {"face_token": "face"},
            "invariants": ["参考件不修改"], "operations": [
                {"id": "H1", "type": "circle", "role": "machining", "source": "user",
                 "x": 10, "y": 20, "diameter": 4.9}]}


def test_missing_questions_only():
    assert len(questions({})) == 3
    assert questions(plan()) == []
    assert questions({**plan(), "unresolved": ["孔深？"]}) == ["孔深？"]


def test_confirmation_is_explicit_and_bound_to_geometry():
    p, snapshot = plan(), {"body": "original", "circle": [10, 20, 4.9]}
    with pytest.raises(ValueError):
        confirm(p, snapshot)
    receipt = confirm(p, snapshot, user_confirmed=True)
    require_confirmation(p, snapshot, receipt)
    with pytest.raises(ValueError):
        require_confirmation(p, {**snapshot, "circle": [11.5, 20, 4.9]}, receipt)
    p["operations"][0]["diameter"] = 6
    with pytest.raises(ValueError):
        require_confirmation(p, snapshot, receipt)


def test_unresolved_cannot_confirm():
    with pytest.raises(ValueError):
        confirm({**plan(), "unresolved": ["位置"]}, {}, user_confirmed=True)


@pytest.mark.parametrize("patch", [{"role": "unknown"}, {"diameter": -1}, {"x": float("nan")},
                                  {"source": "guessed"}, {"diameter": True}])
def test_reject_ambiguous_or_bad_operation(patch):
    p = plan()
    p["operations"][0].update(patch)
    with pytest.raises(ValueError):
        validate_plan(p)


def test_draft_relinks_and_preserves_original():
    ir = {"features": [{"id": "base", "type": "extrude"},
                       {"id": "round", "type": "fillet", "target": "base"},
                       {"id": "bevel", "type": "chamfer", "target": "round"},
                       {"id": "hole", "type": "hole", "target": "bevel", "diameter": 4.9}]}
    original = copy.deepcopy(ir)
    draft = draft_ir(ir)
    assert [f["id"] for f in draft["features"]] == ["base", "hole"]
    assert draft["features"][1]["target"] == "base"
    assert ir == original


def test_derived_dimensions_follow_dependencies():
    resolved = resolve_parameters({"lid_top": {"expression": "lid_bottom + thickness"},
                                   "thickness": {"value": 6}, "lid_bottom": {"value": 98}})
    assert resolved["lid_top"]["value"] == 104
    assert resolved["lid_bottom"]["value"] == 98


@pytest.mark.parametrize("expression", ["__import__('os')", "(1).__class__", "2**100", "1/0", "missing+1", "a+1"])
def test_expression_rejects_code_and_cycles(expression):
    with pytest.raises((ValueError, ZeroDivisionError)):
        resolve_parameters({"a": {"expression": expression}})


def test_parameter_bounds():
    with pytest.raises(ValueError):
        resolve_parameters({"a": {"expression": "2*3", "max": 5}})
