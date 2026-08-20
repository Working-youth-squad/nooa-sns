"""NooaAdapter (FR-C8) — `nooa` import가 허용되는 유일한 모듈.

Alpha(0.0.9) API 변동을 이 파일 한 곳으로 흡수한다. 에이전트·테스트는
전부 여기서 재수출된 이름만 쓴다 (tests/test_adapter_isolation.py가 grep 게이트).

LLM 캐스케이딩(NFR-1): 프로덕션은 make_llm(), 테스트는 FakeLLMClient를
인스턴스 생성자 llm= 로 주입한다 — 에이전트 코드는 어느 쪽인지 모른다.
"""

import os
from typing import Literal

from nooa.agent import Agent
from nooa.config import CodeActConfig
from nooa.decorators import strategy
from nooa.strategies import CodeActStrategy
from nooa.unifiedllm import (
    FakeLLMClient,
    LLMResponse,
    ToolCall,
    UnifiedLLM,
    get_llm_client,
)

__all__ = [
    "Agent",
    "CodeActConfig",
    "CodeActStrategy",
    "FakeLLMClient",
    "LLMResponse",
    "ToolCall",
    "UnifiedLLM",
    "codeact",
    "make_llm",
    "strategy",
]

# FR-O3: 상한 수치는 미결정(spec §7-3) — M1 실측 후 사전등록. 임시 기본값.
DEFAULT_MAX_ITERATIONS = 8

# FR-C3: 역할별 모델 별칭 — 판단=Claude, 대량=Gemini Flash. 장애 시 교차 대체 금지.
_ROLE_MODELS: dict[str, str] = {
    "judgment": "claude-sonnet-5",
    "bulk": "gemini/gemini-2.5-flash",
}

# env 오버라이드(LiteLLM 모델 ID) — 저비용 테스트용 모델 교체(예: gpt-5-nano).
_ROLE_ENV: dict[str, str] = {
    "judgment": "SNS_LLM_JUDGMENT",
    "bulk": "SNS_LLM_BULK",
}

LlmRole = Literal["judgment", "bulk"]


def codeact(max_iterations: int = DEFAULT_MAX_ITERATIONS) -> CodeActStrategy:
    """프로젝트 표준 CodeAct 전략 (iteration 상한 강제, FR-O3)."""
    return CodeActStrategy(config=CodeActConfig(max_iterations=max_iterations))


def make_llm(role: LlmRole) -> UnifiedLLM:
    """역할별 LLM 클라이언트 — env(SNS_LLM_JUDGMENT/BULK)로 모델 오버라이드 가능.

    API 키 부재 시 즉시 실패(fail-fast, FR-C3). 장애 시 역할 간 교차 대체 금지.
    """
    model = os.environ.get(_ROLE_ENV[role]) or _ROLE_MODELS[role]
    return get_llm_client(model)
