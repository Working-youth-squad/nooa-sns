# nooa-sns

NOOA(CodeAct) 기반 멀티에이전트 SNS 성장 엔진 — [multiagent-sns](https://github.com/Working-youth-squad/multiagent-sns) 기획을 계승하고, 에이전트 코어를 [NVIDIA-NeMo/labs-OO-Agents](https://github.com/NVIDIA-NeMo/labs-OO-Agents)(`nooa`) + CodeAct 전면 채택으로 재설계.

## 문서

| 문서 | 내용 |
|---|---|
| [HARNESS.md](HARNESS.md) | 절대 규칙 · 재사용 자산 맵 · 출력 규약 (기획 하네스 Source of Truth) |
| [docs/rough-plan.md](docs/rough-plan.md) | 러프 기획 (하네스 입력 원본) |
| [docs/nooa-sns-spec.md](docs/nooa-sns-spec.md) | **상세기획 spec** — FR/NFR · 데이터모델 · 예외/테스트 · 미결정 |
| [docs/diagrams/](docs/diagrams/) | 발행 사이클 · 학습 루프 시퀀스, 운영자 유저플로우 (Mermaid) |

## 개발 워크플로 (Phase 0)

- 스택: Python 3.12 · uv · `nooa==0.0.9`(고정) · pytest/ruff/mypy strict
- ⚠️ **nooa는 Linux/macOS 전용**(`fcntl` 의존) — Windows에선 Docker로 실행:
  ```
  docker build -t nooa-sns-test . && docker run --rm nooa-sns-test
  ```
- ⚠️ **ruff PIE790 금지**(pyproject에 ignore 고정) — NOOA 생성 메서드의 `...` 본문을 삭제해 탐지가 조용히 꺼진다.
- 반증선 테스트: `tests/test_determinism.py`(a 결정론) · `tests/test_tool_surface.py`(c 표면/시크릿) · `tests/test_adapter_isolation.py`(d 어댑터 격리)

## 핵심 결정 (2026-08-20)

- 7개 에이전트(Orchestrator·Topic·Content·Media·Publisher·Analyst·Growth) **전부 CodeAct**
- Orchestrator **완전 자율 계획** (슬롯 트리거만 받음)
- **Docker 샌드박스 필수** (fail-closed, NOOA README 관례)
- 불변식(멱등 발행·결측=NULL·시크릿 비노출·착지점 3곳)은 **툴 계약 내부에서 강제**
