"""从 mm 单位的对应点 JSON 计算候选安装变换，不写入 CAD 模型。"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow.registration import rigid_registration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    request = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if request.get("units") != "mm" or set(request) != {"units", "source_mm", "target_mm", "tolerance_mm"}:
        raise ValueError("仅接受 units=mm、source_mm、target_mm、tolerance_mm 四个字段")
    result = rigid_registration(request["source_mm"], request["target_mm"], request["tolerance_mm"])
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["status"] == "within_tolerance" else 1


if __name__ == "__main__":
    raise SystemExit(main())
