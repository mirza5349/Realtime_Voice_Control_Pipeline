from fastapi import APIRouter

from app.api.routes.audio import router as audio_router
from app.api.routes.demo import router as demo_router
from app.api.routes.live_audio import router as live_audio_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.session import router as session_router
from app.api.routes.transcription import router as transcription_router
from app.api.ws.routes import router as ws_router
from app.core.config import Settings


def create_api_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix=settings.app_api_v1_prefix)
    router.include_router(audio_router)
    router.include_router(demo_router)
    router.include_router(live_audio_router)
    router.include_router(metrics_router)
    router.include_router(session_router)
    router.include_router(transcription_router)
    router.include_router(ws_router)
    return router
