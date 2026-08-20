"""Publisher 에이전트 (FR-C1) — 멱등 발행 위임.

멱등·이중발행 0은 툴(Publish 구현의 상태머신, NFR-2)이 보장한다.
시크릿 복호화·실 API 호출은 툴 내부에만 있다(FR-S3) — 이 클래스엔 토큰이 없다.
"""

from sns.agents.core import Agent, UnifiedLLM, codeact, strategy
from sns.tools.contracts import MediaAsset, MediaKind, Publish


class PublisherAgent(Agent):
    """너는 발행 담당자다.

    self.publish(platform, media, caption, idempotency_key)로 발행한다.
    media는 self.media_asset(storage_url, checksum, kind)로 만든다.
    같은 발행 건은 반드시 같은 idempotency_key를 재사용한다.
    """

    def __init__(self, *, publish: Publish, llm: UnifiedLLM | None = None) -> None:
        if llm is None:
            super().__init__()
        else:
            super().__init__(llm=llm)
        self.publish = publish

    def media_asset(self, storage_url: str, checksum: str, kind: MediaKind) -> MediaAsset:
        """REPL용 헬퍼 — MediaAsset 생성 (import 없이 사용 가능)."""
        return MediaAsset(kind=kind, storage_url=storage_url, checksum=checksum)

    @strategy(codeact())
    async def publish_item(
        self,
        platform: str,
        caption: str,
        idempotency_key: str,
        storage_url: str,
        checksum: str,
        kind: str,
    ) -> dict[str, str]:
        """{platform}에 idempotency_key={idempotency_key}로 발행한다.

        반환: {"post_id": 발행 ID(실패 시 빈 문자열), "error": 오류 분류(성공 시 빈 문자열)}
        """
        ...
