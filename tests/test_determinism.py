"""반증선 (a) — FakeLLMClient 주입 결정론 재현 (NFR-1, FR-C3).

같은 스크립트 응답 → 같은 착지 결과. 판정 기준은 생성 코드 텍스트가 아니라
반환값(착지 결과)이다 (spec §6 NFR-1 엣지).
"""

from sns.agents.topic import TopicAgent
from sns.tools.fakes import FakeReadStats, FakeResearchTrends
from tests.helpers import exec_call, resp, ret_call, scripted

PICK_CODE = """
digest = self.research_trends(("rss",), 3)
titles = [item for r in digest.source_results for item in r.items]
choice = {"title": titles[0], "rationale": "트렌드 최상위 소재"}
"""


def make_agent() -> tuple[TopicAgent, FakeResearchTrends]:
    trends = FakeResearchTrends()
    llm = scripted(
        resp(tool_calls=[exec_call(PICK_CODE, "c1")]),
        resp(
            tool_calls=[ret_call({"title": "rss-topic-1", "rationale": "트렌드 최상위 소재"}, "c2")]
        ),
    )
    return (
        TopicAgent(research_trends=trends, read_stats=FakeReadStats(), llm=llm),
        trends,
    )


async def test_same_script_same_landing() -> None:
    agent1, _ = make_agent()
    agent2, _ = make_agent()

    result1 = await agent1.pick_topic("훅은 curiosity 우선")
    result2 = await agent2.pick_topic("훅은 curiosity 우선")

    assert result1 == result2 == {"title": "rss-topic-1", "rationale": "트렌드 최상위 소재"}


async def test_topic_grounded_in_trend_tool() -> None:
    """선택된 title이 툴이 실제로 반환한 트렌드 항목에 실재(할루시네이션 방지)."""
    agent, trends = make_agent()
    result = await agent.pick_topic("지침 없음")

    digest = trends(("rss",), 3)
    real_items = {item for r in digest.source_results for item in r.items}
    assert result["title"] in real_items
