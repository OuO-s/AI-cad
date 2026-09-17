import trimesh, numpy as np, math, os
from collections import defaultdict

SRC = r"D:\AI\project\Company\AImodeling\ai-cad\output\go2_ac1_mesh.stl"
DST = r"D:\AI\project\Company\AImodeling\ai-cad\output\go2_ac1_plate_armhole.stl"

mesh = trimesh.load(SRC)
mesh.process(); mesh.apply_scale(0.1)
print(f"loaded: faces={len(mesh.faces)} watertight={mesh.is_watertight} volume={mesh.volume:.1f}")
V = np.asarray(mesh.vertices, dtype=np.float64)
F = np.asarray(mesh.faces)
zmax = float(mesh.bounds[1][2])

# --- locate small-hole centers on top plane ---
on_top = (np.abs(V[F][:, :, 2] - zmax) < 0.03).all(axis=1)
pf = F[on_top]
cnt = defaultdict(int)
for f in pf:
    for i in range(3):
        cnt[tuple(sorted((int(f[i]), int(f[(i + 1) % 3]))))] += 1
bnd = [e for e, c in cnt.items() if c == 1]
adj = defaultdict(list)
for a, b in bnd:
    adj[a].append(b); adj[b].append(a)
loops, visited = [], set()
for s in list(adj):
    if s in visited: continue
    loop, prev, cur = [s], None, s
    visited.add(s)
    while True:
        nxt = next((x for x in adj[cur] if x != prev and x not in visited), None)
        if nxt is None: break
        loop.append(nxt); visited.add(nxt); prev, cur = cur, nxt
    loops.append(loop)
holes = []
for l in loops:
    p = V[l][:, :2]; c = p.mean(axis=0); r = np.linalg.norm(p - c, axis=1).max()
    if r < 2.0:
        holes.append((float(c[0]), float(c[1])))
print(f"small holes: {len(holes)}")

# --- vectorized ray casting (many rays vs all triangles) ---
v0 = V[F[:, 0]]; v1 = V[F[:, 1]]; v2 = V[F[:, 2]]
e1 = v1 - v0; e2 = v2 - v0
EPS = 1e-12

def batch_hits(origins, direction):
    """origins (n,3), direction (3,) -> list of arrays of hit t per ray (sorted)."""
    h = np.cross(direction, e2)                    # (nT,3)
    a = np.einsum('ij,ij->i', e1, h)               # (nT,)
    ok_a = np.abs(a) > EPS
    f = np.zeros_like(a); f[ok_a] = 1.0 / a[ok_a]
    out = []
    d = direction
    for o in origins:
        s = o - v0
        u = f * np.einsum('ij,ij->i', s, h)
        q = np.cross(s, e1)
        v = f * np.einsum('j,ij->i', d, q)
        t = f * np.einsum('ij,ij->i', e2, q)
        ok = ok_a & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > EPS)
        out.append(np.sort(t[ok]))
    return out

# --- per hole: per-column z-boundary segmentation; fill every interior air segment ---
GRID = 0.3
RMAX = 3.0
zmin_g = float(mesh.bounds[0][2])
box_meshes = []
report = []
for cx, cy in holes:
    xs = np.arange(cx - RMAX, cx + RMAX + GRID / 2, GRID)
    ys = np.arange(cy - RMAX, cy + RMAX + GRID / 2, GRID)
    cols = [(x, y) for x in xs for y in ys if (x - cx) ** 2 + (y - cy) ** 2 <= RMAX ** 2]
    downs = batch_hits(np.array([[x, y, 200.0] for x, y in cols]), np.array([0.0, 0.0, -1.0]))
    ups = batch_hits(np.array([[x, y, 20.0] for x, y in cols]), np.array([0.0, 0.0, 1.0]))
    zlists = []
    for td, tu in zip(downs, ups):
        zs = sorted(set([round(200.0 - t, 3) for t in td] + [round(20.0 + t, 3) for t in tu]))
        zlists.append(zs)
    # local underside from columns that have boundaries
    starts = [zs[0] for zs in zlists if zs]
    ring_bot = min(starts) if starts else zmin_g
    boxes = []
    for (x, y), zs in zip(cols, zlists):
        segs = []
        if not zs:
            segs = [(ring_bot, zmax)]  # fully open column: fill whole local span
        else:
            if len(zs) % 2 == 0:
                for k in range(1, len(zs) - 1, 2):
                    segs.append((zs[k], zs[k + 1]))
            else:
                for k in range(1, len(zs) - 1, 2):
                    segs.append((zs[k], zs[k + 1]))
            if zs[-1] < zmax - 0.01:
                segs.append((zs[-1], zmax))  # cavity open through the top surface
        for seg_bot, seg_top in segs:
            if seg_top <= zmin_g + 0.01 or seg_bot >= zmax - 0.01:
                continue
            top_c = min(seg_top + 0.03, zmax + 0.03)
            bot_c = max(seg_bot - 0.03, zmin_g - 0.03)
            if top_c - bot_c < 0.05:
                continue
            b = trimesh.creation.box(extents=[GRID + 0.02, GRID + 0.02, top_c - bot_c])
            b.apply_translation([x, y, (top_c + bot_c) / 2])
            boxes.append(b)
    if boxes:
        vm = np.vstack([b.vertices for b in boxes])
        face_list, off = [], 0
        for b in boxes:
            face_list.append(b.faces + off); off += len(b.vertices)
        combined = trimesh.Trimesh(vertices=vm, faces=np.vstack(face_list))
        box_meshes.append(combined)
        report.append(len(boxes))
print(f"boxes per hole: min={min(report)} max={max(report)} total={sum(report)}")

if os.environ.get("NO_FILL") == "1":
    filled = mesh
    print("fill skipped (original mesh kept)")
else:
    filled = trimesh.boolean.union([mesh] + box_meshes, engine="manifold")
    print(f"after fill: watertight={filled.is_watertight} volume={filled.volume:.1f} (delta {filled.volume - mesh.volume:+.1f})")

# --- subtract 4x M5 holes ---
cx0 = (mesh.bounds[0][0] + mesh.bounds[1][0]) / 2.0
cy0 = 298.59  # 半幅前移：板中心302.92前移4.33 -> 孔y = 263.59 / 333.59，间距仍70
tools = []
for sx in (-1, 1):
    for sy in (-1, 1):
        cyl = trimesh.creation.cylinder(radius=2.45, height=100, sections=48)
        cyl.apply_translation([cx0 + sx * 35.0, cy0 + sy * 35.0, mesh.bounds[0][2] + 50])
        tools.append(cyl)
result = trimesh.boolean.difference([filled] + tools, engine="manifold")
print(f"after M5 holes: watertight={result.is_watertight} volume={result.volume:.1f} (delta {result.volume - filled.volume:+.1f})")
print(f"M5 centers: {[(round(cx0 + s * 35, 2), round(cy0 + t * 35, 2)) for s in (-1, 1) for t in (-1, 1)]}")
result.export(DST)
print("saved:", DST, f"({os.path.getsize(DST)} bytes)")
