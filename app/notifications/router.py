"""Public callback routes for notification providers."""

from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import PlainTextResponse

from app.notifications import webhook

router = APIRouter(prefix="/api/webhooks/meta/whatsapp", tags=["webhooks"])


@router.get("", response_class=PlainTextResponse)
def meta_whatsapp_challenge(
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> str:
    return webhook.verify_challenge(
        mode=mode, token=verify_token, challenge=challenge
    )


@router.post("")
async def meta_whatsapp_statuses(
    request: Request,
    signature: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> dict[str, Any]:
    raw = await request.body()
    webhook.verify_signature(raw, signature)
    payload = await request.json()
    return {"ok": True, "processed": webhook.process_payload(payload)}
