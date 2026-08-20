"""Content 에이전트 (FR-C1) — 포맷별 대본/카피 + 훅 분리 생성 (FR-G5).

부착 툴 없음 — 순수 생성. 산출은 착지점 content_item.body로만 저장된다(코드가 수행).
"""

from sns.agents.core import Agent, UnifiedLLM, codeact, strategy


class ContentAgent(Agent):
    """너는 개발자 채널의 콘텐츠 작가다.

    주어진 주제·포맷·플레이북 지침으로 훅(첫 문장)과 본문을 분리 생성한다.
    근거 없는 수치·인과 주장 금지. 금지 소재(원본 05 FR-Q7)는 다루지 않는다.
    """

    def __init__(self, *, llm: UnifiedLLM | None = None) -> None:
        if llm is None:
            super().__init__()
        else:
            super().__init__(llm=llm)

    @strategy(codeact())
    async def write_content(
        self, topic_title: str, content_format: str, playbook_guidance: str
    ) -> dict[str, str]:
        """주제 {topic_title}, 포맷 {content_format}, 지침 {playbook_guidance}로 작성한다.

        반환: {"hook": 훅 한 문장, "body": 본문,
               "hook_pattern": bold_claim|curiosity|story|shock|question 중 하나,
               "media_spec_json": 렌더 스펙 JSON 문자열}
        """
        ...
