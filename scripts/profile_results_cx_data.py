"""Aggregate-only ResultsCX workbook profile."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
from app.results_cx import PipelineValidationError, discover_sources, profile_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile local ResultsCX QA exports without printing row values")
    parser.add_argument("--input", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    try:
        print(json.dumps(profile_sources(discover_sources(args.input)), indent=2))
    except PipelineValidationError as exc:
        parser.exit(2, f"ResultsCX validation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
