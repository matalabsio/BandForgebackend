"""Admin Cloudflare Stream library + practice-hub video sync."""

from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from typing import Any

from fastapi import HTTPException, status

from app.admin.audit import log_admin_action
from app.config import get_settings
from app.db.supabase_client import get_supabase
from app.storage.stream import (
    StreamError,
    create_direct_upload,
    get_video,
    normalize_customer_code,
    playback_iframe_url,
)

STREAM_TAGS = (
    "bandforge-intro",
    "ielts-intro",
    "listening-intro",
    "reading-intro",
    "writing-intro",
    "speaking-intro",
)

SKILL_TAG_MAP = {
    "listening-intro": "listening",
    "reading-intro": "reading",
    "writing-intro": "writing",
    "speaking-intro": "speaking",
}


def assert_valid_tag(tag: str) -> str:
    value = (tag or "").strip().lower()
    if value not in STREAM_TAGS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tag. Use one of: {', '.join(STREAM_TAGS)}.",
        )
    return value


def _customer_code() -> str:
    settings = get_settings()
    code = normalize_customer_code(settings.stream_customer_code)
    if not code:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STREAM_CUSTOMER_CODE is not configured.",
        )
    return code


def _raise_stream(exc: StreamError) -> None:
    raise HTTPException(exc.status_code, detail=str(exc)) from exc


def merge_hub_videos(
    existing: list[Any],
    *,
    title: str,
    url: str,
    duration_min: int,
    tag: str,
    stream_uid: str,
) -> list[dict[str, Any]]:
    entry = {
        "title": title,
        "url": url,
        "duration_min": int(duration_min or 0),
        "tag": tag,
        "stream_uid": stream_uid,
    }
    videos: list[dict[str, Any]] = []
    replaced_tag = False
    for item in existing or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("tag") or "").strip() == tag:
            videos.append(entry)
            replaced_tag = True
        else:
            videos.append(item)
    if replaced_tag:
        return videos

    replaced_empty = False
    out: list[dict[str, Any]] = []
    for item in videos:
        if not replaced_empty and not str(item.get("url") or "").strip():
            out.append(entry)
            replaced_empty = True
        else:
            out.append(item)
    if not replaced_empty:
        out.append(entry)
    return out


def list_stream_videos() -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("stream_videos")
        .select("*")
        .order("updated_at", desc=True)
        .execute()
    )
    return list(result.data or [])


def start_direct_upload(*, tag: str, title: str, max_duration_seconds: int = 3600) -> dict[str, str]:
    assert_valid_tag(tag)
    _customer_code()
    try:
        created = create_direct_upload(title=title, max_duration_seconds=max_duration_seconds)
    except StreamError as exc:
        _raise_stream(exc)
    return created


def _duration_minutes(video: dict[str, Any] | None, fallback_min: int) -> int:
    if fallback_min > 0:
        return fallback_min
    if not video:
        return 0
    try:
        secs = float(video.get("duration") or 0)
    except (TypeError, ValueError):
        return 0
    if secs <= 0:
        return 0
    return max(1, ceil(secs / 60))


def _status_from_video(video: dict[str, Any] | None) -> str:
    if not video:
        return "processing"
    state = str((video.get("status") or {}).get("state") or "").strip().lower()
    if state in {"ready", "complete"}:
        return "ready"
    if state in {"error", "failed"}:
        return "error"
    return "processing"


def _sync_skill_hubs(
    *,
    tag: str,
    title: str,
    playback_url: str,
    duration_min: int,
    stream_uid: str,
) -> int:
    skill = SKILL_TAG_MAP.get(tag)
    if not skill:
        return 0
    sb = get_supabase()
    result = (
        sb.table("practice_hubs")
        .select("id, videos, practice_sets!inner(practice_banks!inner(skill))")
        .eq("practice_sets.practice_banks.skill", skill)
        .execute()
    )
    rows = list(result.data or [])
    updated = 0
    for row in rows:
        hub_id = str(row.get("id") or "")
        if not hub_id:
            continue
        merged = merge_hub_videos(
            list(row.get("videos") or []),
            title=title,
            url=playback_url,
            duration_min=duration_min,
            tag=tag,
            stream_uid=stream_uid,
        )
        sb.table("practice_hubs").update({"videos": merged}).eq("id", hub_id).execute()
        updated += 1
    if updated:
        from app.cache.hybrid_cache import invalidate_prefix
        from app.practice.repository import clear_hub_list_cache

        clear_hub_list_cache()
        invalidate_prefix("practice:hub:detail:")
    return updated


def complete_stream_video(
    *,
    tag: str,
    title: str,
    stream_uid: str,
    duration_min: int = 0,
    admin_id,
) -> dict[str, Any]:
    tag = assert_valid_tag(tag)
    uid = (stream_uid or "").strip()
    if not uid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="stream_uid is required.")
    label = (title or "").strip() or tag.replace("-", " ").title()
    try:
        stream_meta = get_video(uid)
    except StreamError:
        stream_meta = None
    minutes = _duration_minutes(stream_meta, int(duration_min or 0))
    playback = playback_iframe_url(customer_code=_customer_code(), stream_uid=uid)
    video_status = _status_from_video(stream_meta)
    now = datetime.now(UTC).isoformat()
    payload = {
        "tag": tag,
        "title": label,
        "stream_uid": uid,
        "playback_url": playback,
        "duration_min": minutes,
        "status": video_status,
        "updated_at": now,
    }
    sb = get_supabase()
    result = (
        sb.table("stream_videos")
        .upsert(payload, on_conflict="tag")
        .execute()
    )
    rows = list(result.data or [])
    saved = rows[0] if rows else payload
    hubs_updated = _sync_skill_hubs(
        tag=tag,
        title=label,
        playback_url=playback,
        duration_min=minutes,
        stream_uid=uid,
    )
    log_admin_action(
        admin_id=admin_id,
        action="stream.video_complete",
        resource_type="stream_video",
        resource_id=uid,
        metadata={"tag": tag, "hubs_updated": hubs_updated, "duration_min": minutes},
    )
    return {**saved, "hubs_updated": hubs_updated, "playback_url": playback}
