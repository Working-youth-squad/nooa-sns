"""LocalDirMediaStore (FR-M3) — 공개 URL 매핑·멱등·역조회·경로 탈출 차단 (전 플랫폼)."""

from pathlib import Path

import pytest

from sns.render.storage_local import LocalDirMediaStore


def test_put_returns_public_url_and_roundtrip(tmp_path: Path) -> None:
    store = LocalDirMediaStore(tmp_path, base_url="https://media.example.com/sns/")
    url = store.put(b"png-bytes", checksum="abc123", kind="image", ext="png")

    assert url == "https://media.example.com/sns/image/abc123.png"
    assert (tmp_path / "image" / "abc123.png").read_bytes() == b"png-bytes"
    assert store.load(url) == b"png-bytes"


def test_same_checksum_idempotent(tmp_path: Path) -> None:
    store = LocalDirMediaStore(tmp_path, base_url="https://m.ex")
    url1 = store.put(b"v1", checksum="c", kind="image", ext="png")
    url2 = store.put(b"v2-ignored", checksum="c", kind="image", ext="png")

    assert url1 == url2
    assert store.load(url1) == b"v1", "콘텐츠 주소화 — 같은 checksum 재기록 없음"


def test_load_rejects_foreign_url_and_escape(tmp_path: Path) -> None:
    store = LocalDirMediaStore(tmp_path, base_url="https://m.ex")
    with pytest.raises(ValueError, match="이 스토어의 URL이 아님"):
        store.load("https://other.host/image/x.png")
    with pytest.raises(ValueError, match="루트 밖"):
        store.load("https://m.ex/../secrets.txt")
