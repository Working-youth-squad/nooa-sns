"""실 LLM 스모크 — 스크립트 없는 진짜 CodeAct 1회 (TopicAgent + 결정론 페이크 툴).

발행·DB 없이 "LLM 연결 + CodeAct 생성 메서드 관통"만 검증한다.
비용: LLM 수 회 호출(iteration 상한 내). 툴은 페이크라 외부 부작용 0.

실행(컨테이너 — 샌드박스 게이트 통과 필요, FR-S1):
    cp .env.example .env  # OPENAI_API_KEY 채우기
    docker compose run --rm app uv run python -m sns.smoke
"""

import asyncio

from sns.agents.core import make_llm
from sns.agents.topic import TopicAgent
from sns.sandbox import assert_sandboxed
from sns.tools.fakes import FakeReadStats, FakeResearchTrends


async def main() -> None:
    assert_sandboxed()  # 실 LLM CodeAct = 생성 코드 실행 — 샌드박스 밖 금지
    llm = make_llm("judgment")
    agent = TopicAgent(research_trends=FakeResearchTrends(), read_stats=FakeReadStats(), llm=llm)
    result = await agent.pick_topic("호기심 훅 우선. 트렌드 결과에 실재하는 소재만 골라라.")
    print(f"SMOKE OK — model={llm.model!r} 선택 주제: {result}")


if __name__ == "__main__":
    asyncio.run(main())
