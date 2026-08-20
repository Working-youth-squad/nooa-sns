"""조립 루트 (composition root) — 운영 배선의 단일 지점.

Config→cipher→어댑터→게이트→에이전트 7종의 조립이 전부 여기에 산다.
각 모듈은 주입식이라 조립을 모른다 — 교체·테스트는 seam 단위로 한다.

운영 발행 경로(원본 07-발행 설계 계승):
  ① `sns.runner.run_cycle` — 사이클 산출물이 publication(pending)으로 착지
  ② `sns.publish.runner.run_pending_publications` — 품질 게이트 배선 + 멱등 발행
에이전트 부착 발행 툴(ApprovalGate+StateMachinePublish)은 승인 재개·수동 위임
경로용이며, publication 원장이 없는 시점의 발행 시도는 품질 조회 실패로
fail-closed 된다(QualityGateError — 정직한 보류).
"""

import asyncio
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from sns.adapters.instagram import InstagramPublish
from sns.adapters.instagram.metrics import InstagramInsights
from sns.adapters.youtube import YouTubePublish, build_youtube, load_credentials
from sns.adapters.youtube.auth import build_youtube_analytics
from sns.adapters.youtube.metrics import YouTubeMetrics
from sns.agents.analyst import AnalystAgent
from sns.agents.content import ContentAgent
from sns.agents.core import UnifiedLLM, make_llm
from sns.agents.growth import GrowthAgent
from sns.agents.media import MediaAgent
from sns.agents.orchestrator import OrchestratorAgent
from sns.agents.publisher import PublisherAgent
from sns.agents.topic import TopicAgent
from sns.approval import ApprovalGate, ChannelMode, approve_publication
from sns.config import Config
from sns.crypto import TokenCipher
from sns.learning.loop import NullReward, poll_and_store, settle_rewards
from sns.learning.playbook import PgWritePlaybook
from sns.notify.discord import discord_sender_from_env
from sns.publish.dispatch import PlatformDispatch
from sns.publish.runner import run_pending_publications
from sns.publish.stores import PgPublishAttemptStore
from sns.publish.tool import StateMachinePublish
from sns.render.card.media import CardRenderMedia
from sns.render.storage import InMemoryMediaStore
from sns.research.trends import default_service
from sns.runner import CycleTarget, RunnerResult, run_cycle
from sns.store import PgCycleStore
from sns.tools.contracts import (
    MediaAsset,
    MediaKind,
    Platform,
    Publish,
    ReadStats,
    RenderMedia,
    TopicStat,
)


@dataclass(frozen=True)
class ChannelRow:
    id: str
    platform: Platform
    handle: str
    mode: ChannelMode
    token_encrypted: bytes | None
    token_key_version: int | None


def load_channel(conn: psycopg.Connection, *, platform: Platform, handle: str) -> ChannelRow:
    row = conn.execute(
        "SELECT id, platform, handle, mode, token_encrypted, token_key_version "
        "FROM channel WHERE platform = %s AND handle = %s",
        (platform, handle),
    ).fetchone()
    if row is None:
        raise LookupError(f"채널 없음: {platform}/{handle}")
    if row[3] not in ("auto", "hybrid"):
        raise ValueError(f"발행 불가 모드: {row[3]} ({platform}/{handle})")
    return ChannelRow(
        id=str(row[0]),
        platform=row[1],
        handle=row[2],
        mode=row[3],
        token_encrypted=bytes(row[4]) if row[4] is not None else None,
        token_key_version=row[5],
    )


def token_provider(cipher: TokenCipher, channel: ChannelRow) -> Callable[[], str]:
    """채널 토큰의 지연 복호 콜러블 — 평문은 호출 순간에만 존재 (FR-S3)."""

    def provide() -> str:
        if channel.token_encrypted is None:
            raise ValueError(f"채널 토큰 미등록: {channel.platform}/{channel.handle}")
        return cipher.decrypt(channel.token_encrypted)

    return provide


class KindDispatchRender:
    """RenderMedia 계약 — kind로 카드/영상 렌더러를 고른다 (video는 등록 시에만)."""

    def __init__(self, *, card: RenderMedia, video: RenderMedia | None = None) -> None:
        self._card = card
        self._video = video

    def __call__(self, media_spec: Mapping[str, object], kind: MediaKind) -> MediaAsset:
        if kind in ("image", "thumbnail"):
            return self._card(media_spec, kind)
        if self._video is None:
            raise ValueError(f"video 렌더러 미등록 — kind={kind} 렌더 불가 (미결정 #7: 렌더러)")
        return self._video(media_spec, kind)


