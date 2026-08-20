"""Topic 에이전트 (FR-C1) — 개발자 주제 발굴.

능력 표면 = 부착된 툴 계약 2종(research_trends·read_stats)뿐이다 (FR-C2).
시크릿·DB 커넥션은 어떤 속성에도 없다 (FR-S3).
"""

from sns.agents.core import Agent, UnifiedLLM, codeact, strategy
from sns.tools.contracts import ReadStats, ResearchTrends


class TopicAgent(Agent):
    """너는 개발자 채널의 주제 발굴 에이전트다.

    self.research_trends(sources, limit)로 트렌드 근거를 모으고,
    self.read_stats(platform)으로 과거 주제 성과를 확인한 뒤,
    다음 사이클에 발행할 주제 1개를 고른다. 근거 없는 주제 창작 금지 —
    반드시 트렌드 결과에 있는 소재에서만 고른다(할루시네이션 방지, 원본 04).
    """

    def __init__(
        self,
        *,
        research_trends: ResearchTrends,
        read_stats: ReadStats,
        llm: UnifiedLLM | None = None,
    ) -> None:
        if llm is None:
            super().__init__()
        else:
            super().__init__(llm=llm)
        self.research_trends = research_trends
        self.read_stats = read_stats

    @strategy(codeact())
    async def pick_topic(self, playbook_guidance: str) -> dict[str, str]:
        """플레이북 지침({playbook_guidance})을 반영해 주제 1개를 고른다.

        반환: {"title": 주제 제목, "rationale": 선택 근거 한 줄}
        title은 self.research_trends 결과에 실재하는 제목이어야 한다.
        """
        ...
