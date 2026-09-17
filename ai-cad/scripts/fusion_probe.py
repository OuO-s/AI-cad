import adsk.core, adsk.fusion, json

def run(context):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    out = {"occurrences": [], "timeline_groups": []}
    for occ in root.occurrences:
        bb = occ.boundingBox
        nb = 0
        for f in occ.component.features:
            fb = getattr(f, "bodies", None)
            if fb:
                nb += fb.count
        out["occurrences"].append({
            "name": occ.component.name,
            "bodies": nb,
            "bbox": [round(bb.minPoint.x,3), round(bb.minPoint.y,3), round(bb.minPoint.z,3),
                     round(bb.maxPoint.x,3), round(bb.maxPoint.y,3), round(bb.maxPoint.z,3)],
        })
    print("__JSON__" + json.dumps(out))
