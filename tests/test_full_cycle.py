"""반증선 (b) — Orchestrator 완전 자율 계획으로 한 사이클 dry-run 관통 (FR-C1·C6).

기획→제작→발행(가짜)→분석→다음 변형까지, Orchestrator CodeAct REPL이
`await self.<sub>.<method>()`로 서브에이전트에 위임한다. 실행 경로가 진짜임은
가짜 툴의 호출 원장(FakePublish.calls·FakeWritePlaybook.entries)으로 검증.
"""

from sns.agents.publisher import PublisherAgent
from sns.observe import RunEventRecorder
from sns.tools.fakes import FakePublish, FakeWritePlaybook
from tests.cycle_fixtures import (
    COMPLETED_RESULT,
    EXPECTED_ASSET,
    EXPECTED_POST_ID,
    IDEMPOTENCY_KEY,
    build_orchestrator,
    orchestrator_llm,
    publisher_llm,
)
from tests.helpers import exec_call, resp, ret_call, scripted


async def test_full_cycle_dry_run() -> None:
    fake_publish = FakePublish()
    fake_playbook = FakeWritePlaybook()
    orchestrator = build_orchestrator(
        publish_tool=fake_publish,
        fake_playbook=fake_playbook,
        publisher_client=publisher_llm(),
        orchestrator_client=orchestrator_llm(COMPLETED_RESULT),
    )

    recorder = RunEventRecorder()
    recorder.attach_all(
        orchestrator,
        orchestrator.topic,
        orchestrator.content,
        orchestrator.media,
        orchestrator.publisher,
        orchestrator.analyst,
        orchestrator.growth,
    )

    result = await orchestrator.run_cycle("goal-1", "instagram", "feed_image")

    # 사이클 완주 + 착지 결과
    assert result["status"] == "completed"
    assert result["topic_title"] == "rss-topic-1"
    assert result["post_id"] == EXPECTED_POST_ID

    # 실행 경로가 진짜였음 — 가짜 툴의 호출 원장으로 검증
    assert fake_publish.calls == [IDEMPOTENCY_KEY], "발행 툴 실호출 1회가 아님"
    assert ("global", None) in fake_playbook.entries, "플레이북 착지 미발생"

    # 이벤트 브리지가 사이클 흐름을 관측했음 (FR-C5)
    assert "tool_called" in set(recorder.kinds())


async def test_publish_idempotent_across_duplicate_delegation() -> None:
    """멱등은 툴이 소유(NFR-2) — 같은 idempotency_key 재발행 시 같은 post_id, 실호출 원장 2회."""
    fake_publish = FakePublish()

    code = (
        f'media = self.media_asset("{EXPECTED_ASSET.storage_url}", '
        f'"{EXPECTED_ASSET.checksum}", "image")\n'
        f'r1 = self.publish("instagram", media, "cap", "{IDEMPOTENCY_KEY}")\n'
        f'r2 = self.publish("instagram", media, "cap", "{IDEMPOTENCY_KEY}")\n'
        "same = r1.post_id == r2.post_id"
    )
    llm = scripted(
        resp(tool_calls=[exec_call(code, "d1")]),
        resp(tool_calls=[ret_call({"post_id": "dup-check", "error": ""}, "d2")]),
    )
    publisher = PublisherAgent(publish=fake_publish, llm=llm)
    await publisher.publish_item("instagram", "cap", IDEMPOTENCY_KEY, "u", "c", "image")

    assert fake_publish.calls == [IDEMPOTENCY_KEY, IDEMPOTENCY_KEY]
    assert len(fake_publish.results) == 1, "이중 발행 발생 — 멱등 위반"
