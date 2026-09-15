"""用 urllib（本机已验证可用）从清华镜像下载 jsonschema 及其依赖的 wheel。

pip 自身的网络栈当前会挂起，绕过它：下载到本地后用
    pip install --no-index --find-links <dir> jsonschema
离线安装。
"""

import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
# 需要的包（typing_extensions 已装，跳过）
PACKAGES = ["jsonschema", "attrs", "referencing", "jsonschema-specifications", "rpds-py"]

OUT = Path(__file__).resolve().parent.parent / ".wheels"
OUT.mkdir(exist_ok=True)


def pick_wheel(package: str) -> str:
    """从 simple 索引页挑选合适的 wheel 文件名（最新版本）。"""
    url = f"{MIRROR}/{package}/"
    html = urllib.request.urlopen(url, timeout=30).read().decode("utf-8")
    hrefs = re.findall(r'href="[^"]*/([^"/]+\.whl)[#"]', html)
    if not hrefs:
        raise RuntimeError(f"索引页没有 wheel: {package}")

    def score(name: str):
        # 优先级：cp312 win_amd64 > py3-none-any > 其他兼容
        compat = 0
        if "cp312" in name and "win_amd64" in name:
            compat = 3
        elif "py3-none-any" in name or "py2.py3-none-any" in name:
            compat = 2
        elif "abi3" in name and "cp3" in name and "win_amd64" in name:
            compat = 1
        else:
            return (-1, "")
        # 版本号比较：取文件名第一段 version，按数字元组比较
        ver = name.split("-")[1]
        key = tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", ver))
        return (compat, key)

    best = max(hrefs, key=score)
    if score(best)[0] <= 0:
        raise RuntimeError(f"没有兼容 cp312/Windows 的 wheel: {package}")
    return best


def main():
    base = None
    for pkg in PACKAGES:
        whl = pick_wheel(pkg)
        # simple 页面里文件在 <pkg>/../.. 下，用 files 路径
        file_url = f"https://files.pythonhosted.org/packages/{whl}"  # 占位，实际用镜像跳转
        # 清华镜像支持直接 /simple/<pkg>/ 页面内的完整 URL；重新抓取
        url = f"{MIRROR}/{pkg}/"
        html = urllib.request.urlopen(url, timeout=30).read().decode("utf-8")
        m = re.search(r'href="([^"]+/' + re.escape(whl) + r')[#"]', html)
        if not m:
            raise RuntimeError(f"找不到下载链接: {pkg} {whl}")
        link = urllib.parse.urljoin(url, m.group(1))
        # files.pythonhosted.org 国内直连常超时，改走清华镜像的 /packages/ 路径
        link = link.replace("https://files.pythonhosted.org", "https://pypi.tuna.tsinghua.edu.cn")
        dest = OUT / whl
        print(f"下载 {pkg}: {whl}")
        for attempt in range(3):
            try:
                urllib.request.urlretrieve(link, dest)
                break
            except Exception as e:
                print(f"  重试 {attempt + 1}/3: {e}")
        else:
            raise RuntimeError(f"下载失败: {pkg}")
        print(f"  -> {dest} ({dest.stat().st_size} bytes)")

    print("\n全部完成。离线安装命令：")
    print(f"  pip install --no-index --find-links {OUT} jsonschema")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
