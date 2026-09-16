"""Strict local normalization and aggregate analytics."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
from app.results_cx import PipelineValidationError, analyze, discover_sources, normalize, write_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize local ResultsCX QA exports into ignored JSONL")
    parser.add_argument("--input", type=Path, default=Path("data/raw"))
    parser.add_argument("--output", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    try:
        sources = discover_sources(args.input)
        evaluations = normalize(sources)
        target = write_jsonl(evaluations, args.output)
        stats = analyze(evaluations)
        domains = {domain.value: {"evaluations": len(evaluations),
                                  "criterion_rows": sum(len(s.lineages) for s in stats if s.domain == domain and s.question is None),
                                  "pass_count": sum(s.pass_count for s in stats if s.domain == domain and s.question is None),
                                  "fail_count": sum(s.fail_count for s in stats if s.domain == domain and s.question is None)}
                   for domain in sources}
        print(json.dumps({"normalized_file": str(target), "domains": domains}, indent=2))
    except PipelineValidationError as exc:
        parser.exit(2, f"ResultsCX validation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
