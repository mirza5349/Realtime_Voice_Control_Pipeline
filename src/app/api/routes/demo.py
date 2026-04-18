from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse, JSONResponse

from app.models.demo import (
    DemoContext,
    DemoErrorResponse,
    DemoSampleAssetList,
    DemoSessionOverview,
)
from app.services.demo_service import DemoService, DemoServiceError

router = APIRouter(prefix="/demo", tags=["demo"])


def get_demo_service(request: Request) -> DemoService:
    return request.app.state.demo_service


@router.get("/context", response_model=DemoContext)
def get_demo_context(
    demo_service: Annotated[DemoService, Depends(get_demo_service)],
) -> DemoContext:
    return demo_service.build_context()


@router.get("/samples", response_model=DemoSampleAssetList)
def list_demo_samples(
    demo_service: Annotated[DemoService, Depends(get_demo_service)],
) -> DemoSampleAssetList:
    return demo_service.list_sample_assets()


@router.get(
    "/samples/{name}",
    response_model=None,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": DemoErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": DemoErrorResponse},
    },
)
def get_demo_sample(
    name: str,
    demo_service: Annotated[DemoService, Depends(get_demo_service)],
):
    try:
        path = demo_service.resolve_sample_asset(name)
    except DemoServiceError as error:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if error.code == "sample_not_found"
            else status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(
            status_code=status_code,
            content=DemoErrorResponse(code=error.code, message=error.message).model_dump(
                mode="json"
            ),
        )
    return FileResponse(path=path, filename=path.name)


@router.get(
    "/sessions/{session_id}/overview",
    response_model=DemoSessionOverview,
    responses={status.HTTP_404_NOT_FOUND: {"model": DemoErrorResponse}},
)
async def get_demo_session_overview(
    session_id: UUID,
    demo_service: Annotated[DemoService, Depends(get_demo_service)],
) -> DemoSessionOverview | JSONResponse:
    try:
        return await demo_service.get_session_overview(session_id)
    except DemoServiceError as error:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if error.code == "session_not_found"
            else status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(
            status_code=status_code,
            content=DemoErrorResponse(code=error.code, message=error.message).model_dump(
                mode="json"
            ),
        )
