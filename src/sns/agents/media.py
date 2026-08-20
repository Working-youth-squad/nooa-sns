"""Media 에이전트 (FR-C1) — 결정론 렌더 위임.

렌더 자체는 툴(RenderMedia)이 결정론으로 수행한다 — 같은 spec → 같은 checksum(FR-M1).
에이전트 재량은 spec 해석·렌더 시도 순서까지만이다.
"""

from collections.abc import Mapping
from typing import Any

from sns.agents.core import Agent, UnifiedLLM, codeact, strategy
from sns.tools.contracts import RenderMedia


class MediaAgent(Agent):
    """너는 미디어 프로듀서다.

    media_spec을 해석해 self.render_media(spec, kind)로 자산을 렌더한다.
    스펙 임의 창작 금지 — 주어진 spec 범위 안에서만 렌더한다.
    """

    def __init__(self, *, render_media: RenderMedia, llm: UnifiedLLM | None = None) -> None:
        if llm is None:
            super().__init__()
        else:
            super().__init__(llm=llm)
        self.render_media = render_media

    def parse_spec(self, media_spec_json: str) -> Mapping[str, Any]:
        """REPL용 헬퍼 — JSON 문자열 spec을 매핑으로 (import 없이 사용 가능)."""
        import json

        parsed = json.loads(media_spec_json)
        if not isinstance(parsed, dict):
            raise TypeError(f"media_spec은 객체여야 함: {media_spec_json[:100]}")
        return parsed

    @strategy(codeact())
    async def produce(self, media_spec_json: str, kind: str) -> dict[str, str]:
        """spec({media_spec_json})을 {kind} 자산으로 렌더한다.

        반환: {"storage_url": 저장 URL, "checksum": 렌더 체크섬}
        """
        ...
