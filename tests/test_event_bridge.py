"""반증선 관측 — FR-C5 NOOA 이벤트 → run_event 브리지."""

from sns.observe import RunEventRecorder
from sns.tools.fakes import FakeReadStats, FakeResearchTrends
from tests.test_determinism import make_agent

ALLOWED_KINDS = {"agent_called", "tool_called", "cost", "error"}


async def test_bridge_records_tool_calls_within_schema_enum() -> None:
    agent, _ = make_agent()
    recorder = RunEventRecorder()
    unsubscribe = recorder.attach(agent)

    await agent.pick_topic("브리지 관측")
    unsubscribe()

    assert recorder.events, "이벤트가 하나도 기록되지 않음"
    kinds = set(recorder.kinds())
    assert kinds <= ALLOWED_KINDS, f"스키마 enum 밖 kind: {kinds - ALLOWED_KINDS}"
    assert "tool_called" in kinds, f"tool_called 미기록 — 관측 kinds: {kinds}"


async def test_unsubscribe_stops_recording() -> None:
    from sns.agents.topic import TopicAgent
    from tests.helpers import exec_call, resp, ret_call, scripted

    llm = scripted(
        resp(tool_calls=[exec_call("x = 1", "u1")]),
        resp(tool_calls=[ret_call({"title": "rss-topic-1", "rationale": "r"}, "u2")]),
    )
    agent = TopicAgent(research_trends=FakeResearchTrends(), read_stats=FakeReadStats(), llm=llm)
    recorder = RunEventRecorder()
    recorder.attach(agent)()  # 즉시 해제

    await agent.pick_topic("해제 후")
    assert recorder.events == []
