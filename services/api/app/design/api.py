"""M5 aggregate create/read routes. Provider internals never appear in errors."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.diagnostics.api import http_error as diagnostic_http_error
from app.diagnostics.engine import DiagnosticError

from .service import DesignError, DesignService


router = APIRouter(prefix="/designs", tags=["designs"])


def service(request: Request) -> DesignService:
    return request.app.state.designs


def _error(exc: DesignError | DiagnosticError) -> HTTPException:
    if isinstance(exc, DiagnosticError):
        return diagnostic_http_error(exc)
    status = {"design_not_found": 404, "design_provider_unavailable": 503,
              "invalid_design_output": 502, "design_provider_failure": 502}.get(exc.code, 500)
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


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
