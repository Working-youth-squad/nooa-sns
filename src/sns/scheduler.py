"""슬롯 스케줄러 (FR-O1) — 시계 주입식, 결정론 테스트 가능.

실행 방식(상주 러너 vs GHA cron)은 미결정(spec §7-4) — 이 모듈은 두 모드가
공유하는 순수 계산(다음 슬롯·놓친 슬롯)과 상주 루프 시임만 제공한다.
중복 트리거 멱등(FR-O1 수용기준)은 트리거 함수 쪽 cycle 유일성이 보장하며,
여기서는 같은 슬롯을 두 번 반환하지 않는 것으로 1차 방어한다.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta


@dataclass(frozen=True)
class SlotSchedule:
    """UTC 기준 하루 안의 발행 슬롯 목록."""

    slots: tuple[time, ...]

    def __post_init__(self) -> None:
        if not self.slots:
            raise ValueError("슬롯이 비어 있음")
        if list(self.slots) != sorted(self.slots):
            raise ValueError(f"슬롯은 오름차순이어야 함: {self.slots}")

    def next_slot(self, now: datetime) -> datetime:
        """now 이후(초과) 첫 슬롯 시각."""
        today = now.date()
        for slot in self.slots:
            candidate = datetime.combine(today, slot, tzinfo=UTC)
            if candidate > now:
                return candidate
        return datetime.combine(today + timedelta(days=1), self.slots[0], tzinfo=UTC)

    def due_slots(self, last_run: datetime | None, now: datetime) -> list[datetime]:
        """(last_run, now] 사이 놓친 슬롯 전부 — GHA cron 모드의 따라잡기 계산.

        last_run이 None이면 now가 속한 날의 지난 슬롯은 건너뛰고 빈 목록을
        반환한다(첫 기동 시 과거 소급 발행 금지).
        """
        if last_run is None:
            return []
        due: list[datetime] = []
        day = last_run.date()
        while day <= now.date():
            for slot in self.slots:
                candidate = datetime.combine(day, slot, tzinfo=UTC)
                if last_run < candidate <= now:
                    due.append(candidate)
            day += timedelta(days=1)
        return due


async def run_resident(
    schedule: SlotSchedule,
    trigger: Callable[[datetime], Awaitable[None]],
    *,
    clock: Callable[[], datetime],
    sleep: Callable[[float], Awaitable[None]],
    until: Callable[[], bool],
) -> int:
    """상주 러너 루프 시임 — clock/sleep/until 전부 주입식(결정론 테스트 가능).

    반환: 트리거한 슬롯 수. 트리거 실패는 해당 슬롯만 삼키지 않고 전파한다
    (실패 격리·재시도는 Orchestrator/툴 계층의 책임 — 여기서 중복 방어 금지).
    """
    fired = 0
    while not until():
        now = clock()
        target = schedule.next_slot(now)
        wait_s = (target - now).total_seconds()
        if wait_s > 0:
            await sleep(wait_s)
        if until():
            break
        await trigger(target)
        fired += 1
    return fired
