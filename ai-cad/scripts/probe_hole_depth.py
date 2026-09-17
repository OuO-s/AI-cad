import trimesh, numpy as np
from collections import defaultdict

mesh = trimesh.load(r"D:\AI\project\Company\AImodeling\ai-cad\output\go2_ac1_mesh.stl")
mesh.process(); mesh.apply_scale(0.1)
V = np.asarray(mesh.vertices, dtype=np.float64)
F = np.asarray(mesh.faces)
zmax = mesh.bounds[1][2]

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

# triangle data
v0 = V[F[:, 0]]; v1 = V[F[:, 1]]; v2 = V[F[:, 2]]
e1 = v1 - v0; e2 = v2 - v0
EPS = 1e-9

def ray_hits(o, d):
    """Moller-Trumbore, ray vs all triangles; return sorted hit t along -z from z=200."""
    h = np.cross(d, e2)
    a = np.einsum('ij,ij->i', e1, h)
    mask = np.abs(a) > EPS
    f = np.zeros_like(a); f[mask] = 1.0 / a[mask]
    s = o - v0
    u = f * np.einsum('ij,ij->i', s, h)
    q = np.cross(s, e1)
    v = f * np.einsum('j,ij->i', d, q)
    t = f * np.einsum('ij,ij->i', e2, q)
    ok = mask & (u >= -EPS) & (v >= -EPS) & (u + v <= 1 + EPS) & (t > EPS)
    return sorted((200.0 - t[ok]).tolist())  # hit z

probe = [(0.0, 0.0), (0.5, 0.0), (-0.5, 0.0), (0.0, 0.5), (0.0, -0.5), (1.2, 0.0), (-1.2, 0.0), (0.0, 1.2), (0.0, -1.2)]
o = np.array([0.0, 0.0, 200.0]); d = np.array([0.0, 0.0, -1.0])
stats = []
for cx, cy in holes:
    zs = set()
    for px, py in probe:
        o[0], o[1] = cx + px, cy + py
        zs.update(round(z, 1) for z in ray_hits(o, d))
    stats.append(sorted(zs))
from collections import Counter
prof = Counter(tuple(s) for s in stats)
for k, n in prof.most_common():
    print(f'{n:3d} holes, hit-z profile: {k}')
