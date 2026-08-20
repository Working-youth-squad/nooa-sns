"""반증선 (b) — Orchestrator 완전 자율 계획으로 한 사이클 dry-run 관통 (FR-C1·C6).

기획→제작→발행(가짜)→분석→다음 변형까지, Orchestrator CodeAct REPL이
`await self.<sub>.<method>()`로 서브에이전트에 위임한다. 모든 값은 결정론
가짜에서 사전 계산해 스크립트에 리터럴로 박는다 — 실행 경로가 진짜임은
가짜 툴의 호출 원장(FakePublish.calls·FakeWritePlaybook.entries)으로 검증.
"""

from sns.agents.analyst import AnalystAgent
from sns.agents.content import ContentAgent
from sns.agents.growth import GrowthAgent
from sns.agents.media import MediaAgent
from sns.agents.orchestrator import OrchestratorAgent
from sns.agents.publisher import PublisherAgent
from sns.agents.topic import TopicAgent
from sns.observe import RunEventRecorder
from sns.tools.fakes import (
    FakePollMetrics,
    FakePublish,
    FakeReadStats,
    FakeRenderMedia,
    FakeResearchTrends,
    FakeWritePlaybook,
)
from tests.helpers import exec_call, resp, ret_call, scripted

MEDIA_SPEC_JSON = '{"layout": "card-v1"}'
CAPTION_HOOK = "왜 다들 rss-topic-1을 놓칠까?"
CAPTION_BODY = "rss-topic-1 핵심 정리."
IDEMPOTENCY_KEY = "cycle-1-ig"

# 결정론 가짜에서 기대값 사전 계산 (테스트가 곧 오라클)
_EXPECTED_ASSET = FakeRenderMedia()({"layout": "card-v1"}, "image")
_EXPECTED_POST_ID = (
    FakePublish()(
        "instagram",
        _EXPECTED_ASSET,
        f"{CAPTION_HOOK}\n{CAPTION_BODY}",
        IDEMPOTENCY_KEY,
    ).post_id
    or ""
)


def _topic_llm() -> object:
    code = (
        'digest = self.research_trends(("rss",), 3)\n'
        "titles = [item for r in digest.source_results for item in r.items]"
    )
    return scripted(
        resp(tool_calls=[exec_call(code, "t1")]),
        resp(tool_calls=[ret_call({"title": "rss-topic-1", "rationale": "트렌드 1위"}, "t2")]),
    )


def _content_llm() -> object:
    return scripted(
        resp(
            tool_calls=[
                ret_call(
                    {
                        "hook": CAPTION_HOOK,
                        "body": CAPTION_BODY,
                        "media_spec_json": MEDIA_SPEC_JSON,
                    },
                    "c1",
                )
            ]
        ),
    )


def _media_llm() -> object:
    code = 'asset = self.render_media({"layout": "card-v1"}, "image")'
    return scripted(
        resp(tool_calls=[exec_call(code, "m1")]),
        resp(
            tool_calls=[
                ret_call(
                    {
                        "storage_url": _EXPECTED_ASSET.storage_url,
                        "checksum": _EXPECTED_ASSET.checksum,
                    },
                    "m2",
                )
            ]
        ),
    )


def _publisher_llm() -> object:
    code = (
        f'media = self.media_asset("{_EXPECTED_ASSET.storage_url}", '
        f'"{_EXPECTED_ASSET.checksum}", "image")\n'
        f'r = self.publish("instagram", media, "{CAPTION_HOOK}\\n{CAPTION_BODY}", '
        f'"{IDEMPOTENCY_KEY}")'
    )
    return scripted(
        resp(tool_calls=[exec_call(code, "p1")]),
        resp(tool_calls=[ret_call({"post_id": _EXPECTED_POST_ID, "error": ""}, "p2")]),
    )


def _analyst_llm() -> object:
    code = (
        f'vals = self.poll_metrics("instagram", "{_EXPECTED_POST_ID}", 0)\n'
        "missing = [v.metric_key for v in vals if v.missing]\n"
        'self.write_playbook("global", "curiosity 훅 유지 — reach 상위")'
    )
    return scripted(
        resp(tool_calls=[exec_call(code, "a1")]),
        resp(
            tool_calls=[
                ret_call(
                    {"analysis_note": "reach 상위. 근거 충분.", "insufficient_evidence": "false"},
                    "a2",
                )
            ]
        ),
    )


def _growth_llm() -> object:
    return scripted(
        resp(tool_calls=[exec_call("stats = self.read_stats()", "g1")]),
        resp(tool_calls=[ret_call({"variant": "hook=curiosity", "rationale": "탐색 우선"}, "g2")]),
    )


