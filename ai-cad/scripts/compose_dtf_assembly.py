# -*- coding: utf-8 -*-
"""合成“蒸汽朋克机械龙龟茶炉” STEP AP242 装配体。

- 读取 ai-cad 管线产出的各零件 STEP（每个 = 单个水密 B-rep 实体）
- 按 XCAF 产品结构建立装配树（命名层级 + 多实例引用）
- 按零件赋简单显示颜色（古铜/墨绿/米白/朱红/深胡桃木/铸铁灰）
- 以 AP242DIS/IS、单位=米 导出（1 单位 = 1 m，Z 向上）
"""
import math
from pathlib import Path

from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorType
from OCP.TDataStd import TDataStd_Name
from OCP.TCollection import TCollection_ExtendedString
from OCP.TopLoc import TopLoc_Location
from OCP.gp import gp_Trsf, gp_Vec, gp_Pnt, gp_Dir, gp_Ax1, gp_Ax2
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_StepModelType
from OCP.Interface import Interface_Static
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"

# ---------- 颜色 ----------
COLORS = {
    "brass":  (0.72, 0.56, 0.34),   # 古铜(黄铜)
    "patina": (0.13, 0.35, 0.28),   # 墨绿(青瓦/壳)
    "rice":   (0.93, 0.91, 0.84),   # 米白(纸窗/镜片)
    "vermil": (0.70, 0.15, 0.12),   # 朱红(门/灯笼)
    "walnut": (0.36, 0.22, 0.13),   # 深胡桃木
    "iron":   (0.36, 0.38, 0.41),   # 铸铁灰
}

def read_step(path: Path):
    r = STEPControl_Reader()
    assert r.ReadFile(str(path)) == IFSelect_RetDone, f"read fail {path}"
    r.TransferRoots()
    return r.OneShape()

def trsf_translate(x, y, z):
    t = gp_Trsf(); t.SetTranslation(gp_Vec(x, y, z)); return t

def trsf_rx(deg):
    t = gp_Trsf(); t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), math.radians(deg)); return t

def trsf_rz(deg):
    t = gp_Trsf(); t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), math.radians(deg)); return t

def mirrored_y(shape):
    """绕 XZ 平面镜像 (y -> -y)，生成独立几何变体。"""
    t = gp_Trsf(); t.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 1, 0)))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()

def compose(t1: gp_Trsf, t2: gp_Trsf) -> gp_Trsf:
    t = gp_Trsf(); t = t1.Multiplied(t2); return t

# ---------- 装配文档 ----------
app = XCAFApp_Application.GetApplication_s()
doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

def set_name(label, name):
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))

