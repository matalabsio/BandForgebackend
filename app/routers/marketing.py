"""Public marketing routes — landing hero Stream metadata (no auth)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.admin.stream_videos import get_marketing_hero

router = APIRouter(prefix="/api/marketing", tags=["marketing"])


@router.get("/hero")
def marketing_hero() -> JSONResponse:
    payload = get_marketing_hero()
    ttl = 5 if payload.get("status") == "processing" else 60
    return JSONResponse(
        payload,
        headers={
            "Cache-Control": (
                f"public, max-age=0, s-maxage={ttl}, stale-while-revalidate=30"
            )
        },
    )
