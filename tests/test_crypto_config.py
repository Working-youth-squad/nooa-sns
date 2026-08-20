"""NFR-4 — 설정 fail-fast + 토큰 암복호 (nooa 무관, 전 플랫폼)."""

import pytest

from sns.config import Config, ConfigError
from sns.crypto import DecryptionError, TokenCipher, generate_key

BASE_ENV = {"DATABASE_URL": "postgresql://x/y"}


def test_missing_encryption_key_fails_boot() -> None:
    with pytest.raises(ConfigError, match="APP_ENCRYPTION_KEY"):
        Config.from_env(BASE_ENV)


def test_invalid_encryption_key_fails_boot() -> None:
    with pytest.raises(ConfigError, match="Fernet"):
        Config.from_env({**BASE_ENV, "APP_ENCRYPTION_KEY": "평문키아님"})


def test_roundtrip_and_tamper_detection() -> None:
    cipher = TokenCipher(generate_key(), key_version=1)
    token, version = cipher.encrypt("ig-access-token-비밀")
    assert version == 1
    assert cipher.decrypt(token) == "ig-access-token-비밀"
    with pytest.raises(DecryptionError):
        cipher.decrypt(b"tampered" + token)


def test_wrong_key_rejected() -> None:
    token, _ = TokenCipher(generate_key(), 1).encrypt("secret")
    with pytest.raises(DecryptionError):
        TokenCipher(generate_key(), 2).decrypt(token)
