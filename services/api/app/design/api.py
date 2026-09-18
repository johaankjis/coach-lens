"""M5 aggregate create/read routes. Provider internals never appear in errors."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.diagnostics.api import http_error as diagnostic_http_error
from app.diagnostics.engine import DiagnosticError

from .alignment_review import ERROR_MESSAGES as ALIGNMENT_ERROR_MESSAGES
from .alignment_service import AlignmentReviewService
from .service import DesignError, DesignService


router = APIRouter(prefix="/designs", tags=["designs"])


def service(request: Request) -> DesignService:
    return request.app.state.designs


def alignment_service(request: Request) -> AlignmentReviewService:
    return request.app.state.alignment_reviews


def _error(exc: DesignError | DiagnosticError) -> HTTPException:
    if isinstance(exc, DiagnosticError):
        return diagnostic_http_error(exc)
    status = {"design_not_found": 404, "design_provider_unavailable": 503,
              "invalid_design_output": 502, "design_provider_failure": 502,
              # AWS-4 handoff preconditions and the service gate on provider-backed design.
              "intervention_not_proposed": 409, "solution_not_validated": 409,
              "training_design_withheld": 409, "solution_questioned": 409,
              "intervention_stale": 409, "training_design_not_permitted": 409,
              # AWS-5 designer refusal and privacy stop.
              "training_design_refused": 422, "design_privacy_blocked": 502,
              # AWS-6 alignment review.
              "alignment_review_not_found": 404, "alignment_validator_unavailable": 503,
              "invalid_alignment_output": 502, "alignment_validator_failure": 502,
              "alignment_privacy_blocked": 502, "no_training_design": 409,
              "alignment_review_not_permitted": 409, "alignment_review_stale": 409}.get(exc.code, 500)
    # AWS-6 codes always carry their fixed table text, never provider prose.
    message = ALIGNMENT_ERROR_MESSAGES.get(exc.code, str(exc))
    return HTTPException(status_code=status, detail={"code": exc.code, "message": message})


@router.post("/diagnoses/{hypothesis_id}")
async def orchestrate(hypothesis_id: str, svc: DesignService = Depends(service)):
    try:
        return await svc.run(hypothesis_id)
    except (DiagnosticError, DesignError) as exc:
        raise _error(exc) from exc


@router.get("/diagnoses/{hypothesis_id}")
def result(hypothesis_id: str, svc: DesignService = Depends(service)):
    try:
        return svc.get(hypothesis_id)
    except (DiagnosticError, DesignError) as exc:
        raise _error(exc) from exc


@router.post("/diagnoses/{hypothesis_id}/alignment-review")
async def review_alignment(hypothesis_id: str, svc: AlignmentReviewService = Depends(alignment_service)):
    """AWS-6: one immutable semantic alignment review of the stored training package."""
    try:
        return await svc.review(hypothesis_id)
    except (DiagnosticError, DesignError) as exc:
        raise _error(exc) from exc


@router.get("/diagnoses/{hypothesis_id}/alignment-review")
def alignment_review(hypothesis_id: str, svc: AlignmentReviewService = Depends(alignment_service)):
    try:
        return svc.get(hypothesis_id)
    except (DiagnosticError, DesignError) as exc:
        raise _error(exc) from exc
