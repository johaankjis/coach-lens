"""AWS-4 routes. Provider internals never appear in errors."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.diagnostics.api import http_error as diagnostic_http_error
from app.diagnostics.engine import DiagnosticError

from .bedrock import InterventionError
from .service import ERROR_MESSAGES, InterventionService


router = APIRouter(prefix="/interventions", tags=["interventions"])

STATUS = {"intervention_not_found": 404, "intervention_provider_unavailable": 503,
          "solution_validator_unavailable": 503, "invalid_intervention_output": 502,
          "intervention_provider_failure": 502, "invalid_solution_output": 502,
          "solution_validator_failure": 502, "intervention_stale": 409, "provider_privacy_blocked": 403}


def service(request: Request) -> InterventionService:
    return request.app.state.interventions


def _error(exc: InterventionError | DiagnosticError) -> HTTPException:
    if isinstance(exc, DiagnosticError):
        return diagnostic_http_error(exc)
    code = exc.code if exc.code in ERROR_MESSAGES else "intervention_provider_failure"
    return HTTPException(status_code=STATUS.get(code, 500), detail={"code": code, "message": ERROR_MESSAGES[code]})


@router.post("/diagnoses/{hypothesis_id}/propose")
async def propose(hypothesis_id: str, svc: InterventionService = Depends(service)):
    try:
        return await svc.propose(hypothesis_id)
    except (DiagnosticError, InterventionError) as exc:
        raise _error(exc) from exc


@router.post("/diagnoses/{hypothesis_id}/validate-solution")
async def validate_solution(hypothesis_id: str, svc: InterventionService = Depends(service)):
    try:
        return await svc.validate_solution(hypothesis_id)
    except (DiagnosticError, InterventionError) as exc:
        raise _error(exc) from exc


@router.get("/diagnoses/{hypothesis_id}")
def record(hypothesis_id: str, svc: InterventionService = Depends(service)):
    try:
        return svc.get(hypothesis_id)
    except (DiagnosticError, InterventionError) as exc:
        raise _error(exc) from exc
