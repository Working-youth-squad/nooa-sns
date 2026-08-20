"""승인 재개 관통 (FR-O2) — approve → publish-pending 배치가 발행 완결 (PG)."""

import pytest

from sns.approval import approve_publication
from sns.publish.runner import run_pending_publications
from sns.tools.fakes import FakePublish


def test_awaiting_review_then_approve_then_publish(db, seed) -> None:  # type: ignore[no-untyped-def]
    pub = seed(quality_status="needs_review")
    db.execute("UPDATE content_item SET status = 'needs_review'")
    fake = FakePublish()

    # 승인 전: 배치는 발행하지 않고 대기(awaiting_review)로 남긴다
    (before,) = run_pending_publications(db, fake)
    assert before.outcome == "awaiting_review" and fake.calls == []

    # 운영자 승인
    summary = approve_publication(db, pub)
    assert summary == {"content_approved": 1, "media_passed": 1}

    # 승인 후: 같은 배치 러너가 멱등 발행 완결
    (after,) = run_pending_publications(db, fake)
    assert after.outcome == "published" and fake.calls == [pub]

    status, external = db.execute(
        "SELECT status, external_post_id FROM publication WHERE id = %s", (pub,)
    ).fetchone()
    assert status == "published" and external

    # 재실행 멱등 — 종결 건은 재선택되지 않는다
    assert run_pending_publications(db, fake) == []
    assert fake.calls == [pub]


def test_approve_unknown_publication_raises(db) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(LookupError):
        approve_publication(db, "00000000-0000-0000-0000-000000000000")


def test_approve_is_idempotent(db, seed) -> None:  # type: ignore[no-untyped-def]
    pub = seed(quality_status="needs_review")
    db.execute("UPDATE content_item SET status = 'needs_review'")
    approve_publication(db, pub)
    again = approve_publication(db, pub)
    assert again == {"content_approved": 0, "media_passed": 0}, "이미 승인된 건은 무변경"
