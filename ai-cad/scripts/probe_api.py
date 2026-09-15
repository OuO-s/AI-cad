"""build123d 0.11.1 代数模式 API 探针：写生成器前逐一验证假设。"""

import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from build123d import (
    Axis, Plane, Pos, Rectangle, Circle, RegularPolygon, Cylinder,
    extrude, revolve, fillet, chamfer, export_step,
)

ok, fail = [], []


def probe(name, fn):
    try:
        result = fn()
        ok.append((name, result))
        print(f"OK   {name}: {result}")
    except Exception as e:
        fail.append((name, f"{type(e).__name__}: {e}"))
        print(f"FAIL {name}: {type(e).__name__}: {e}")


# 1. 基础拉伸
probe("extrude rectangle", lambda: extrude(Rectangle(60, 40), amount=20).volume)

# 2. 平面上偏移的轮廓 + 拉伸方向
probe("offset plane extrude", lambda: extrude(Plane.XY.offset(-5) * Rectangle(10, 10), amount=20).volume)

# 3. Pos 定位轮廓
probe("pos located circle", lambda: extrude(Pos(15, 10, 0) * Circle(2.5), amount=20).volume)

# 4. 布尔差（贯穿孔：超长圆柱）
def _hole():
    box = extrude(Rectangle(60, 40), amount=20)
    box -= Pos(15, 10, 10) * Cylinder(2.5, 40)
    return box.volume
probe("boolean subtract cylinder", _hole)

# 5. 盲孔：对齐圆柱（Cylinder 默认轴向下对称？验证）
def _blind():
    box = extrude(Rectangle(60, 40), amount=20)
    cyl = Pos(15, 10, 20) * Cylinder(2.5, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    box -= cyl
    return box.volume
probe("aligned cylinder blind hole", _blind)

# 6. fillet 全部边
def _fillet():
    box = extrude(Rectangle(30, 30), amount=10)
    return fillet(box.edges(), radius=2).volume
probe("fillet all edges", _fillet)

# 7. 边选择器
def _sel():
    box = extrude(Rectangle(30, 30), amount=10)
    return (len(box.edges().filter_by(Axis.Z)),
            len(box.faces().sort_by(Axis.Z)[-1].edges()))
probe("edge selectors vertical/top", _sel)

# 8. chamfer
def _chamfer():
    box = extrude(Rectangle(30, 30), amount=10)
    return chamfer(box.edges().filter_by(Axis.Z), length=2).volume
probe("chamfer vertical edges", _chamfer)

# 9. revolve 全局轴
def _revolve():
    prof = Plane.XZ.offset(10) * Rectangle(5, 20)  # 距 X 轴 10 的矩形
    return revolve(prof, axis=Axis.X).volume
probe("revolve around Axis.X", _revolve)

# 10. symmetric extrude
probe("symmetric extrude", lambda: extrude(Rectangle(10, 10), amount=2.5, both=True).volume)

# 11. RegularPolygon
probe("regular polygon", lambda: extrude(RegularPolygon(5, 6), amount=3).volume)

# 12. intersect 运算符
def _inter():
    a = extrude(Rectangle(10, 10), amount=5)
    b = Pos(5, 5, 0) * extrude(Rectangle(10, 10), amount=5)
    return (a & b).volume
probe("intersect operator", _inter)

print(f"\n{len(ok)} 通过, {len(fail)} 失败")
sys.exit(1 if fail else 0)
