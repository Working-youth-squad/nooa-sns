"""FR-C5 — NOOA 이벤트 → run_event 브리지.

nooa를 import하지 않는다(FR-C8): 이벤트 객체는 `.event_type` 덕타이핑,
구독은 `agent.event_manager.on("*", handler)` 표면만 쓴다.
run_event kind는 원본 스키마 enum(001_initial.sql)의 부분집합으로 매핑한다.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sns.store import CycleStore, EventKind

# event_type 부분 문자열 → run_event.kind (스키마 enum 준수)
_KIND_BY_SUBSTRING: tuple[tuple[str, EventKind], ...] = (
    ("AgentCall", "agent_called"),
    ("ToolCall", "tool_called"),
    ("LLMCallEnd", "cost"),
    ("Error", "error"),
)


@dataclass(frozen=True)
class RunEvent:
    kind: EventKind
    payload: dict[str, Any]
    cost_usd: float | None = None


def store_sink(store: CycleStore, cycle_id: str) -> Callable[["RunEvent"], None]:
    """RunEvent를 CycleStore.log_event로 즉시 착지시키는 싱크 (FR-C5 DB 원장)."""

    def sink(event: RunEvent) -> None:
        store.log_event(
            cycle_id=cycle_id, kind=event.kind, payload=event.payload, cost_usd=event.cost_usd
        )

    return sink


@dataclass
class RunEventRecorder:
    """append-only 수집기 — 인메모리 원장 + 선택적 싱크(store_sink로 DB 착지)."""

    events: list[RunEvent] = field(default_factory=list)
    sink: Callable[[RunEvent], None] | None = None

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]

    def handle(self, event: Any) -> None:
        event_type = str(getattr(event, "event_type", type(event).__name__))
        for needle, kind in _KIND_BY_SUBSTRING:
            if needle in event_type:
                run_event = RunEvent(kind=kind, payload=self._payload(event, event_type))
                self.events.append(run_event)
                if self.sink is not None:
                    self.sink(run_event)
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
