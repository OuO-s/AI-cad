import adsk.core, adsk.fusion, json

def run(context):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    names = [o.name for o in root.occurrences]
    for occ in list(root.occurrences):
        occ.deleteMe()
    print("__JSON__" + json.dumps({"deleted": names, "remaining": [o.name for o in root.occurrences],
                                   "meshes": [m.name for m in root.meshBodies]}, ensure_ascii=False))
