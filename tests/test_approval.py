"""FR-O2 — hybrid 승인 관문: 승인 전 publish 0건은 툴 레벨 불변식 (nooa 무관)."""

import pytest

from sns.approval import ApprovalGate, ApprovalPending
from sns.tools.fakes import FakePublish, FakeRenderMedia

ASSET = FakeRenderMedia()({"layout": "card-v1"}, "image")


def test_auto_mode_passes_through() -> None:
    inner = FakePublish()
    gate = ApprovalGate(inner=inner, mode="auto")
    result = gate("instagram", ASSET, "cap", "key-1")
    assert result.post_id and inner.calls == ["key-1"]


def test_hybrid_unapproved_blocked_and_notified_once() -> None:
    inner = FakePublish()
    notes: list[str] = []
    gate = ApprovalGate(inner=inner, mode="hybrid", notify=notes.append)

    for _ in range(3):  # 재시도해도 발행 0건 + 알림 1회
        with pytest.raises(ApprovalPending):
            gate("instagram", ASSET, "cap", "key-1")

    assert inner.calls == [], "승인 전 publish 발생 — FR-O2 위반"
    assert len(notes) == 1 and "key-1" in notes[0]
    assert gate.pending_keys() == ("key-1",)


def test_approve_then_publish() -> None:
    inner = FakePublish()
    gate = ApprovalGate(inner=inner, mode="hybrid", notify=lambda _: None)
    with pytest.raises(ApprovalPending):
        gate("instagram", ASSET, "cap", "key-1")

    gate.approve("key-1")
    result = gate("instagram", ASSET, "cap", "key-1")

    assert result.post_id and inner.calls == ["key-1"]
    assert gate.pending_keys() == ()


def test_approval_is_per_key() -> None:
    gate = ApprovalGate(inner=FakePublish(), mode="hybrid")
    gate.approve("key-1")
    with pytest.raises(ApprovalPending):
        gate("instagram", ASSET, "cap", "key-2")