def _orchestrator_llm() -> object:
    plan1 = (
        't = await self.topic.pick_topic("플레이북 v1")\n'
        'c = await self.content.write_content(t["title"], "feed_image", "플레이북 v1")'
    )
    plan2 = (
        'm = await self.media.produce(c["media_spec_json"], "image")\n'
        'p = await self.publisher.publish_item("instagram", c["hook"] + "\\n" + c["body"], '
        f'"{IDEMPOTENCY_KEY}", m["storage_url"], m["checksum"], "image")'
    )
    plan3 = (
        'a = await self.analyst.analyze("instagram", p["post_id"], 0)\n'
        'g = await self.growth.choose_variant("goal-1")'
    )
    return scripted(
        resp(tool_calls=[exec_call(plan1, "o1")]),
        resp(tool_calls=[exec_call(plan2, "o2")]),
        resp(tool_calls=[exec_call(plan3, "o3")]),
        resp(
            tool_calls=[
                ret_call(
                    {
                        "status": "completed",
                        "topic_title": "rss-topic-1",
                        "post_id": _EXPECTED_POST_ID,
                        "next_variant": "hook=curiosity",
                    },
                    "o4",
                )
            ]
        ),
    )


async def test_full_cycle_dry_run() -> None:
    fake_publish = FakePublish()
    fake_playbook = FakeWritePlaybook()

    topic = TopicAgent(
        research_trends=FakeResearchTrends(), read_stats=FakeReadStats(), llm=_topic_llm()
    )
    content = ContentAgent(llm=_content_llm())
    media = MediaAgent(render_media=FakeRenderMedia(), llm=_media_llm())
    publisher = PublisherAgent(publish=fake_publish, llm=_publisher_llm())
    analyst = AnalystAgent(
        poll_metrics=FakePollMetrics(),
        read_stats=FakeReadStats(),
        write_playbook=fake_playbook,
        llm=_analyst_llm(),
    )
    growth = GrowthAgent(read_stats=FakeReadStats(), llm=_growth_llm())

    orchestrator = OrchestratorAgent(
        topic=topic,
        content=content,
        media=media,
        publisher=publisher,
        analyst=analyst,
        growth=growth,
        llm=_orchestrator_llm(),
    )

    recorder = RunEventRecorder()
    recorder.attach_all(orchestrator, topic, content, media, publisher, analyst, growth)

    result = await orchestrator.run_cycle("goal-1", "instagram", "feed_image")

    # 사이클 완주 + 착지 결과
    assert result["status"] == "completed"
    assert result["topic_title"] == "rss-topic-1"
    assert result["post_id"] == _EXPECTED_POST_ID

    # 실행 경로가 진짜였음 — 가짜 툴의 호출 원장으로 검증
    assert fake_publish.calls == [IDEMPOTENCY_KEY], "발행 툴 실호출 1회가 아님"
    assert ("global", None) in fake_playbook.entries, "플레이북 착지 미발생"

    # 이벤트 브리지가 사이클 흐름을 관측했음 (FR-C5)
    kinds = set(recorder.kinds())
    assert "tool_called" in kinds


async def test_publish_idempotent_across_duplicate_delegation() -> None:
    """멱등은 툴이 소유(NFR-2) — 같은 idempotency_key 재발행 시 같은 post_id, 실호출 원장 2회."""
    fake_publish = FakePublish()

    def llm() -> object:
        code = (
            f'media = self.media_asset("{_EXPECTED_ASSET.storage_url}", '
            f'"{_EXPECTED_ASSET.checksum}", "image")\n'
            f'r1 = self.publish("instagram", media, "cap", "{IDEMPOTENCY_KEY}")\n'
            f'r2 = self.publish("instagram", media, "cap", "{IDEMPOTENCY_KEY}")\n'
            "same = r1.post_id == r2.post_id"
        )
        return scripted(
            resp(tool_calls=[exec_call(code, "d1")]),
            resp(tool_calls=[ret_call({"post_id": "dup-check", "error": ""}, "d2")]),
        )

    publisher = PublisherAgent(publish=fake_publish, llm=llm())
    await publisher.publish_item("instagram", "cap", IDEMPOTENCY_KEY, "u", "c", "image")

    assert fake_publish.calls == [IDEMPOTENCY_KEY, IDEMPOTENCY_KEY]
    assert len(fake_publish.results) == 1, "이중 발행 발생 — 멱등 위반"
