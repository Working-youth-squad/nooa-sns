"""`PollMetrics` 계약의 인스타그램 구현 — Graph API 미디어 인사이트 (FR-L1).

metric_key 표준(원본 11-데이터모델 §4, fakes.PLATFORM_METRIC_KEYS와 동일 집합)을
항상 전부 반환한다: API가 주지 않는 키는 missing=True·value=NULL — 0 대체 금지
(NFR-3). 오류는 예외로 전파한다(폴링 격리는 학습 루프의 몫).

토큰은 콜러블 주입(FR-S3), 공식 API만(개발원칙 1).
"""

from collections.abc import Callable
from typing import Any

import httpx

from sns.tools.contracts import MetricValue, Platform, PollMetrics

GRAPH_BASE = "https://graph.facebook.com"

# 표준 metric_key → Graph insights metric 이름
_KEY_TO_GRAPH: dict[str, str] = {
    "reach": "reach",
    "likes": "likes",
    "shares": "shares",
    "saved": "saved",
    "comments": "comments",
    "views": "views",
    "avg_watch_time_ms": "ig_reels_avg_watch_time",  # 릴스 전용 — 이미지 게시물은 결측
}
STANDARD_KEYS: tuple[str, ...] = tuple(_KEY_TO_GRAPH)


class InstagramInsightsError(RuntimeError):
    """인사이트 조회 실패 — 원문 보존."""


class InstagramInsights:
    def __init__(
        self,
        *,
        access_token: Callable[[], str],
        client: httpx.Client | None = None,
        api_version: str = "v21.0",
    ) -> None:
        self._access_token = access_token
        self._client = client or httpx.Client(timeout=30.0)
        self._base = f"{GRAPH_BASE}/{api_version}"

    def __call__(
        self, platform: Platform, post_id: str, window_index: int
    ) -> tuple[MetricValue, ...]:
        if platform != "instagram":
            raise ValueError(f"인스타그램 인사이트가 처리할 수 없는 platform: {platform}")
        fetched = self._fetch(post_id)
        values: list[MetricValue] = []
        for key in STANDARD_KEYS:
            raw = fetched.get(_KEY_TO_GRAPH[key])
            if raw is None:
                values.append(MetricValue(metric_key=key, value=None, missing=True))
            else:
                values.append(MetricValue(metric_key=key, value=float(raw), missing=False))
        return tuple(values)

    def _fetch(self, media_id: str) -> dict[str, float]:
        try:
            response = self._client.get(
                f"{self._base}/{media_id}/insights",
                params={
                    "metric": ",".join(_KEY_TO_GRAPH.values()),
                    "access_token": self._access_token(),
                },
            )
        except (httpx.HTTPError, OSError) as exc:
            raise InstagramInsightsError(f"인사이트 요청 실패: {exc}") from exc
        try:
            payload: dict[str, Any] = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400 or "error" in payload:
            raise InstagramInsightsError(f"HTTP {response.status_code}: {response.text[:500]}")
        fetched: dict[str, float] = {}
        for entry in payload.get("data", []):
            name = entry.get("name")
            entry_values = entry.get("values") or []
            if not name or not entry_values:
                continue
            value = entry_values[0].get("value")
            if isinstance(value, (int, float)):
                fetched[str(name)] = float(value)
        return fetched


# 계약 적합성을 mypy가 강제.
_check_poll: PollMetrics = InstagramInsights(access_token=lambda: "")
