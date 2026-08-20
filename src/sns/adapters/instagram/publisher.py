"""`Publish` 계약의 인스타그램 구현 — Graph API 2단계 발행 (FR-P1).

1단계 컨테이너 생성 → (영상이면 처리 대기) → 2단계 media_publish.
생성된 container_id는 오류 시에도 PublishResult에 보존한다 — 상태머신이
재시작 복구(container_created부터 재개)에 재사용한다.

액세스 토큰은 콜러블 주입: 복호화(sns.crypto)는 툴 조립부가 소유하고,
이 어댑터는 호출 시점에만 토큰을 받아 요청에 싣는다 (FR-S3).
공식 API만 사용한다 — 비공식 엔드포인트 금지 (개발원칙 1).
"""

from collections.abc import Callable
from typing import Any

import httpx

from sns.tools.contracts import (
    ErrorClass,
    MediaAsset,
    Platform,
    Publish,
    PublishResult,
    ToolError,
)

GRAPH_BASE = "https://graph.facebook.com"

# Graph API 오류 code → ErrorClass (FR-P4). 미분류는 permanent_unknown + 원문 보존.
_AUTH_CODES = frozenset({102, 190})
_QUOTA_CODES = frozenset({4, 17, 32, 613})
_SPAM_CODES = frozenset({368})
_TRANSIENT_CODES = frozenset({1, 2})  # API unknown / service


class _IgApiError(Exception):
    def __init__(self, error_class: ErrorClass, raw: str, container_id: str | None = None):
        super().__init__(raw)
        self.error_class = error_class
        self.raw = raw
        self.container_id = container_id


def classify_graph_error(status: int, code: int | None, subcode: int | None) -> ErrorClass:
    """HTTP 상태 + Graph error code/subcode → 계약 ErrorClass."""
    if status == 401 or code in _AUTH_CODES:
        return "auth"
    if status == 429 or code in _QUOTA_CODES:
        return "quota"
    if code in _SPAM_CODES:
        return "spam_block"
    if status >= 500 or code in _TRANSIENT_CODES:
        return "transient"
    return "permanent_unknown"


class InstagramPublish:
    """인스타그램 발행을 `Publish` 계약에 바인딩.

    media.storage_url은 공개 접근 가능한 URL이어야 한다(Graph API 제약 —
    호스팅은 렌더/스토리지 계층의 책무). image→피드, video→릴스(REELS).
    """

    def __init__(
        self,
        *,
        ig_user_id: str,
        access_token: Callable[[], str],
        client: httpx.Client | None = None,
        api_version: str = "v21.0",
        sleep: Callable[[float], None] | None = None,
        poll_interval_s: float = 2.0,
        max_status_checks: int = 30,
    ) -> None:
        self._ig_user_id = ig_user_id
        self._access_token = access_token
        self._client = client or httpx.Client(timeout=30.0)
        self._base = f"{GRAPH_BASE}/{api_version}"
        self._sleep = sleep if sleep is not None else _default_sleep
        self._poll_interval_s = poll_interval_s
        self._max_status_checks = max_status_checks

    def __call__(
        self,
        platform: Platform,
        media: MediaAsset,
        caption: str,
        idempotency_key: str,
        container_id: str | None = None,
    ) -> PublishResult:
        if platform != "instagram":
            raise ValueError(f"인스타그램 어댑터가 처리할 수 없는 platform: {platform}")
        if media.kind not in ("image", "video"):
            raise ValueError(f"IG 발행은 image(피드)·video(릴스)만 가능: {media.kind}")

        cid = container_id
        try:
            if cid is None:
                cid = self._create_container(media, caption)
            if media.kind == "video":
                self._wait_processed(cid)
            post_id = self._media_publish(cid)
            return PublishResult(post_id=post_id, container_id=cid)
        except _IgApiError as exc:
            return PublishResult(
                container_id=cid,
                error=ToolError(error_class=exc.error_class, error_raw=exc.raw),
            )
        except (httpx.HTTPError, OSError) as exc:  # 네트워크 계열 = 재시도 여지
            return PublishResult(
                container_id=cid,
                error=ToolError(error_class="transient", error_raw=str(exc)),
            )

    # ── Graph API 호출 ──────────────────────────────────────────────

    def _create_container(self, media: MediaAsset, caption: str) -> str:
        data: dict[str, str] = {"caption": caption}
        if media.kind == "image":
            data["image_url"] = media.storage_url
        else:
            data["media_type"] = "REELS"
            data["video_url"] = media.storage_url
        payload = self._post(f"{self._ig_user_id}/media", data)
        return str(payload["id"])

    def _wait_processed(self, container_id: str) -> None:
        """영상 컨테이너 처리 대기 — FINISHED까지 폴링. 시한 초과=transient(재시도)."""
        for _ in range(self._max_status_checks):
            payload = self._get(container_id, {"fields": "status_code"})
            status = str(payload.get("status_code", ""))
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise _IgApiError(
                    "permanent_unknown", f"컨테이너 처리 실패: {status}", container_id
                )
            self._sleep(self._poll_interval_s)
        raise _IgApiError(
            "transient", f"컨테이너 처리 대기 시한 초과({self._max_status_checks}회)", container_id
        )

    def _media_publish(self, container_id: str) -> str:
        payload = self._post(f"{self._ig_user_id}/media_publish", {"creation_id": container_id})
        return str(payload["id"])

    def _post(self, path: str, data: dict[str, str]) -> dict[str, Any]:
        response = self._client.post(
            f"{self._base}/{path}", data={**data, "access_token": self._access_token()}
        )
        return self._parse(response)

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        response = self._client.get(
            f"{self._base}/{path}", params={**params, "access_token": self._access_token()}
        )
        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> dict[str, Any]:
        try:
            payload: dict[str, Any] = response.json()
        except ValueError:
            payload = {}
        error = payload.get("error")
        if response.status_code >= 400 or error is not None:
            error = error if isinstance(error, dict) else {}
            raise _IgApiError(
                classify_graph_error(
                    response.status_code, error.get("code"), error.get("error_subcode")
                ),
                f"HTTP {response.status_code}: {response.text[:500]}",
            )
        return payload


def _default_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


# 계약 적합성을 mypy가 강제 (어댑터 공통 패턴).
_check_publish: Publish = InstagramPublish(ig_user_id="", access_token=lambda: "")
