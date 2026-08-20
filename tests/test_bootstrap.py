"""조립 루트 — 배선 정합성 (KindDispatch·품질 SQL·채널/토큰·에이전트 조립)."""

import pytest

from sns.approval import ApprovalGate
from sns.bootstrap import (
    ChannelRow,
    KindDispatchRender,
    PgReadStats,
    ToolSet,
    build_agent_publish_tool,
    build_orchestrator,
    load_channel,
    quality_check_sql,
    token_provider,
)
from sns.crypto import TokenCipher, generate_key
from sns.tools.contracts import MediaAsset
from sns.tools.fakes import (
    FakePollMetrics,
    FakePublish,
    FakeReadStats,
    FakeRenderMedia,
    FakeResearchTrends,
    FakeWritePlaybook,
)
from tests.helpers import scripted


def test_kind_dispatch_routes_image_to_card() -> None:
    card_calls: list[str] = []

    class CardFake(FakeRenderMedia):
        def __call__(self, media_spec, kind):  # type: ignore[no-untyped-def]
            card_calls.append(kind)
            return super().__call__(media_spec, kind)

    render = KindDispatchRender(card=CardFake())
    asset = render({"layout": "card-v1"}, "image")
    assert isinstance(asset, MediaAsset) and card_calls == ["image"]


def test_kind_dispatch_video_unregistered_fails_fast() -> None:
    render = KindDispatchRender(card=FakeRenderMedia())
    with pytest.raises(ValueError, match="video 렌더러 미등록"):
        render({"scenes": []}, "video")


def test_token_provider_roundtrip_and_missing() -> None:
    cipher = TokenCipher(generate_key(), key_version=1)
    token, version = cipher.encrypt("ig-token-비밀")
    row = ChannelRow(
        id="ch-1",
        platform="instagram",
        handle="h",
        mode="auto",
        token_encrypted=token,
        token_key_version=version,
    )
    assert token_provider(cipher, row)() == "ig-token-비밀"

    empty = ChannelRow(
        id="ch-2",
        platform="instagram",
        handle="h2",
        mode="auto",
        token_encrypted=None,
        token_key_version=None,
    )
    with pytest.raises(ValueError, match="토큰 미등록"):
        token_provider(cipher, empty)()


def test_build_orchestrator_wires_all_seven() -> None:
    tools = ToolSet(
        research_trends=FakeResearchTrends(),
        read_stats=FakeReadStats(),
        render_media=FakeRenderMedia(),
        publish=FakePublish(),
        poll_metrics=FakePollMetrics(),
        write_playbook=FakeWritePlaybook(),
    )
    orch = build_orchestrator(tools, llm=scripted())  # type: ignore[arg-type]

    assert orch.topic.research_trends is tools.research_trends
    assert orch.media.render_media is tools.render_media
    assert orch.publisher.publish is tools.publish
    assert orch.analyst.write_playbook is tools.write_playbook
    assert orch.growth.read_stats is tools.read_stats
    for name in ("topic", "content", "media", "publisher", "analyst", "growth"):
        assert getattr(orch, name) is not None


# ── PG 배선 (PostgreSQL 필요 — 미가동이면 conftest가 skip) ──────────


def test_quality_check_sql_states(db, seed) -> None:  # type: ignore[no-untyped-def]
    check = quality_check_sql(db)
    assert check(seed(quality_status="passed", checksum="q1")) is True
    assert check(seed(quality_status="needs_review", checksum="q2")) is False
    assert check(seed(quality_status="failed", checksum="q3")) is False
    assert check("00000000-0000-0000-0000-000000000000") is False, "행 부재=fail-closed"


def test_load_channel_and_mode_guard(db) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO channel (platform, handle, mode) VALUES ('instagram', 'boot-h', 'auto')"
    )
    row = load_channel(db, platform="instagram", handle="boot-h")
    assert row.mode == "auto" and row.token_encrypted is None

    db.execute("INSERT INTO channel (platform, handle, mode) VALUES ('youtube', 'off-h', 'off')")
    with pytest.raises(ValueError, match="발행 불가 모드"):
        load_channel(db, platform="youtube", handle="off-h")
    with pytest.raises(LookupError):
        load_channel(db, platform="instagram", handle="없는핸들")


def test_agent_publish_tool_chain_composition(db, seed) -> None:  # type: ignore[no-untyped-def]
    row = ChannelRow(
        id="ch-x",
        platform="instagram",
        handle="h",
        mode="hybrid",
        token_encrypted=None,
        token_key_version=None,
    )
    gate = build_agent_publish_tool(db, channel=row, inner=FakePublish(), notify=None)
    assert isinstance(gate, ApprovalGate) and gate.mode == "hybrid"


def test_pg_read_stats_scope(db) -> None:  # type: ignore[no-untyped-def]
    tid = db.execute("INSERT INTO topic (title) VALUES ('t') RETURNING id").fetchone()[0]
    db.execute(
        "INSERT INTO topic_stats (topic_id, format, platform, trials, reward_sum) "
        "VALUES (%s, 'feed_image', 'instagram', 3, 1.5)",
        (tid,),
    )
    stats = PgReadStats(db)
    assert stats("youtube") == ()
    (row,) = stats("instagram")
    assert row.trials == 3 and row.reward_sum == 1.5
