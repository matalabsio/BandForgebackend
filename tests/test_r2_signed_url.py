"""Regression: generate_signed_url must read bucket from settings."""

from unittest.mock import MagicMock, patch

from app.storage.r2 import generate_signed_url


def test_generate_signed_url_uses_settings_bucket():
    with patch("app.storage.r2.get_settings") as gs, patch(
        "app.storage.r2._s3_client"
    ) as client_fn:
        settings = MagicMock()
        settings.r2_access_key_id = "key"
        settings.r2_secret_access_key = "secret"
        settings.r2_bucket_name = "my-bucket"
        gs.return_value = settings
        client = MagicMock()
        client.generate_presigned_url.return_value = "https://example.com/signed"
        client_fn.return_value = client

        url = generate_signed_url("listening/m01/part-1/full.mp3", expiry=60)

    assert url == "https://example.com/signed"
    client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "my-bucket", "Key": "listening/m01/part-1/full.mp3"},
        ExpiresIn=60,
    )
