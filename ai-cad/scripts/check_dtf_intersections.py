# -*- coding: utf-8 -*-
"""检查装配体中实体两两之间是否存在体积相交（穿模）。
bbox 严格分离的对直接跳过；其余用 BRepAlgoAPI_Common 求交并量体积。"""
import itertools
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp

r = STEPControl_Reader()
assert r.ReadFile("output/steam_turtle_tea_furnace_ap242.step") == IFSelect_RetDone
r.TransferRoots()
shape = r.OneShape()

solids = []
e = TopExp_Explorer(shape, TopAbs_SOLID)
while e.More():
    s = TopoDS.Solid_s(e.Current())
    bb = Bnd_Box(); BRepBndLib.Add_s(s, bb)
    solids.append((s, bb.Get()))
    e.Next()
print("solids:", len(solids))

def gap_overlaps(a, b, tol=1e-7):
    ax0, ay0, az0, ax1, ay1, az1 = a
    bx0, by0, bz0, bx1, by1, bz1 = b
    # 严格分离则无交（允许面接触：用开区间判定）
    if ax1 <= bx0 + tol or bx1 <= ax0 + tol: return False
    if ay1 <= by0 + tol or by1 <= ay0 + tol: return False
    if az1 <= bz0 + tol or bz1 <= az0 + tol: return False
    return True

bad = 0
checked = 0
for (sa, ba), (sb, bb2) in itertools.combinations(solids, 2):
    if not gap_overlaps(ba, bb2):
        continue
    checked += 1
    common = BRepAlgoAPI_Common(sa, sb)
    if common.IsDone():
        res = common.Shape()
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(res, props)
        v = props.Mass()
        if v > 1.0:  # mm^3，>1mm^3 视为实际穿模
            bad += 1
            print("INTERSECTION vol=%.1f mm^3  bboxA=%s bboxB=%s" % (v, tuple(round(x) for x in ba), tuple(round(x) for x in bb2)))
print("bbox-overlap pairs checked:", checked, " real intersections:", bad)
