"""원인 1줄 분석 — UnifiedLLM 시임 재작성판 (FR-W4)."""

from typing import Any

from sns.agents.core import FakeLLMClient
from sns.notify.alerts import publish_failure
from sns.notify.cause import analyze_cause
from sns.tools.contracts import ToolError

_ALERT = publish_failure("instagram", ToolError("auth", "OAuth 190"), publication_id="pub-1")


def test_returns_first_line_trimmed() -> None:
    llm = FakeLLMClient.simple_message("  토큰 만료로 보인다.  \n둘째 줄은 버린다")
    assert analyze_cause(llm, _ALERT) == "토큰 만료로 보인다."


def test_no_evidence_returns_none_without_llm_call() -> None:
    from dataclasses import replace

    llm = FakeLLMClient()
    alert = replace(_ALERT, error_class=None, error_raw=None)
    assert analyze_cause(llm, alert) is None
    assert llm.call_count == 0


def test_llm_failure_swallowed() -> None:
    class Raising(FakeLLMClient):
        def call(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("down")

    assert analyze_cause(Raising(), _ALERT) is None


def test_empty_response_is_none() -> None:
    llm = FakeLLMClient.simple_message("")
    assert analyze_cause(llm, _ALERT) is None
