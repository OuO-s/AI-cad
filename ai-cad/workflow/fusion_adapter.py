"""在 Fusion 内执行；由 fusion_rpc.ps1 与 plan.py 拼接加载。

首版写操作限根组件平面上的圆孔；读取支持组件实例。
不静默把实例坐标当作根坐标，不猜测孔深或切削方向。
"""

import json
import math
import uuid
import adsk.core
import adsk.fusion

GROUP = "ai_cad_workflow_v1"


def point_mm(p):
    return [round(p.x * 10, 6), round(p.y * 10, 6), round(p.z * 10, 6)]


def vector(v):
    return [v.x, v.y, v.z]


def context_design():
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        raise ValueError("当前文档不是 Fusion Design")
    return app, design


def resolve(design, token, cls):
    matches = [x for x in design.findEntityByToken(token) if cls.cast(x)]
    if len(matches) != 1:
        raise ValueError("对象引用失效或不唯一，请重新选择")
    return cls.cast(matches[0])


def describe(entity):
    row = {"type": entity.objectType}
    if hasattr(entity, "entityToken"):
        row["token"] = entity.entityToken
    if hasattr(entity, "name"):
        row["name"] = entity.name
    occ = getattr(entity, "assemblyContext", None)
    if occ:
        row["occurrence"] = occ.fullPathName
        row["transform_cm"] = list(occ.transform2.asArray())
    body = adsk.fusion.BRepBody.cast(entity)
    face = adsk.fusion.BRepFace.cast(entity)
    if face:
        body = face.body
    if body:
        row["body_token"] = body.entityToken
        row["bounds_mm"] = [point_mm(body.boundingBox.minPoint), point_mm(body.boundingBox.maxPoint)]
    return row


def read_selection():
    app, design = context_design()
    selected = app.userInterface.activeSelections
    return {"document": app.activeDocument.name, "units": "mm",
            "selection": [describe(selected.item(i).entity) for i in range(selected.count)]}


def sketch_snapshot(sketch):
    circles = []
    for c in sketch.sketchCurves.sketchCircles:
        p = c.centerSketchPoint.geometry
        circles.append({"center_mm": point_mm(p), "diameter_mm": round(c.radius * 20, 6),
                        "construction": c.isConstruction, "reference": c.isReference})
    lines = []
    for line in sketch.sketchCurves.sketchLines:
        lines.append([point_mm(line.startSketchPoint.geometry), point_mm(line.endSketchPoint.geometry)])
    circles.sort(key=lambda x: json.dumps(x, sort_keys=True))
    lines.sort()
    return {"circles": circles, "lines": lines,
            "origin_mm": point_mm(sketch.origin), "x_direction": vector(sketch.xDirection),
            "y_direction": vector(sketch.yDirection),
            "curve_count": sketch.sketchCurves.count}


def read_annotations(token=None):
    app, design = context_design()
    if token:
        sketches = [resolve(design, token, adsk.fusion.Sketch)]
    else:
        # 优先用户选中的草图，否则只读取可见草图。
        selected = app.userInterface.activeSelections
        sketches = [adsk.fusion.Sketch.cast(selected.item(i).entity) for i in range(selected.count)]
        sketches = [s for s in sketches if s]
        if not sketches:
            sketches = [s for c in design.allComponents for s in c.sketches if s.isVisible]
    return {"document": app.activeDocument.name, "units": "mm", "sketches": [
        {**describe(s), **sketch_snapshot(s), "dimensions": [
            {"type": d.objectType, "expression": d.parameter.expression}
            for d in s.sketchDimensions]} for s in sketches]}


def body_snapshot(body):
    # 对受影响实体作局部快照；不扫描机械狗整机。
    return {"bounds": [point_mm(body.boundingBox.minPoint), point_mm(body.boundingBox.maxPoint)],
            "volume_cm3": round(body.volume, 9), "faces": body.faces.count,
            "vertices": sorted(point_mm(v.geometry) for v in body.vertices),
            "edge_lengths_cm": sorted(round(e.length, 9) for e in body.edges)}


