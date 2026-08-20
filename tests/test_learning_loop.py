"""학습 루프 (FR-L1~L3) — 창 도래·적재 멱등·결측 보존·reward 정산·stats 갱신 (PG)."""

from collections.abc import Mapping

from sns.learning.loop import (
    METRIC_WINDOWS_H,
    NullReward,
    due_windows,
    poll_and_store,
    settle_rewards,
)
from sns.tools.fakes import FakePollMetrics


def publish_seeded(db, seed, *, hours_ago: float, post_id: str = "post-1") -> str:  # type: ignore[no-untyped-def]
    pub_id = seed(quality_status="passed")
    db.execute(
        "UPDATE publication SET status='published', external_post_id=%s, "
        "published_at=now() - %s * interval '1 hour' WHERE id=%s",
        (post_id, hours_ago, pub_id),
    )
    return str(pub_id)


def test_due_windows_by_elapsed_time(db, seed) -> None:  # type: ignore[no-untyped-def]
    pub = publish_seeded(db, seed, hours_ago=25)  # 6h·24h 도래, 72h 미도래
    due = due_windows(db)
    assert [(d.publication_id, d.window_index) for d in due] == [(pub, 0), (pub, 1)]


def test_poll_stores_and_is_idempotent(db, seed) -> None:  # type: ignore[no-untyped-def]
    pub = publish_seeded(db, seed, hours_ago=100)  # 3창 전부 도래
    outcomes = poll_and_store(db, FakePollMetrics())

    assert [o.due.window_index for o in outcomes] == [0, 1, 2]
    assert all(o.error is None and o.stored > 0 for o in outcomes)

    # 결측 보존: FakePollMetrics 기본 missing_keys=skip_rate → missing=True·NULL
    missing = db.execute(
        "SELECT count(*) FROM metric_value mv JOIN metric_observation mo "
        "ON mo.id=mv.observation_id WHERE mo.publication_id=%s AND mv.missing",
        (pub,),
    ).fetchone()[0]
    assert missing == len(METRIC_WINDOWS_H), "결측 지표가 창마다 NULL로 보존돼야 함"

    # 멱등: 재실행 시 도래 창 없음
    assert poll_and_store(db, FakePollMetrics()) == []


def test_poll_failure_isolated_and_logged(db, seed) -> None:  # type: ignore[no-untyped-def]
    publish_seeded(db, seed, hours_ago=7)  # 창 0만 도래

    def broken(platform, post_id, window_index):  # type: ignore[no-untyped-def]
        raise RuntimeError("insights down")

    (outcome,) = poll_and_store(db, broken)
    assert outcome.error is not None and outcome.stored == 0
    # 관측 행은 없고 error 이벤트만 남는다
    assert db.execute("SELECT count(*) FROM metric_observation").fetchone()[0] == 0
    kinds = [r[0] for r in db.execute("SELECT kind FROM run_event").fetchall()]
    assert "error" in kinds


def test_null_reward_settles_but_excludes_from_learning(db, seed) -> None:  # type: ignore[no-untyped-def]
    publish_seeded(db, seed, hours_ago=100)
    poll_and_store(db, FakePollMetrics())

    assert settle_rewards(db, NullReward(), formula_version="null-v0") == 1
    reward = db.execute("SELECT reward_value, formula_version FROM reward").fetchone()
    assert reward == (None, "null-v0")
    assert db.execute("SELECT count(*) FROM topic_stats").fetchone()[0] == 0, (
        "NULL reward는 학습 제외 (FR-L2)"
    )
    # 재정산 없음(1회 기록)
    assert settle_rewards(db, NullReward(), formula_version="null-v0") == 0


class FixedReward:
    def __call__(self, values: Mapping[str, float | None], *, goal_ref: str) -> float | None:
        assert values.get("reach") is not None, "정산 입력에 적재 지표가 와야 함"
        return 2.5


def test_reward_updates_topic_stats_upsert(db, seed) -> None:  # type: ignore[no-untyped-def]
    pub = publish_seeded(db, seed, hours_ago=100)
    poll_and_store(db, FakePollMetrics())
    assert settle_rewards(db, FixedReward(), formula_version="fixed-v1") == 1

    row = db.execute("SELECT trials, reward_sum FROM topic_stats").fetchone()
    assert row == (1, 2.5)

    # 같은 (topic, format, platform)의 두 번째 발행 → upsert 누적
    topic_id, format_, channel_id = db.execute(
        "SELECT ci.topic_id, ci.format, p.channel_id FROM publication p "
        "JOIN content_item ci ON ci.id=p.content_item_id WHERE p.id=%s",
        (pub,),
    ).fetchone()
    cy = db.execute("INSERT INTO cycle (goal_ref) VALUES ('g2') RETURNING id").fetchone()[0]
    ci2 = db.execute(
        "INSERT INTO content_item (cycle_id, topic_id, format, body) "
        "VALUES (%s, %s, %s, 'b2') RETURNING id",
        (cy, topic_id, format_),
    ).fetchone()[0]
    pub2 = db.execute(
        "INSERT INTO publication (content_item_id, channel_id, status, external_post_id, "
        "published_at) VALUES (%s, %s, 'published', 'post-2', now() - interval '100 hour') "
        "RETURNING id",
        (ci2, channel_id),
    ).fetchone()[0]
    poll_and_store(db, FakePollMetrics())
    assert settle_rewards(db, FixedReward(), formula_version="fixed-v1") == 1

    row = db.execute("SELECT trials, reward_sum FROM topic_stats").fetchone()
    assert row == (2, 5.0), f"upsert 누적 실패 (pub2={pub2})"
