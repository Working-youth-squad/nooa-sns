# 실 LLM 스모크 실행 기록

> 실행: `docker compose run --rm --no-deps app uv run python -m sns.smoke`(단일 에이전트)
> / `python -m sns.smoke_cycle`(풀사이클). 툴은 전부 결정론 페이크 — 실발행·외부 부작용 0.

## 2026-08-20 — 단일 에이전트(TopicAgent) 모델 비교

| 모델 | 가격(입/출 per M) | 판정 | 관찰 |
|---|---|---|---|
| gpt-5-nano | $0.05/$0.40 | **NOT GROUNDED** | 툴 1회 호출, 트렌드 12개 받고도 "데이터 없음"이라며 `Untitled Topic` 날조 |
| gpt-5.4-nano | $0.20/$1.25 | **GROUNDED** | 툴 5회 탐색, 실재 항목 선택 + 한국어 근거 |

→ **CodeAct 최저 가용선 = gpt-5.4-nano** (.env 기본값 채택).

## 2026-08-20 — 풀사이클 드라이런(smoke_cycle, gpt-5.4-nano)

7 에이전트 전부 스크립트 없는 진짜 CodeAct. `sns.runner.run_cycle` 경로(샌드박스
게이트→원장→자율 계획→위임→영속화) 그대로, InMemory 원장으로 착지 검증.

**run 1 — FAIL (교정 반영)**: Orchestrator가 `self.topic.select_topic` 등 존재하지
않는 메서드명을 추측 → 서브에이전트 위임 API(메서드명·시그니처·반환 키)를
Orchestrator 클래스 docstring(=시스템 프롬프트)에 명시해 교정. 실패 격리 자체는
설계대로 작동(오류를 정직 보고, 사이클 failed 원장 기록).

**run 2 — 판정 기준 교정**: 사이클 완주·접지·착지 전부 성공했으나, 에이전트가 같은
idempotency_key로 publish를 2회 호출(멱등 계층이 실발행 1회로 흡수 — NFR-2 설계
의도) → 판정을 "호출 1회"에서 "실발행 1회"로 정정. 또 Analyst가 write_playbook을
실행별로 건너뛰는 편차 관찰 → 프롬프트를 "필수 1회 호출"로 강화.

**run 3 — PASS**:

```
CYCLE     : status=completed / 원장=completed
GROUNDED  : True (topic_title='github-topic-1', 트렌드 18개 제공·툴 5회 호출)
LANDED    : content=True media=1 publication=True(published=True)
            publish호출=2회/실발행=1회 playbook=[('global', None)]
run_event : 86건 — kinds=[agent_called, cost, cycle_completed, cycle_started, tool_called]
결과 요약  : hook_pattern='story' next_variant='topic=explainer / hook=contrarian question / format=shorts'
VERDICT   : PASS
```

질적 관찰:
- 분석글이 페이크 지표 수치(reach 667, views 712, likes 926…)를 그대로 인용 —
  **정직 귀인**(수치는 툴, LLM은 서술) 원칙이 실 LLM에서도 유지됨.
- publish 중복 호출은 멱등 상태머신이 흡수 — 프롬프트가 아니라 코드가 불변식 소유.
- 페이크 트렌드 툴은 요청된 소스명을 그대로 에코하므로(예: `instagram-topic-1`)
  접지 판정은 "툴이 실제 반환한 항목" 기준 — 실소스 연결 시 재검증 필요.

한계: nano급은 실행별 편차 존재(툴 호출 횟수·플레이북 준수). 판단 품질이 중요한
운영 단계에서는 상위 모델(FR-C3 기본값) 재평가.
