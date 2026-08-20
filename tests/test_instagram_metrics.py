"""IG 인사이트 어댑터 (FR-L1) — 표준 키 전량 반환·결측 보존·오류 전파 (전 플랫폼)."""

import httpx
import pytest

from sns.adapters.instagram.metrics import (
    STANDARD_KEYS,
    InstagramInsights,
    InstagramInsightsError,
)


def make(handler) -> InstagramInsights:  # type: ignore[no-untyped-def]
    return InstagramInsights(
        access_token=lambda: "tok",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _payload(**named: float) -> dict:
    return {"data": [{"name": k, "values": [{"value": v}]} for k, v in named.items()]}


def test_all_standard_keys_always_returned() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "access_token=tok" in str(request.url)
        return httpx.Response(
            200, json=_payload(reach=594, likes=760, views=385, ig_reels_avg_watch_time=8200)
        )

    values = make(handler)("instagram", "media-1", 0)
    by_key = {v.metric_key: v for v in values}

    assert tuple(by_key) == STANDARD_KEYS, "표준 키 전량 반환(스키마 안정)"
    assert by_key["reach"].value == 594 and not by_key["reach"].missing
    assert by_key["avg_watch_time_ms"].value == 8200, "릴스 시청시간 키 매핑"
    # API가 주지 않은 키 = 결측 보존(0 대체 금지, NFR-3)
    assert by_key["shares"].missing and by_key["shares"].value is None
    assert by_key["saved"].missing and by_key["comments"].missing


def test_api_error_raises_with_raw() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 100, "message": "Invalid metric"}})

    with pytest.raises(InstagramInsightsError, match="HTTP 400"):
        make(handler)("instagram", "media-1", 0)


def test_network_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(InstagramInsightsError, match="요청 실패"):
        make(handler)("instagram", "media-1", 0)


def test_wrong_platform_rejected() -> None:
    with pytest.raises(ValueError, match="platform"):
        make(lambda _: httpx.Response(200, json={}))("youtube", "m", 0)
