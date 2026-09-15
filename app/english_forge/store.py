"""Persistence for English Forge — Supabase with in-memory fallback.

Always mirrors successful DB rows into memory so updates still work when
PostgREST returns empty under RLS / no-returning quirks.
"""

from __future__ import annotations

import logging
import threading
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_sessions: dict[str, dict[str, Any]] = {}
_responses: dict[str, dict[str, Any]] = {}
_evaluations: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _use_db() -> bool:
    try:
        from app.db.supabase_client import get_supabase

        get_supabase()
        return True
    except Exception:  # noqa: BLE001
        return False


def _mem_put_session(row: dict[str, Any]) -> None:
    with _lock:
        _sessions[str(row["id"])] = deepcopy(row)


def _mem_put_response(row: dict[str, Any]) -> None:
    with _lock:
        _responses[str(row["id"])] = deepcopy(row)


def _mem_put_evaluation(row: dict[str, Any]) -> None:
    with _lock:
        _evaluations[str(row["id"])] = deepcopy(row)


def create_session(row: dict[str, Any]) -> dict[str, Any]:
    payload = {
        **row,
        "id": str(row.get("id") or uuid4()),
        "created_at": _now(),
        "updated_at": _now(),
    }
    if _use_db():
        try:
            from app.db.supabase_client import get_supabase

            res = get_supabase().table("english_forge_sessions").insert(payload).execute()
            data = (res.data or [None])[0]
            if data:
                _mem_put_session(data)
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("EF session DB insert failed, using memory: %s", exc)
    _mem_put_session(payload)
    return payload


def get_session(session_id: UUID | str) -> dict[str, Any] | None:
    sid = str(session_id)
    if _use_db():
        try:
            from app.db.supabase_client import get_supabase

            res = (
                get_supabase()
                .table("english_forge_sessions")
                .select("*")
                .eq("id", sid)
                .limit(1)
                .execute()
            )
            if res.data:
                _mem_put_session(res.data[0])
                return res.data[0]
        except Exception as exc:  # noqa: BLE001
            logger.debug("EF session DB read failed: %s", exc)
    with _lock:
        row = _sessions.get(sid)
        return deepcopy(row) if row else None


