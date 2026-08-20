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
from sns.approval import ApprovalGate, ChannelMode
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


def main() -> None:
    """상주 러너/cron 공용 CLI — 슬롯 1회 실행. (스케줄 방식은 미결정 #7)

    필요 env: DATABASE_URL, APP_ENCRYPTION_KEY, ANTHROPIC_API_KEY,
    IG_USER_ID(인스타) 또는 YT_CLIENT_SECRET/YT_TOKEN(유튜브),
    DISCORD_WEBHOOK_URL(선택), SNS_SANDBOX=1(샌드박스 내 필수).
    """
    import argparse

    parser = argparse.ArgumentParser(description="nooa-sns 슬롯 1회 실행")
    parser.add_argument("--platform", required=True, choices=["instagram", "youtube"])
    parser.add_argument("--handle", required=True)
    parser.add_argument("--format", default="feed_image", choices=["feed_image", "reels", "shorts"])
    parser.add_argument("--goal", default="follower_growth")
    args = parser.parse_args()

    config = Config.from_env()
    cipher = TokenCipher.from_config(config)
    with psycopg.connect(config.database_url, autocommit=True) as conn:
        channel = load_channel(conn, platform=args.platform, handle=args.handle)
        notify = discord_sender_from_env()
        media_store = InMemoryMediaStore()  # ponytail: 외부 스토리지(공개 URL) 교체 지점
        adapters = build_platform_publish(
            channel=channel, cipher=cipher, media_bytes=media_store.blobs.__getitem__
        )
        tools = ToolSet(
            research_trends=default_service(),
            read_stats=PgReadStats(conn),
            render_media=KindDispatchRender(card=CardRenderMedia(media_store)),
            publish=build_agent_publish_tool(
                conn, channel=channel, inner=adapters, notify=_as_text_notify(notify)
            ),
            poll_metrics=build_poll_metrics(channel=channel, cipher=cipher),
            write_playbook=PgWritePlaybook(conn),
        )
        orchestrator = build_orchestrator(tools, llm=make_llm("judgment"))
        target = CycleTarget(
            channel_id=channel.id,
            platform=channel.platform,
            content_format=args.format,
            media_kind="image" if args.format == "feed_image" else "video",
            mode=channel.mode,
        )
        result = asyncio.run(
            run_slot(
                conn=conn,
                orchestrator=orchestrator,
                goal_ref=args.goal,
                target=target,
                batch_publish=adapters,
            )
        )
        print(f"cycle={result.cycle_id} published={result.published}")


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
