import adsk.core, adsk.fusion, json, os

def run(context):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    out = r"D:\AI\project\Company\AImodeling\ai-cad\output\go2_ac1_mesh.stl"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    # Try exporting the design's geometry (mesh) as STL
    export_mgr = design.exportManager
    opts = export_mgr.createSTLExportOptions(root, out)
    opts.sendToPrintUtility = False
    res = export_mgr.execute(opts)
    print("__JSON__" + json.dumps({"exported": res, "path": out, "exists": os.path.exists(out), "size": os.path.getsize(out) if os.path.exists(out) else 0}))
