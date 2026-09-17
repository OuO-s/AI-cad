import adsk.core, adsk.fusion, json

def run(context):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    step_path = r"D:\AI\project\Company\AImodeling\ai-cad\output\go2_ac1_arm_adapter.step"
    opts = app.importManager.createSTEPImportOptions(step_path)
    ok = app.importManager.importToTarget(opts, root)

    bodies = []
    for f in root.features:
        fb = getattr(f, "bodies", None)
        if fb:
            for b in fb:
                bodies.append(b)
    out = {"imported": bool(ok), "feature_bodies": []}
    for b in bodies:
        bb = b.boundingBox
        out["feature_bodies"].append({
            "name": b.name,
            "bbox": [round(bb.minPoint.x,3), round(bb.minPoint.y,3), round(bb.minPoint.z,3),
                     round(bb.maxPoint.x,3), round(bb.maxPoint.y,3), round(bb.maxPoint.z,3)],
        })
    for m in root.meshBodies:
        bb = m.boundingBox
        out["mesh_bbox"] = [round(bb.minPoint.x,3), round(bb.minPoint.y,3), round(bb.minPoint.z,3),
                            round(bb.maxPoint.x,3), round(bb.maxPoint.y,3), round(bb.maxPoint.z,3)]
    print("__JSON__" + json.dumps(out))
