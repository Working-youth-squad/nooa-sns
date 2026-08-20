"""FR-C5 — NOOA 이벤트 → run_event 브리지.

nooa를 import하지 않는다(FR-C8): 이벤트 객체는 `.event_type` 덕타이핑,
구독은 `agent.event_manager.on("*", handler)` 표면만 쓴다.
run_event kind는 원본 스키마 enum(001_initial.sql)의 부분집합으로 매핑한다.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# event_type 부분 문자열 → run_event.kind (스키마 enum 준수)
_KIND_BY_SUBSTRING: tuple[tuple[str, str], ...] = (
    ("AgentCall", "agent_called"),
    ("ToolCall", "tool_called"),
    ("LLMCallEnd", "cost"),
    ("Error", "error"),
)


@dataclass(frozen=True)
class RunEvent:
    kind: str
    payload: dict[str, Any]
    cost_usd: float | None = None


@dataclass
class RunEventRecorder:
    """append-only 수집기 — DB 착지(PgCycleStore) 전 단계의 인메모리 원장."""

    events: list[RunEvent] = field(default_factory=list)

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]

    def handle(self, event: Any) -> None:
        event_type = str(getattr(event, "event_type", type(event).__name__))
        for needle, kind in _KIND_BY_SUBSTRING:
            if needle in event_type:
                self.events.append(RunEvent(kind=kind, payload=self._payload(event, event_type)))
                return
        # 열거 외 이벤트는 기록하지 않음 (스키마 enum 밖 kind 생성 금지)

    @staticmethod
    def _payload(event: Any, event_type: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"event_type": event_type}
        for attr in ("name", "arguments", "usage", "model", "content"):
            value = getattr(event, attr, None)
            if value is not None:
                payload[attr] = str(value)[:500]
        return payload

    def attach(self, agent: Any) -> Callable[[], None]:
        """에이전트의 이벤트 버스에 구독 — 해제 함수 반환."""
        unsubscribe = agent.event_manager.on("*", self.handle)
        return unsubscribe  # type: ignore[no-any-return]

    def attach_all(self, *agents: Any) -> Callable[[], None]:
        unsubs = [self.attach(a) for a in agents]

        def unsubscribe_all() -> None:
            for u in unsubs:
                u()

        return unsubscribe_all
