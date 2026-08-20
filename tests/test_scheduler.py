"""FR-O1 — 슬롯 스케줄러 순수 계산·상주 루프 (시계 주입, 결정론)."""

from datetime import UTC, datetime, time, timedelta

import pytest

from sns.scheduler import SlotSchedule, run_resident

SCHEDULE = SlotSchedule(slots=(time(9, 0), time(18, 0)))


def dt(y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def test_next_slot_same_day() -> None:
    assert SCHEDULE.next_slot(dt(2026, 8, 20, 10)) == dt(2026, 8, 20, 18)


def test_next_slot_exactly_on_slot_moves_forward() -> None:
    assert SCHEDULE.next_slot(dt(2026, 8, 20, 9)) == dt(2026, 8, 20, 18)


def test_next_slot_rolls_to_next_day() -> None:
    assert SCHEDULE.next_slot(dt(2026, 8, 20, 19)) == dt(2026, 8, 21, 9)


def test_due_slots_first_boot_skips_backfill() -> None:
    assert SCHEDULE.due_slots(None, dt(2026, 8, 20, 23)) == []


def test_due_slots_multi_day_catchup() -> None:
    due = SCHEDULE.due_slots(dt(2026, 8, 18, 10), dt(2026, 8, 20, 9, 30))
    assert due == [
        dt(2026, 8, 18, 18),
        dt(2026, 8, 19, 9),
        dt(2026, 8, 19, 18),
        dt(2026, 8, 20, 9),
    ]


def test_invalid_schedule_rejected() -> None:
    with pytest.raises(ValueError, match="비어"):
        SlotSchedule(slots=())
    with pytest.raises(ValueError, match="오름차순"):
        SlotSchedule(slots=(time(18, 0), time(9, 0)))


async def test_run_resident_fires_slots_deterministically() -> None:
    state = {"now": dt(2026, 8, 20, 8)}
    fired: list[datetime] = []

    async def fake_sleep(seconds: float) -> None:
        state["now"] += timedelta(seconds=seconds)

    async def trigger(slot: datetime) -> None:
        fired.append(slot)

    count = await run_resident(
        SCHEDULE,
        trigger,
        clock=lambda: state["now"],
        sleep=fake_sleep,
        until=lambda: len(fired) >= 3,
    )

    assert count == 3
    assert fired == [dt(2026, 8, 20, 9), dt(2026, 8, 20, 18), dt(2026, 8, 21, 9)]