def update_session(session_id: UUID | str, patch: dict[str, Any]) -> dict[str, Any] | None:
    sid = str(session_id)
    patch = {**patch, "updated_at": _now()}
    if _use_db():
        try:
            from app.db.supabase_client import get_supabase

            res = (
                get_supabase()
                .table("english_forge_sessions")
                .update(patch)
                .eq("id", sid)
                .execute()
            )
            if res.data:
                _mem_put_session(res.data[0])
                return res.data[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning("EF session DB update failed: %s", exc)
    with _lock:
        row = _sessions.get(sid)
        if not row:
            return None
        row.update(patch)
        return deepcopy(row)


def create_response(row: dict[str, Any]) -> dict[str, Any]:
    payload = {
        **row,
        "id": str(row.get("id") or uuid4()),
        "created_at": _now(),
        "updated_at": _now(),
    }
    if _use_db():
        try:
            from app.db.supabase_client import get_supabase

            res = get_supabase().table("english_forge_responses").insert(payload).execute()
            data = (res.data or [None])[0]
            if data:
                _mem_put_response(data)
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("EF response DB insert failed, using memory: %s", exc)
    _mem_put_response(payload)
    return payload


def get_response(response_id: UUID | str) -> dict[str, Any] | None:
    rid = str(response_id)
    if _use_db():
        try:
            from app.db.supabase_client import get_supabase

            res = (
                get_supabase()
                .table("english_forge_responses")
                .select("*")
                .eq("id", rid)
                .limit(1)
                .execute()
            )
            if res.data:
                _mem_put_response(res.data[0])
                return res.data[0]
        except Exception as exc:  # noqa: BLE001
            logger.debug("EF response DB read failed: %s", exc)
    with _lock:
        row = _responses.get(rid)
        return deepcopy(row) if row else None


def get_latest_response(session_id: UUID | str) -> dict[str, Any] | None:
    sid = str(session_id)
    if _use_db():
        try:
            from app.db.supabase_client import get_supabase

            res = (
                get_supabase()
                .table("english_forge_responses")
                .select("*")
                .eq("session_id", sid)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if res.data:
                _mem_put_response(res.data[0])
                return res.data[0]
        except Exception as exc:  # noqa: BLE001
            logger.debug("EF latest response DB read failed: %s", exc)
    with _lock:
        rows = [r for r in _responses.values() if str(r.get("session_id")) == sid]
        if not rows:
            return None
        rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return deepcopy(rows[0])


def update_response(response_id: UUID | str, patch: dict[str, Any]) -> dict[str, Any] | None:
    rid = str(response_id)
    patch = {**patch, "updated_at": _now()}
    if _use_db():
        try:
            from app.db.supabase_client import get_supabase

            res = (
                get_supabase()
                .table("english_forge_responses")
                .update(patch)
                .eq("id", rid)
                .execute()
            )
            if res.data:
                _mem_put_response(res.data[0])
                return res.data[0]
            # Empty return — still apply locally then re-read
            logger.warning("EF response DB update returned empty for %s", rid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("EF response DB update failed: %s", exc)
    with _lock:
        row = _responses.get(rid)
        if not row:
            # Hydrate from DB if possible
            pass
        else:
            row.update(patch)
            return deepcopy(row)
    # Last resort: hydrate then patch
    existing = get_response(rid)
    if not existing:
        return None
    existing.update(patch)
    _mem_put_response(existing)
    if _use_db():
        try:
            from app.db.supabase_client import get_supabase

            get_supabase().table("english_forge_responses").update(patch).eq("id", rid).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("EF response DB update retry failed: %s", exc)
    return existing


def upsert_evaluation(session_id: UUID | str, row: dict[str, Any]) -> dict[str, Any]:
    sid = str(session_id)
    payload = {
        **row,
        "session_id": sid,
        "updated_at": _now(),
    }
    if _use_db():
        try:
            from app.db.supabase_client import get_supabase

            existing = (
                get_supabase()
                .table("english_forge_evaluations")
                .select("id")
                .eq("session_id", sid)
                .limit(1)
                .execute()
            )
            if existing.data:
                eid = existing.data[0]["id"]
                res = (
                    get_supabase()
                    .table("english_forge_evaluations")
                    .update(payload)
                    .eq("id", eid)
                    .execute()
                )
                if res.data:
                    _mem_put_evaluation(res.data[0])
                    return res.data[0]
                payload = {**payload, "id": str(eid)}
            else:
                payload = {**payload, "id": str(uuid4()), "created_at": _now()}
                res = (
                    get_supabase()
                    .table("english_forge_evaluations")
                    .insert(payload)
                    .execute()
                )
                if res.data:
                    _mem_put_evaluation(res.data[0])
                    return res.data[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning("EF evaluation DB upsert failed, using memory: %s", exc)
    with _lock:
        existing = next(
            (e for e in _evaluations.values() if str(e.get("session_id")) == sid),
            None,
        )
        if existing:
            existing.update(payload)
            return deepcopy(existing)
        payload = {**payload, "id": str(payload.get("id") or uuid4()), "created_at": _now()}
        _evaluations[payload["id"]] = deepcopy(payload)
        return payload


def get_evaluation(session_id: UUID | str) -> dict[str, Any] | None:
    sid = str(session_id)
    if _use_db():
        try:
            from app.db.supabase_client import get_supabase

            res = (
                get_supabase()
                .table("english_forge_evaluations")
                .select("*")
                .eq("session_id", sid)
                .limit(1)
                .execute()
            )
            if res.data:
                _mem_put_evaluation(res.data[0])
                return res.data[0]
        except Exception as exc:  # noqa: BLE001
            logger.debug("EF evaluation DB read failed: %s", exc)
    with _lock:
        row = next((e for e in _evaluations.values() if str(e.get("session_id")) == sid), None)
        return deepcopy(row) if row else None