def target_context(design, face):
    """返回定义空间对象；共享组件定义不能按单一实例安全修改。"""
    occurrence = face.assemblyContext
    if not occurrence:
        if face.body.parentComponent != design.rootComponent:
            raise ValueError("非根组件原生面缺少装配实例上下文，请从装配中选择实例面")
        return face, face.body, face.body.parentComponent, None
    native_face = face.nativeObject
    if not native_face:
        raise ValueError("无法取得实例面的原生定义，请重新选择")
    component = native_face.body.parentComponent
    occurrences = design.rootComponent.allOccurrencesByComponent(component)
    if occurrences.count != 1:
        raise ValueError("目标组件定义被多个实例共享；为防止同时修改其他实例，请先创建独立组件或明确全实例修改")
    return native_face, native_face.body, component, occurrence


def occurrence_snapshot(occurrence):
    if not occurrence:
        return None
    return {"token": occurrence.entityToken, "path": occurrence.fullPathName,
            "transform_cm": [round(x, 12) for x in occurrence.transform2.asArray()]}


def load_task(design, task_id):
    attr = design.rootComponent.attributes.itemByName(GROUP, task_id)
    if not attr:
        raise ValueError("当前文档中没有此任务")
    return json.loads(attr.value)


def save_task(design, task_id, task):
    design.rootComponent.attributes.add(GROUP, task_id, json.dumps(task, ensure_ascii=False))


def task_snapshot(design, task):
    body = resolve(design, task["body_token"], adsk.fusion.BRepBody)
    sketch = resolve(design, task["sketch_token"], adsk.fusion.Sketch)
    occurrence = None
    if task.get("occurrence_token"):
        occurrence = resolve(design, task["occurrence_token"], adsk.fusion.Occurrence)
        if occurrence_snapshot(occurrence) != task["occurrence"]:
            raise ValueError("目标组件实例路径或变换已变化，请重新预览")
        if design.rootComponent.allOccurrencesByComponent(body.parentComponent).count != 1:
            raise ValueError("确认后出现了共享组件实例，请重新确定修改范围")
    return body, sketch, {"body": body_snapshot(body), "sketch": sketch_snapshot(sketch),
                          "occurrence": occurrence_snapshot(occurrence)}


def machining_profiles(sketch):
    # 面上草图会自动投影边界，不能把面外轮廓一起拉伸切除。
    selected = []
    for profile in sketch.profiles:
        if profile.profileLoops.count != 1:
            continue
        curves = profile.profileLoops.item(0).profileCurves
        if curves.count != 1:
            continue
        entity = curves.item(0).sketchEntity
        circle = adsk.fusion.SketchCircle.cast(entity)
        if circle and not circle.isReference and not circle.isConstruction and circle.attributes.itemByName(GROUP, "operation_id"):
            selected.append(profile)
    return selected


def preview_change(plan):
    validate_plan(plan)
    app, design = context_design()
    face = resolve(design, plan["target"]["face_token"], adsk.fusion.BRepFace)
    if face.geometry.surfaceType != adsk.core.SurfaceTypes.PlaneSurfaceType:
        raise ValueError("需选择平面以定义标注坐标系")
    if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
        raise ValueError("当前写操作需要参数化设计，请先明确是否转换设计类型")
    native_face, body, component, occurrence = target_context(design, face)
    task_id = uuid.uuid4().hex
    sketch = component.sketches.add(native_face)
    sketch.name = "AI_待确认_" + task_id[:8]
    for op in plan["operations"]:
        p = adsk.core.Point3D.create(op["x"] / 10, op["y"] / 10, 0)
        if op["type"] == "circle":
            curve = sketch.sketchCurves.sketchCircles.addByCenterRadius(p, op["diameter"] / 20)
            curve.isConstruction = op["role"] == "locator"
            curve.attributes.add(GROUP, "operation_id", op["id"])
        else:
            p0 = adsk.core.Point3D.create((op["x"] - op["width"] / 2) / 10,
                                        (op["y"] - op["height"] / 2) / 10, 0)
            p1 = adsk.core.Point3D.create((op["x"] + op["width"] / 2) / 10,
                                        (op["y"] + op["height"] / 2) / 10, 0)
            curves = sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
            for curve in curves:
                curve.isConstruction = op["role"] == "locator"
    task = {"status": "preview", "plan": plan, "body_token": body.entityToken,
            "sketch_token": sketch.entityToken, "document": app.activeDocument.name}
    task["reference"] = body_snapshot(body)
    if occurrence:
        task["occurrence_token"] = occurrence.entityToken
        task["occurrence"] = occurrence_snapshot(occurrence)
    save_task(design, task_id, task)
    return {"task_id": task_id, "status": "preview", "annotation": read_annotations(sketch.entityToken)}


