"""Explicit, in-memory ResultsCX demo ingestion. No processed file is written."""

from pathlib import Path

from .models import Domain, Evaluation
from .pipeline import PipelineValidationError, discover_sources, normalize


REQUIRED_WORKBOOKS = {
    Domain.BUSINESS_PROCESS: "Call Flow - Business Process (Healthcare Partner).xlsx",
    Domain.COMPLIANCE: "Compliance Raw Data (Healthcare Partner).xlsx",
    Domain.MEMBER_EXPERIENCE: "QA Raw Data - Member Experience Focus (Healthcare Partner).xlsx",
}


def load_results_cx_demo(raw_dir: Path | str) -> list[Evaluation]:
    """Validate the exact local inputs, then delegate parsing and joining to M2."""
    root = Path(raw_dir)
    missing = [name for name in REQUIRED_WORKBOOKS.values() if not (root / name).is_file()]
    if missing:
        raise PipelineValidationError(
            "missing_demo_workbooks",
            f"Required ResultsCX workbooks absent from {root}: {', '.join(missing)}",
        )
    expected = set(REQUIRED_WORKBOOKS.values())
    unexpected = sorted(str(path.relative_to(root)) for path in root.rglob("*.xlsx")
                        if not path.name.startswith("~$") and path.relative_to(root).as_posix() not in expected)
    if unexpected:
        raise PipelineValidationError(
            "unexpected_demo_workbooks",
            f"Remove unrelated .xlsx workbooks from {root} before starting real-data mode",
        )
    sources = discover_sources(root)
    for domain, name in REQUIRED_WORKBOOKS.items():
        if sources[domain].path.name != name:
            raise PipelineValidationError(
                "demo_domain_mismatch", f"{name} does not contain the expected {domain.value} QA domain"
            )
    return normalize(sources)