class PgReadStats:
    """ReadStats 계약 — topic_stats 집계 조회 (자기 채널 스코프만, 원칙 5)."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def __call__(self, platform: Platform | None = None) -> tuple[TopicStat, ...]:
        sql = "SELECT topic_id, format, platform, trials, reward_sum FROM topic_stats"
        params: tuple[object, ...] = ()
        if platform is not None:
            sql += " WHERE platform = %s"
            params = (platform,)
        rows = self._conn.execute(sql, params).fetchall()
        return tuple(
            TopicStat(
                topic_id=str(r[0]),
                format=r[1],
                platform=r[2],
                trials=int(r[3]),
                reward_sum=float(r[4]),
            )
            for r in rows
        )


def quality_check_sql(conn: psycopg.Connection) -> Callable[[str], bool]:
    """publication_id → 매칭 자산의 품질 게이트 통과 여부. 행 부재=False(fail-closed)."""

    def check(publication_id: str) -> bool:
        row = conn.execute(
            """
            SELECT ma.quality_status
              FROM publication p
              JOIN content_item ci ON ci.id = p.content_item_id
              JOIN media_asset ma
                ON ma.content_item_id = ci.id
               AND ma.kind = CASE WHEN ci.format = 'feed_image' THEN 'image' ELSE 'video' END
             WHERE p.id = %s
            """,
            (publication_id,),
        ).fetchone()
        return row is not None and row[0] == "passed"

    return check


def build_platform_publish(
    *,
    channel: ChannelRow,
    cipher: TokenCipher,
    env: Mapping[str, str] | None = None,
    media_bytes: Callable[[str], bytes] | None = None,
) -> Publish:
    """채널 플랫폼에 맞는 실 어댑터 디스패처. 필요한 설정 부재 시 fail-fast."""
    env = os.environ if env is None else env
    routes: dict[Platform, Publish] = {}
    if channel.platform == "instagram":
        ig_user_id = env.get("IG_USER_ID", "")
        if not ig_user_id:
            raise ValueError("IG_USER_ID 미설정 — 인스타그램 발행 불가")
        routes["instagram"] = InstagramPublish(
            ig_user_id=ig_user_id, access_token=token_provider(cipher, channel)
        )
    else:
        client_secret = Path(env.get("YT_CLIENT_SECRET", "secrets/yt_client_secret.json"))
        token = Path(env.get("YT_TOKEN", "secrets/yt_token.json"))
        if media_bytes is None:
            raise ValueError("youtube 발행에는 media_bytes(스토리지 조회 seam)가 필요")
        youtube = build_youtube(load_credentials(client_secret, token))
        routes["youtube"] = YouTubePublish(youtube, media_bytes=media_bytes)
    return PlatformDispatch(routes)


def build_poll_metrics(
    *,
    channel: ChannelRow,
    cipher: TokenCipher,
    env: Mapping[str, str] | None = None,
) -> Any:
    """채널 플랫폼의 지표 폴러 (PollMetrics 계약, FR-L1)."""
    env = os.environ if env is None else env
    if channel.platform == "instagram":
        return InstagramInsights(access_token=token_provider(cipher, channel))
    client_secret = Path(env.get("YT_CLIENT_SECRET", "secrets/yt_client_secret.json"))
    token = Path(env.get("YT_TOKEN", "secrets/yt_token.json"))
    return YouTubeMetrics(build_youtube_analytics(load_credentials(client_secret, token)))


def run_metrics_slot(conn: psycopg.Connection, poll_metrics: Any) -> tuple[int, int]:
    """지표 슬롯 1회: 도래 창 폴링·적재 → reward 정산(NullReward=판정 보류).

    반환: (폴링한 창 수, 정산한 publication 수). 산식 계수 사전등록 후
    reward_fn만 교체하면 학습이 켜진다(spec §7 미결정 유지).
    """
    reward_fn = NullReward()
    outcomes = poll_and_store(conn, poll_metrics)
    settled = settle_rewards(conn, reward_fn, formula_version=reward_fn.formula_version)
    return len(outcomes), settled


def build_agent_publish_tool(
    conn: psycopg.Connection,
    *,
    channel: ChannelRow,
    inner: Publish,
    notify: Callable[[str], None] | None,
) -> ApprovalGate:
    """에이전트 부착용 발행 사슬: ApprovalGate(StateMachinePublish(원장, 어댑터, 품질))."""
    return ApprovalGate(
        inner=StateMachinePublish(
            attempt_store=PgPublishAttemptStore(conn),
            publish=inner,
            quality_passed=quality_check_sql(conn),
        ),
        mode=channel.mode,
        notify=notify,
    )


@dataclass(frozen=True)
class ToolSet:
    """에이전트 7종에 부착할 툴 계약 묶음."""

    research_trends: Any
    read_stats: ReadStats
    render_media: RenderMedia
    publish: Publish
    poll_metrics: Any
    write_playbook: Any


def build_orchestrator(tools: ToolSet, *, llm: UnifiedLLM) -> OrchestratorAgent:
    """7 에이전트 전부 CodeAct(확정 결정) — 판단 LLM 하나를 공유 주입."""
    return OrchestratorAgent(
        topic=TopicAgent(
            research_trends=tools.research_trends, read_stats=tools.read_stats, llm=llm
        ),
        content=ContentAgent(llm=llm),
        media=MediaAgent(render_media=tools.render_media, llm=llm),
        publisher=PublisherAgent(publish=tools.publish, llm=llm),
        analyst=AnalystAgent(
            poll_metrics=tools.poll_metrics,
            read_stats=tools.read_stats,
            write_playbook=tools.write_playbook,
            llm=llm,
        ),
        growth=GrowthAgent(read_stats=tools.read_stats, llm=llm),
        llm=llm,
    )


async def run_slot(
    *,
    conn: psycopg.Connection,
    orchestrator: OrchestratorAgent,
    goal_ref: str,
    target: CycleTarget,
    batch_publish: Publish,
) -> RunnerResult:
    """운영 슬롯 1회: 사이클(착지) → 대기 발행 배치(품질 배선+멱등)."""
    result = await run_cycle(
        store=PgCycleStore(conn), orchestrator=orchestrator, goal_ref=goal_ref, target=target
    )
    run_pending_publications(conn, batch_publish)
    return result


@dataclass(frozen=True)
class ChannelContext:
    """CLI 서브커맨드가 공유하는 채널별 조립 결과."""

    channel: ChannelRow
    adapters: Publish
    media_store: InMemoryMediaStore


def _build_channel_context(
    conn: psycopg.Connection, cipher: TokenCipher, args: Any
) -> ChannelContext:
    channel = load_channel(conn, platform=args.platform, handle=args.handle)
    media_store = InMemoryMediaStore()  # ponytail: LocalDirMediaStore(공개 base_url)로 교체 지점
    adapters = build_platform_publish(
        channel=channel, cipher=cipher, media_bytes=media_store.blobs.__getitem__
    )
    return ChannelContext(channel=channel, adapters=adapters, media_store=media_store)


def _cmd_cycle(conn: psycopg.Connection, cipher: TokenCipher, args: Any) -> None:
    ctx = _build_channel_context(conn, cipher, args)
    notify = discord_sender_from_env()
    tools = ToolSet(
        research_trends=default_service(),
        read_stats=PgReadStats(conn),
        render_media=KindDispatchRender(card=CardRenderMedia(ctx.media_store)),
        publish=build_agent_publish_tool(
            conn, channel=ctx.channel, inner=ctx.adapters, notify=_as_text_notify(notify)
        ),
        poll_metrics=build_poll_metrics(channel=ctx.channel, cipher=cipher),
        write_playbook=PgWritePlaybook(conn),
    )
    orchestrator = build_orchestrator(tools, llm=make_llm("judgment"))
    target = CycleTarget(
        channel_id=ctx.channel.id,
        platform=ctx.channel.platform,
        content_format=args.format,
        media_kind="image" if args.format == "feed_image" else "video",
        mode=ctx.channel.mode,
    )
    result = asyncio.run(
        run_slot(
            conn=conn,
            orchestrator=orchestrator,
            goal_ref=args.goal,
            target=target,
            batch_publish=ctx.adapters,
        )
    )
    print(f"cycle={result.cycle_id} published={result.published}")


def _cmd_metrics(conn: psycopg.Connection, cipher: TokenCipher, args: Any) -> None:
    channel = load_channel(conn, platform=args.platform, handle=args.handle)
    polled, settled = run_metrics_slot(conn, build_poll_metrics(channel=channel, cipher=cipher))
    print(f"polled_windows={polled} settled_rewards={settled}")


def _cmd_publish_pending(conn: psycopg.Connection, cipher: TokenCipher, args: Any) -> None:
    ctx = _build_channel_context(conn, cipher, args)
    results = run_pending_publications(conn, ctx.adapters)
    for r in results:
        print(f"{r.publication_id}: {r.outcome}")
    print(f"total={len(results)}")


def _cmd_approve(conn: psycopg.Connection, cipher: TokenCipher, args: Any) -> None:
    summary = approve_publication(conn, args.publication_id)
    print(
        f"approved: content={summary['content_approved']} media={summary['media_passed']} "
        f"— 발행은 `publish-pending`으로"
    )


def _cmd_resident(conn: psycopg.Connection, cipher: TokenCipher, args: Any) -> None:
    """상주 러너 — 슬롯마다 사이클→발행배치→지표정산. (스케줄 방식 미결정 #7의 한 축)"""
    from datetime import UTC as _UTC
    from datetime import datetime as _dt
    from datetime import time as _time

    from sns.scheduler import SlotSchedule, run_resident

    slots = tuple(
        _time(int(part.split(":")[0]), int(part.split(":")[1]))
        for part in str(args.slots).split(",")
    )
    schedule = SlotSchedule(slots=slots)

    async def trigger(slot: Any) -> None:
        print(f"slot fired: {slot}")
        _cmd_cycle(conn, cipher, args)
        _cmd_metrics(conn, cipher, args)

    async def loop() -> None:
        await run_resident(
            schedule,
            trigger,
            clock=lambda: _dt.now(tz=_UTC),
            sleep=asyncio.sleep,
            until=lambda: False,
        )

    asyncio.run(loop())


def main() -> None:
    """운영 CLI. 필요 env: DATABASE_URL, APP_ENCRYPTION_KEY, LLM 키(SNS_LLM_* 참조),
    IG_USER_ID(인스타) 또는 YT_CLIENT_SECRET/YT_TOKEN(유튜브),
    DISCORD_WEBHOOK_URL(선택), SNS_SANDBOX=1(샌드박스 내 필수)."""
    import argparse

    parser = argparse.ArgumentParser(description="nooa-sns 운영 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    def channel_args(p: Any) -> None:
        p.add_argument("--platform", required=True, choices=["instagram", "youtube"])
        p.add_argument("--handle", required=True)

    p_cycle = sub.add_parser("cycle", help="사이클 1회(기획→제작→착지) + 대기 발행 배치")
    channel_args(p_cycle)
    p_cycle.add_argument(
        "--format", default="feed_image", choices=["feed_image", "reels", "shorts"]
    )
    p_cycle.add_argument("--goal", default="follower_growth")
    p_cycle.set_defaults(func=_cmd_cycle)

    p_metrics = sub.add_parser("metrics", help="지표 창 폴링·적재 + reward 정산")
    channel_args(p_metrics)
    p_metrics.set_defaults(func=_cmd_metrics)

    p_pending = sub.add_parser("publish-pending", help="대기 발행 배치(승인 재개 포함, 멱등)")
    channel_args(p_pending)
    p_pending.set_defaults(func=_cmd_publish_pending)

    p_approve = sub.add_parser("approve", help="hybrid 승인 — needs_review→발행 가능 상태로")
    p_approve.add_argument("--publication-id", required=True)
    p_approve.set_defaults(func=_cmd_approve)

    p_resident = sub.add_parser("resident", help="상주 러너 — 슬롯마다 cycle+metrics")
    channel_args(p_resident)
    p_resident.add_argument("--slots", default="09:00,18:00", help="UTC HH:MM 콤마 구분")
    p_resident.add_argument(
        "--format", default="feed_image", choices=["feed_image", "reels", "shorts"]
    )
    p_resident.add_argument("--goal", default="follower_growth")
    p_resident.set_defaults(func=_cmd_resident)

    args = parser.parse_args()
    config = Config.from_env()
    cipher = TokenCipher.from_config(config)
    with psycopg.connect(config.database_url, autocommit=True) as conn:
        args.func(conn, cipher, args)


def _as_text_notify(
    sender: Callable[[dict[str, object]], None] | None,
) -> Callable[[str], None] | None:
    if sender is None:
        return None

    def notify(text: str) -> None:
        sender({"content": text[:1900]})

    return notify


if __name__ == "__main__":
    main()
