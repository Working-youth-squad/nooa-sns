"""PgWritePlaybook (FR-L4) — scope별 버전 전진, 착지점 계약 적합 (PG)."""

from sns.learning.playbook import PgWritePlaybook


def test_version_advances_per_scope(db) -> None:  # type: ignore[no-untyped-def]
    store = PgWritePlaybook(db)

    v1 = store("global", "훅은 curiosity 우선")
    v2 = store("global", "저장 유도 문구 추가")
    assert (v1.version, v2.version) == (1, 2)

    # scope_ref가 다르면 독립 시퀀스
    p1 = store("platform", "릴스는 첫 2초", scope_ref="instagram")
    assert p1.version == 1

    rows = db.execute(
        "SELECT scope, scope_ref, version, guidance FROM playbook ORDER BY scope, version"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0][3] == "훅은 curiosity 우선"
