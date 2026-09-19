"""提取 STL 最大安装面与圆形边界候选，输出残差而非宣称精确孔位。"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow.stl_interface import inspect_stl_interface


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stl", type=Path)
    parser.add_argument("--units", required=True, choices=["mm"], help="STL 单位必须由用户明确声明")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--circle-max-residual-mm", type=float, default=.1)
    args = parser.parse_args()
    report = inspect_stl_interface(args.stl, args.units, circle_max_residual_mm=args.circle_max_residual_mm)
    output = args.out or args.stl.with_suffix(".interface.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"report": str(output), "plane": report["installation_plane_candidate"],
                      "circle_candidates": len(report["circle_candidates"]), "requires_user_confirmation": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
