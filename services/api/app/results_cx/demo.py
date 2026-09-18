"""Explicit, in-memory ResultsCX demo ingestion. No processed file is written."""

from pathlib import Path

from app.design.service import DesignService, UnavailableDesignProvider
from app.config import get_settings
from app.diagnostics.bedrock import BedrockReasoner
from app.diagnostics.engine import DiagnosticService, UnavailableReasoner
from app.diagnostics.evidence_policy import population_digest

from .models import Domain, Evaluation
from .pipeline import PipelineValidationError, discover_sources, normalize


REQUIRED_WORKBOOKS = {
    Domain.BUSINESS_PROCESS: "Call Flow - Business Process (Healthcare Partner).xlsx",
    Domain.COMPLIANCE: "Compliance Raw Data (Healthcare Partner).xlsx",
    Domain.MEMBER_EXPERIENCE: "QA Raw Data - Member Experience Focus (Healthcare Partner).xlsx",
}

REAL_MODE = "real_results_cx"


class TrustedResultsCXEvaluations(list):
    """In-process provenance minted only after strict local workbook validation.

    The container is immutable, refuses copy and pickle reconstruction, holds its own deep
    copies, and records a content digest at mint time. `verify()` fails if any record was
    changed in place afterward, so a trusted object cannot be refilled with other data.
    """

    def __init__(self, evaluations: list[Evaluation], *, _loader_token: object):
        if _loader_token is not _TRUSTED_LOADER_TOKEN:
            raise ValueError("Trusted ResultsCX evidence requires the local workbook loader")
        super().__init__(evaluation.model_copy(deep=True) for evaluation in evaluations)
        self._content_digest = population_digest(self)

    @property
    def content_digest(self) -> str:
        return self._content_digest

    def verify(self) -> None:
        if (type(self) is not TrustedResultsCXEvaluations or
                population_digest(self) != getattr(self, "_content_digest", None)):
            raise ValueError("Trusted ResultsCX evidence changed after loading")

    def _immutable(self, *args, **kwargs):
        raise TypeError("Trusted ResultsCX evidence is immutable")

    append = extend = insert = pop = remove = clear = sort = reverse = _immutable
    __setitem__ = __delitem__ = __iadd__ = __imul__ = _immutable

    def __reduce_ex__(self, protocol):
        raise TypeError("Trusted ResultsCX evidence cannot be copied or pickled")


_TRUSTED_LOADER_TOKEN = object()


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
    return TrustedResultsCXEvaluations(normalize(sources), _loader_token=_TRUSTED_LOADER_TOKEN)


def install_results_cx_demo(app, evaluations: list[Evaluation]) -> None:
    """Serve M2 records with unavailable design providers and truthful diagnostic mode.

    Only the strict loader's provenance object enables AWS-2 preparation when configured.
    A plain list keeps the Bedrock privacy block.
    """
    settings = get_settings()
    if settings.bedrock_enabled and type(evaluations) is TrustedResultsCXEvaluations:
        reasoner = BedrockReasoner.for_trusted_results_cx(
            settings.bedrock_region, settings.bedrock_model_id, evaluations)
    else:
        reasoner = (BedrockReasoner(settings.bedrock_region, settings.bedrock_model_id)
                    if settings.bedrock_enabled else UnavailableReasoner())
    app.state.diagnostics = DiagnosticService(evaluations, reasoner)
    unavailable = UnavailableDesignProvider()
    app.state.designs = DesignService(app.state.diagnostics, unavailable, unavailable)
    app.state.demo_mode = REAL_MODE
