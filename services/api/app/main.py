"""FastAPI application entry point."""

from fastapi import FastAPI
from pydantic import BaseModel
from app.diagnostics.api import router as diagnostics_router
from app.diagnostics.engine import DiagnosticService, UnavailableReasoner  # noqa: F401 re-export
from app.design.api import router as design_router
from app.design.service import DesignService, UnavailableDesignProvider
from app.results_cx.models import Evaluation

from app.config import get_settings
from app.diagnostics.bedrock import BedrockReasoner
from app.diagnostics.evidence_validator import (BedrockEvidenceValidator,
                                                 EvidenceValidationService,
                                                 UnavailableEvidenceValidator)
from app.interventions.api import router as intervention_router
from app.interventions.bedrock import BedrockInterventionReasoner, BedrockSolutionValidator
from app.interventions.handoff import ValidatedInterventionHandoff
from app.interventions.service import (InterventionService, UnavailableInterventionReasoner,
                                       UnavailableSolutionValidator)


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


app.state.diagnostics = DiagnosticService(
    _local_evaluations(),
    BedrockReasoner(settings.bedrock_region, settings.bedrock_model_id)
    if settings.bedrock_enabled else UnavailableReasoner(),
)
app.state.evidence_validations = EvidenceValidationService(
    app.state.diagnostics,
    BedrockEvidenceValidator(settings.bedrock_region, settings.bedrock_model_id)
    if settings.bedrock_enabled else UnavailableEvidenceValidator(),
)
app.state.demo_mode = "local_normalized" if settings.diagnostic_evaluations_path else "unconfigured"
# AWS-4: the intervention reasoner and solution validator follow the same Bedrock switch; the
# M5 intervention step reads their stored record instead of deciding on its own.
app.state.interventions = InterventionService(
    app.state.diagnostics, app.state.evidence_validations,
    BedrockInterventionReasoner(settings.bedrock_region, settings.bedrock_model_id)
    if settings.bedrock_enabled else UnavailableInterventionReasoner(),
    BedrockSolutionValidator(settings.bedrock_region, settings.bedrock_model_id)
    if settings.bedrock_enabled else UnavailableSolutionValidator())
app.state.designs = DesignService(app.state.diagnostics, ValidatedInterventionHandoff(app.state.interventions),
                                  UnavailableDesignProvider())
app.include_router(diagnostics_router)
app.include_router(design_router)
app.include_router(intervention_router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.service_name)
