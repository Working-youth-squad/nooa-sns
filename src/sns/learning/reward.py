"""임시 reward 산식 `interim-baseline-v1` — 팀 사전등록 전 가배치 (FR-L2).

⚠️ 지위: 이것은 **사전등록된 산식이 아니다**. 계수·형태의 팀 확정 전까지의
임시안이며, 모든 reward 행에 formula_version='interim-baseline-v1'이 남으므로
확정 산식 등록 후 임시분을 식별·재정산할 수 있다.

임시안 원칙(기존 동결 규칙만 조합, 새 재량 최소화):
1. **goal 프리셋 1차 신호만** 사용 — 신호 선택은 goals.py 동결 범위를 따른다.
2. **자기 베이스라인 대비 비율** — 같은 플랫폼·정산 창(72h) 이력의 중앙값 대비.
   절대치 사용 금지(원칙 6: 자기 베이스라인 성장만).
3. **표본 부족 = 판정 보류(None)** — 베이스라인 표본 < MIN_BASELINE_N(스코어보드와
   동일 5)이면 학습에서 제외한다. 초기 사이클은 자연히 전부 보류(K2 게이트 정합).
4. **비율 상한 10배** — 분산 연구 근거(scoreboard.VARIANCE_WARNING)로 heavy-tail 방어.
5. 결측 신호 제외, 사용 가능 신호 0개면 None. 미등록 goal_ref도 None(정직 보류).

reward = 사용 가능 1차 신호들의 (값 ÷ 베이스라인 중앙값, 상한 10) 산술 평균.
"""

import statistics

import psycopg

from sns.goals import GOAL_PRESETS
from sns.signals.scoreboard import MIN_BASELINE_N
from sns.tools.contracts import Platform

RATIO_CAP = 10.0
FORMULA_VERSION = "interim-baseline-v1"


class InterimBaselineReward:
    formula_version = FORMULA_VERSION

    def __init__(self, conn: psycopg.Connection, *, settle_window_index: int = 2) -> None:
        self._conn = conn
        self._window = settle_window_index

    def __call__(
        self,
        values: dict[str, float | None] | object,
        *,
        goal_ref: str,
        platform: Platform,
        publication_id: str,
    ) -> float | None:
        preset = GOAL_PRESETS.get(goal_ref)  # type: ignore[call-overload]
        if preset is None:
            return None  # 미등록 goal — 임의 해석하지 않고 보류
        signals = preset.ig_signals if platform == "instagram" else preset.yt_signals
        assert isinstance(values, dict)
        ratios: list[float] = []
        for key in signals:
            value = values.get(key)
            if value is None:
                continue  # 결측 — 0 대체 금지 (NFR-3)
            baseline = self._baseline(platform, key, exclude_publication_id=publication_id)
            if baseline is None or baseline <= 0:
                continue
            ratios.append(min(float(value) / baseline, RATIO_CAP))
        if not ratios:
            return None
        return sum(ratios) / len(ratios)

    def _baseline(
        self, platform: Platform, metric_key: str, *, exclude_publication_id: str
    ) -> float | None:
        """같은 플랫폼·정산 창 이력의 중앙값. 표본 < MIN_BASELINE_N → None(보류)."""
        rows = self._conn.execute(
            """
            SELECT mv.value
              FROM metric_value mv
              JOIN metric_observation mo ON mo.id = mv.observation_id
              JOIN publication p ON p.id = mo.publication_id
              JOIN channel ch ON ch.id = p.channel_id
             WHERE ch.platform = %s
               AND mo.window_index = %s
               AND mv.metric_key = %s
               AND mv.value IS NOT NULL
               AND p.id != %s
            """,
            (platform, self._window, metric_key, exclude_publication_id),
        ).fetchall()
        samples = [float(r[0]) for r in rows]
        if len(samples) < MIN_BASELINE_N:
            return None
        return float(statistics.median(samples))
