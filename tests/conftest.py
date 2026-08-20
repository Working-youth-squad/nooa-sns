"""테스트 공용 픽스처.

① Windows 가드: nooa는 fcntl 의존으로 Linux/macOS 전용 — Windows 네이티브에선
   nooa 의존 테스트 제외. 로컬 실행 경로: `docker compose up --build`.
   CI(ubuntu)가 전체 스위트의 정본 검증 환경이다.
② PG 픽스처(원본 multiagent-sns 이식): 스키마는 세션 1회 재생성, 데이터는
   테스트마다 TRUNCATE로 격리. PostgreSQL 미가동이면 해당 테스트 skip.
"""

import os
import sys
import uuid
from collections.abc import Callable, Iterator

import psycopg
import pytest

from sns.db.migrate import apply_migrations

if sys.platform == "win32":
    collect_ignore = [
        "helpers.py",
        "cycle_fixtures.py",
        "test_determinism.py",
        "test_tool_surface.py",
        "test_event_bridge.py",
        "test_full_cycle.py",
        "test_runner.py",
        # sns.notify는 cause.py가 어댑터(sns.agents.core→nooa)를 임포트
        "test_bootstrap.py",
        "test_token_and_ytauth.py",
        "test_notify_cause.py",
        "test_notify_discord.py",
        "test_notify_dispatch.py",
        "test_notify_pg_sink.py",
    ]

DSN = os.environ.get("DATABASE_URL", "postgresql://sns:sns@localhost:5432/sns")

_MUTABLE_TABLES = (
    "channel, cycle, topic, content_item, media_asset, publication, publish_attempt, run_event"
)

# channel~publication FK 체인 + (선택) media_asset을 한 번에 만들고 publication id 반환.
_SEED_WITH_MEDIA = """
WITH ch AS (
    INSERT INTO channel (platform, handle, mode)
    VALUES (%(platform)s, %(handle)s, 'auto') RETURNING id
), cy AS (
    INSERT INTO cycle (goal_ref) VALUES ('test-goal') RETURNING id
), tp AS (
    INSERT INTO topic (title) VALUES ('test-topic') RETURNING id
), ci AS (
    INSERT INTO content_item (cycle_id, topic_id, format, body)
    SELECT cy.id, tp.id, %(fmt)s, %(body)s FROM cy, tp RETURNING id
), ma AS (
    INSERT INTO media_asset (content_item_id, kind, storage_url, checksum, quality_status)
    SELECT ci.id, %(kind)s, %(storage_url)s, %(checksum)s, %(qstatus)s FROM ci RETURNING id
)
INSERT INTO publication (content_item_id, channel_id)
SELECT ci.id, ch.id FROM ci, ch RETURNING id
"""

# media_asset 없이 발행 건만 (러너 no_media 경로).
_SEED_NO_MEDIA = """
WITH ch AS (
    INSERT INTO channel (platform, handle, mode)
    VALUES (%(platform)s, %(handle)s, 'auto') RETURNING id
), cy AS (
    INSERT INTO cycle (goal_ref) VALUES ('test-goal') RETURNING id
), tp AS (
    INSERT INTO topic (title) VALUES ('test-topic') RETURNING id
), ci AS (
    INSERT INTO content_item (cycle_id, topic_id, format, body)
    SELECT cy.id, tp.id, %(fmt)s, %(body)s FROM cy, tp RETURNING id
)
INSERT INTO publication (content_item_id, channel_id)
SELECT ci.id, ch.id FROM ci, ch RETURNING id
"""


@pytest.fixture(scope="session")
def _schema() -> Iterator[None]:
    try:
        c = psycopg.connect(DSN, connect_timeout=5, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL 미가동 — docker compose up -d db")
    with c:
        c.execute("DROP SCHEMA public CASCADE")
        c.execute("CREATE SCHEMA public")
        apply_migrations(c)
        yield


@pytest.fixture
def db(_schema: None) -> Iterator[psycopg.Connection]:
    c = psycopg.connect(DSN, autocommit=True)
    with c:
        c.execute(f"TRUNCATE {_MUTABLE_TABLES} RESTART IDENTITY CASCADE")
        yield c


SeedFn = Callable[..., str]


@pytest.fixture
def seed(db: psycopg.Connection) -> SeedFn:
    """발행 대기 publication 1건을 시드하고 그 id(str)를 돌려준다."""

    def _seed(
        *,
        quality_status: str = "passed",
        kind: str = "video",
        fmt: str = "reels",
        body: str = "훅 문장\n본문",
        platform: str = "instagram",
        checksum: str = "chk-seed",
        with_media: bool = True,
    ) -> str:
        params = {
            "platform": platform,
            "handle": f"h-{uuid.uuid4().hex[:8]}",
            "fmt": fmt,
            "body": body,
            "kind": kind,
            "storage_url": f"mem://{checksum}",
            "checksum": checksum,
            "qstatus": quality_status,
        }
        sql = _SEED_WITH_MEDIA if with_media else _SEED_NO_MEDIA
        row = db.execute(sql, params).fetchone()
        assert row is not None
        return str(row[0])

    return _seed