_part_cache = {}
def part(file_stem, color, display_name, mirror_y=False):
    """注册一个零件（引用几何 + 名称 + 颜色），返回其 label。"""
    key = (file_stem, mirror_y)
    if key in _part_cache:
        return _part_cache[key]
    shape = read_step(OUT / f"{file_stem}.step")
    if mirror_y:
        shape = mirrored_y(shape)
    lbl = st.AddShape(shape, False)
    set_name(lbl, display_name)
    r, g, b = COLORS[color]
    ct.SetColor(lbl, Quantity_Color(r, g, b, Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorSurf)
    _part_cache[key] = lbl
    return lbl

def asm(parent_lbl, name):
    lbl = st.NewShape()
    set_name(lbl, name)
    st.AddComponent(parent_lbl, lbl, TopLoc_Location())
    return lbl

def place(asm_lbl, part_lbl, t: gp_Trsf):
    st.AddComponent(asm_lbl, part_lbl, TopLoc_Location(t))

# ---------- 根 ----------
root = st.NewShape()
set_name(root, "SteamTurtleTeaFurnace")

# ========== Body_Assembly 机体 ==========
body = asm(root, "Body_Assembly")
P_PLAT = part("dtf_01_body_platform", "iron", "Body_Platform")
place(body, P_PLAT, gp_Trsf())

head_asm = asm(body, "Head_Assembly")
P_HEAD = part("dtf_17_head", "iron", "Turtle_Head")
place(head_asm, P_HEAD, trsf_translate(1500, 0, 0))
P_SMOKE = part("dtf_16_smoke_pipe", "brass", "Head_SmokePipe")
place(head_asm, P_SMOKE, trsf_translate(1745, 0, 860))
P_GRING = part("dtf_18_goggle_ring", "brass", "Goggle_Ring")
P_GLENS = part("dtf_19_goggle_lens", "rice", "Goggle_Lens")
P_GBR = part("dtf_20_goggle_bridge", "brass", "Goggle_Bridge")
for sy in (1, -1):
    place(head_asm, P_GRING, trsf_translate(1870, 170 * sy, 740))
    place(head_asm, P_GLENS, trsf_translate(1896, 170 * sy, 740))
place(head_asm, P_GBR, trsf_translate(1890, 0, 780))

# ========== Shell_Assembly 龟壳 ==========
shell = asm(body, "Shell_Assembly")
P_DRUM = part("dtf_02_shell_drum", "patina", "Shell_Drum")
place(shell, P_DRUM, trsf_translate(-700, 0, 560))
P_HEX = part("dtf_03_hex_shell_plate", "brass", "HexShellPlate_Brass")
for k in range(6):
    th = math.radians(30 + 60 * k)
    t = compose(trsf_translate(-700 + 500 * math.cos(th), 500 * math.sin(th), 980), trsf_rz(math.degrees(th)))
    place(shell, P_HEX, t)
place(shell, P_HEX, trsf_translate(-700, 0, 980))
P_RIVET = part("dtf_04_rivet", "brass", "Rivet_Brass")
for k in range(12):
    th = math.radians(15 + 30 * k)
    place(shell, P_RIVET, trsf_translate(-700 + 830 * math.cos(th), 830 * math.sin(th), 980))
for yy in (-600, -300, 0, 300, 600):
    place(body, P_RIVET, trsf_translate(1385, yy, 560))
P_GEARL = part("dtf_05_gear_large", "brass", "Gear_Large_Brass")
place(shell, P_GEARL, compose(trsf_translate(-700, 965, 920), trsf_rx(90)))
place(shell, P_GEARL, compose(trsf_translate(-700, -965, 920), trsf_rx(-90)))
P_GEARS = part("dtf_06_gear_small", "iron", "Gear_Small_Iron")
place(body, P_GEARS, trsf_translate(250, 880, 560))
place(body, P_GEARS, trsf_translate(250, -880, 560))

# ========== TeaHouse_Assembly 龟背茶室 ==========
house = asm(root, "TeaHouse_Assembly")
P_FLOOR = part("dtf_07_house_floor", "walnut", "TeaHouse_Floor")
place(house, P_FLOOR, trsf_translate(800, 0, 560))
P_POST = part("dtf_08_house_post", "walnut", "TeaHouse_Post")
for px, py in ((300, 425), (300, -425), (1300, 425), (1300, -425)):
    place(house, P_POST, trsf_translate(px, py, 620))
P_WSIDE = part("dtf_09_house_wall_side", "walnut", "TeaHouse_Wall_Side")
place(house, P_WSIDE, trsf_translate(800, 455, 620))
place(house, P_WSIDE, trsf_translate(800, -455, 620))
P_WBACK = part("dtf_10_house_wall_back", "walnut", "TeaHouse_Wall_Back")
place(house, P_WBACK, compose(trsf_translate(300, 0, 620), trsf_rz(90)))
P_PAPER = part("dtf_11_paper_panel", "rice", "Shoji_PaperPanel")
for wx in (570, 1030):
    place(house, P_PAPER, trsf_translate(wx, 455, 1030))
    place(house, P_PAPER, trsf_translate(wx, -455, 1030))
place(house, P_PAPER, compose(trsf_translate(300, 0, 1030), trsf_rz(90)))
P_DOOR = part("dtf_12_shoji_door", "vermil", "Shoji_SlidingDoor_Vermilion")
place(house, P_DOOR, trsf_translate(1265, 0, 1010))
place(house, P_DOOR, trsf_translate(1220, 0, 1010))
P_LINTEL = part("dtf_31_house_lintel", "walnut", "TeaHouse_Lintel")
place(house, P_LINTEL, trsf_translate(1265, 0, 1400))
P_BOILER = part("dtf_32_boiler", "iron", "TeaFurnace_Boiler")
place(house, P_BOILER, trsf_translate(900, 0, 620))
P_CHIM = part("dtf_15_chimney", "brass", "Copper_Chimney")
place(house, P_CHIM, trsf_translate(550, -300, 620))
P_LANT = part("dtf_14_lantern", "vermil", "Red_Lantern")
place(house, P_LANT, trsf_translate(1200, 800, 560))
place(house, P_LANT, trsf_translate(1200, -800, 560))

# ----- Roof_Assembly 可开合屋顶（铰链轴 = X） -----
roof = asm(house, "Roof_Assembly_Openable_AxisX")
P_ROOFR = part("dtf_13_roof_half", "patina", "Roof_Half_Right_Tile")
P_ROOFL = part("dtf_13_roof_half", "patina", "Roof_Half_Left_Tile", mirror_y=True)
place(roof, P_ROOFR, trsf_translate(800, 0, 1440))
place(roof, P_ROOFL, trsf_translate(800, 0, 1440))
P_HINGE = part("dtf_30_ridge_hinge_rod", "brass", "Roof_RidgeHingeRod")
place(roof, P_HINGE, trsf_translate(230, 0, 1760))

# ========== 四条腿 ==========
P_LUP = part("dtf_21_leg_upper", "iron", "Leg_Upper")
P_LLOW = part("dtf_22_leg_lower", "iron", "Leg_Lower")
P_AXLE = part("dtf_23_joint_axle", "brass", "Joint_Axle_RotAxisY")
P_CYL = part("dtf_24_hydraulic_cylinder", "brass", "Hydraulic_Cylinder")
P_ROD = part("dtf_25_piston_rod", "iron", "Hydraulic_PistonRod")
P_BRK = part("dtf_26_hydraulic_bracket", "iron", "Hydraulic_Bracket")
P_CBASE = part("dtf_27_claw_base", "iron", "Claw_Base")
P_CPRONG = part("dtf_28_claw_prong", "iron", "Claw_Prong")
P_CPIN = part("dtf_29_claw_pin", "brass", "Claw_FoldPin_RotAxisY")

def build_leg(parent, lx, sy, name):
    la = asm(parent, name)
    s = 1 if sy > 0 else -1
    place(la, P_LUP, trsf_translate(lx, 820 * s, 150))
    place(la, P_LLOW, trsf_translate(lx, 815 * s, 60))
    # 髋关节销（z330）与膝关节销（z115），两侧
    for cy in (715, 925):
        place(la, P_AXLE, trsf_translate(lx, cy * s, 330))
    for cy in (720, 910):
        place(la, P_AXLE, trsf_translate(lx, cy * s, 110))
    # 液压组件（y 外侧）
    place(la, P_BRK, trsf_translate(lx - 170, 1100 * s, 540))
    place(la, P_ROD, trsf_translate(lx - 170, 1130 * s, 410))
    place(la, P_CYL, trsf_translate(lx - 170, 1130 * s, 90))
    # 可折叠爪
    place(la, P_CBASE, trsf_translate(lx, 820 * s, 30))
    place(la, P_CPRONG, trsf_translate(lx + 180, 820 * s, 0))
    place(la, P_CPRONG, trsf_translate(lx - 180, 770 * s, 0))
    place(la, P_CPRONG, trsf_translate(lx - 180, 870 * s, 0))
    for cy in (697.5, 942.5):
        place(la, P_CPIN, trsf_translate(lx, cy * s, 45))

legs = asm(root, "Legs_Assembly")
build_leg(legs, 950, +1, "Leg_FR_RotAxisY")
build_leg(legs, 950, -1, "Leg_FL_RotAxisY")
build_leg(legs, -1150, +1, "Leg_RR_RotAxisY")
build_leg(legs, -1150, -1, "Leg_RL_RotAxisY")

st.UpdateAssemblies()

# ---------- 导出 AP242，单位 = 米 ----------
Interface_Static.SetCVal_s("write.step.schema", "AP242IS")
Interface_Static.SetCVal_s("write.step.unit", "M")
Interface_Static.SetIVal_s("write.step.assembly", 1)
Interface_Static.SetCVal_s("write.step.product.name", "SteamTurtleTeaFurnace")

writer = STEPCAFControl_Writer()
writer.Transfer(doc, STEPControl_StepModelType.STEPControl_AsIs)
out_file = OUT / "steam_turtle_tea_furnace_ap242.step"
status = writer.Write(str(out_file))
print("write status:", status, "->", out_file)

# ---------- 自检：读回装配，统计实体/包围盒/有效性 ----------
r = STEPControl_Reader()
assert r.ReadFile(str(out_file)) == IFSelect_RetDone
r.TransferRoots()
s = r.OneShape()
n = 0
e = TopExp_Explorer(s, TopAbs_SOLID)
while e.More():
    n += 1
    e.Next()
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
bb = Bnd_Box()
BRepBndLib.Add_s(s, bb)
xmin, ymin, zmin, xmax, ymax, zmax = bb.Get()
print("solids:", n, "valid:", BRepCheck_Analyzer(s).IsValid())
print("bbox(m): x %.3f..%.3f  y %.3f..%.3f  z %.3f..%.3f" % (xmin, xmax, ymin, ymax, zmin, zmax))
print("size(m): L=%.3f W=%.3f H=%.3f" % (xmax - xmin, ymax - ymin, zmax - zmin))
