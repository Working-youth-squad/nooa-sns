"""에이전트 부착용 발행 툴 — 멱등 상태머신을 안쪽에 품은 `Publish` 구현 (NFR-2).

PublisherAgent(CodeAct)에 부착되는 것은 이 클래스(를 ApprovalGate로 감싼 것)다.
에이전트 재량과 무관하게: 종결 상태 재호출=무동작(이중 발행 0), 품질 미통과=
진입 거부(QualityGateError — REPL에서 관측됨), 컨테이너 진척 보존.

규약: idempotency_key == publication_id (발행 러너·원본 07-발행 §2와 동일).
"""

from collections.abc import Callable

from sns.publish.state_machine import PublishAttemptStore, run_publish
from sns.tools.contracts import MediaAsset, Platform, Publish, PublishResult, ToolError


class StateMachinePublish:
    def __init__(
        self,
        *,
        attempt_store: PublishAttemptStore,
        publish: Publish,
        quality_passed: Callable[[str], bool],
    ) -> None:
        self._attempt_store = attempt_store
        self._publish = publish
        self._quality_passed = quality_passed

    def __call__(
        self,
        platform: Platform,
        media: MediaAsset,
        caption: str,
        idempotency_key: str,
        container_id: str | None = None,
    ) -> PublishResult:
        # container_id 인자는 무시한다 — 재시작 복구용 컨테이너는 원장(attempt)이
        # 소유하며, 에이전트가 임의 컨테이너를 주입하는 경로를 차단한다.
        attempt = run_publish(
            store=self._attempt_store,
            publish=self._publish,
            publication_id=idempotency_key,
            platform=platform,
            media=media,
            caption=caption,
            idempotency_key=idempotency_key,
            quality_passed=self._quality_passed(idempotency_key),
        )
        if attempt.state == "published":
            return PublishResult(
                post_id=attempt.external_post_id, container_id=attempt.container_id
            )
        return PublishResult(
            container_id=attempt.container_id,
            error=ToolError(
                error_class=attempt.error_class or "permanent_unknown",
                error_raw=attempt.error_raw or f"발행 미완: state={attempt.state}",
            ),
        )


# 계약 적합성을 mypy가 강제.
def _check_tool(tool: StateMachinePublish) -> Publish:
    return tool
