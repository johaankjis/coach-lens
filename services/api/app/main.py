"""FastAPI application entry point."""

from fastapi import FastAPI
from pydantic import BaseModel
from app.diagnostics.api import router as diagnostics_router
from app.diagnostics.engine import DiagnosticService, UnavailableReasoner  # noqa: F401 re-export
from app.design.api import router as design_router
from app.results_cx.models import Evaluation

from app.config import get_settings
from app.diagnostics.bedrock import BedrockReasoner
from app.interventions.api import router as intervention_router
from app.pipeline import install_pipeline


class HealthResponse(BaseModel):
    status: str
    service: str


settings = get_settings()
app = FastAPI(title=settings.title)


def _local_evaluations() -> list[Evaluation]:
    path = settings.diagnostic_evaluations_path
    if path is None:
        return []
    return [Evaluation.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]


# The diagnostic reasoner, AWS-3 validator, AWS-4 reasoner and validator, and AWS-5 training
# designer all follow the one Bedrock switch. The M5 intervention step is the AWS-4 handoff,
# so a design run reads the stored solution-reviewed record and the training designer only
# runs on a training or practice intervention that the review found aligned.
install_pipeline(app, DiagnosticService(
    _local_evaluations(),
    BedrockReasoner(settings.bedrock_region, settings.bedrock_model_id)
    if settings.bedrock_enabled else UnavailableReasoner()), settings)
app.state.demo_mode = "local_normalized" if settings.diagnostic_evaluations_path else "unconfigured"
app.include_router(diagnostics_router)
app.include_router(design_router)
app.include_router(intervention_router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.service_name)
