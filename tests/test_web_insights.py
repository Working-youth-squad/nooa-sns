"""웹 인사이트 탭 (FR-W) — read-only 요약·사이클 목록·HTML 렌더 (PG)."""

from contextlib import contextmanager

from fastapi.testclient import TestClient

from sns.web.app import create_app


def make_client(db) -> TestClient:  # type: ignore[no-untyped-def]
    @contextmanager
    def factory():  # type: ignore[no-untyped-def]
        yield db  # 테스트 커넥션 재사용 — close는 conftest 몫

    return TestClient(create_app(factory))


def test_health(db) -> None:  # type: ignore[no-untyped-def]
    assert make_client(db).get("/health").json() == {"status": "ok"}


def test_summary_counts_and_landing_points(db, seed) -> None:  # type: ignore[no-untyped-def]
    pub = seed(quality_status="passed")
    db.execute(
        "UPDATE publication SET status='published', external_post_id='p-1', "
        "published_at=now() WHERE id=%s",
        (pub,),
    )
    cy = db.execute("SELECT id FROM cycle LIMIT 1").fetchone()[0]
    db.execute(
        "INSERT INTO analysis_note (cycle_id, body, insufficient_evidence) "
        "VALUES (%s, 'reach 상위 — 근거 충분', false)",
        (cy,),
    )
    db.execute(
        "INSERT INTO playbook (scope, scope_ref, version, guidance) "
        "VALUES ('global', NULL, 1, 'curiosity 훅 유지')"
    )

    body = make_client(db).get("/api/insights/summary").json()

    assert body["publications"] == {"published": 1}
    assert body["rewards"] == {"total": 0, "with_value": 0}
    assert body["latest_analysis_note"]["body"] == "reach 상위 — 근거 충분"
    assert body["latest_playbook"]["guidance"] == "curiosity 훅 유지"


def test_cycles_listing(db, seed) -> None:  # type: ignore[no-untyped-def]
    seed()
    rows = make_client(db).get("/api/insights/cycles?limit=5").json()
    assert len(rows) == 1
    assert rows[0]["publications"] == 1 and rows[0]["published"] == 0
    assert rows[0]["goal_ref"] == "test-goal"


def test_index_html_renders(db, seed) -> None:  # type: ignore[no-untyped-def]
    seed()
    response = make_client(db).get("/")
    assert response.status_code == 200
    text = response.text
    assert "nooa-sns 인사이트" in text and "최근 사이클" in text
    assert "판정 보류" in text, "NULL reward를 0처럼 보이지 않게 표기 (NFR-3 정신)"


def test_no_mutating_endpoints(db) -> None:  # type: ignore[no-untyped-def]
    client = make_client(db)
    assert client.post("/api/insights/summary").status_code == 405
    assert client.post("/approve").status_code in (404, 405), "웹은 관측만 — 상태 변경 없음"