def confirm_change(task_id, user_confirmed=False, depth_mm=None):
    app, design = context_design()
    task = load_task(design, task_id)
    if task["status"] not in ("preview", "confirmed"):
        raise ValueError("此任务已执行或状态不允许确认")
    if not user_confirmed:
        raise ValueError("请用户确认当前可见草图；不能自动确认")
    if isinstance(depth_mm, bool) or not isinstance(depth_mm, (float, int)) or not math.isfinite(depth_mm) or depth_mm == 0:
        raise ValueError("必须明确沿草图法向的有符号切削深度 depth_mm")
    body, sketch, snapshot = task_snapshot(design, task)
    if task["reference"] != snapshot["body"]:
        raise ValueError("参考实体已变化，请重新预览")
    if any(op["type"] != "circle" or op["role"] != "machining" for op in task["plan"]["operations"]):
        raise ValueError("首版自动执行仅支持加工圆孔；矩形与定位标记仅用于预览")
    editable = [c for c in sketch.sketchCurves if not c.isReference]
    if len(editable) != len(task["plan"]["operations"]):
        raise ValueError("草图曲线数量变化，请重新制定计划")
    operations = {op["id"]: op for op in task["plan"]["operations"]}
    updated = []
    for circle in sketch.sketchCurves.sketchCircles:
        if circle.isReference:
            continue
        attr = circle.attributes.itemByName(GROUP, "operation_id")
        if not attr or attr.value not in operations or circle.isConstruction or circle.isReference:
            raise ValueError("加工圆的角色或绑定已变化")
        p = circle.centerSketchPoint.geometry
        updated.append({**operations.pop(attr.value), "x": p.x * 10, "y": p.y * 10,
                        "diameter": circle.radius * 20, "source": "user"})
    if operations or len(machining_profiles(sketch)) != len(updated):
        raise ValueError("圆孔重叠、嵌套或轮廓不完整，请修正草图")
    task["plan"]["operations"] = updated
    task["plan"]["depth_mm"] = depth_mm
    task["receipt"] = confirm(task["plan"], snapshot, user_confirmed=True)
    task["status"] = "confirmed"
    save_task(design, task_id, task)
    return {"task_id": task_id, "status": "confirmed", "receipt": task["receipt"]}


def apply_confirmed_change(task_id):
    app, design = context_design()
    task = load_task(design, task_id)
    if task["status"] == "applied":
        return {"task_id": task_id, "status": "applied", "repeated": True}
    if task["status"] != "confirmed":
        raise ValueError("任务尚未确认")
    body, sketch, snapshot = task_snapshot(design, task)
    require_confirmation(task["plan"], snapshot, task["receipt"])
    profiles = adsk.core.ObjectCollection.create()
    for profile in machining_profiles(sketch):
        profiles.add(profile)
    before = body.volume
    task["status"] = "applying"
    save_task(design, task_id, task)
    extrudes = body.parentComponent.features.extrudeFeatures
    settings = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
    settings.participantBodies = [body]
    settings.setDistanceExtent(False, adsk.core.ValueInput.createByReal(task["plan"]["depth_mm"] / 10))
    feature = extrudes.add(settings)
    feature.name = "AI_已确认孔位_" + task_id[:8]
    if not body.isSolid or body.volume >= before or feature.bodies.count != 1:
        raise ValueError("切削结果异常，请检查方向和深度；不得自动重试")
    task["status"] = "applied"
    task["feature_token"] = feature.entityToken
    save_task(design, task_id, task)
    return {"task_id": task_id, "status": "applied", "feature_token": feature.entityToken,
            "checks": "切削体积和实体数已检查，装配干涉未检查"}


