"""실 LLM 스모크 — 스크립트 없는 진짜 CodeAct 1회 (TopicAgent + 결정론 페이크 툴).

발행·DB 없이 "LLM 연결 + CodeAct 생성 메서드 관통 + 근거 접지"를 검증한다.
비용: LLM 수 회 호출(iteration 상한 내). 툴은 페이크라 외부 부작용 0.

판정 2단:
  PIPE OK   — 생성 메서드가 스키마에 맞는 결과를 냈다(연결·CodeAct 관통).
  GROUNDED  — 선택 title이 툴이 실제 반환한 트렌드 항목에 실재(할루시네이션 없음).

실행(컨테이너 — 샌드박스 게이트 통과 필요, FR-S1):
    cp .env.example .env  # OPENAI_API_KEY 채우기
    docker compose run --rm --no-deps app uv run python -m sns.smoke
모델 교체: docker compose run -e SNS_LLM_JUDGMENT=gpt-5.4-nano --rm --no-deps app ...
"""

import asyncio

from sns.agents.core import make_llm
from sns.agents.topic import TopicAgent
from sns.sandbox import assert_sandboxed
from sns.tools.fakes import FakeReadStats, FakeResearchTrends


class RecordingTrends(FakeResearchTrends):
    """툴 실호출 관측 — 에이전트가 근거를 진짜로 조회했는지 확인."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.served: set[str] = set()

    def __call__(self, sources=None, limit=10):  # type: ignore[no-untyped-def]
        self.calls += 1
        digest = super().__call__(sources, limit)
        self.served |= {item for r in digest.source_results for item in r.items}
        return digest


async def main() -> None:
    assert_sandboxed()  # 실 LLM CodeAct = 생성 코드 실행 — 샌드박스 밖 금지
    llm = make_llm("judgment")
    trends = RecordingTrends()
    agent = TopicAgent(research_trends=trends, read_stats=FakeReadStats(), llm=llm)
    result = await agent.pick_topic("호기심 훅 우선. 트렌드 결과에 실재하는 소재만 골라라.")

    grounded = result.get("title") in trends.served
    print(f"PIPE OK — model={llm.model!r} 선택: {result}")
    print(f"툴 호출 {trends.calls}회 · 제공된 트렌드 {len(trends.served)}개")
    if grounded:
        print("GROUNDED — 선택 title이 툴 반환 항목에 실재")
    else:
        print("NOT GROUNDED — title이 툴 반환에 없음(할루시네이션 또는 툴 미탐색)")
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
