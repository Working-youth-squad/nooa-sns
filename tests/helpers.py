"""테스트 헬퍼 — CodeAct용 스크립트 응답 빌더.

nooa 타입은 어댑터(sns.agents.core) 재수출만 사용한다 (FR-C8).
"""

import json

from sns.agents.core import FakeLLMClient, LLMResponse, ToolCall


def exec_call(code: str, call_id: str = "call_exec") -> ToolCall:
    return ToolCall(id=call_id, name="execute_python", arguments=json.dumps({"code": code}))


def ret_call(result: object, call_id: str = "call_ret") -> ToolCall:
    return ToolCall(id=call_id, name="return_result", arguments=json.dumps({"result": result}))


def resp(content: str = "", tool_calls: list[ToolCall] | None = None) -> LLMResponse:
    return LLMResponse(
        raw_response=None,
        content=content,
        tool_calls=tool_calls or [],
        finish_reason="tool_calls" if tool_calls else "stop",
        assistant_message={"role": "assistant", "content": content},
        usage={"prompt_tokens": 50, "completion_tokens": 10},
    )


def scripted(*responses: LLMResponse) -> FakeLLMClient:
    return FakeLLMClient(scripted_responses=list(responses))