def preview_envelopes(request):
    """根装配坐标下的纯图形包络；不创建 BRep，不参与制造导出。"""
    app, design = context_design()
    if request.get("units") != "mm" or request.get("frame") != "assembly_world":
        raise ValueError("包络必须明确 units=mm、frame=assembly_world")
    envelopes = request.get("envelopes")
    if not isinstance(envelopes, list) or not envelopes or len(envelopes) > 100:
        raise ValueError("需提供 1～100 个包络")
    seen = set()
    for item in envelopes:
        label = item.get("id")
        if not isinstance(label, str) or not label or label in seen:
            raise ValueError("包络 id 必须非空且唯一")
        seen.add(label)
        bounds = item.get("bounds_mm")
        if not isinstance(bounds, list) or len(bounds) != 2 or any(not isinstance(p, list) or len(p) != 3 for p in bounds):
            raise ValueError("bounds_mm 必须是 [最小点, 最大点]")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for p in bounds for x in p):
            raise ValueError("包络坐标必须是有限数值")
        if any(bounds[1][i] <= bounds[0][i] for i in range(3)):
            raise ValueError("包络三轴必须有正长度")
        if set(item) != {"id", "bounds_mm"}:
            raise ValueError("不支持的包络字段，不静默忽略旋转或定位信息")
    task_id = uuid.uuid4().hex
    task = {"status": "creating", "kind": "graphics_envelopes", "graphics_id": GROUP + ":" + task_id,
            "envelopes": envelopes, "frame": "assembly_world", "manufacturing": False}
    save_task(design, task_id, task)
    group = design.rootComponent.customGraphicsGroups.add()
    group.id = task["graphics_id"]
    # 顶点编号 x*4+y*2+z，向外三角面。仅用于显示，不能冒充精确实体。
    indices = [0,1,3, 0,3,2, 4,6,7, 4,7,5, 0,4,5, 0,5,1,
               2,3,7, 2,7,6, 0,2,6, 0,6,4, 1,5,7, 1,7,3]
    for item in envelopes:
        lo, hi = item["bounds_mm"]
        coordinates = [v / 10 for x in (lo[0],hi[0]) for y in (lo[1],hi[1])
                       for z in (lo[2],hi[2]) for v in (x,y,z)]
        mesh = group.addMesh(adsk.fusion.CustomGraphicsCoordinates.create(coordinates), indices, [], [])
        mesh.id = item["id"]
        mesh.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(50, 160, 240, 255))
        if not mesh.setOpacity(0.3, True):
            raise ValueError("设置半透明失败；请按任务 id 清理图形，不重试实体操作")
    task["status"] = "preview"
    save_task(design, task_id, task)
    app.activeViewport.refresh()
    return {"task_id": task_id, "status": "preview", "manufacturing": False,
            "checks": "仅检查单位、坐标和正尺寸；位置、干涉未验证", "envelopes": envelopes}


def clear_envelopes(task_id):
    app, design = context_design()
    task = load_task(design, task_id)
    if task.get("kind") != "graphics_envelopes":
        raise ValueError("只能清理本工具创建的包络任务")
    groups = design.rootComponent.customGraphicsGroups
    for i in range(groups.count - 1, -1, -1):
        group = groups.item(i)
        if group.id == task["graphics_id"]:
            group.deleteMe()
    task["status"] = "cleared"
    save_task(design, task_id, task)
    app.activeViewport.refresh()
    return {"task_id": task_id, "status": "cleared"}


def dispatch(request):
    action = request["action"]
    if action == "read_selection":
        return read_selection()
    if action == "read_annotations":
        return read_annotations(request.get("sketch_token"))
    if action == "preview_change":
        return preview_change(request["plan"])
    if action == "preview_envelopes":
        return preview_envelopes(request)
    if action == "clear_envelopes":
        return clear_envelopes(request["task_id"])
    if action == "confirm_change":
        return confirm_change(request["task_id"], request.get("user_confirmed", False), request.get("depth_mm"))
    if action == "apply_confirmed_change":
        return apply_confirmed_change(request["task_id"])
    if action == "status":
        _, design = context_design()
        return load_task(design, request["task_id"])
    raise ValueError("未知操作")
