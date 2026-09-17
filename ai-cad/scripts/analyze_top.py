import struct, json, sys
from collections import defaultdict

path = r"D:\AI\project\Company\AImodeling\ai-cad\output\go2_ac1_mesh.stl"
with open(path, "rb") as f:
    header = f.read(80)
    n = struct.unpack("<I", f.read(4))[0]
    tris = []
    for _ in range(n):
        data = struct.unpack("<12fH", f.read(50))
        v = [(data[3], data[4], data[5]), (data[6], data[7], data[8]), (data[9], data[10], data[11])]
        tris.append(v)

zs = [z for t in tris for _,_,z in t]
zmin, zmax = min(zs), max(zs)
print(f"triangles={n} z=[{zmin:.3f},{zmax:.3f}]")

# top-surface triangles: all vertices within 0.3 of zmax
top = [t for t in tris if all(abs(z - zmax) < 0.3 for _,_,z in t)]
print(f"top_triangles={len(top)}")

# boundary edges: edges appearing once among top triangles
edge_count = defaultdict(int)
edge_verts = {}
for t in top:
    for i in range(3):
        a, b = t[i], t[(i+1)%3]
        key = tuple(sorted([a, b]))
        edge_count[key] += 1
        edge_verts[key] = (a, b)
boundary = [e for e, c in edge_count.items() if c == 1]
print(f"boundary_edges={len(boundary)}")

# build adjacency and find loops
adj = defaultdict(list)
for a, b in boundary:
    adj[a].append(b)
    adj[b].append(a)

visited = set()
loops = []
for start in adj:
    if start in visited:
        continue
    # walk the loop
    loop = [start]
    visited.add(start)
    prev, cur = None, start
    while True:
        nxts = [x for x in adj[cur] if x != prev]
        nxt = None
        for x in nxts:
            if x not in visited:
                nxt = x
                break
        if nxt is None:
            break
        loop.append(nxt)
        visited.add(nxt)
        prev, cur = cur, nxt
    loops.append(loop)

def centroid(pts):
    n = len(pts)
    return tuple(round(sum(p[i] for p in pts)/n, 2) for i in range(2))

loops.sort(key=len, reverse=True)
result = {"zmax": round(zmax,3), "loops": []}
for i, lp in enumerate(loops):
    xs = [p[0] for p in lp]; ys = [p[1] for p in lp]
    cx, cy = sum(xs)/len(lp), sum(ys)/len(lp)
    rs = [((p[0]-cx)**2 + (p[1]-cy)**2)**0.5 for p in lp]
    rmin, rmax = min(rs), max(rs)
    result["loops"].append({
        "idx": i, "n": len(lp),
        "center": [round(cx,2), round(cy,2)],
        "r_min": round(rmin,2), "r_max": round(rmax,2),
        "extent": [round(min(xs),2), round(min(ys),2), round(max(xs),2), round(max(ys),2)],
    })
print(json.dumps(result, indent=1))
