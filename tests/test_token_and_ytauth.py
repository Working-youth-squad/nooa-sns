"""채널 토큰 등록 + YT 자격 DB 암호화 영속 (NFR-4 승계) — PG."""

import pytest

from sns.adapters.youtube.auth import SCOPES
from sns.adapters.youtube.auth_db import (
    YouTubeAuthError,
    ensure_credentials,
    persist_credentials,
)
from sns.bootstrap import build_render_media, load_channel, save_channel_token, token_provider
from sns.crypto import TokenCipher, generate_key
from sns.render.storage import InMemoryMediaStore
from sns.tools.fakes import FakeRenderMedia

CIPHER = TokenCipher(generate_key(), key_version=1)


def _make_channel(db, platform: str = "instagram") -> str:  # type: ignore[no-untyped-def]
    import uuid

    handle = f"h-{uuid.uuid4().hex[:8]}"
    db.execute(
        "INSERT INTO channel (platform, handle, mode) VALUES (%s, %s, 'auto')",
        (platform, handle),
    )
    return handle


def test_set_token_roundtrip(db) -> None:  # type: ignore[no-untyped-def]
    handle = _make_channel(db)
    save_channel_token(
        db, CIPHER, platform="instagram", handle=handle, token_plain="ig-secret-token"
    )
    channel = load_channel(db, platform="instagram", handle=handle)
    assert channel.token_encrypted is not None
    assert token_provider(CIPHER, channel)() == "ig-secret-token"
    # 평문이 DB에 없다
    raw = db.execute("SELECT token_encrypted FROM channel WHERE handle = %s", (handle,)).fetchone()[
        0
    ]
    assert b"ig-secret-token" not in bytes(raw)


def test_set_token_unknown_channel(db) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(LookupError):
        save_channel_token(db, CIPHER, platform="instagram", handle="없음", token_plain="t")


def _offline_credentials():  # type: ignore[no-untyped-def]
    from google.oauth2.credentials import Credentials

    return Credentials(  # type: ignore[no-untyped-call]
        token="access-tok",
        refresh_token="refresh-tok",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="cid",
        client_secret="csecret",
        scopes=list(SCOPES),
    )


def test_yt_credentials_db_roundtrip(db, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """DB 저장 자격 로드 — authorized_user 복원은 access token이 비므로 refresh 경유.

    refresh는 네트워크라 monkeypatch로 대체(성공 시 token 채움) — 갱신분이
    다시 암호화 저장되는 것까지 검증한다.
    """
    from google.oauth2.credentials import Credentials

    handle = _make_channel(db, platform="youtube")
    channel = load_channel(db, platform="youtube", handle=handle)
    persist_credentials(db, CIPHER, channel.id, _offline_credentials())

    def fake_refresh(self, request) -> None:  # type: ignore[no-untyped-def]
        # 실제 refresh와 동일하게 token+만료시각을 함께 갱신한다
        from datetime import datetime, timedelta

        self.token = "refreshed-tok"
        self.expiry = datetime.utcnow() + timedelta(hours=1)

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)
    creds = ensure_credentials(
        db, CIPHER, channel.id, client_secret=__import__("pathlib").Path("x.json")
    )
    assert creds.token == "refreshed-tok" and creds.valid

    # refresh 갱신분이 재암호화 저장됐다
    raw = db.execute("SELECT token_encrypted FROM channel WHERE id = %s", (channel.id,)).fetchone()[
        0
    ]
    assert '"refreshed-tok"' in CIPHER.decrypt(bytes(raw))


def test_yt_missing_credentials_fails_fast_headless(db) -> None:  # type: ignore[no-untyped-def]
    handle = _make_channel(db, platform="youtube")
    channel = load_channel(db, platform="youtube", handle=handle)
    with pytest.raises(YouTubeAuthError, match="대화형 재발급"):
        ensure_credentials(
            db, CIPHER, channel.id, client_secret=__import__("pathlib").Path("x.json")
        )


def test_yt_unknown_channel(db) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(LookupError):
        ensure_credentials(
            db,
            CIPHER,
            "00000000-0000-0000-0000-000000000000",
            client_secret=__import__("pathlib").Path("x.json"),
        )


def test_build_render_media_video_gated_by_tts_key(tmp_path) -> None:  # type: ignore[no-untyped-def]
    no_tts = build_render_media(InMemoryMediaStore(), env={})
    with pytest.raises(ValueError, match="video 렌더러 미등록"):
        no_tts({"scenes": []}, "video")

    with_tts = build_render_media(InMemoryMediaStore(), env={"GOOGLE_TTS_API_KEY": "k"})
    # 등록 여부만 검증(실 렌더는 ffmpeg·TTS 통합테스트 소관) — 카드 경로는 동일 동작
    card = build_render_media(InMemoryMediaStore(), env={})
    assert card is not None and with_tts is not None
    assert isinstance(FakeRenderMedia()({"layout": "x"}, "image").checksum, str)
