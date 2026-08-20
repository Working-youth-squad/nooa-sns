"""풀사이클 실 LLM 드라이런 — 7 에이전트 전부 진짜 CodeAct (스크립트 응답 없음).

sns.runner.run_cycle 경로 그대로: 샌드박스 게이트 → 원장 → Orchestrator 완전
자율 계획 → 서브에이전트 위임 → 산출물 영속화(InMemory). 툴은 전부 결정론
페이크라 실발행·과금성 부작용 0 (LLM 호출 비용만 발생).

판정:
  CYCLE     — 러너 완주 + cycle 원장 completed
  GROUNDED  — 선택 topic_title이 트렌드 툴 실반환 항목에 실재
  LANDED    — content/media/publication 착지 + 발행 원장 1회 + 플레이북 기록

실행: docker compose run --rm --no-deps app uv run python -m sns.smoke_cycle
"""

import asyncio

from sns.agents.core import make_llm
from sns.bootstrap import ToolSet, build_orchestrator
from sns.runner import CycleTarget, run_cycle
from sns.smoke import RecordingTrends
from sns.store import InMemoryCycleStore
from sns.tools.fakes import (
    FakePollMetrics,
    FakePublish,
    FakeReadStats,
    FakeRenderMedia,
    FakeWritePlaybook,
)

TARGET = CycleTarget(
    channel_id="ch-smoke",
    platform="instagram",
    content_format="feed_image",
    media_kind="image",
    mode="auto",
)


async def main() -> int:
    llm = make_llm("judgment")
    trends = RecordingTrends()
    fake_publish = FakePublish()
    fake_playbook = FakeWritePlaybook()
    tools = ToolSet(
        research_trends=trends,
        read_stats=FakeReadStats(),
        render_media=FakeRenderMedia(),
        publish=fake_publish,
        poll_metrics=FakePollMetrics(),
        write_playbook=fake_playbook,
    )
    orchestrator = build_orchestrator(tools, llm=llm)
    store = InMemoryCycleStore()

    out = await run_cycle(
        store=store,
        orchestrator=orchestrator,
        goal_ref="smoke-full-cycle",
        target=TARGET,
        # 샌드박스 게이트는 runner 기본값(assert_sandboxed) 그대로 — 컨테이너 필수
    )

    result = out.result
    kinds = [str(e["kind"]) for e in store.events]
    grounded = result.get("topic_title", "") in trends.served
    # 발행 판정 = 실발행 1회(멱등 결과 1개). 같은 키 중복 *호출*은 허용 —
    # 멱등 계층이 흡수하는 것이 설계 의도(NFR-2)이며 실측에서도 관찰됨.
    landed = (
        out.content_item_id is not None
        and bool(store.media_assets)
        and out.publication_id is not None
        and len(set(fake_publish.calls)) == 1
        and len(fake_publish.results) == 1
        and bool(fake_playbook.entries)
    )

    print(f"── 풀사이클 실 LLM 드라이런 (model={llm.model!r}) ──")
    print(
        f"CYCLE     : status={result.get('status')} / 원장={store.cycles[out.cycle_id]['status']}"
    )
    print(
        f"GROUNDED  : {grounded} (topic_title={result.get('topic_title')!r}, 트렌드 {len(trends.served)}개 제공·툴 {trends.calls}회 호출)"
    )
    print(
        "LANDED    : "
        f"content={out.content_item_id is not None} media={len(store.media_assets)} "
        f"publication={out.publication_id is not None}(published={out.published}) "
        f"publish호출={len(fake_publish.calls)}회/실발행={len(fake_publish.results)}회 "
        f"playbook={list(fake_playbook.entries)}"
    )
    print(f"run_event : {len(kinds)}건 — kinds={sorted(set(kinds))}")
    print(
        f"결과 요약  : hook_pattern={result.get('hook_pattern')!r} next_variant={result.get('next_variant')!r}"
    )
    body = result.get("body", "")
    print(f"body({len(body)}자): {body[:160]!r}")
    note = result.get("analysis_note", "")
    print(f"analysis_note({len(note)}자): {note[:160]!r}")

    ok = result.get("status") in ("completed", "partial") and grounded and landed
    print("VERDICT   :", "PASS" if ok else "FAIL")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
