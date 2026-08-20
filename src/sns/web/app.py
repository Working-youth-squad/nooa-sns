"""웹 인사이트 탭 (FR-W 필수분) — read-only 대시보드 + JSON API.

원칙: 웹은 관측만 한다 — 여기서 상태를 바꾸는 엔드포인트는 두지 않는다
(승인은 CLI `approve`, 발행은 배치 러너). 수치는 전부 SQL 집계(코드),
LLM 서술은 저장된 착지점(analysis_note·playbook)을 그대로 보여줄 뿐이다.

실행: DATABASE_URL=... uv run python -m sns.web
테스트: create_app(conn_factory 주입) + fastapi TestClient.
"""

import html
from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import psycopg
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

ConnFactory = Callable[[], AbstractContextManager[psycopg.Connection]]


def create_app(conn_factory: ConnFactory) -> FastAPI:
    app = FastAPI(title="nooa-sns insights", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/insights/summary")
    def summary() -> dict[str, Any]:
        with conn_factory() as conn:
            return _summary(conn)

    @app.get("/api/insights/cycles")
    def cycles(limit: int = 20) -> list[dict[str, Any]]:
        with conn_factory() as conn:
            return _recent_cycles(conn, limit=min(max(limit, 1), 100))

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        with conn_factory() as conn:
            return _render_page(_summary(conn), _recent_cycles(conn, limit=10))

    return app


def _summary(conn: psycopg.Connection) -> dict[str, Any]:
    cycle_by_status: dict[str, int] = {
        str(r[0]): int(r[1])
        for r in conn.execute("SELECT status, count(*) FROM cycle GROUP BY status").fetchall()
    }
    pub_by_status: dict[str, int] = {
        str(r[0]): int(r[1])
        for r in conn.execute("SELECT status, count(*) FROM publication GROUP BY status").fetchall()
    }
    rewards = conn.execute("SELECT count(*), count(reward_value) FROM reward").fetchone() or (0, 0)
    stats = [
        {
            "topic_id": str(r[0]),
            "format": r[1],
            "platform": r[2],
            "trials": int(r[3]),
            "reward_sum": float(r[4]),
        }
        for r in conn.execute(
            "SELECT topic_id, format, platform, trials, reward_sum FROM topic_stats "
            "ORDER BY reward_sum DESC LIMIT 5"
        ).fetchall()
    ]
    note = conn.execute(
        "SELECT body, insufficient_evidence, created_at FROM analysis_note "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    playbook = conn.execute(
        "SELECT scope, scope_ref, version, guidance FROM playbook ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return {
        "cycles": cycle_by_status,
        "publications": pub_by_status,
        # 판정 보류(NULL reward)는 별도 집계 — 결측을 0으로 보이지 않게 (NFR-3 정신)
        "rewards": {"total": rewards[0], "with_value": rewards[1]},
        "top_topic_stats": stats,
        "latest_analysis_note": None
        if note is None
        else {
            "body": note[0],
            "insufficient_evidence": bool(note[1]),
            "created_at": note[2].isoformat(),
        },
        "latest_playbook": None
        if playbook is None
        else {
            "scope": playbook[0],
            "scope_ref": playbook[1],
            "version": int(playbook[2]),
            "guidance": playbook[3],
        },
    }


def _recent_cycles(conn: psycopg.Connection, *, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT cy.id, cy.goal_ref, cy.status, cy.created_at,
               count(DISTINCT p.id) AS publications,
               count(DISTINCT p.id) FILTER (WHERE p.status = 'published') AS published,
               count(DISTINCT e.id) AS events
          FROM cycle cy
          LEFT JOIN content_item ci ON ci.cycle_id = cy.id
          LEFT JOIN publication p ON p.content_item_id = ci.id
          LEFT JOIN run_event e ON e.cycle_id = cy.id
         GROUP BY cy.id
         ORDER BY cy.created_at DESC
         LIMIT %s
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "cycle_id": str(r[0]),
            "goal_ref": r[1],
            "status": r[2],
            "created_at": r[3].isoformat(),
            "publications": int(r[4]),
            "published": int(r[5]),
            "events": int(r[6]),
        }
        for r in rows
    ]


def _render_page(summary: dict[str, Any], cycles: list[dict[str, Any]]) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value))

    note = summary["latest_analysis_note"]
    playbook = summary["latest_playbook"]
    rows = "".join(
        f"<tr><td>{esc(c['created_at'][:16])}</td><td>{esc(c['goal_ref'])}</td>"
        f"<td>{esc(c['status'])}</td><td>{c['published']}/{c['publications']}</td>"
        f"<td>{c['events']}</td></tr>"
        for c in cycles
    )
    stats_rows = "".join(
        f"<tr><td>{esc(s['platform'])}</td><td>{esc(s['format'])}</td>"
        f"<td>{s['trials']}</td><td>{s['reward_sum']:.2f}</td></tr>"
        for s in summary["top_topic_stats"]
    )
    note_html = (
        "<p>아직 분석글 없음</p>"
        if note is None
        else f"<p>{esc(note['body'])}</p>"
        + ("<p><em>근거 부족(판정 보류)</em></p>" if note["insufficient_evidence"] else "")
    )
    playbook_html = (
        "<p>아직 플레이북 없음</p>"
        if playbook is None
        else f"<p>[{esc(playbook['scope'])} v{playbook['version']}] {esc(playbook['guidance'])}</p>"
    )
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>nooa-sns 인사이트</title>
<style>body{{font-family:sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:.3rem .6rem;text-align:left}}
h2{{margin-top:2rem}}</style></head><body>
<h1>nooa-sns 인사이트</h1>
<p>사이클: {esc(summary["cycles"])} · 발행: {esc(summary["publications"])} ·
reward: {summary["rewards"]["with_value"]}/{summary["rewards"]["total"]} (값 있음/전체 — 나머지는 판정 보류)</p>
<h2>최근 사이클</h2>
<table><tr><th>시각(UTC)</th><th>goal</th><th>상태</th><th>발행/시도</th><th>이벤트</th></tr>{rows}</table>
<h2>주제 성과 상위</h2>
<table><tr><th>플랫폼</th><th>포맷</th><th>trials</th><th>reward 합</th></tr>{stats_rows}</table>
<h2>최근 분석글</h2>{note_html}
<h2>최신 플레이북</h2>{playbook_html}
</body></html>"""


def default_conn_factory(database_url: str) -> ConnFactory:
    @contextmanager
    def factory() -> Any:
        with psycopg.connect(database_url, autocommit=True) as conn:
            yield conn

    return factory
