"""Fusion 实机验收脚本，拼接 plan.py 和 fusion_adapter.py 后运行。

仅在新建临时文档里测试，关闭时不保存，并恢复原活动文档。
"""

def run(context):
    app = adsk.core.Application.get()
    previous = app.activeDocument
    scratch = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        root = design.rootComponent
        # 图形包络必须可清理，且绝不成为制造实体。
        other_graphics = root.customGraphicsGroups.add()
        other_graphics.id = "user_owned_graphics"
        envelope = preview_envelopes({"units": "mm", "frame": "assembly_world",
                                     "envelopes": [{"id": "A", "bounds_mm": [[0,0,0],[110,110,70]]}]})
        assert root.bRepBodies.count == 0
        assert root.customGraphicsGroups.count == 2
        clear_envelopes(envelope["task_id"])
        clear_envelopes(envelope["task_id"])
        assert root.customGraphicsGroups.count == 1
        assert other_graphics.isValid
        sketch = root.sketches.add(root.xYConstructionPlane)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(
            adsk.core.Point3D.create(-2.5, -2.5, 0), adsk.core.Point3D.create(2.5, 2.5, 0))
        settings = root.features.extrudeFeatures.createInput(
            sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        settings.setDistanceExtent(False, adsk.core.ValueInput.createByReal(1))
        body = root.features.extrudeFeatures.add(settings).bodies.item(0)
        face = max((f for f in body.faces), key=lambda f: f.pointOnFace.z)
        volume = body.volume
        plan = {"version": 1, "mode": "preview", "units": "mm",
                "target": {"face_token": face.entityToken}, "invariants": [],
                "operations": [{"id": "H1", "type": "circle", "role": "machining",
                                "source": "user", "x": 0, "y": 0, "diameter": 4}]}
        preview = preview_change(plan)
        task_id = preview["task_id"]
        assert abs(body.volume - volume) < 1e-8
        task = load_task(design, task_id)
        drawn = resolve(design, task["sketch_token"], adsk.fusion.Sketch)
        depth = -2 if drawn.xDirection.crossProduct(drawn.yDirection).z > 0 else 2
        confirm_change(task_id, True, depth)
        drawn.sketchCurves.sketchCircles.item(0).radius = 0.3
        task = load_task(design, task_id)
        _, _, changed = task_snapshot(design, task)
        rejected = False
        try:
            require_confirmation(task["plan"], changed, task["receipt"])
        except ValueError:
            rejected = True
        assert rejected, "草图编辑后旧确认必须失效"
        confirm_change(task_id, True, depth)
        result = apply_confirmed_change(task_id)
        assert result["status"] == "applied"
        assert abs((volume - body.volume) - math.pi * 0.3 ** 2 * 0.2) < 1e-6
        again = apply_confirmed_change(task_id)
        assert again["repeated"]
        # 旋转、平移的唯一组件实例可在定义空间安全修改；新增共享实例后必须拒绝。
        transform = adsk.core.Matrix3D.create()
        transform.setToRotation(math.pi / 4, adsk.core.Vector3D.create(0, 0, 1), adsk.core.Point3D.create(0, 0, 0))
        transform.translation = adsk.core.Vector3D.create(8, 3, 2)
        occurrence = root.occurrences.addNewComponent(transform)
        component = occurrence.component
        local_sketch = component.sketches.add(component.xYConstructionPlane)
        local_sketch.sketchCurves.sketchLines.addTwoPointRectangle(
            adsk.core.Point3D.create(-1, -1, 0), adsk.core.Point3D.create(1, 1, 0))
        local_input = component.features.extrudeFeatures.createInput(
            local_sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        local_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(.5))
        local_body = component.features.extrudeFeatures.add(local_input).bodies.item(0)
        proxy_body = occurrence.bRepBodies.item(0)
        proxy_face = max((f for f in proxy_body.faces), key=lambda f: f.pointOnFace.z)
        instance_plan = {"version": 1, "mode": "preview", "units": "mm",
                         "target": {"face_token": proxy_face.entityToken}, "invariants": [],
                         "operations": [{"id": "I1", "type": "circle", "role": "machining",
                                         "source": "user", "x": 0, "y": 0, "diameter": 3}]}
        instance_preview = preview_change(instance_plan)
        instance_task = load_task(design, instance_preview["task_id"])
        instance_sketch = resolve(design, instance_task["sketch_token"], adsk.fusion.Sketch)
        instance_depth = -2 if instance_sketch.xDirection.crossProduct(instance_sketch.yDirection).z > 0 else 2
        confirm_change(instance_preview["task_id"], True, instance_depth)
        instance_volume = local_body.volume
        apply_confirmed_change(instance_preview["task_id"])
        assert local_body.volume < instance_volume
        second = root.occurrences.addExistingComponent(component, adsk.core.Matrix3D.create())
        rejected_shared = False
        try:
            preview_change(instance_plan)
        except ValueError:
            rejected_shared = True
        assert rejected_shared
        second.deleteMe()
        print(json.dumps({"smoke": "passed", "tests": ["preview_no_body_change",
                         "stale_confirmation_rejected", "edited_radius_applied", "idempotent_apply",
                         "graphics_not_manufacturing", "cleanup_preserves_user_graphics",
                         "rotated_unique_instance_applied", "shared_component_rejected"]}))
    finally:
        scratch.close(False)
        if previous and previous.isValid:
            previous.activate()
