"""Orchestrator 에이전트 (FR-C6) — 완전 자율 사이클 계획.

슬롯 트리거만 받는다. 단계 순서·병렬화(asyncio.gather)·스킵·재시도를
CodeAct가 스스로 계획한다. 서브에이전트 6개가 속성으로 부착되어 있고,
REPL에서 `await self.topic.pick_topic(...)`처럼 위임한다.
불변식(멱등 발행·결정론 렌더)은 서브에이전트 너머 툴 계약이 강제하므로
계획이 틀려도 이중 발행·시크릿 유출은 구조적으로 불가능하다.
"""

from sns.agents.analyst import AnalystAgent
from sns.agents.content import ContentAgent
from sns.agents.core import Agent, UnifiedLLM, codeact, strategy
from sns.agents.growth import GrowthAgent
from sns.agents.media import MediaAgent
from sns.agents.publisher import PublisherAgent
from sns.agents.topic import TopicAgent

ORCHESTRATOR_MAX_ITERATIONS = 16  # 사이클 위임 예산 (FR-O3, 수치는 미결정 #3 — 임시)


class OrchestratorAgent(Agent):
    """너는 발행 사이클의 오케스트레이터다.

    한 사이클 = 주제 선정 → 콘텐츠 작성 → 미디어 렌더 → 발행 → 분석 → 다음 변형.
    순서·병렬화·실패 대응은 네가 계획한다. 서브에이전트:
    self.topic / self.content / self.media / self.publisher / self.analyst / self.growth.
    서브에이전트 하나가 실패해도 사이클 전체를 죽이지 말고 격리·기록 후 진행을 판단한다.
    """

    def __init__(
        self,
        *,
        topic: TopicAgent,
        content: ContentAgent,
        media: MediaAgent,
        publisher: PublisherAgent,
        analyst: AnalystAgent,
        growth: GrowthAgent,
        llm: UnifiedLLM | None = None,
    ) -> None:
        if llm is None:
            super().__init__()
        else:
            super().__init__(llm=llm)
        self.topic = topic
        self.content = content
        self.media = media
        self.publisher = publisher
        self.analyst = analyst
        self.growth = growth

    @strategy(codeact(max_iterations=ORCHESTRATOR_MAX_ITERATIONS))
    async def run_cycle(self, goal_ref: str, platform: str, content_format: str) -> dict[str, str]:
        """목표 {goal_ref}, 플랫폼 {platform}, 포맷 {content_format}로 한 사이클을 완주한다.

        반환: {"status": "completed"|"partial"|"failed",
               "topic_title": 선정 주제, "post_id": 발행 ID(미발행 시 빈 문자열),
               "next_variant": 다음 사이클 변형}
        """
        ...
