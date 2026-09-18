"""Serve the local ResultsCX workspace with an optional AWS-2 diagnostic reasoner."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from app.config import get_settings  # noqa: E402
from app.results_cx.demo import install_results_cx_demo, load_results_cx_demo  # noqa: E402
from app.results_cx.pipeline import PipelineValidationError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local ResultsCX review demo")
    parser.add_argument("--input", type=Path, default=Path("data/raw"))
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if get_settings().diagnostic_evaluations_path is not None:
        parser.exit(2, "Real ResultsCX demo refuses COACHLENS_API_DIAGNOSTIC_EVALUATIONS_PATH; unset it first.\n")
    try:
        evaluations = load_results_cx_demo(args.input)
    except PipelineValidationError as exc:
        parser.exit(2, f"ResultsCX demo could not start: {exc}\n")

    from app.main import app
    import uvicorn

    install_results_cx_demo(app, evaluations)
    diagnostic_state = ("Bedrock diagnostic, evidence-review, intervention, solution-review, and training-design "
                        "providers with AWS-2 structured evidence only; evaluator comments stay local; training design "
                        "runs only behind the AWS-4 solution-validated handoff"
                        if get_settings().bedrock_enabled
                        else "diagnostic, intervention, and training-design providers unavailable")
    print(f"Mode: REAL RESULTS CX (local data; {diagnostic_state})", flush=True)
    print(f"Loaded {len(evaluations)} evaluations, "
          f"{sum(len(e.criteria) for e in evaluations)} criterion records, "
          f"{len(app.state.diagnostics.signals)} observed signals", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
