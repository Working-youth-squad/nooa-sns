"""실패 원인 1줄 분석 (C6, FR-W4) — LLM은 서술만, 장애는 삼켜 None 반환.

FR-W4: "LLM 호출 실패 시 분류명만이라도 발송". 이 함수가 None을 돌려주면 상위
(dispatch)는 `error_class`만으로 알림을 보낸다 — 알림 경로는 LLM 장애에 막히지 않는다.
클라이언트는 주입받는다(NooaAdapter의 UnifiedLLM — 원본의 LangChain BaseChatModel
시임을 교체). 테스트는 FakeLLMClient.
"""

from sns.agents.core import UnifiedLLM
from sns.notify.alerts import Alert

_SYSTEM = (
    "당신은 SNS 발행 파이프라인의 운영 보조다. 오류 분류와 원문을 보고 가장 그럴듯한 "
    "원인을 한국어 한 문장으로만 말한다. 근거가 약하면 단정하지 말고 '~로 보인다'로 쓴다. "
    "한 문장만 출력한다."
)


def _first_line(text: str, *, limit: int = 200) -> str:
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


def analyze_cause(llm: UnifiedLLM, alert: Alert) -> str | None:
    """실패 알림의 원인 1줄. 분석거리(원문·분류)가 없거나 LLM 장애면 None."""
    if not alert.error_raw and not alert.error_class:
        return None
    prompt = f"분류: {alert.error_class}\n원문: {alert.error_raw}\n한 문장 원인:"
    try:
        response = llm.call(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ]
        )
        content = response.content
        line = _first_line(content if isinstance(content, str) else str(content or ""))
    except Exception:  # noqa: BLE001 — LLM 장애는 삼키고 분류명 폴백 (FR-W4)
        return None
    return line or None
