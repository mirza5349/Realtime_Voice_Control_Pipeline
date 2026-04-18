from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import FileResponse, JSONResponse

from app.models.audio import AudioAssetErrorResponse
from app.services.audio_store import AudioStore

router = APIRouter(prefix="/audio", tags=["audio"])


def get_audio_store(request: Request) -> AudioStore:
    return request.app.state.audio_store


@router.get(
    "/{asset_id}",
    response_model=None,
    responses={status.HTTP_404_NOT_FOUND: {"model": AudioAssetErrorResponse}},
)
def get_audio_asset(
    asset_id: UUID,
    audio_store: Annotated[AudioStore, Depends(get_audio_store)],
):
    asset = audio_store.get_asset(asset_id)
    if asset is None:
        error_response = AudioAssetErrorResponse(
            code="audio_asset_not_found",
            message="Audio asset not found",
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=error_response.model_dump(mode="json"),
        )

    return FileResponse(
        path=asset.file_path,
        media_type=asset.content_type,
        filename=asset.filename,
        headers={"Cache-Control": "no-store"},
    )
