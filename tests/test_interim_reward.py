"""임시 reward 산식 interim-baseline-v1 (팀 사전등록 전 가배치) — PG.

원칙 검증: goal 1차 신호만 · 자기 베이스라인 중앙값 대비 비율 · 표본<5=보류 ·
비율 상한 10배 · 미등록 goal=보류.
"""

from sns.learning.loop import settle_rewards
from sns.learning.reward import RATIO_CAP, InterimBaselineReward


def _published(db, seed, *, goal_ref: str = "engagement_depth") -> str:  # type: ignore[no-untyped-def]
    pub = seed(quality_status="passed")
    db.execute(
        "UPDATE publication SET status='published', external_post_id=%s, "
        "published_at=now() - interval '100 hour' WHERE id=%s",
        (f"post-{pub[:8]}", pub),
    )
    db.execute(
        "UPDATE cycle SET goal_ref=%s WHERE id="
        "(SELECT ci.cycle_id FROM content_item ci JOIN publication p "
        " ON p.content_item_id=ci.id WHERE p.id=%s)",
        (goal_ref, pub),
    )
    return str(pub)


def _observe_window2(db, pub: str, values: dict[str, float]) -> None:  # type: ignore[no-untyped-def]
    oid = db.execute(
        "INSERT INTO metric_observation (publication_id, window_index) VALUES (%s, 2) RETURNING id",
        (pub,),
    ).fetchone()[0]
    for key, value in values.items():
        db.execute(
            "INSERT INTO metric_value (observation_id, metric_key, value, missing) "
            "VALUES (%s, %s, %s, false)",
            (oid, key, value),
        )


def _history(db, seed, n: int, values: dict[str, float]) -> None:  # type: ignore[no-untyped-def]
    """베이스라인 이력 n건 — 이미 정산된 것으로 표시해 settle 대상에서 제외."""
    for _ in range(n):
        pub = _published(db, seed)
        _observe_window2(db, pub, values)
        db.execute(
            "INSERT INTO reward (publication_id, reward_value, formula_version) "
            "VALUES (%s, NULL, 'seed-history')",
            (pub,),
        )


def test_insufficient_baseline_is_held(db, seed) -> None:  # type: ignore[no-untyped-def]
    """이력 표본 < 5 → reward NULL(판정 보류) — 초기 사이클은 학습하지 않는다."""
    _history(db, seed, 2, {"saved": 100.0, "shares": 50.0})
    target = _published(db, seed)
    _observe_window2(db, target, {"saved": 200.0, "shares": 100.0})

    assert settle_rewards(db, InterimBaselineReward(db), formula_version="interim-baseline-v1") == 1
    row = db.execute(
        "SELECT reward_value FROM reward WHERE publication_id=%s", (target,)
    ).fetchone()
    assert row == (None,)
    assert db.execute("SELECT count(*) FROM topic_stats").fetchone()[0] == 0


def test_baseline_ratio_mean(db, seed) -> None:  # type: ignore[no-untyped-def]
    """이력 5건 확보 후: 사용 가능 신호들의 (값/중앙값, 상한) 평균."""
    _history(db, seed, 5, {"saved": 100.0, "shares": 50.0})
    target = _published(db, seed)
    # saved 2배, shares 3배 — likes/comments 결측은 제외 → (2+3)/2 = 2.5
    _observe_window2(db, target, {"saved": 200.0, "shares": 150.0})

    settle_rewards(db, InterimBaselineReward(db), formula_version="interim-baseline-v1")
    row = db.execute(
        "SELECT reward_value, formula_version FROM reward WHERE publication_id=%s", (target,)
    ).fetchone()
    assert row is not None and row[1] == "interim-baseline-v1"
    assert abs(float(row[0]) - 2.5) < 1e-9
    assert db.execute("SELECT trials, reward_sum FROM topic_stats").fetchone() == (1, 2.5)


def test_ratio_capped_at_10x(db, seed) -> None:  # type: ignore[no-untyped-def]
    """heavy-tail 방어 — 분산 연구 근거(10배)로 비율 상한."""
    _history(db, seed, 5, {"saved": 100.0})
    target = _published(db, seed)
    _observe_window2(db, target, {"saved": 100_000.0})

    settle_rewards(db, InterimBaselineReward(db), formula_version="interim-baseline-v1")
    row = db.execute(
        "SELECT reward_value FROM reward WHERE publication_id=%s", (target,)
    ).fetchone()
    assert float(row[0]) == RATIO_CAP


def test_unregistered_goal_is_held(db, seed) -> None:  # type: ignore[no-untyped-def]
    """미등록 goal_ref는 임의 해석하지 않고 보류(None)."""
    _history(db, seed, 5, {"saved": 100.0})
    target = _published(db, seed, goal_ref="test-goal")  # 미등록
    _observe_window2(db, target, {"saved": 200.0})

    settle_rewards(db, InterimBaselineReward(db), formula_version="interim-baseline-v1")
    row = db.execute(
        "SELECT reward_value FROM reward WHERE publication_id=%s", (target,)
    ).fetchone()
    assert row == (None,)
