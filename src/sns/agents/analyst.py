"""Analyst 에이전트 (FR-C1) — 지표 해석·정직 귀인 (FR-L5).

수치 계산은 코드(툴)만 한다. 이 에이전트의 산출은 서술(분석글·플레이북 지침)뿐이며
착지점은 analysis_note.body·playbook.guidance 2곳이다(FR-C4).
"""

from sns.agents.core import Agent, UnifiedLLM, codeact, strategy
from sns.tools.contracts import PollMetrics, ReadStats, WritePlaybook


class AnalystAgent(Agent):
    """너는 지표 분석가다.

    self.poll_metrics(platform, post_id, window_index)로 지표를 읽고,
    self.read_stats()로 과거 성과를 참조해 분석글을 쓴다.
    근거가 있을 때만 인과를 주장한다 — 결측(missing=True)이 많으면
    insufficient_evidence를 "true"로 정직하게 표기한다. 수치 재계산 금지.

    필수 절차: return_result 전에 **반드시** self.write_playbook("global", 지침 한 줄)을
    정확히 1회 호출해 배운 지침을 남긴다. 이 호출 없이 분석을 끝내면 안 된다.
    """

    def __init__(
        self,
        *,
        poll_metrics: PollMetrics,
        read_stats: ReadStats,
        write_playbook: WritePlaybook,
        llm: UnifiedLLM | None = None,
    ) -> None:
        if llm is None:
            super().__init__()
        else:
            super().__init__(llm=llm)
        self.poll_metrics = poll_metrics
        self.read_stats = read_stats
        self.write_playbook = write_playbook

    @strategy(codeact())
    async def analyze(self, platform: str, post_id: str, window_index: int) -> dict[str, str]:
        """{platform} 게시물 {post_id}의 창 {window_index} 지표를 분석한다.

        반환: {"analysis_note": 분석글, "insufficient_evidence": "true"|"false"}
        """
        ...
