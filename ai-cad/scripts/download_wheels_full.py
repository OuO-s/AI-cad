"""全量离线 wheel 打包：把 ai-cad 管线的完整依赖树下载到 .wheels-full\\。

背景：本机 pip 的网络栈会挂起（download_wheels.py 同理），改用 urllib 走清华镜像。
依赖树不是手写的——从本机已安装发行版的 metadata 递归解析，保证与当前验证过
的环境完全一致。

用法：
    python scripts/download_wheels_full.py            # 下载到 .wheels-full\\
目标机离线安装：
    pip install --no-index --find-links <dir>\\.wheels-full -r deploy\\requirements.txt
"""

import re
import sys
import urllib.parse
import urllib.request
from importlib import metadata
from pathlib import Path

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
ROOTS = ["build123d", "jsonschema", "pytest"]  # 与 deploy/requirements.txt 对齐
SKIP = {"pip", "setuptools", "wheel"}  # 环境自带/无需随包
OUT = Path(__file__).resolve().parent.parent / ".wheels-full"
OUT.mkdir(exist_ok=True)


def norm(name: str) -> str:
    """PEP 503 规范名（dist-info 里依赖名可能是大小写/下划线混写）。"""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requires(dist) -> list[str]:
    """从已装 dist 的 metadata 提取必装依赖名（跳过 extra==... 的可选项）。"""
    names = []
    for req in (dist.requires or []):
        if "extra ==" in req:
            continue  # 可选extras（dev/doc/test），不进离线包
        m = re.match(r"([A-Za-z0-9._-]+)", req)
        if m:
            names.append(norm(m.group(1)))
    return names


def collect(pkgs: list[str]) -> list[str]:
    seen, order, queue = set(), [], [norm(p) for p in pkgs]
    while queue:
        pkg = queue.pop(0)
        if pkg in seen or pkg in SKIP:
            continue
        seen.add(pkg)
        order.append(pkg)
        try:
            dist = metadata.distribution(pkg)
        except metadata.PackageNotFoundError:
            print(f"  (本机未装 {pkg}，作为叶节点直接下载)")
            continue
        for dep in parse_requires(dist):
            if dep not in seen:
                queue.append(dep)
    return order


def pick_wheel(package: str) -> str:
    """从 simple 索引页挑 wheel：cp312/win_amd64 > py3-none-any > abi3。"""
    url = f"{MIRROR}/{package}/"
    html = urllib.request.urlopen(url, timeout=30).read().decode("utf-8")
    hrefs = re.findall(r'href="[^"]*/([^"/]+\.whl)[#"]', html)
    if not hrefs:
        raise RuntimeError(f"索引页没有 wheel: {package}")

    def score(name: str):
        compat = 0
        if "cp312" in name and "win_amd64" in name:
            compat = 3
        elif "py3-none-any" in name or "py2.py3-none-any" in name:
            compat = 2
        elif "abi3" in name and "cp3" in name and "win_amd64" in name:
            compat = 1
        else:
            return (-1, ())
        ver = name.split("-")[1]
        key = tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", ver))
        return (compat, key)

    best = max(hrefs, key=score)
    if score(best)[0] <= 0:
        raise RuntimeError(f"没有兼容 cp312/Windows 的 wheel: {package}")
    return best


def download(package: str) -> None:
    whl = pick_wheel(package)
    dest = OUT / whl
    if dest.exists():
        print(f"已有 {package}: {whl}")
        return
    url = f"{MIRROR}/{package}/"
    html = urllib.request.urlopen(url, timeout=30).read().decode("utf-8")
    m = re.search(r'href="([^"]+/' + re.escape(whl) + r')[#"]', html)
    if not m:
        raise RuntimeError(f"找不到下载链接: {package} {whl}")
    link = urllib.parse.urljoin(url, m.group(1))
    link = link.replace("https://files.pythonhosted.org", "https://pypi.tuna.tsinghua.edu.cn")
    print(f"下载 {package}: {whl}")
    for attempt in range(3):
        try:
            urllib.request.urlretrieve(link, dest)
            break
        except Exception as e:
            print(f"  重试 {attempt + 1}/3: {e}")
    else:
        raise RuntimeError(f"下载失败: {package}")
    print(f"  -> {dest.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    order = collect(ROOTS)
    print("依赖树（解析顺序）:")
    print("  " + " ".join(order))
    for pkg in order:
        download(pkg)
    total = sum(f.stat().st_size for f in OUT.glob("*.whl")) / 1e6
    print(f"\n全部完成：{len(list(OUT.glob('*.whl')))} 个 wheel，共 {total:.0f} MB")
    print(f"目标机离线安装：")
    print(f"  pip install --no-index --find-links {OUT} -r deploy\\requirements.txt")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
