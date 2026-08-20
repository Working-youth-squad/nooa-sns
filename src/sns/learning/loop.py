"""학습 루프 배선 (FR-L1~L3) — 지표 폴링→적재→reward→topic_stats. 수치는 전부 코드.

- 창 도래 계산은 시계 주입(결정론 테스트). 창: 0=6h, 1=24h, 2=72h (FR-A3 확정,
  3+ 일 1회는 후속).
- 결측 지표는 missing=True·value=NULL 그대로 적재 — 0 대체 금지 (NFR-3, DB CHECK).
- reward 산식 계수는 **사전등록 미결정**(spec §7) — RewardFn seam만 배선하고
  기본 NullReward는 전부 NULL(판정 보류)을 낸다. NULL reward는 topic_stats
  학습에서 제외된다(FR-L2). 산식 확정은 M1 실측 후 별도 PR.
- 한 publication의 폴링 실패는 그 건만 격리한다(다른 건 계속).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import psycopg

from sns.tools.contracts import MetricValue, Platform, PollMetrics

# window_index → 발행 후 경과 시간 (FR-A3)
METRIC_WINDOWS_H: tuple[tuple[int, int], ...] = ((0, 6), (1, 24), (2, 72))
# reward 정산 기준 창 — 72h 관측 완료 후 1회
SETTLE_WINDOW_INDEX = 2


class RewardFn(Protocol):
    """지표 dict → reward 값. None=판정 보류(학습 제외, FR-L2)."""

    def __call__(
        self,
        values: Mapping[str, float | None],
        *,
        goal_ref: str,
        platform: Platform,
        publication_id: str,
    ) -> float | None: ...


class NullReward:
    """전량 보류 산식 — 학습을 완전히 끌 때(K2 폴백 등) 쓴다."""

    formula_version = "null-v0"

    def __call__(
        self,
        values: Mapping[str, float | None],
        *,
        goal_ref: str,
        platform: Platform,
        publication_id: str,
    ) -> float | None:
        return None


@dataclass(frozen=True)
class DueWindow:
    publication_id: str
    cycle_id: str
    platform: Platform
    external_post_id: str
    window_index: int


@dataclass(frozen=True)
class PollOutcome:
    due: DueWindow
    stored: int  # 적재된 metric_value 행 수 (실패 시 0)
    error: str | None = None


def due_windows(conn: psycopg.Connection, *, now: datetime | None = None) -> list[DueWindow]:
    """발행됨 + 창 시간 도래 + 아직 미관측인 (publication, window) 목록."""
    now = now if now is not None else datetime.now(tz=UTC)
    rows = conn.execute(
        """
        SELECT p.id, ci.cycle_id, ch.platform, p.external_post_id, p.published_at
          FROM publication p
          JOIN channel ch ON ch.id = p.channel_id
          JOIN content_item ci ON ci.id = p.content_item_id
         WHERE p.status = 'published' AND p.external_post_id IS NOT NULL
        """
    ).fetchall()
    observed = {
        (str(r[0]), int(r[1]))
        for r in conn.execute(
            "SELECT publication_id, window_index FROM metric_observation"
        ).fetchall()
    }
    due: list[DueWindow] = []
    for pub_id, cycle_id, platform, post_id, published_at in rows:
        for window_index, hours in METRIC_WINDOWS_H:
            if (str(pub_id), window_index) in observed:
                continue
            if published_at + timedelta(hours=hours) <= now:
                due.append(
                    DueWindow(
                        publication_id=str(pub_id),
                        cycle_id=str(cycle_id),
                        platform=platform,
                        external_post_id=str(post_id),
                        window_index=window_index,
                    )
                )
    return due


def poll_and_store(
    conn: psycopg.Connection,
    poll_metrics: PollMetrics,
    *,
    now: datetime | None = None,
) -> list[PollOutcome]:
    """도래한 창을 폴링해 관측+값을 적재한다. 재실행 멱등(관측된 창은 재선택 안 됨)."""
    outcomes: list[PollOutcome] = []
    for due in due_windows(conn, now=now):
        try:
            values = poll_metrics(due.platform, due.external_post_id, due.window_index)
        except Exception as exc:  # noqa: BLE001 — 폴링 실패는 그 건만 격리 (FR-P4 규율)
            _log_event(conn, due, error=str(exc)[:300])
            outcomes.append(PollOutcome(due=due, stored=0, error=str(exc)[:300]))
            continue
        stored = _store_observation(conn, due, values)
        _log_event(conn, due, stored=stored)
        outcomes.append(PollOutcome(due=due, stored=stored))
    return outcomes


def _store_observation(
    conn: psycopg.Connection, due: DueWindow, values: tuple[MetricValue, ...]
) -> int:
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO metric_observation (publication_id, window_index) "
            "VALUES (%s, %s) RETURNING id",
            (due.publication_id, due.window_index),
        ).fetchone()
        assert row is not None
        observation_id = row[0]
        for v in values:
            conn.execute(
                "INSERT INTO metric_value (observation_id, metric_key, value, missing) "
                "VALUES (%s, %s, %s, %s)",
                (observation_id, v.metric_key, v.value, v.missing),
            )
    return len(values)


def _log_event(
    conn: psycopg.Connection, due: DueWindow, *, stored: int | None = None, error: str | None = None
) -> None:
    from psycopg.types.json import Json

    kind = "error" if error is not None else "metric_polled"
    payload = {
        "publication_id": due.publication_id,
        "window_index": due.window_index,
        "platform": due.platform,
    }
    if stored is not None:
        payload["stored"] = stored
    if error is not None:
        payload["error"] = error
    conn.execute(
        "INSERT INTO run_event (cycle_id, kind, payload) VALUES (%s, %s, %s)",
        (due.cycle_id, kind, Json(payload)),
    )


def settle_rewards(
    conn: psycopg.Connection,
    reward_fn: RewardFn,
    *,
    formula_version: str,
) -> int:
    """정산 창(72h) 관측이 끝난 publication에 reward를 1회 기록하고,
    reward가 NULL이 아니면 topic_stats를 갱신한다(NULL=학습 제외, FR-L2)."""
    rows = conn.execute(
        """
        SELECT p.id, cy.goal_ref, ci.topic_id, ci.format, ch.platform, mo.id
          FROM publication p
          JOIN content_item ci ON ci.id = p.content_item_id
          JOIN cycle cy ON cy.id = ci.cycle_id
          JOIN channel ch ON ch.id = p.channel_id
          JOIN metric_observation mo
            ON mo.publication_id = p.id AND mo.window_index = %s
         WHERE NOT EXISTS (SELECT 1 FROM reward r WHERE r.publication_id = p.id)
        """,
        (SETTLE_WINDOW_INDEX,),
    ).fetchall()
    settled = 0
    for pub_id, goal_ref, topic_id, content_format, platform, observation_id in rows:
        values: dict[str, float | None] = {
            str(r[0]): (float(r[1]) if r[1] is not None else None)
            for r in conn.execute(
                "SELECT metric_key, value FROM metric_value WHERE observation_id = %s",
                (observation_id,),
            ).fetchall()
        }
        reward_value = reward_fn(
            values, goal_ref=str(goal_ref), platform=platform, publication_id=str(pub_id)
        )
        with conn.transaction():
            conn.execute(
                "INSERT INTO reward (publication_id, reward_value, formula_version) "
                "VALUES (%s, %s, %s)",
                (pub_id, reward_value, formula_version),
            )
            if reward_value is not None:
                conn.execute(
                    """
                    INSERT INTO topic_stats (topic_id, format, platform, trials, reward_sum)
                    VALUES (%s, %s, %s, 1, %s)
                    ON CONFLICT (topic_id, format, platform) DO UPDATE SET
                        trials = topic_stats.trials + 1,
                        reward_sum = topic_stats.reward_sum + EXCLUDED.reward_sum,
                        updated_at = now()
                    """,
                    (topic_id, content_format, platform, reward_value),
                )
        settled += 1
    return settled
