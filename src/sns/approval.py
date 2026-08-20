"""hybrid 승인 관문 (FR-O2) — "승인 전 publish 0건"을 툴 레벨에서 강제.

에이전트 프롬프트가 아니라 Publish 툴을 감싸는 게이트가 불변식을 소유한다:
CodeAct가 어떤 계획을 세우든, hybrid 채널에서 미승인 발행은 inner publish에
도달하지 못한다. 승인 단위는 idempotency_key(발행 건 단위).

알림(notify)은 시임 — Discord 어댑터는 후속 증분에서 주입한다.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from sns.tools.contracts import MediaAsset, Platform, Publish, PublishResult

ChannelMode = Literal["auto", "hybrid"]


class ApprovalPending(RuntimeError):
    """미승인 발행 시도 — 발행은 일어나지 않았다(보류)."""


@dataclass
class ApprovalGate:
    """Publish 계약을 그대로 구현하는 래퍼 — auto는 통과, hybrid는 승인 필수."""

    inner: Publish
    mode: ChannelMode
    notify: Callable[[str], None] | None = None
    _approved: set[str] = field(default_factory=set)
    _notified: set[str] = field(default_factory=set)

    def approve(self, idempotency_key: str) -> None:
        """운영자 승인 — 이후 같은 키의 발행이 통과한다."""
        self._approved.add(idempotency_key)

    def pending_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._notified - self._approved))

    def __call__(
        self,
        platform: Platform,
        media: MediaAsset,
        caption: str,
        idempotency_key: str,
        container_id: str | None = None,
    ) -> PublishResult:
        if self.mode == "hybrid" and idempotency_key not in self._approved:
            if self.notify is not None and idempotency_key not in self._notified:
                self.notify(
                    f"[승인 요청] {platform} 발행 대기: {idempotency_key}\n캡션: {caption[:200]}"
                )
            self._notified.add(idempotency_key)
            raise ApprovalPending(
                f"발행 보류(needs_review): {idempotency_key} — 운영자 승인 전 publish 금지 (FR-O2)"
            )
        return self.inner(platform, media, caption, idempotency_key, container_id)


# 타입체크: 게이트가 Publish 계약을 구조적으로 만족함을 강제
def _check_gate(gate: ApprovalGate) -> Publish:
    return gate


def approve_publication(conn: object, publication_id: str) -> dict[str, int]:
    """승인 재개 (FR-O2) — needs_review 산출물을 발행 가능 상태로 전환.

    content_item(needs_review→approved) + media_asset(needs_review→passed)만 바꾼다.
    실발행은 이후 `publish-pending` 배치가 멱등 상태머신으로 수행한다.
    conn은 psycopg autocommit 커넥션(덕타이핑 — 이 모듈은 psycopg 무의존 유지).
    """
    row = conn.execute(  # type: ignore[attr-defined]
        "SELECT content_item_id FROM publication WHERE id = %s", (publication_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"publication 없음: {publication_id}")
    content_item_id = row[0]
    with conn.transaction():  # type: ignore[attr-defined]
        content = conn.execute(  # type: ignore[attr-defined]
            "UPDATE content_item SET status = 'approved' WHERE id = %s AND status = 'needs_review'",
            (content_item_id,),
        ).rowcount
        media = conn.execute(  # type: ignore[attr-defined]
            "UPDATE media_asset SET quality_status = 'passed' "
            "WHERE content_item_id = %s AND quality_status = 'needs_review'",
            (content_item_id,),
        ).rowcount
    return {"content_approved": content, "media_passed": media}
