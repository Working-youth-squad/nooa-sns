# HARNESS.md — nooa-sns Source of Truth

> 이 폴더에서 기획 하네스가 상시 로드하는 규칙서. 러프 기획을 상세기획으로 확장할 때의 절대 기준.
> 확정 결정(2026-08-20): **NOOA 통째 도입 + 7개 에이전트 전부 CodeAct + Orchestrator 완전 자율 계획 + Docker 샌드박스.**

## 절대 규칙 (도메인 금지/원칙)

NOOA 관례("재량은 에이전트에, 불변식은 에이전트 바깥의 코드·규칙에")를 따른다.

1. **공식 API만** — 비공식 스크래핑/자동화 금지(계정 정지 리스크).
2. **불변식은 툴 계약 내부에서 강제** — 멱등 발행(이중 발행 0, 상태머신), 결정론 렌더(checksum)는 CodeAct 재량과 무관하게 툴 구현이 보장한다. 에이전트 프롬프트에 의존한 안전장치 금지.
3. **missing=NULL** — 지표 결측을 0으로 채우지 않음(DB CHECK 강제).
4. **정직 귀인** — LLM 분석글은 근거 있을 때만 인과 주장. 수치 계산은 코드만.
5. **자기 베이스라인 성장만** — 타 계정 절대 비교 금지.
6. **시크릿 비노출** — OAuth 토큰·raw DB 커넥션을 CodeAct REPL 네임스페이스(`self` 속성 평문 포함)에 노출 금지. 복호화는 툴 내부에서만.
7. **CodeAct는 샌드박스 안에서만** — 에이전트 프로세스는 Docker 컨테이너(비루트, 이그레스 화이트리스트)에서만 실행. NOOA 내장 AST 검사는 봉쇄 경계가 아님(업스트림 README 명시). fail-closed: 격리 불가 시 실행 거부.
8. **thin spec** — 경계·데이터·측정만 고정. 에이전트 내부 행동은 docstring 프롬프트/플레이북에.
9. **사후확신 금지** — 성공지표 목표치는 사전등록 후 고정, 사후에 목표를 맞추지 않는다.

## 재사용 자산 맵 (실재 확인된 경로만)

원본 기획·코드: [Working-youth-squad/multiagent-sns](https://github.com/Working-youth-squad/multiagent-sns) (로컬 체크아웃 `C:\Users\biop9\multiagent-sns`)

- 기획서 원본 — `docs/PLAN.md` + `docs/plan/01~14` — 제품 정의·실험설계·데이터모델·발행·렌더 등 §2(계승 목록) 전부
- 툴 계약 6종 — `sns/tools/contracts.py` — ResearchTrends·RenderMedia·Publish·PollMetrics·ReadStats·WritePlaybook Protocol(프레임워크 무관, NOOA 속성 부착으로 재사용)
- 툴 페이크 — `sns/tools/fakes.py` — 결정론 테스트용
- 발행 상태머신 — `sns/publish/state_machine.py`, `sns/publish/runner.py` — 멱등 발행(툴 내부로 이식)
- DB 스키마 — `sns/db/migrations/001_initial.sql`, `sns/db/migrate.py` — 테이블 15·CHECK
- 스토어 시임 — `sns/runner/store.py` — CycleStore Protocol + InMemory/Pg 구현
- 시크릿 암호화 — `sns/crypto.py`
- 렌더러 — `sns/render/` (Pillow 결정론 카드)
- **재사용 불가(교체 대상)** — `sns/agents/*.py`(deepagents 결합), `sns/agents/models.py`(LangChain 모델 시임), `sns/runner/cycle.py`(고정 시퀀스 오케스트레이터 — 완전 자율 계획으로 대체)

NOOA 프레임워크: [NVIDIA-NeMo/labs-OO-Agents](https://github.com/NVIDIA-NeMo/labs-OO-Agents) (패키지 `nooa`, Apache-2.0, Alpha)

- 에이전트 코어 — `src/nooa/agent.py`, `src/nooa/metaclass.py` — class docstring=프롬프트, `...` 메서드=생성 메서드
- CodeAct — `src/nooa/strategies/codeact.py:287`(CodeActStrategy), `src/nooa/config/strategy_config.py:33`(CodeActConfig, max_iterations)
- LLM 클라이언트 — `src/nooa/unifiedllm/registry.py` `get_llm_client()` — LiteLLM, `.nooa/llm_config.yaml` 별칭, 5단계 캐스케이딩 주입
- 이벤트 소싱 — `src/nooa/events.py`, `runtime/event_manager.py` — run_event 브리지 소스
- 채널/잡 — `src/nooa/runtime/channels.py` — hybrid 승인 관문 후보
- 샌드박스 참고 구현 — `examples/arc_agi_3/sandbox.py`(fail-closed 격리), `examples/arc_agi_3/harness.py`(행동 상한·IPC)
- **신규 필요** — Docker 샌드박스 실행기(compose 서비스), UnifiedLLM 가짜 클라이언트(테스트), NOOA 이벤트→run_event 브리지, 슬롯 스케줄러 트리거

## 참조 문서

- 러프 기획(이 파이프라인의 spec 원본): `docs/rough-plan.md`
- 원본 다이어그램: multiagent-sns `docs/diagrams/*.mermaid`
- NOOA 업스트림: README.md(§Safety), `examples/quickstart/01~15`, `notebook_tutorials/04_composing_subagents.ipynb`

## 규약

- Python 3.12 고정(nooa 지원 3.12~3.13) · `nooa` 버전 고정(Alpha API 변동 흡수, 어댑터 계층 1곳으로 격리)
- 마이그레이션: 원본 규약 승계(`sns/db/migrations/NNN_*.sql` 순번, UTF-8)
- 문서 인코딩 UTF-8 · 한국어

## 출력 규약

- 상세기획 spec → `docs/nooa-sns-spec.md`
- 다이어그램 → `docs/diagrams/*.mermaid`
- 미결정은 "미결정 — 결정 필요"로 명시(임의 확정 금지).
