"""러너 — 사이클 산출물 영속화 + 샌드박스 게이트 + hybrid needs_review (FR-C5·S1·O2)."""

import pytest

from sns.approval import ApprovalGate
from sns.runner import CycleTarget, run_cycle
from sns.sandbox import SandboxError
from sns.store import InMemoryCycleStore
from sns.tools.fakes import FakePublish, FakeWritePlaybook
from tests.cycle_fixtures import (
    COMPLETED_RESULT,
    EXPECTED_ASSET,
    EXPECTED_POST_ID,
    FULL_BODY,
    PARTIAL_RESULT,
    build_orchestrator,
    hybrid_publisher_llm,
    orchestrator_llm,
    publisher_llm,
)

AUTO_TARGET = CycleTarget(
    channel_id="ch-1",
    platform="instagram",
    content_format="feed_image",
    media_kind="image",
    mode="auto",
)
HYBRID_TARGET = CycleTarget(
    channel_id="ch-2",
    platform="instagram",
    content_format="feed_image",
    media_kind="image",
    mode="hybrid",
)


def _no_sandbox_check() -> None:  # 테스트 전용 우회 — 프로덕션 기본값은 assert_sandboxed
    return None


async def test_auto_cycle_persists_everything() -> None:
    store = InMemoryCycleStore()
    orchestrator = build_orchestrator(
        publish_tool=FakePublish(),
        fake_playbook=FakeWritePlaybook(),
        publisher_client=publisher_llm(),
        orchestrator_client=orchestrator_llm(COMPLETED_RESULT),
    )

    out = await run_cycle(
        store=store,
        orchestrator=orchestrator,
        goal_ref="goal-1",
        target=AUTO_TARGET,
        sandbox_check=_no_sandbox_check,
    )

    assert out.published is True
    assert store.cycles[out.cycle_id]["status"] == "completed"

    (topic,) = store.topics.values()
    assert topic["title"] == "rss-topic-1"

    assert out.content_item_id is not None
    content = store.content_items[out.content_item_id]
    assert content["status"] == "approved"
    assert content["body"] == FULL_BODY
    assert content["hook_pattern"] == "curiosity"
    assert content["media_spec"] == {"layout": "card-v1"}

    (media,) = store.media_assets.values()
    assert media["checksum"] == EXPECTED_ASSET.checksum

    assert out.publication_id is not None
    pub = store.publications[out.publication_id]
    assert pub["status"] == "published"
    assert pub["external_post_id"] == EXPECTED_POST_ID

    (note,) = store.analysis_notes.values()
    assert note["insufficient_evidence"] is False

    kinds = [e["kind"] for e in store.events]
    assert kinds[0] == "cycle_started"
    assert kinds[-1] == "cycle_completed"
    assert "tool_called" in kinds, "브리지 착지 미발생 (FR-C5)"


async def test_hybrid_cycle_blocks_publish_and_lands_needs_review() -> None:
    store = InMemoryCycleStore()
    inner = FakePublish()
    notes: list[str] = []
    gate = ApprovalGate(inner=inner, mode="hybrid", notify=notes.append)
    orchestrator = build_orchestrator(
        publish_tool=gate,
        fake_playbook=FakeWritePlaybook(),
        publisher_client=hybrid_publisher_llm(),
        orchestrator_client=orchestrator_llm(PARTIAL_RESULT, with_analysis=False),
    )

    out = await run_cycle(
        store=store,
        orchestrator=orchestrator,
        goal_ref="goal-1",
        target=HYBRID_TARGET,
        sandbox_check=_no_sandbox_check,
    )

    # 승인 전 publish 0건 (FR-O2) — 게이트 안쪽 실발행 원장 비어 있음
    assert inner.calls == []
    assert len(notes) == 1, "Discord 알림 시임 1회 호출이 아님"
    assert out.published is False

    assert out.content_item_id is not None
    assert store.content_items[out.content_item_id]["status"] == "needs_review"

    assert out.publication_id is not None
    pub = store.publications[out.publication_id]
    assert pub["status"] == "pending"
    assert "external_post_id" not in pub

    assert store.analysis_notes == {}, "미발행 사이클에 분석글이 생기면 안 됨"
    assert store.cycles[out.cycle_id]["status"] == "completed"  # partial=사이클은 완료


async def test_sandbox_gate_blocks_before_any_ledger_write() -> None:
    store = InMemoryCycleStore()
    orchestrator = build_orchestrator(
        publish_tool=FakePublish(),
        fake_playbook=FakeWritePlaybook(),
        publisher_client=publisher_llm(),
        orchestrator_client=orchestrator_llm(COMPLETED_RESULT),
    )

    def refusing_check() -> None:
        raise SandboxError("격리 미확인")

    with pytest.raises(SandboxError):
        await run_cycle(
            store=store,
            orchestrator=orchestrator,
            goal_ref="goal-1",
            target=AUTO_TARGET,
            sandbox_check=refusing_check,
        )

    assert store.cycles == {} and store.events == [], "게이트 거부 후 원장 기록 발생 (FR-S1)"
