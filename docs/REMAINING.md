# 남은 작업 (2026-08-20 기준)

> 코드 트랙은 종료 상태 — compose pytest 260/260 · mypy strict · ruff · CI GREEN.
> 남은 것은 전부 **팀 결정** 또는 **실계정 준비**이며, 각 항목에 재개 진입점을 명시한다.

## 현재 완성 범위 (요약)

- NOOA 7 에이전트 전부 CodeAct(스크립트 없는 실 LLM 풀사이클 dry-run **PASS** — docs/smoke-runs.md)
- 반증선 4건 관통(결정론·샌드박스 dry-run·툴 표면/시크릿·어댑터 격리)
- 발행 계층: 멱등 상태머신 + IG Graph(발행·인사이트) + YT(업로드·애널리틱스·OAuth DB 암호화)
- hybrid 승인 관문(승인 전 publish 0건, 툴 강제) + 승인 재개 관통(approve→배치 발행)
- 학습 루프: 6/24/72h 폴링→적재(결측 NULL)→reward 정산→topic_stats (임시 산식 가동)
- 렌더(카드 Pillow·영상 ffmpeg+ASS)·품질 게이트·Discord 알림·트렌드 소스 6종
- 운영 CLI 7종(`python -m sns.bootstrap cycle|metrics|publish-pending|approve|set-token|yt-auth|resident`)
- 웹 인사이트 탭(read-only): `python -m sns.web` 또는 `docker compose --profile web up web`

## 1. 팀 결정 대기

| # | 항목 | 현재 상태 | 결정 후 할 일 |
|---|---|---|---|
| 1 | **reward 산식 사전등록** (FR-L2, spec §7-6) | 임시안 `interim-baseline-v1` 가동 중(`sns/learning/reward.py`): goal 1차 신호 × 자기 베이스라인 중앙값 비율 평균, 표본<5=보류, 상한 10배 | 확정 산식을 새 RewardFn 클래스로 구현 → `run_metrics_slot(reward_fn=...)` 교체 → `formula_version='interim-baseline-v1'` 행 재정산 여부 결정 |
| 2 | **스케줄 방식** (미결정 #7) | 상주 러너 축은 구현됨(`resident` CLI). GHA cron 축은 `due_slots()` 계산까지 준비 | 상주=배포 위치 결정(VM/컨테이너), cron=워크플로 작성(`cycle`+`metrics` 호출) |
| 3 | (선택) 결정론 판정 방식(#4)·hybrid Channel 활용(#5)·상한 수치(#6)·002 마이그(#5) | spec §7 참조 — 현행 동작에 지장 없음 | M1 실측 후 사전등록 |

## 2. 실계정 관통 (사용자/팀 준비 필요)

### Instagram
1. IG 프로페셔널 계정 전환 + Meta 앱 생성 → 장기 액세스 토큰 + IG User ID 확보
2. 채널 행 등록(마이그 적용된 DB): `INSERT INTO channel (platform, handle, mode) VALUES ('instagram','<핸들>','hybrid')` — 첫 관통은 hybrid 권장
3. 토큰 등록: `SNS_CHANNEL_TOKEN=<토큰> uv run python -m sns.bootstrap set-token --platform instagram --handle <핸들>` (암호화 저장, 평문 비잔존)
4. `.env`에 `IG_USER_ID=` 설정
5. **미디어 공개 URL**: IG 발행은 공개 접근 URL 필수 — `LocalDirMediaStore(root, base_url=<공개 호스트>)`를 정적 호스팅에 연결하고 `_build_channel_context`의 InMemoryMediaStore를 교체(ponytail 주석 위치)
6. 관통: `cycle` → (hybrid면 Discord 알림 확인 → `approve`) → `publish-pending` → 24h 후 `metrics`

### YouTube
1. GCP OAuth 클라이언트(데스크톱) JSON → `YT_CLIENT_SECRET` 경로에
2. 채널 행 등록 후 대화형 발급: `uv run python -m sns.bootstrap yt-auth --platform youtube --handle <핸들>` (자격이 DB 암호화 저장 — 이후 무인 실행 가능)
3. 쇼츠는 영상 렌더 필요 → `.env`에 `GOOGLE_TTS_API_KEY=` (없으면 video 렌더 fail-fast)
4. 첫 업로드는 privacy_status=private(미감사 API 기본) — 관통 확인 후 공개 정책 결정

### 공통 주의
- 모든 실행은 **컨테이너 안**(nooa=Linux 전용, 샌드박스 게이트 SNS_SANDBOX=1 필수)
- 실 LLM 판단 모델: `.env` `SNS_LLM_JUDGMENT` — 실측상 **gpt-5.4-nano가 최저 가용선**(gpt-5-nano는 근거 무시·날조로 탈락, docs/smoke-runs.md). 운영 품질이 중요해지면 상위 모델 재평가
- 첫 5사이클은 reward가 전부 보류(베이스라인 표본 축적) — 정상 동작

## 3. 선택/후속 (급하지 않음)

- 미디어 스토리지 벤더 확정(정적 호스팅/오브젝트 스토리지) 후 LocalDirMediaStore base_url 배선
- IG 계정 단위 팔로워 지표(follower_count) 별도 관측(goals.py 주석 참조)
- nooa 업그레이드 정책: 버전 고정(0.0.9) 유지 — 올릴 땐 어댑터(`sns/agents/core.py`) 수정 PR + 전체 테스트
- 운영 배포(compose 프로덕션 구성·시크릿 관리)·metric 창 3+(일 1회) 폴링 확장

## 재개 시 읽을 것

1. `docs/nooa-sns-spec.md` — 정본 spec(§7 미결정 현황 포함)
2. `docs/smoke-runs.md` — 실 LLM 실측 기록·모델 판단 근거
3. `README.md` — 개발 워크플로(Windows=Docker 경유)·함정(PIE790 등)
4. 이 문서 §2 — 실계정 관통 절차
