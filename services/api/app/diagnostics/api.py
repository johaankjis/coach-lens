"""Minimal HTTP transport for M3; service state is process-local and ephemeral."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.design.service import design_provider_kind

from .engine import DiagnosticError, DiagnosticService, ProviderOutputError, provider_kind
from .models import HumanRevision


router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


def service(request: Request) -> DiagnosticService:
    return request.app.state.diagnostics


def http_error(exc: DiagnosticError) -> HTTPException:
    """Stable code plus short message; never row values, provider text, or tracebacks."""
    if isinstance(exc, ProviderOutputError):
        status = 502  # The upstream reasoner failed or returned invalid output; not a client error.
    else:
        status = {"signal_not_found": 404, "diagnosis_not_found": 404,
                  "diagnosis_not_approved": 403, "invalid_state_transition": 409,
                  "reasoner_unavailable": 503}.get(exc.code, 422)
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


class ReviewerRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)


class RejectRequest(ReviewerRequest):
    rationale: str = Field(min_length=1)


class ReviseRequest(RejectRequest):
    revision: HumanRevision


@router.get("/signals")
def signals(svc: DiagnosticService = Depends(service)):
    return svc.list_signals()


@router.get("/mode")
def mode(request: Request):
    """Non-sensitive operator-visible provenance for the running process.

    `mode` is the label the startup path declared. Provider fields and counts are read from
    the installed services, so the label cannot claim a provider that is not really there.
    """
    state = request.app.state
    diagnostics: DiagnosticService = state.diagnostics
    designs = state.designs
    return {"mode": state.demo_mode,
            "diagnostic_provider": provider_kind(diagnostics.reasoner),
            "design_provider": design_provider_kind(designs.intervention, designs.training),
            "evaluation_count": len(diagnostics.evaluations),
            "signal_count": len(diagnostics.signals)}


@router.get("/signals/{signal_id}/evidence")
def evidence(signal_id: str, svc: DiagnosticService = Depends(service)):
    try:
        return svc.provider_evidence(signal_id)
    except DiagnosticError as exc:
        raise http_error(exc) from exc


@router.get("/signals/{signal_id}/review-evidence")
def review_evidence(signal_id: str, svc: DiagnosticService = Depends(service)):
    """Local reviewer view with source lineage. Feedback remains confidential."""
    try:
        return svc.evidence(signal_id)
    except DiagnosticError as exc:
        raise http_error(exc) from exc


@router.get("/signals/{signal_id}/hypotheses")
def hypotheses(signal_id: str, svc: DiagnosticService = Depends(service)):
    try:
        return svc.list_hypotheses(signal_id)
    except DiagnosticError as exc:
        raise http_error(exc) from exc


@router.post("/signals/{signal_id}/hypotheses", status_code=201)
async def diagnose(signal_id: str, svc: DiagnosticService = Depends(service)):
    try:
        return await svc.diagnose(signal_id)
    except DiagnosticError as exc:
        raise http_error(exc) from exc


@router.get("/hypotheses/{hypothesis_id}")
def hypothesis(hypothesis_id: str, svc: DiagnosticService = Depends(service)):
    try:
        return svc.get(hypothesis_id)
    except DiagnosticError as exc:
        raise http_error(exc) from exc


@router.post("/hypotheses/{hypothesis_id}/approve")
def approve(hypothesis_id: str, body: ReviewerRequest, svc: DiagnosticService = Depends(service)):
    try:
        return svc.approve(hypothesis_id, body.reviewer_id)
    except DiagnosticError as exc:
        raise http_error(exc) from exc


@router.post("/hypotheses/{hypothesis_id}/reject")
def reject(hypothesis_id: str, body: RejectRequest, svc: DiagnosticService = Depends(service)):
    try:
        return svc.reject(hypothesis_id, body.reviewer_id, body.rationale)
    except DiagnosticError as exc:
        raise http_error(exc) from exc


@router.post("/hypotheses/{hypothesis_id}/revise")
def revise(hypothesis_id: str, body: ReviseRequest, svc: DiagnosticService = Depends(service)):
    try:
        return svc.revise(hypothesis_id, body.reviewer_id, body.revision, body.rationale)
    except DiagnosticError as exc:
        raise http_error(exc) from exc


@router.get("/hypotheses/{hypothesis_id}/approved")
def approved(hypothesis_id: str, svc: DiagnosticService = Depends(service)):
    try:
        return svc.get_approved_diagnosis(hypothesis_id)
    except DiagnosticError as exc:
        raise http_error(exc) from exc
