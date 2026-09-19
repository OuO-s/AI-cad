"""同坐标系 STEP 装配校核、制造白名单交付。"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow.assembly import deliver_assembly


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "output" / "assemblies")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    path, result = deliver_assembly(plan, args.plan.resolve().parent, args.out)
    print(json.dumps({"manifest": str(path), "status": result["status"], "error": result.get("error")}, ensure_ascii=False))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
