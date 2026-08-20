# nooa-sns 상세기획 (Spec) — NOOA/CodeAct 전면 적용 멀티에이전트 SNS 성장 엔진

> 입력: `docs/rough-plan.md` · 하네스 생성 · 작성일: 2026-08-20 · 상태: 상세기획(제안)
> 원본 기획: [Working-youth-squad/multiagent-sns](https://github.com/Working-youth-squad/multiagent-sns) `docs/PLAN.md` + `docs/plan/01~14`
> 확정 결정(2026-08-20): **NOOA 통째 도입 · 7개 에이전트 전부 CodeAct · Orchestrator 완전 자율 계획 · Docker 샌드박스 · 불변식은 툴 계약 내부 강제**

## 1. 개요 / 목표

개발자 주제 콘텐츠를 IG 피드·릴스·YouTube 쇼츠에 자동 기획·제작·발행하고 반응 지표를 학습해 채널을 키우는 자율 성장 엔진(원본 정의 계승). 에이전트 코어를 deepagents(LangGraph)에서 **NOOA(`nooa`, LiteLLM 기반 OO 에이전트 프레임워크) + CodeAct 전면 채택**으로 교체한다.

**통제 철학 전환**: 원본의 "LLM은 DB 착지점 3곳에만"(프롬프트·경로 수준 통제)에서 → NOOA 관례인 "**재량은 에이전트에, 불변식은 에이전트 바깥의 코드에**"로. CodeAct 재량은 최대로 주되, 멱등 발행·결정론 렌더·시크릿 비노출·착지점 제한은 **툴 계약 구현과 OS 샌드박스가 구조적으로 강제**한다.

계승 범위(변경 없음): 실험설계(계정 4개 auto vs hybrid)·성공기준(S1~S5)·kill criteria(K1~K4)·데이터모델(15테이블)·발행 규격·미디어 렌더·트렌드/품질게이트/지표학습 — 원본 docs/plan/01·04~12 참조(thin spec).

## 2. 재사용 자산 & 제약 (plan-search)

원본 클론과 NOOA 클론에서 전 경로 실재 확인(2026-08-20 grep 검증).

| 개념 | 상태 | 경로 (multiagent-sns / oo-agents) | 요지 |
|---|---|---|---|
| 툴 계약 6종 | 재사용 | `sns/tools/contracts.py:42,56,70,95,113,127` | ResearchTrends·RenderMedia·Publish·PollMetrics·ReadStats·WritePlaybook Protocol + 반환 dataclass. 프레임워크 무관 → NOOA 클래스 속성으로 부착 |
| 툴 페이크 | 재사용 | `sns/tools/fakes.py` | 결정론 테스트용 |
| 멱등 발행 상태머신 | 재사용(툴 내부로 이식) | `sns/publish/state_machine.py:59` `run_publish`, `PublishAttemptStore` | 이중 발행 0 보장 |
| DB 스키마 15테이블 | 재사용 | `sns/db/migrations/001_initial.sql`(CREATE 14) + `schema_version`(migrate.py) | CHECK·enum·append-only 승계 |
| 스토어 시임 | 재사용 | `sns/runner/store.py:25` CycleStore(InMemory:58/Pg:144) | 테스트/프로드 이중 구현 |
| 시크릿 암호화 | 재사용 | `sns/crypto.py` | 토큰 평문 저장 금지 |
| 렌더러 | 재사용 | `sns/render/{card,video,storage.py}` | Pillow 결정론 카드(checksum) |
| deepagents 결합부 | **교체 대상** | `sns/agents/*.py`, `sns/agents/models.py`, `sns/runner/cycle.py` | LangChain 모델 시임·고정 시퀀스 오케스트레이터 폐기 |
| NOOA Agent 코어 | 신규 도입 | `src/nooa/agent.py`, `metaclass.py` | docstring=프롬프트, `...` 메서드=생성 메서드, 타입=계약 |
| CodeAct | 신규 도입 | `strategies/codeact.py:287`, `config/strategy_config.py:33` | 지속 REPL 실행, `max_iterations` 강제(:166) |
| LLM 클라이언트 | 신규 도입 | `unifiedllm/registry.py:297` `get_llm_client()`, `unifiedllm.py:1153` UnifiedLLM ABC | LiteLLM 라우팅, 5단계 캐스케이딩 주입, ABC=가짜 주입 시임 |
| 이벤트 소싱 | 신규 도입 | `src/nooa/events.py`, `runtime/event_manager.py` | run_event 브리지 소스 |
| Channel/JobHandle | 후보 | `runtime/channels.py:180/:83`, spawn`:963` | hybrid 승인 관문 후보(미결정 #5) |
| 샌드박스 참고 | 참고 구현 | `examples/arc_agi_3/sandbox.py`(fail-closed), `harness.py`(행동 상한·IPC) | NOOA 관례: 하네스+격리 |
| Docker 샌드박스 실행기 | **신규 필요** | — | compose 서비스(비루트+이그레스 화이트리스트) |
| FakeUnifiedLLM | **신규 필요** | — | 스크립트 응답 가짜 클라이언트(결정론 테스트) |
| 이벤트→run_event 브리지 | **신규 필요** | — | NOOA 이벤트를 DB append-only로 |
| 슬롯 스케줄러 | **신규 필요** | — | 사이클 트리거(방식 미결정 #7) |

**제약**: Python 3.12 고정(nooa 3.12~3.13) · `nooa` 버전 고정(Alpha ~v0.0.7, API 변동) · NOOA AST 검사는 봉쇄 경계 아님(README:133 — OS 격리 필수) · Apache-2.0(상용 문제 없음).

## 3. 요구사항 (plan-split)

### 3.1 기능 요구사항 (FR)

#### FR-C 에이전트 코어 (원본 FR-C1~C5 전면 재작성)

| ID | 설명 | 근거 | 수용기준 |
|---|---|---|---|
| FR-C1 | 코어 = **nooa 전면 도입**. 7개 에이전트(Orchestrator·Topic·Content·Media·Publisher·Analyst·Growth) 전부 `class Xxx(Agent)` + CodeActStrategy | NOOA agent.py·codeact.py:287 | NOOA로 한 사이클(기획→제작→발행→학습)이 샌드박스 내 관통 |
| FR-C2 | 외부 상호작용은 **툴 계약 6종을 클래스 속성으로 부착**한 경로만. REPL에 raw DB 커넥션·평문 시크릿 비노출 | contracts.py 재사용 | 착지점 외 기록 경로 부재 + REPL 시크릿 비노출 테스트 green |
| FR-C3 | LLM = LiteLLM `get_llm_client()`. 판단=`claude-sonnet-5`, 대량=`gemini/gemini-2.5-flash`(설정 고정, 장애 시 임의 교차 대체 금지). `.nooa/llm_config.yaml` 별칭 + 5단계 캐스케이딩 주입 | registry.py:297 | FakeUnifiedLLM 주입 결정론 재현 테스트 green |
| FR-C4 | LLM 서술 착지점 3곳(`content_item.body`·`playbook.guidance`·`analysis_note.body`) 유지 — 툴 계약 서명이 강제 | 원본 plan/11 §6 | 착지점 외 LLM 기록 경로 부재(쓰기 API 표면 검사) |
| FR-C5 | NOOA 이벤트 소싱 → `run_event` 브리지: 에이전트 호출·iteration·토큰/비용 append-only 기록 | events.py + 원본 run_event | 사이클 로그만으로 흐름·비용 재구성 |
| FR-C6 | **Orchestrator 완전 자율 계획**: 슬롯 트리거만 받고 순서·병렬(asyncio.gather)·스킵·재시도를 CodeAct가 계획. 서브에이전트 6개 속성 부착 | 확정 결정 · NOOA notebook 04 | 서브에이전트 1개 실패 주입 시 격리·대응이 run_event에 기록, 사이클 전체 생존 |
| FR-C7 | 구조화 출력: 반환 타입(Pydantic) 자동 검증 + 실패 시 오류 피드백 재시도(상한 有). 원본 Rejected 수동 게이트 대체(품질 게이트 FR-Q는 별도 유지) | NOOA README | 스키마 위반 주입 시 재시도 후 유효 산출 또는 상한 실패 관측 |
| FR-C8 | **어댑터 계층 1곳**: nooa API 사용을 단일 모듈로 격리 + 버전 고정 | 러프 §5(d) | nooa import가 어댑터 밖에 없음(grep 게이트) |

#### FR-S 샌드박스 (신규)

| ID | 설명 | 근거 | 수용기준 |
|---|---|---|---|
| FR-S1 | CodeAct 실행은 **Docker 컨테이너(비루트)** 안에서만. 격리 미확인 시 **fail-closed** 기동 거부 | NOOA README:133 · arc_agi_3/sandbox.py 패턴 | 비샌드박스 기동 → 거부 테스트 |
| FR-S2 | 이그레스 화이트리스트: LLM API·발행 API·트렌드 소스만 | HARNESS 규칙 7 | 외부 도메인 요청 차단 + 시도 run_event 기록 |
| FR-S3 | 시크릿 복호화·실발행은 툴 구현 내부만. REPL에서 토큰 접근 수단 부재 | crypto.py · HARNESS 규칙 6 | REPL 시크릿 탐색 테스트 실패(비노출) |

#### FR-O 운영/스케줄

| ID | 설명 | 근거 | 수용기준 | 태그 |
|---|---|---|---|---|
| FR-O1 | 슬롯 스케줄러가 사이클 트리거(웹 무관 실행), 중복 트리거 멱등 | 원본 02 §2 | 슬롯 도래 시 기동, 중복 사이클 0 | 미결정 #7 |
| FR-O2 | hybrid: `needs_review` 시 Discord 알림 + 승인 전 publish 0건 | 원본 FR-W 승계 | 승인 전 실발행 0 테스트 | 미결정 #5 |
| FR-O3 | 비용 관측·상한: `max_iterations` + 사이클 위임 예산 + cost cap(S5) 초과 시 K4 | 원본 FR-P6 + strategy_config.py:33 | cap 초과 주입 시 자율 발행 중단 | 미결정 #6(수치) |

### 3.2 비기능 요구사항 (NFR)

| ID | 설명 | 근거 | 수용기준 | 태그 |
|---|---|---|---|---|
| NFR-1 | 결정론 재현: FakeUnifiedLLM 스크립트 주입, 판정=착지 결과+이벤트 시퀀스(생성 코드 텍스트 아님) | UnifiedLLM ABC:1153 | 동일 스크립트 2회 → 동일 DB 착지 | 미결정 #4 |
| NFR-2 | 멱등 발행: 상태머신 툴 내부 이식, 크래시 복구 포함 이중 발행 0 | state_machine.py:59 | 재시작·동시 호출 시 실발행 1회 |
| NFR-3 | missing=NULL: metric_value XOR CHECK 승계 | 001_initial.sql | 위반 insert 실패 |
| NFR-4 | 시크릿 암호화 + REPL·로그·트레이스 비노출 | crypto.py | 평문 토큰 0건(시크릿 스캔) |
| NFR-5 | Alpha 리스크: 버전 고정·어댑터 1곳·반증선 게이트(§7 참조) 미통과 시 deepagents/자작 폴백 | 러프 §5 | Phase 0 게이트 판정 기록 |
| NFR-6 | CI: pytest+ruff+mypy strict. 결정론 테스트는 가짜 LLM → 샌드박스·네트워크 불필요, GHA 실행 가능 | 원본 12 승계 | CI green |
| NFR-7 | 관측: run_event 재구성(필수) + OpenTelemetry 트레이싱(옵션) | nooa[tracing] | 비활성 환경에서도 run_event만으로 재구성 |

### 3.3 데이터 모델 초안

- 15테이블 전부 승계(001_initial.sql + schema_version). LLM 착지점 3곳 열거 유지.
- **002_nooa_events.sql(제안)**: `run_event`에 `agent_name text`·`codeact_iteration int`·`llm_cost_usd numeric` 추가(FR-C5 착지). append-only 불변 유지. 마이그레이션 규약(`NNN_*.sql` 전진 순번) 준수. — 채택 여부 구현 시 확정.

## 4. 시퀀스 (plan-sequence)

- 발행 사이클: [diagrams/publish-cycle-sequence.mermaid](diagrams/publish-cycle-sequence.mermaid) — 슬롯 트리거 → fail-closed 격리 확인 → CodeAct 자율 계획 → 툴 계약 경유 착지 → hybrid 승인 분기 → 멱등 발행 → cost cap 분기.
- 학습 루프: [diagrams/learning-loop-sequence.mermaid](diagrams/learning-loop-sequence.mermaid) — 지표 창 폴링(결측=NULL) → reward(코드) → 분석글(정직 귀인) → 플레이북 → Growth 다음 변형.

## 5. 유저 플로우 (plan-flow)

- 운영자 플로우: [diagrams/operator-userflow.mermaid](diagrams/operator-userflow.mermaid) — 초기 설정(채널 연결·모드 지정) → 무인 사이클 → hybrid 승인(승인/수정/거부/무응답) → 인사이트(표본 부족=보류 표시) → K2~K4 대응 경로.

## 6. 예외 · 테스트 케이스 (plan-logic-check)

| 요구사항 ID | 케이스 | 유형 | 기대 결과 |
|---|---|---|---|
| FR-C1 | Fake 스크립트로 사이클 관통 | 정상 | 완주 + DB 착지 일치 |
| FR-C1 | max_iterations 내 미완 | 예외 | 채널 격리 실패 + run_event |
| FR-C1 | LLM 타임아웃/5xx | 예외 | 백오프 재시도 → 소진 시 사이클 실패, 다음 슬롯 무영향 |
| FR-C2 | REPL이 raw DB 커넥션 import 시도 | 보안 | 자격증명 부재로 실패 |
| FR-C2 | 툴 외 파일시스템 쓰기 | 보안 | read-only 마운트 차단 |
| FR-C3 | API 키 미설정 기동 | 예외 | fail-fast 설정 오류 |
| FR-C3 | 판단 모델 장애 시 대량 모델 대체 | 예외 | 자동 대체 금지(설정 고정) |
| FR-C4 | 착지점 외 테이블 기록 시도 | 보안 | 쓰기 API 부재로 불가능 |
| FR-C5 | 브리지 중 DB 순단 | 예외 | 버퍼·재시도, 이벤트 수 정합 |
| FR-C6 | 서브에이전트 1개 실패 | 예외 | partial 완료 + 사유 기록 |
| FR-C6 | 무한 재위임 | 엣지 | 사이클 위임 예산으로 강제 종료 |
| FR-C7 | 스키마 위반 N회 연속 | 예외 | 재시도 상한 후 실패 확정 + 비용 기록 |
| FR-C7 | 구조 유효·품질 미달 | 예외 | FR-Q 경로 분리(needs_review/reject) |
| FR-C8 | nooa API 변경 | 예외 | 버전 고정 무영향, 업그레이드=어댑터 1곳 |
| FR-S1 | 호스트 직접 기동 | 보안 | fail-closed 거부 + 알림 |
| FR-S2 | 화이트리스트 외 fetch | 보안 | 차단 + 시도 기록 |
| FR-S3 | `self` 순회 토큰 탐색 | 보안 | 속성 부재(툴 프로세스 경계 내부만) |
| FR-O1 | 스케줄러 재시작 중복 트리거 | 엣지 | 중복 사이클 0 |
| FR-O2 | 승인 무응답 지속 | 엣지 | 보류 유지·publish 0건(만료 정책 미결정) |
| FR-O2 | 중복 승인 요청 | 엣지 | 상태 전이 1회만 |
| FR-O3 | 사이클 중 cap 도달 | 예외 | 즉시 중단(K4), 착지물 보존 |
| NFR-1 | 동일 스크립트 2회 | 정상 | 착지 결과 동일 |
| NFR-1 | 생성 코드 실행마다 상이 | 엣지 | 판정=착지+이벤트 시퀀스 기준 |
| NFR-2 | publish 중 크래시 재시작 | 예외 | 상태 복구, 이중 발행 0 |
| NFR-2 | 동시 publish 2회 | 엣지 | 실발행 1회 |
| NFR-3 | 지표 일부 미제공 | 정상 | missing=TRUE·NULL(0 금지) |
| NFR-3 | value·missing 동시 세팅 | 예외 | CHECK 실패 |
| NFR-4 | 로그/트레이스 토큰 유출 | 보안 | 시크릿 스캔 0건 |
| NFR-6 | GHA(무샌드박스) 결정론 테스트 | 정상 | green |
| NFR-7 | 트레이싱 비활성 | 정상 | run_event 단독 재구성 |

도메인 금지 위반 시나리오 커버: 비공식 스크래핑 경로 부재(툴=공식 API만) · 타 계정 비교 산출 부재(read_stats 자기 스코프만) · 사후확신(임계 사전등록 전 판정 코드 미참조).

## 7. 미결정 (결정 필요)

1. **결정론 테스트 전략**(#4): 이벤트 리플레이 vs 골든 이벤트 로그 비교 — NFR-1 판정 방식. Phase 0 스파이크에서 확정.
2. **hybrid 승인 관문 구현**(#5): NOOA Channel/JobHandle 활용 vs DB 폴링 — FR-O2.
3. **상한 수치**(#6): `max_iterations`·사이클 위임 예산·cost cap 값 — M1 실측 후 사전등록.
4. **원본 승계 미결정**(#7): 스케줄 방식(상주 러너 vs GHA cron — `resident` CLI로 상주 축은 구현됨)·TTS 엔진.
   영상 렌더러는 **ffmpeg+ASS로 실용 확정(2026-08-20)**: 원본 스파이크 구현이 실재·테스트 green,
   Remotion은 미착수 — 구현 실재 기준. 팀 이견 시 재론.
5. **002 마이그레이션 채택 여부**: run_event 확장 컬럼 vs 기존 payload 컬럼 활용.
6. **reward 산식 계수**(FR-L2): 팀 사전등록 대기. **임시안 가배치(2026-08-20 사용자 결정)** —
   `interim-baseline-v1`(`sns/learning/reward.py`): goal 1차 신호의 자기 베이스라인
   중앙값 대비 비율 평균, 표본<5=보류(NULL), 비율 상한 10배. formula_version이
   reward 행에 남아 확정 산식 등록 후 임시분 식별·재정산 가능.

**반증선(Phase 0 게이트, NFR-5)**: (a) Fake 주입 결정론 green (b) 샌드박스 내 CodeAct 사이클 dry-run 관통 (c) DB 쓰기 경로 계약 밖 유출 0 (d) 버전 고정+어댑터 격리 확인 — 미통과 시 deepagents 원안 또는 자작 thin loop 폴백.

## 8. 검증 노트 (plan-assemble)

- **역추적** ✅ — FR-C1~C8·FR-S1~S3·FR-O1~O3·NFR-1~7 전부 러프 doc §3~§6 또는 확정 결정(2026-08-20 사용자 답변 4건)으로 추적됨. 출처 없는 요구사항 없음.
- **자산 실재** ✅ — §2 표의 원본·NOOA 경로 전부 2026-08-20 클론에서 grep/파일 존재 확인. 부재 항목 4종은 "신규 필요"로 명시. (참고: 원본 문서상 "테이블 15" = SQL의 CREATE 14 + migrate.py 생성 schema_version — 드리프트 아님)
- **일관성** ✅ — 시퀀스·플로우 노드의 FR ID 주석이 §3과 일치. 다이어그램에 §3에 없는 라우트/테이블 없음.
- **도메인 금지** ✅ — HARNESS.md 규칙 9종 위반 문구 0건(§6에 위반 시나리오를 테스트로 역커버).
- **미결정 보존** ✅ — 가드레일 미답 5건이 §7에 "결정 필요"로 보존, 임의 확정 없음.
- 한계 고지: NOOA는 Alpha(~v0.0.7)로 §2 라인 번호는 2026-08-20 스냅샷 기준 — 업그레이드 시 재검증 필요.
