"""사이클 러너 — 코드 소유 진입점 (FR-C5·FR-O1·FR-S1).

역할 분담: Orchestrator(CodeAct)는 계획·위임의 재량을 갖고, 이 러너는
그 전후의 불변식을 소유한다 — 샌드박스 게이트, cycle 원장, run_event 브리지
착지, 사이클 산출물의 DB 영속화. LLM 서술은 착지점(content_item.body·
analysis_note.body)으로만 저장된다.

Orchestrator run_cycle 반환 계약(dict[str, str], 빈 문자열=없음):
  status("completed"|"partial"|"failed"), topic_title, topic_rationale,
  hook_pattern, body, media_spec_json, storage_url, checksum,
  post_id, analysis_note, insufficient_evidence, next_variant
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sns.agents.orchestrator import OrchestratorAgent
from sns.observe import RunEventRecorder, store_sink
from sns.sandbox import assert_sandboxed
from sns.store import CycleStore
from sns.tools.contracts import ContentFormat, MediaKind, Platform

HOOK_PATTERNS = frozenset({"bold_claim", "curiosity", "story", "shock", "question"})


@dataclass(frozen=True)
class CycleTarget:
    channel_id: str
    platform: Platform
    content_format: ContentFormat
    media_kind: MediaKind
    mode: str  # "auto" | "hybrid" — 발행 차단 자체는 ApprovalGate(툴)가 소유


@dataclass(frozen=True)
class RunnerResult:
    cycle_id: str
    content_item_id: str | None
    publication_id: str | None
    published: bool
    result: dict[str, str]


async def run_cycle(
    *,
    store: CycleStore,
    orchestrator: OrchestratorAgent,
    goal_ref: str,
    target: CycleTarget,
    sandbox_check: Callable[[], None] = assert_sandboxed,
) -> RunnerResult:
    """한 사이클: 게이트 → 원장 개시 → 자율 실행(관측) → 영속화 → 원장 마감."""
    sandbox_check()  # FR-S1 fail-closed — 어떤 원장 기록보다 먼저

    cycle_id = store.create_cycle(goal_ref)
    store.log_event(
        cycle_id=cycle_id,
        kind="cycle_started",
        payload={"goal_ref": goal_ref, "platform": target.platform, "mode": target.mode},
    )

    recorder = RunEventRecorder(sink=store_sink(store, cycle_id))
    subagents = (
        orchestrator.topic,
        orchestrator.content,
        orchestrator.media,
        orchestrator.publisher,
        orchestrator.analyst,
        orchestrator.growth,
    )
    unsubscribe = recorder.attach_all(orchestrator, *subagents)

    try:
        result: dict[str, str] = await orchestrator.run_cycle(
            goal_ref, target.platform, target.content_format
        )
    except Exception as exc:
        store.log_event(
            cycle_id=cycle_id,
            kind="error",
            payload={"stage": "orchestrator", "error": str(exc)[:500]},
        )
        store.complete_cycle(cycle_id, status="failed")
        raise
    finally:
        unsubscribe()

    content_item_id, publication_id, published = _persist(store, cycle_id, target, result)

    cycle_status: Any = (
        "completed" if result.get("status") in ("completed", "partial") else "failed"
    )
    store.complete_cycle(cycle_id, status=cycle_status)
    store.log_event(
        cycle_id=cycle_id,
        kind="cycle_completed",
        payload={"status": result.get("status", ""), "published": str(published)},
    )
    return RunnerResult(
        cycle_id=cycle_id,
        content_item_id=content_item_id,
        publication_id=publication_id,
        published=published,
        result=result,
    )


def _persist(
    store: CycleStore, cycle_id: str, target: CycleTarget, result: dict[str, str]
) -> tuple[str | None, str | None, bool]:
    """사이클 산출물 영속화 — 값이 있는 것만, 스키마 불변식은 DB CHECK가 최종 방어."""
    title = result.get("topic_title", "")
    if not title:
        return None, None, False

    topic_id = store.save_topic(
        title=title, summary=result.get("topic_rationale", ""), source="agent"
    )

    body = result.get("body", "")
    if not body:
        return None, None, False

    post_id = result.get("post_id", "")
    published = bool(post_id)
    # 미발행 + hybrid = 승인 대기 산출물 (FR-O2)
    content_status = "needs_review" if (target.mode == "hybrid" and not published) else "approved"
    hook_pattern = result.get("hook_pattern", "")
    content_item_id = store.save_content_item(
        cycle_id=cycle_id,
        topic_id=topic_id,
        content_format=target.content_format,
        body=body,
        media_spec=_parse_spec(result.get("media_spec_json", "")),
        hook_pattern=hook_pattern if hook_pattern in HOOK_PATTERNS else "curiosity",
        status=content_status,
    )

    publication_id: str | None = None
    storage_url = result.get("storage_url", "")
    if storage_url:
        store.save_media_asset(
            content_item_id=content_item_id,
            kind=target.media_kind,
            storage_url=storage_url,
            checksum=result.get("checksum", ""),
            quality_status="needs_review",  # 품질 게이트(FR-Q)는 후속 증분
            quality_report=None,
        )
        publication_id = store.create_publication(
            content_item_id=content_item_id, channel_id=target.channel_id
        )
        if published:
            store.mark_published(publication_id, external_post_id=post_id)

    note = result.get("analysis_note", "")
    if note:
        store.save_analysis_note(
            cycle_id=cycle_id,
            body=note,
            insufficient_evidence=result.get("insufficient_evidence", "") == "true",
        )
    return content_item_id, publication_id, published


def _parse_spec(media_spec_json: str) -> dict[str, object]:
    if not media_spec_json:
        return {}
    try:
        parsed = json.loads(media_spec_json)
    except json.JSONDecodeError:
        return {"raw": media_spec_json[:500]}
    return parsed if isinstance(parsed, dict) else {"raw": media_spec_json[:500]}
