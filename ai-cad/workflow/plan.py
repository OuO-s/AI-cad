"""不依赖 CAD 内核的计划校验和确认协议。"""

import copy
import hashlib
import json
import math


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def questions(plan):
    """只返回缺失项；已指定的偏好不重复询问。"""
    prompts = []
    for key, question in (
        ("mode", "本轮需要位置预览、快速样式还是最终交付？"),
        ("target", "参考哪个文档、组件或当前选中的对象？"),
        ("invariants", "哪些尺寸、安装面或原始零件必须保持不变？"),
    ):
        if key not in plan:
            prompts.append(question)
    prompts.extend(plan.get("unresolved", []))
    return prompts


def validate_plan(plan):
    if plan.get("version") != 1 or plan.get("units") != "mm":
        raise ValueError("计划版本须为 1，单位须为 mm")
    if plan.get("mode") not in ("preview", "draft", "final"):
        raise ValueError("mode 必须为 preview/draft/final")
    if not isinstance(plan.get("target"), dict) or not plan["target"]:
        raise ValueError("必须指定目标对象")
    if not isinstance(plan.get("invariants"), list):
        raise ValueError("必须列明固定约束（没有时显式用空列表）")
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("至少需要一个操作")
    ids = set()
    for op in operations:
        if not isinstance(op.get("id"), str) or not op["id"] or op["id"] in ids:
            raise ValueError("操作 id 必须唯一且非空")
        ids.add(op["id"])
        if op.get("type") not in ("circle", "rectangle"):
            raise ValueError("当前预览支持 circle/rectangle")
        if op.get("role") not in ("locator", "machining"):
            raise ValueError("必须区分 locator 圈选标记和 machining 加工轮廓")
        if op.get("source") not in ("user", "measured", "proposed"):
            raise ValueError("必须注明尺寸来源")
        fields = ("diameter",) if op["type"] == "circle" else ("width", "height")
        for key in ("x", "y") + fields:
            n = op.get(key)
            if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n):
                raise ValueError(f"{op['id']}.{key} 必须为有限数值")
            if key in fields and n <= 0:
                raise ValueError(f"{key} 必须大于零")
    return plan


def confirm(plan, snapshot, *, user_confirmed=False):
    validate_plan(plan)
    if not user_confirmed or plan.get("unresolved"):
        raise ValueError("必须获得用户确认并解决待定项")
    return {"plan_hash": fingerprint(plan), "snapshot_hash": fingerprint(snapshot)}


def require_confirmation(plan, snapshot, receipt):
    validate_plan(plan)
    if plan.get("unresolved") or receipt != {
        "plan_hash": fingerprint(plan), "snapshot_hash": fingerprint(snapshot)
    }:
        raise ValueError("计划或预览已变化，需重新确认")


def draft_ir(ir):
    """快速样式仅省略圆角/倒角，目标链重定向；不移动参考或修改孔位。"""
    result = copy.deepcopy(ir)
    aliases = {}
    features = []
    for feature in result["features"]:
        for key in ("target",):
            if key in feature:
                feature[key] = aliases.get(feature[key], feature[key])
        for key in ("operands", "depends_on"):
            if key in feature:
                feature[key] = [aliases.get(x, x) for x in feature[key]]
        if feature["type"] in ("fillet", "chamfer"):
            aliases[feature["id"]] = feature["target"]
        else:
            features.append(feature)
    result["features"] = features
    return result
