"""StateMachinePublish — 에이전트 부착 발행 툴의 불변식 (NFR-2, 전 플랫폼 실행)."""

import pytest

from sns.publish.state_machine import QualityGateError
from sns.publish.stores import InMemoryPublishAttemptStore
from sns.publish.tool import StateMachinePublish
from sns.tools.contracts import MediaAsset, PublishResult, ToolError
from sns.tools.fakes import FakePublish

MEDIA = MediaAsset(kind="image", storage_url="https://cdn.example/c.png", checksum="c1")


def make_tool(publish, *, quality: bool = True) -> StateMachinePublish:  # type: ignore[no-untyped-def]
    return StateMachinePublish(
        attempt_store=InMemoryPublishAttemptStore(),
        publish=publish,
        quality_passed=lambda _pid: quality,
    )


def test_quality_gate_blocks_entry() -> None:
    inner = FakePublish()
    tool = make_tool(inner, quality=False)
    with pytest.raises(QualityGateError):
        tool("instagram", MEDIA, "cap", "pub-1")
    assert inner.calls == [], "품질 미통과인데 발행 툴 호출됨"


def test_terminal_state_never_republishes() -> None:
    inner = FakePublish()
    tool = make_tool(inner)

    first = tool("instagram", MEDIA, "cap", "pub-1")
    second = tool("instagram", MEDIA, "cap", "pub-1")

    assert first.post_id and first.post_id == second.post_id
    assert inner.calls == ["pub-1"], "종결 상태 재호출에서 이중 발행 (FR-P3 위반)"


def test_transient_error_keeps_retry_path() -> None:
    outcomes = iter(
        [
            PublishResult(error=ToolError(error_class="transient", error_raw="504")),
            PublishResult(post_id="post-ok", container_id="c-1"),
        ]
    )
    calls: list[str | None] = []

    def flaky(platform, media, caption, idempotency_key, container_id=None):  # type: ignore[no-untyped-def]
        calls.append(container_id)
        return next(outcomes)

    tool = make_tool(flaky)

    first = tool("instagram", MEDIA, "cap", "pub-2")
    assert first.error is not None and first.error.error_class == "transient"

    second = tool("instagram", MEDIA, "cap", "pub-2")
    assert second.post_id == "post-ok"
    assert len(calls) == 2, "transient는 재시도 여지를 유지해야 함"


def test_nonretryable_error_terminal() -> None:
    def denied(platform, media, caption, idempotency_key, container_id=None):  # type: ignore[no-untyped-def]
        return PublishResult(error=ToolError(error_class="auth", error_raw="401"))

    inner_calls: list[str] = []

    def counting(platform, media, caption, idempotency_key, container_id=None):  # type: ignore[no-untyped-def]
        inner_calls.append(idempotency_key)
        return denied(platform, media, caption, idempotency_key, container_id)

    tool = make_tool(counting)
    first = tool("instagram", MEDIA, "cap", "pub-3")
    second = tool("instagram", MEDIA, "cap", "pub-3")

    assert first.error is not None and first.error.error_class == "auth"
    assert second.error is not None and second.error.error_class == "auth"
    assert inner_calls == ["pub-3"], "비재시도 오류를 재시도함 (FR-P4 위반)"


def test_agent_supplied_container_id_ignored() -> None:
    seen: list[str | None] = []

    def capture(platform, media, caption, idempotency_key, container_id=None):  # type: ignore[no-untyped-def]
        seen.append(container_id)
        return PublishResult(post_id="p", container_id="real-c")

    tool = make_tool(capture)
    tool("instagram", MEDIA, "cap", "pub-4", container_id="에이전트-임의-주입")

    assert seen == [None], "에이전트 주입 container_id가 어댑터까지 전달됨"
