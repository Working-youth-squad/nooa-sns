"""반증선 (c) — 능력 표면 = 부착 툴 계약뿐 (FR-C2), 시크릿 비노출 (FR-S3).

CodeAct REPL은 `self`로 에이전트에 접근한다. 따라서 에이전트 인스턴스의
속성 표면이 곧 LLM의 행동 반경이다 — 여기서 그 표면을 물리 검사한다.
"""

from sns.agents.topic import TopicAgent
from sns.tools.fakes import FakeReadStats, FakeResearchTrends
from tests.helpers import exec_call, resp, ret_call, scripted

FORBIDDEN_ATTRS = (
    "token",
    "token_encrypted",
    "secret",
    "secrets",
    "db",
    "conn",
    "connection",
    "pool",
    "api_key",
)


def make_agent(llm):  # type: ignore[no-untyped-def]
    return TopicAgent(research_trends=FakeResearchTrends(), read_stats=FakeReadStats(), llm=llm)


def test_no_secret_or_db_attributes() -> None:
    agent = make_agent(scripted())
    for name in FORBIDDEN_ATTRS:
        assert not hasattr(agent, name), f"금지 속성 노출: {name}"


async def test_repl_cannot_reach_secrets() -> None:
    """REPL 안에서 시크릿을 찾아도 None — 계약 툴 2종 외 외부 채널 부재."""
    probe = """
leak = [n for n in ("token", "token_encrypted", "secret", "api_key", "conn")
        if getattr(self, n, None) is not None]
"""
    llm = scripted(
        resp(tool_calls=[exec_call(probe, "p1")]),
        resp(tool_calls=[ret_call({"title": "probe", "rationale": "leak=[]"}, "p2")]),
    )
    agent = make_agent(llm)
    result = await agent.pick_topic("표면 검사")
    assert result["rationale"] == "leak=[]"


async def test_attached_tools_are_callable_from_repl() -> None:
    """부착된 계약 툴은 REPL에서 호출 가능(허용 경로) — 호출 사실을 페이크로 검증."""

    calls: list[tuple[str, object]] = []

    class RecordingTrends(FakeResearchTrends):
        def __call__(self, sources=None, limit=10):  # type: ignore[no-untyped-def]
            calls.append(("research_trends", sources))
            return super().__call__(sources, limit)

    llm = scripted(
        resp(tool_calls=[exec_call('d = self.research_trends(("rss",), 2)', "t1")]),
        resp(tool_calls=[ret_call({"title": "rss-topic-1", "rationale": "ok"}, "t2")]),
    )
    agent = TopicAgent(research_trends=RecordingTrends(), read_stats=FakeReadStats(), llm=llm)
    await agent.pick_topic("툴 호출 확인")
    assert calls == [("research_trends", ("rss",))]
