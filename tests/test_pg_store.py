"""PgCycleStore + 마이그레이션 + 브리지 DB 착지 — 실 PostgreSQL 필요 (DATABASE_URL).

CI(ubuntu, postgres 서비스)와 docker compose가 정본 실행 환경.
DATABASE_URL 없으면 전부 skip.
"""

import os
import uuid
from collections.abc import Iterator

import pytest

psycopg = pytest.importorskip("psycopg")

from sns.db.migrate import apply_migrations
from sns.observe import RunEvent, RunEventRecorder, store_sink
from sns.store import PgCycleStore

DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL 미설정 — PG 통합 생략")


@pytest.fixture(scope="module")
def migrated() -> None:
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as conn:
        apply_migrations(conn)


@pytest.fixture
def conn(migrated: None) -> Iterator["psycopg.Connection"]:
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL, autocommit=True) as c:
        yield c


@pytest.fixture
def store(conn: "psycopg.Connection") -> PgCycleStore:
    return PgCycleStore(conn)


def test_migrations_idempotent(migrated: None) -> None:
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as conn:
        assert apply_migrations(conn) == []  # 2회차 = 적용 없음


def test_cycle_roundtrip_with_bridge_landing(
    conn: "psycopg.Connection", store: PgCycleStore
) -> None:
    cycle_id = store.create_cycle(f"goal-{uuid.uuid4()}")
    topic_id = store.save_topic(title="rss-topic-1", summary="요약", source="rss")
    content_id = store.save_content_item(
        cycle_id=cycle_id,
        topic_id=topic_id,
        content_format="feed_image",
        body="본문",
        media_spec={"layout": "card-v1"},
        hook_pattern="curiosity",
        status="approved",
    )
    media_id = store.save_media_asset(
        content_item_id=content_id,
        kind="image",
        storage_url="fake://media/abc",
        checksum="abc",
        quality_status="passed",
        quality_report=None,
    )
    channel_id = _make_channel(conn)
    pub_id = store.create_publication(content_item_id=content_id, channel_id=channel_id)

    # 브리지 → DB 착지 (FR-C5): RunEvent가 run_event 행이 된다
    recorder = RunEventRecorder(sink=store_sink(store, cycle_id))
    recorder.handle(_FakeNooaEvent("ToolCallEvent", name="execute_python"))
    recorder.handle(_FakeNooaEvent("LLMCallEnd", usage={"total_tokens": 42}))

    store.complete_cycle(cycle_id, status="completed")

    rows = conn.execute(
        "SELECT kind FROM run_event WHERE cycle_id = %s ORDER BY created_at", (cycle_id,)
    ).fetchall()
    assert [r[0] for r in rows] == ["tool_called", "cost"]
    assert media_id and pub_id

    status = conn.execute("SELECT status FROM cycle WHERE id = %s", (cycle_id,)).fetchone()
    assert status is not None and status[0] == "completed"


def test_duplicate_publication_blocked(conn: "psycopg.Connection", store: PgCycleStore) -> None:
    cycle_id = store.create_cycle(f"goal-{uuid.uuid4()}")
    topic_id = store.save_topic(title="t", summary="s", source="rss")
    content_id = store.save_content_item(
        cycle_id=cycle_id,
        topic_id=topic_id,
        content_format="feed_image",
        body="b",
        media_spec={},
        hook_pattern="story",
        status="approved",
    )
    channel_id = _make_channel(conn)
    store.create_publication(content_item_id=content_id, channel_id=channel_id)
    with pytest.raises(psycopg.errors.UniqueViolation):
        store.create_publication(content_item_id=content_id, channel_id=channel_id)


def test_metric_missing_xor_check_enforced(conn: "psycopg.Connection") -> None:
    """NFR-3 — 결측인데 값이 있는 행은 DB CHECK가 물리적으로 거부."""
    obs_id = _make_observation(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO metric_value (observation_id, metric_key, value, missing) "
            "VALUES (%s, 'reach', 10.0, true)",
            (obs_id,),
        )


class _FakeNooaEvent:
    """브리지 덕타이핑 검증용 — event_type 속성만 흉내."""

    def __init__(self, event_type: str, **attrs: object) -> None:
        self.event_type = event_type
        for k, v in attrs.items():
            setattr(self, k, v)


def _make_channel(conn: "psycopg.Connection") -> str:
    row = conn.execute(
        "INSERT INTO channel (platform, handle, mode) VALUES ('instagram', %s, 'auto') "
        "RETURNING id",
        (f"handle-{uuid.uuid4()}",),
    ).fetchone()
    assert row is not None
    return str(row[0])


def _make_observation(conn: "psycopg.Connection") -> str:
    store = PgCycleStore(conn)
    cycle_id = store.create_cycle(f"goal-{uuid.uuid4()}")
    topic_id = store.save_topic(title="t", summary="s", source="rss")
    content_id = store.save_content_item(
        cycle_id=cycle_id,
        topic_id=topic_id,
        content_format="feed_image",
        body="b",
        media_spec={},
        hook_pattern="question",
        status="approved",
    )
    channel_id = _make_channel(conn)
    pub_id = store.create_publication(content_item_id=content_id, channel_id=channel_id)
    row = conn.execute(
        "INSERT INTO metric_observation (publication_id, window_index) VALUES (%s, 0) RETURNING id",
        (pub_id,),
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_run_event_dataclass_shape() -> None:
    e = RunEvent(kind="cost", payload={"usage": "42"}, cost_usd=0.01)
    assert e.kind == "cost" and e.cost_usd == 0.01
