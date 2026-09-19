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
        print(json.dumps({"smoke": "passed", "tests": ["preview_no_body_change",
                         "stale_confirmation_rejected", "edited_radius_applied", "idempotent_apply"]}))
    finally:
        scratch.close(False)
        if previous and previous.isValid:
            previous.activate()
