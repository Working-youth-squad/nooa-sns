"""Growth 에이전트 (FR-C1) — 다음 사이클 변형 선택.

선택 근거는 self.read_stats()가 주는 집계뿐이다(자기 베이스라인만, 타 계정 비교 금지).
"""

from sns.agents.core import Agent, UnifiedLLM, codeact, strategy
from sns.tools.contracts import ReadStats


class GrowthAgent(Agent):
    """너는 성장 전략가다.

    self.read_stats()의 주제×포맷×플랫폼 집계를 보고 다음 사이클 변형
    (주제 카테고리·훅 패턴·포맷)을 고른다. 표본이 부족한 조합은 탐색을 우선한다.
    """

    def __init__(self, *, read_stats: ReadStats, llm: UnifiedLLM | None = None) -> None:
        if llm is None:
            super().__init__()
        else:
            super().__init__(llm=llm)
        self.read_stats = read_stats

    @strategy(codeact())
    async def choose_variant(self, goal_ref: str) -> dict[str, str]:
        """목표 {goal_ref} 기준 다음 사이클 변형을 고른다.

        반환: {"variant": 변형 요약(예: hook=curiosity/format=reels), "rationale": 근거 한 줄}
        """
        ...
