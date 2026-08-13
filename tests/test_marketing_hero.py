"""Public landing hero — only hero-intro, cache, processing refresh."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.admin import stream_videos as sv
from app.storage.stream import StreamError


def _sb_with_rows(rows: list[dict]) -> MagicMock:
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.update.return_value = chain
    chain.execute.return_value = MagicMock(data=rows)
    sb = MagicMock()
    sb.table.return_value = chain
    return sb


def test_get_marketing_hero_empty():
    settings = MagicMock()
    settings.stream_customer_code = "customer-abc"
    with (
        patch("app.cache.hybrid_cache.get_json", return_value=None),
        patch("app.cache.hybrid_cache.set_json") as set_json,
        patch("app.admin.stream_videos.get_supabase", return_value=_sb_with_rows([])),
        patch("app.admin.stream_videos.get_settings", return_value=settings),
    ):
        out = sv.get_marketing_hero()
    assert out["configured"] is False
    assert out["stream_uid"] == ""
    assert out["status"] == ""
    set_json.assert_called()


def test_get_marketing_hero_ready_only_hero_fields():
    settings = MagicMock()
    settings.stream_customer_code = "customer-abc"
    uid = "aaa111aaa111aaa111aaa111aaa111aa"
    with (
        patch("app.cache.hybrid_cache.get_json", return_value=None),
        patch("app.cache.hybrid_cache.set_json"),
        patch(
            "app.admin.stream_videos.get_supabase",
            return_value=_sb_with_rows(
                [{"title": "Talking head", "stream_uid": uid, "status": "ready"}]
            ),
        ),
        patch("app.admin.stream_videos.get_settings", return_value=settings),
    ):
        out = sv.get_marketing_hero()
    assert out["configured"] is True
    assert out["stream_uid"] == uid
    assert out["customer_code"] == "customer-abc"
    assert out["status"] == "ready"
    assert uid in out["poster_url"]
    assert "listening-intro" not in str(out)
    assert set(out) == {
        "configured",
        "stream_uid",
        "customer_code",
        "poster_url",
        "status",
        "title",
    }


def test_get_marketing_hero_processing_not_configured():
    settings = MagicMock()
    settings.stream_customer_code = "customer-abc"
    uid = "bbb222bbb222bbb222bbb222bbb222bb"
    with (
        patch("app.cache.hybrid_cache.get_json", return_value=None),
        patch("app.cache.hybrid_cache.set_json"),
        patch(
            "app.admin.stream_videos.get_supabase",
            return_value=_sb_with_rows(
                [{"title": "Talking head", "stream_uid": uid, "status": "processing"}]
            ),
        ),
        patch("app.admin.stream_videos.get_settings", return_value=settings),
        patch.object(sv, "get_video", return_value={"status": {"state": "inprogress"}}),
    ):
        out = sv.get_marketing_hero()
    assert out["configured"] is False
    assert out["status"] == "processing"
    assert out["stream_uid"] == uid


def test_get_marketing_hero_processing_refreshes_to_ready():
    settings = MagicMock()
    settings.stream_customer_code = "customer-abc"
    uid = "ccc333ccc333ccc333ccc333ccc333cc"
    with (
        patch("app.cache.hybrid_cache.get_json", return_value=None),
        patch("app.cache.hybrid_cache.set_json"),
        patch(
            "app.admin.stream_videos.get_supabase",
            return_value=_sb_with_rows(
                [{"title": "Talking head", "stream_uid": uid, "status": "processing"}]
            ),
        ),
        patch("app.admin.stream_videos.get_settings", return_value=settings),
        patch.object(sv, "get_video", return_value={"status": {"state": "ready"}}),
    ):
        out = sv.get_marketing_hero()
    assert out["configured"] is True
    assert out["status"] == "ready"
    assert out["stream_uid"] == uid


def test_get_marketing_hero_uses_cache():
    cached = {
        "configured": True,
        "stream_uid": "cached",
        "customer_code": "customer-abc",
        "poster_url": "https://x",
        "status": "ready",
        "title": "Talking head",
    }
    with (
        patch("app.cache.hybrid_cache.get_json", return_value=cached),
        patch("app.admin.stream_videos.get_supabase") as get_sb,
    ):
        out = sv.get_marketing_hero()
    assert out == cached
    get_sb.assert_not_called()


def test_complete_hero_invalidates_cache():
    chain = MagicMock()
    chain.upsert.return_value = chain
    chain.execute.return_value = MagicMock(
        data=[{"tag": "hero-intro", "stream_uid": "uid"}]
    )
    sb = MagicMock()
    sb.table.return_value = chain
    with (
        patch.object(sv, "get_video", return_value={"status": {"state": "ready"}, "duration": 90}),
        patch.object(sv, "_customer_code", return_value="customer-abc"),
        patch.object(sv, "_sync_skill_hubs", return_value=0),
        patch.object(sv, "invalidate_hero_cache") as inv,
        patch.object(sv, "log_admin_action"),
        patch("app.admin.stream_videos.get_supabase", return_value=sb),
    ):
        sv.complete_stream_video(
            tag="hero-intro",
            title="Talking head",
            stream_uid="479d46fb3847e47b3a569d6a9ae05586",
            admin_id="admin-1",
        )
    inv.assert_called_once()


def test_complete_skill_does_not_invalidate_hero_cache():
    chain = MagicMock()
    chain.upsert.return_value = chain
    chain.execute.return_value = MagicMock(
        data=[{"tag": "listening-intro", "stream_uid": "uid"}]
    )
    sb = MagicMock()
    sb.table.return_value = chain
    with (
        patch.object(sv, "get_video", return_value={"status": {"state": "ready"}, "duration": 90}),
        patch.object(sv, "_customer_code", return_value="customer-abc"),
        patch.object(sv, "_sync_skill_hubs", return_value=1),
        patch.object(sv, "invalidate_hero_cache") as inv,
        patch.object(sv, "log_admin_action"),
        patch("app.admin.stream_videos.get_supabase", return_value=sb),
    ):
        sv.complete_stream_video(
            tag="listening-intro",
            title="Listening intro",
            stream_uid="479d46fb3847e47b3a569d6a9ae05586",
            admin_id="admin-1",
        )
    inv.assert_not_called()


def test_delete_hero_invalidates_cache():
    chain = MagicMock()
    chain.select.return_value = chain
    chain.delete.return_value = chain
    chain.eq.return_value = chain
    chain.execute.side_effect = [
        MagicMock(data=[{"tag": "hero-intro"}]),
        MagicMock(data=[]),
    ]
    sb = MagicMock()
    sb.table.return_value = chain
    with (
        patch.object(sv, "delete_video"),
        patch.object(sv, "_clear_skill_hubs", return_value=0),
        patch.object(sv, "invalidate_hero_cache") as inv,
        patch.object(sv, "log_admin_action"),
        patch("app.admin.stream_videos.get_supabase", return_value=sb),
    ):
        sv.delete_stream_library_video(
            stream_uid="479d46fb3847e47b3a569d6a9ae05586",
            admin_id="admin-1",
        )
    inv.assert_called_once()


def test_get_video_error_keeps_processing():
    settings = MagicMock()
    settings.stream_customer_code = "customer-abc"
    uid = "ddd444ddd444ddd444ddd444ddd444dd"
    with (
        patch("app.cache.hybrid_cache.get_json", return_value=None),
        patch("app.cache.hybrid_cache.set_json"),
        patch(
            "app.admin.stream_videos.get_supabase",
            return_value=_sb_with_rows(
                [{"title": "Talking head", "stream_uid": uid, "status": "processing"}]
            ),
        ),
        patch("app.admin.stream_videos.get_settings", return_value=settings),
        patch.object(sv, "get_video", side_effect=StreamError("down", status_code=502)),
    ):
        out = sv.get_marketing_hero()
    assert out["configured"] is False
    assert out["status"] == "processing"
