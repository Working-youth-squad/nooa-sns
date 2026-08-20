# nooa-sns — 러프 기획 (NOOA/CodeAct 전면 적용)

> 작성 2026-08-20 · 상태: 러프(기획 하네스 입력용)
> 원본 기획서: [Working-youth-squad/multiagent-sns](https://github.com/Working-youth-squad/multiagent-sns) `docs/PLAN.md` + `docs/plan/01~14`
> 에이전트 프레임워크: [NVIDIA-NeMo/labs-OO-Agents](https://github.com/NVIDIA-NeMo/labs-OO-Agents) (패키지 `nooa`, Apache-2.0, Alpha ~v0.0.7)

## 1. 한 줄 정의

multiagent-sns 기획(개발자 주제 콘텐츠를 IG 피드·릴스·YouTube 쇼츠에 자동 기획·제작·발행하고 지표를 학습해 채널을 키우는 자율 성장 엔진)을 **그대로 계승**하되, 에이전트 코어를 **deepagents(LangGraph) → NOOA + CodeAct 전면 채택**으로 교체한 신규 구현.

## 2. 계승하는 것 (원본 기획서에서 변경 없음)

- **제품 정의·실험설계**: 계정 4개 auto vs hybrid 비교, 자기 베이스라인 성장만, 통제 변수 (원본 01)
- **성공 기준·kill criteria**: DoD 실환경 관통, S1~S5, K1~K4 (원본 PLAN §4)
- **데이터 모델**: PostgreSQL 단일 DB, 테이블 15, CHECK, missing=NULL (원본 11)
- **발행**: 공식 API만(IG Graph·YouTube Data v3), 멱등 상태머신, 비용 상한 (원본 07)
- **미디어 렌더**: Pillow 결정론 카드, ffmpeg/Remotion 스파이크, TTS (원본 06)
- **트렌드·품질게이트·지표학습·알고리즘 신호**: 원본 04·05·08·09
- **개발 원칙 8종** 중 1(공식 API)·3(멱등)·4(결측 NULL)·5(정직 귀인)·6(자기 베이스라인)·7(시크릿 암호화)·8(thin spec)은 그대로. **2(결정론 재현)와 "제어 채널 분리"는 §4에서 재정의.**

## 3. 바꾸는 것 — 에이전트 코어 (FR-C 전면 재작성 대상)

| 항목 | 원본 (deepagents) | 신규 (NOOA) |
|---|---|---|
| 프레임워크 | deepagents 0.7.5 (LangGraph/LangChain) | `nooa` (LiteLLM 기반, OO 에이전트) |
| 에이전트 정의 | `create_deep_agent(model, tools, system_prompt)` | `class XxxAgent(Agent, llm=...)` — docstring=시스템 프롬프트, 타입 시그니처=계약 |
| 행동 방식 | 툴 콜 루프 (LangGraph) | **CodeAct 전면**: LLM이 지속 REPL에서 Python을 작성·실행, `self`의 툴/서브에이전트에 직접 접근 |
| 툴 | LangChain tool 바인딩 | 툴 계약 6종(research_trends·render_media·publish·poll_metrics·read_stats·write_playbook)을 **클래스 속성으로 부착** — 기존 Protocol 계약 재사용 |
| LLM | `make_model()` → LangChain `BaseChatModel` (Gemini) | `get_llm_client()` (LiteLLM) — 판단=`claude-sonnet-5`, 대량=`gemini/gemini-2.5-flash`, `.nooa/llm_config.yaml` 별칭·5단계 캐스케이딩 주입 |
| 오케스트레이션 | 순수 Python `run_cycle` | **Orchestrator도 NOOA 에이전트**: 서브에이전트(Topic/Content/Media/Publisher/Analyst/Growth)를 속성으로 부착, CodeAct가 위임·병렬 fan-out(`asyncio.gather`)·실패 격리를 코드로 수행 |
| 구조화 출력 | 수동 검증 + Rejected 예외 | 반환 타입(Pydantic) 자동 검증 + 검증 실패 시 오류를 LLM에 보여주고 자동 재시도 |
| 관측 | `run_event` 수동 기록 | NOOA 이벤트 소싱(`agent.events.query()`) + OpenTelemetry/OpenInference 트레이싱 → `run_event` 브리지 |
| 비동기 | sync invoke | async-first (`asyncio.run`) |

## 4. 철학 전환 — "착지점 통제"에서 "샌드박스 통제"로

원본의 제어 채널 분리(LLM은 DB 착지점 3곳에만 기록)는 CodeAct의 개방형 코드 실행과 정면 충돌한다. 전면 CodeAct 채택에 따라 통제 모델을 재정의한다:

1. **실행 격리 = OS 수준 샌드박스**(필수): CodeAct REPL은 Docker 컨테이너(비루트, 네트워크 이그레스 화이트리스트) 안에서만 실행. NOOA 자체 AST 체크는 봉쇄 경계가 아님(업스트림 문서 명시).
2. **DB 쓰기는 여전히 툴 계약 경유만**: REPL 네임스페이스에 raw DB 커넥션·시크릿을 노출하지 않는다. LLM 서술 착지점 3곳(`content_item.body`·`playbook.guidance`·`analysis_note.body`) 원칙은 툴 계약 서명으로 유지.
3. **시크릿 비노출**: OAuth 토큰은 발행 툴 내부에서만 복호화, `self`에 평문 부착 금지.
4. **결정론 재현 재정의**: LangChain 가짜 모델 → NOOA `UnifiedLLM` 주입 시임으로 교체. 스크립트된 가짜 LLM 클라이언트로 사이클 재현 테스트. CodeAct 생성 코드의 재현성은 이벤트 소싱 리플레이로 보강.

## 5. 반증선 (Phase 0 게이트, 원본 03 §1 계승·개정)

NOOA가 다음을 지원하지 못하면 → 원본 계획(deepagents) 또는 자작 thin loop로 폴백:
- (a) LLM 주입(가짜 클라이언트로 결정론 테스트 green)
- (b) 샌드박스 격리 하에서 CodeAct 사이클 관통(기획→제작→발행 dry-run)
- (c) DB 쓰기 경로가 툴 계약 밖으로 새지 않음(착지점 외 기록 경로 부재 테스트)
- (d) Alpha API 변동 흡수: `nooa` 버전 고정 + 어댑터 계층 1곳으로 격리

## 6. 기술 스택 델타

| 층 | 원본 | 신규 |
|---|---|---|
| 에이전트 | deepagents 0.7.5 | `nooa`(버전 고정) + `nooa[tracing]`, 샌드박스 extra 검토 |
| LLM 클라이언트 | langchain-google-genai | LiteLLM (`litellm>=1.84.0`) — ANTHROPIC_API_KEY + GEMINI_API_KEY |
| Python | 3.12 | 3.12 유지 (nooa는 3.12~3.13) |
| 실행 격리 | 없음(불필요했음) | **Docker 샌드박스 필수** — compose에 REPL 실행 컨테이너 추가 |
| 나머지 | PostgreSQL·psycopg·Pillow·ffmpeg·FastAPI·GitHub Actions | 동일 |

## 7. 쟁점·미결정 (기획 하네스에서 상세화 필요)

1. **CodeAct 적용 범위**: 7개 에이전트 전부 CodeAct인가, Media/Publisher/Growth처럼 결정론이 요구되는 역할은 PredictStrategy 또는 순수 코드로 두는가? (원본은 이 3개를 에이전트가 아닌 코드로 구현했음)
2. **샌드박스 구현**: nooa `sandbox` extra(openshell) vs 자체 Docker 실행기 — 발행 툴(실 API 호출)과 REPL 격리의 경계 설계.
3. **Orchestrator의 재량 범위**: 사이클 계획을 CodeAct 재량에 맡기는 정도 vs 슬롯 스케줄러가 고정 시퀀스를 강제하는 정도.
4. **결정론 테스트 전략**: CodeAct는 생성 코드가 매번 달라질 수 있음 — 리플레이 기반 테스트로 충분한가, 골든 이벤트 로그 비교인가.
5. **hybrid 승인 관문**: CodeAct 흐름 중간에 사람 승인(needs_review)을 어디서 끼워 넣는가 — NOOA Channel/JobHandle 활용 여부.
6. **비용 관측**: CodeAct 반복(max_iterations)이 LLM 호출량을 늘림 — S5 cost cap과 iteration 상한 설계.
7. **원본 미결정 승계**: 스케줄 방식(상주 러너 vs GHA cron), 영상 렌더러(ffmpeg vs Remotion), TTS 엔진.
