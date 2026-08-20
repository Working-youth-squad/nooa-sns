"""플랫폼 → 어댑터 디스패처 — `Publish` 계약 합성 (FR-P1·P2)."""

from collections.abc import Mapping

from sns.tools.contracts import MediaAsset, Platform, Publish, PublishResult


class PlatformDispatch:
    """platform 값으로 실제 어댑터(IG/YT)를 고르는 `Publish` 구현."""

    def __init__(self, routes: Mapping[Platform, Publish]) -> None:
        self._routes = dict(routes)

    def __call__(
        self,
        platform: Platform,
        media: MediaAsset,
        caption: str,
        idempotency_key: str,
        container_id: str | None = None,
    ) -> PublishResult:
        route = self._routes.get(platform)
        if route is None:
            raise ValueError(f"등록되지 않은 발행 플랫폼: {platform}")
        return route(platform, media, caption, idempotency_key, container_id)


# 계약 적합성을 mypy가 강제.
_check_dispatch: Publish = PlatformDispatch({})
