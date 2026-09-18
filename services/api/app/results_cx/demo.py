"""Explicit, in-memory ResultsCX demo ingestion. No processed file is written."""

from pathlib import Path

from app.design.service import DesignService, UnavailableDesignProvider
from app.config import get_settings
from app.diagnostics.bedrock import BedrockReasoner
from app.diagnostics.engine import DiagnosticService, UnavailableReasoner

from .models import Domain, Evaluation
from .pipeline import PipelineValidationError, discover_sources, normalize


REQUIRED_WORKBOOKS = {
    Domain.BUSINESS_PROCESS: "Call Flow - Business Process (Healthcare Partner).xlsx",
    Domain.COMPLIANCE: "Compliance Raw Data (Healthcare Partner).xlsx",
    Domain.MEMBER_EXPERIENCE: "QA Raw Data - Member Experience Focus (Healthcare Partner).xlsx",
}

REAL_MODE = "real_results_cx"


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
    # Case-insensitive filesystems satisfy `is_file()` for a differently cased name, and M2
    # discovery recurses, so anything else on disk is reported by its real path.
    unexpected = sorted(path.relative_to(root).as_posix() for path in root.rglob("*.xlsx")
                        if not path.name.startswith("~$") and path.relative_to(root).as_posix() not in expected)
    if unexpected:
        raise PipelineValidationError(
            "unexpected_demo_workbooks",
            f"Only the three required workbooks may be under {root}; remove or rename exactly: "
            f"{', '.join(unexpected)}",
        )
    sources = discover_sources(root)
    for domain, name in REQUIRED_WORKBOOKS.items():
        if sources[domain].path.name != name:
            raise PipelineValidationError(
                "demo_domain_mismatch", f"{name} does not contain the expected {domain.value} QA domain"
            )
    return normalize(sources)


def install_results_cx_demo(app, evaluations: list[Evaluation]) -> None:
    """Serve M2 records with unavailable design providers and truthful diagnostic mode.

    Bedrock may be installed by setting, but its default privacy policy refuses remote
    invocation with these real records before an AWS client is created.
    """
    settings = get_settings()
    reasoner = (BedrockReasoner(settings.bedrock_region, settings.bedrock_model_id)
                if settings.bedrock_enabled else UnavailableReasoner())
    app.state.diagnostics = DiagnosticService(evaluations, reasoner)
    unavailable = UnavailableDesignProvider()
    app.state.designs = DesignService(app.state.diagnostics, unavailable, unavailable)
    app.state.demo_mode = REAL_MODE
