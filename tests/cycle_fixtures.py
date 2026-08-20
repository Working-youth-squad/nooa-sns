"""풀사이클 스크립트 픽스처 — test_full_cycle·test_runner 공용.

모든 값은 결정론 가짜에서 사전 계산해 스크립트에 리터럴로 삽입한다.
"""

from sns.agents.analyst import AnalystAgent
from sns.agents.content import ContentAgent
from sns.agents.growth import GrowthAgent
from sns.agents.media import MediaAgent
from sns.agents.orchestrator import OrchestratorAgent
from sns.agents.publisher import PublisherAgent
from sns.agents.topic import TopicAgent
from sns.tools.contracts import Publish
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
FULL_BODY = f"{CAPTION_HOOK}\n{CAPTION_BODY}"
IDEMPOTENCY_KEY = "cycle-1-ig"

EXPECTED_ASSET = FakeRenderMedia()({"layout": "card-v1"}, "image")
EXPECTED_POST_ID = (
    FakePublish()("instagram", EXPECTED_ASSET, FULL_BODY, IDEMPOTENCY_KEY).post_id or ""
)

COMPLETED_RESULT: dict[str, str] = {
    "status": "completed",
    "topic_title": "rss-topic-1",
    "topic_rationale": "트렌드 1위",
    "hook_pattern": "curiosity",
    "body": FULL_BODY,
    "media_spec_json": MEDIA_SPEC_JSON,
    "storage_url": EXPECTED_ASSET.storage_url,
    "checksum": EXPECTED_ASSET.checksum,
    "post_id": EXPECTED_POST_ID,
    "analysis_note": "reach 상위. 근거 충분.",
    "insufficient_evidence": "false",
    "next_variant": "hook=curiosity",
}

PARTIAL_RESULT: dict[str, str] = {
    **COMPLETED_RESULT,
    "status": "partial",
    "post_id": "",
    "analysis_note": "",
    "insufficient_evidence": "",
}


def topic_llm() -> object:
    code = (
        'digest = self.research_trends(("rss",), 3)\n'
        "titles = [item for r in digest.source_results for item in r.items]"
    )
    return scripted(
        resp(tool_calls=[exec_call(code, "t1")]),
        resp(tool_calls=[ret_call({"title": "rss-topic-1", "rationale": "트렌드 1위"}, "t2")]),
    )


def content_llm() -> object:
    return scripted(
        resp(
            tool_calls=[
                ret_call(
                    {
                        "hook": CAPTION_HOOK,
                        "body": CAPTION_BODY,
                        "hook_pattern": "curiosity",
                        "media_spec_json": MEDIA_SPEC_JSON,
                    },
                    "c1",
                )
            ]
        ),
    )


def media_llm() -> object:
    return scripted(
        resp(
            tool_calls=[
                exec_call('asset = self.render_media({"layout": "card-v1"}, "image")', "m1")
            ]
        ),
        resp(
            tool_calls=[
                ret_call(
                    {
                        "storage_url": EXPECTED_ASSET.storage_url,
                        "checksum": EXPECTED_ASSET.checksum,
                    },
                    "m2",
                )
            ]
        ),
    )


def publisher_llm() -> object:
    code = (
        f'media = self.media_asset("{EXPECTED_ASSET.storage_url}", '
        f'"{EXPECTED_ASSET.checksum}", "image")\n'
        f'r = self.publish("instagram", media, "{CAPTION_HOOK}\\n{CAPTION_BODY}", '
        f'"{IDEMPOTENCY_KEY}")'
    )
    return scripted(
        resp(tool_calls=[exec_call(code, "p1")]),
        resp(tool_calls=[ret_call({"post_id": EXPECTED_POST_ID, "error": ""}, "p2")]),
    )


def hybrid_publisher_llm() -> object:
    """발행 시도 → ApprovalPending 관측 → 보류를 정직 보고."""
    code = (
        f'media = self.media_asset("{EXPECTED_ASSET.storage_url}", '
        f'"{EXPECTED_ASSET.checksum}", "image")\n'
        f'r = self.publish("instagram", media, "{CAPTION_HOOK}\\n{CAPTION_BODY}", '
        f'"{IDEMPOTENCY_KEY}")'
    )
    return scripted(
        resp(tool_calls=[exec_call(code, "hp1")]),  # ApprovalPending으로 실패 관측
        resp(tool_calls=[ret_call({"post_id": "", "error": "approval_pending"}, "hp2")]),
    )


def analyst_llm() -> object:
    code = (
        f'vals = self.poll_metrics("instagram", "{EXPECTED_POST_ID}", 0)\n'
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


def growth_llm() -> object:
    return scripted(
        resp(tool_calls=[exec_call("stats = self.read_stats()", "g1")]),
        resp(tool_calls=[ret_call({"variant": "hook=curiosity", "rationale": "탐색 우선"}, "g2")]),
    )


def orchestrator_llm(final_result: dict[str, str], *, with_analysis: bool = True) -> object:
    plan1 = (
        't = await self.topic.pick_topic("플레이북 v1")\n'
        'c = await self.content.write_content(t["title"], "feed_image", "플레이북 v1")'
    )
    plan2 = (
        'm = await self.media.produce(c["media_spec_json"], "image")\n'
        'p = await self.publisher.publish_item("instagram", c["hook"] + "\\n" + c["body"], '
        f'"{IDEMPOTENCY_KEY}", m["storage_url"], m["checksum"], "image")'
    )
    if with_analysis:
        plan3 = (
            'a = await self.analyst.analyze("instagram", p["post_id"], 0)\n'
            'g = await self.growth.choose_variant("goal-1")'
        )
    else:
        plan3 = 'g = await self.growth.choose_variant("goal-1")'
    return scripted(
        resp(tool_calls=[exec_call(plan1, "o1")]),
        resp(tool_calls=[exec_call(plan2, "o2")]),
        resp(tool_calls=[exec_call(plan3, "o3")]),
        resp(tool_calls=[ret_call(final_result, "o4")]),
    )


def build_orchestrator(
    *,
    publish_tool: Publish,
    fake_playbook: FakeWritePlaybook,
    publisher_client: object,
    orchestrator_client: object,
) -> OrchestratorAgent:
    return OrchestratorAgent(
        topic=TopicAgent(
            research_trends=FakeResearchTrends(), read_stats=FakeReadStats(), llm=topic_llm()
        ),
        content=ContentAgent(llm=content_llm()),
        media=MediaAgent(render_media=FakeRenderMedia(), llm=media_llm()),
        publisher=PublisherAgent(publish=publish_tool, llm=publisher_client),
        analyst=AnalystAgent(
            poll_metrics=FakePollMetrics(),
            read_stats=FakeReadStats(),
            write_playbook=fake_playbook,
            llm=analyst_llm(),
        ),
        growth=GrowthAgent(read_stats=FakeReadStats(), llm=growth_llm()),
        llm=orchestrator_client,
    )
