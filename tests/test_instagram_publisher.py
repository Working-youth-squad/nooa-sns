"""IG Graph 어댑터 — 2단계 발행·컨테이너 재사용·오류 분류 (FR-P1·P4, 전 플랫폼 실행)."""

import json
from collections.abc import Callable

import httpx
import pytest

from sns.adapters.instagram import InstagramPublish, classify_graph_error
from sns.tools.contracts import MediaAsset

IMAGE = MediaAsset(kind="image", storage_url="https://cdn.example/card.png", checksum="c1")
VIDEO = MediaAsset(kind="video", storage_url="https://cdn.example/reel.mp4", checksum="v1")


def make_publisher(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    sleeps: list[float] | None = None,
    max_status_checks: int = 30,
) -> InstagramPublish:
    return InstagramPublish(
        ig_user_id="17840000",
        access_token=lambda: "tok-decrypted",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
        max_status_checks=max_status_checks,
    )


def test_image_two_step_publish() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        body = request.read().decode()
        assert "access_token=tok-decrypted" in body, "토큰 미탑재"
        if request.url.path.endswith("/media"):
            assert "image_url" in body and "media_type" not in body
            return httpx.Response(200, json={"id": "container-1"})
        return httpx.Response(200, json={"id": "post-1"})

    result = make_publisher(handler)("instagram", IMAGE, "캡션", "pub-1")

    assert result.post_id == "post-1"
    assert result.container_id == "container-1"
    assert result.error is None
    assert [p.split("/")[-1] for p in calls] == ["media", "media_publish"]


def test_container_reuse_skips_creation() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"id": "post-2"})

    result = make_publisher(handler)("instagram", IMAGE, "캡션", "pub-1", container_id="c-saved")

    assert result.post_id == "post-2" and result.container_id == "c-saved"
    assert [p.split("/")[-1] for p in calls] == ["media_publish"], "컨테이너 재사용 실패"


def test_video_polls_until_finished() -> None:
    statuses = iter(["IN_PROGRESS", "IN_PROGRESS", "FINISHED"])
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status_code": next(statuses)})
        if request.url.path.endswith("/media"):
            body = request.read().decode()
            assert "media_type=REELS" in body and "video_url" in body
            return httpx.Response(200, json={"id": "vc-1"})
        return httpx.Response(200, json={"id": "vpost-1"})

    result = make_publisher(handler, sleeps=sleeps)("instagram", VIDEO, "릴스", "pub-2")

    assert result.post_id == "vpost-1"
    assert len(sleeps) == 2, "IN_PROGRESS 동안만 대기해야 함"


def test_video_processing_error_is_terminal_with_container_preserved() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status_code": "ERROR"})
        return httpx.Response(200, json={"id": "vc-err"})

    result = make_publisher(handler)("instagram", VIDEO, "릴스", "pub-3")

    assert result.error is not None and result.error.error_class == "permanent_unknown"
    assert result.container_id == "vc-err", "실패해도 컨테이너 진척은 보존(재시작 복구)"


def test_poll_timeout_is_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"status_code": "IN_PROGRESS"})
        return httpx.Response(200, json={"id": "vc-slow"})

    result = make_publisher(handler, max_status_checks=2)("instagram", VIDEO, "릴스", "pub-4")

    assert result.error is not None and result.error.error_class == "transient"
    assert result.container_id == "vc-slow"


@pytest.mark.parametrize(
    ("status", "error_body", "expected"),
    [
        (400, {"error": {"code": 190}}, "auth"),
        (401, {}, "auth"),
        (429, {}, "quota"),
        (400, {"error": {"code": 4}}, "quota"),
        (400, {"error": {"code": 368}}, "spam_block"),
        (500, {}, "transient"),
        (400, {"error": {"code": 9999}}, "permanent_unknown"),
    ],
)
def test_graph_error_classification(status: int, error_body: dict, expected: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=json.dumps(error_body).encode())

    result = make_publisher(handler)("instagram", IMAGE, "캡션", "pub-5")

    assert result.error is not None and result.error.error_class == expected
    assert result.error.error_raw, "원문 미보존 (FR-P4)"


def test_network_error_is_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = make_publisher(handler)("instagram", IMAGE, "캡션", "pub-6")
    assert result.error is not None and result.error.error_class == "transient"


def test_wrong_platform_and_kind_rejected() -> None:
    pub = make_publisher(lambda _: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="platform"):
        pub("youtube", IMAGE, "c", "k")
    with pytest.raises(ValueError, match="image"):
        pub("instagram", MediaAsset(kind="audio", storage_url="u", checksum="c"), "c", "k")


def test_classify_pure_table() -> None:
    assert classify_graph_error(200, 190, None) == "auth"
    assert classify_graph_error(200, 17, None) == "quota"
    assert classify_graph_error(503, None, None) == "transient"
    assert classify_graph_error(200, None, None) == "permanent_unknown"
