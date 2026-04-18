from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.models.metrics import MetricsErrorResponse, MetricsSummary, SessionDiagnostics
from app.services.diagnostics_service import DiagnosticsService, DiagnosticsServiceError

router = APIRouter(tags=["metrics"])


def get_diagnostics_service(request: Request) -> DiagnosticsService:
    return request.app.state.diagnostics_service


@router.get("/metrics/summary", response_model=MetricsSummary)
async def get_metrics_summary(
    diagnostics_service: Annotated[DiagnosticsService, Depends(get_diagnostics_service)],
) -> MetricsSummary:
    return await diagnostics_service.get_metrics_summary()


@router.get(
    "/sessions/{session_id}/diagnostics",
    response_model=SessionDiagnostics,
    responses={status.HTTP_404_NOT_FOUND: {"model": MetricsErrorResponse}},
)
async def get_session_diagnostics(
    session_id: UUID,
    diagnostics_service: Annotated[DiagnosticsService, Depends(get_diagnostics_service)],
) -> SessionDiagnostics | JSONResponse:
    try:
        return await diagnostics_service.get_session_diagnostics(session_id)
    except DiagnosticsServiceError as error:
        status_code = status.HTTP_404_NOT_FOUND if error.code == "session_not_found" else 500
        error_response = MetricsErrorResponse(code=error.code, message=error.message)
        return JSONResponse(
            status_code=status_code,
            content=error_response.model_dump(mode="json"),
        )
