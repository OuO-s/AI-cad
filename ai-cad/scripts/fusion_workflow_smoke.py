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
        # 命名长度参数增量修改：预览不改几何，旧确认失效，固定底面保持不动。
        height_parameter = design.userParameters.add(
            "workflow_height", adsk.core.ValueInput.createByString("5 mm"), "mm", "workflow smoke")
        fixed_parameter = design.userParameters.add(
            "workflow_width", adsk.core.ValueInput.createByString("20 mm"), "mm", "workflow smoke")
        parameter_sketch = root.sketches.add(root.xYConstructionPlane)
        parameter_sketch.sketchCurves.sketchLines.addTwoPointRectangle(
            adsk.core.Point3D.create(9, -1, 0), adsk.core.Point3D.create(11, 1, 0))
        parameter_input = root.features.extrudeFeatures.createInput(
            parameter_sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        parameter_input.setDistanceExtent(False, adsk.core.ValueInput.createByString("workflow_height"))
        parameter_body = root.features.extrudeFeatures.add(parameter_input).bodies.item(0)
        parameter_plan = {"version": 1, "units": "mm", "scope": "document",
                          "changes": [{"name": "workflow_height", "value_mm": 7}],
                          "fixed_parameters": ["workflow_width"], "bodies": [parameter_body.entityToken],
                          "body_constraints": [{"body_token": parameter_body.entityToken,
                                                "preserve": ["min_x", "max_x", "min_y", "max_y", "min_z"],
                                                "tolerance_mm": 0.0001}]}
        parameter_preview = preview_parameter_change(parameter_plan)
        before_parameter = body_snapshot(parameter_body)
        assert body_snapshot(parameter_body) == before_parameter
        height_parameter.expression = "6 mm"
        design.computeAll()
        stale_rejected = False
        try:
            confirm_parameter_change(parameter_preview["task_id"], True)
        except ValueError:
            stale_rejected = True
        assert stale_rejected
        height_parameter.expression = "5 mm"
        design.computeAll()
        parameter_preview = preview_parameter_change(parameter_plan)
        confirm_parameter_change(parameter_preview["task_id"], True)
        parameter_result = apply_parameter_change(parameter_preview["task_id"])
        assert parameter_result["status"] == "applied"
        assert abs(parameter_body.boundingBox.maxPoint.z - .7) < 1e-8
        assert fixed_parameter.expression == "20 mm"
        assert apply_parameter_change(parameter_preview["task_id"])["repeated"]
        rollback_plan = dict(parameter_plan)
        rollback_plan["changes"] = [{"name": "workflow_height", "value_mm": 9}]
        rollback_plan["body_constraints"] = [{"body_token": parameter_body.entityToken,
                                               "preserve": ["max_z"], "tolerance_mm": 0.0001}]
        rollback_preview = preview_parameter_change(rollback_plan)
        confirm_parameter_change(rollback_preview["task_id"], True)
        invariant_rejected = False
        try:
            apply_parameter_change(rollback_preview["task_id"])
        except ValueError:
            invariant_rejected = True
        assert invariant_rejected
        assert abs(height_parameter.value - .7) < 1e-8
        assert load_task(design, rollback_preview["task_id"])["status"] == "failed_rolled_back"
        recovery_plan = dict(parameter_plan)
        recovery_plan["changes"] = [{"name": "workflow_height", "value_mm": 8}]
        recovery_preview = preview_parameter_change(recovery_plan)
        confirm_parameter_change(recovery_preview["task_id"], True)
        recovery_task = load_task(design, recovery_preview["task_id"])
        recovery_task["old_expressions"] = {"workflow_height": height_parameter.expression}
        recovery_task["status"] = "applying"
        save_task(design, recovery_preview["task_id"], recovery_task)
        height_parameter.expression = "8 mm"
        design.computeAll()
        recover_parameter_change(recovery_preview["task_id"])
        assert abs(height_parameter.value - .7) < 1e-8
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
                         "rotated_unique_instance_applied", "shared_component_rejected",
                         "parameter_preview_stale_rejected", "parameter_invariant_applied",
                         "parameter_invariant_rollback", "interrupted_parameter_recovery"]}))
    finally:
        scratch.close(False)
        if previous and previous.isValid:
            previous.activate()
