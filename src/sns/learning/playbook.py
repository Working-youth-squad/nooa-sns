"""WritePlaybook 계약의 PG 구현 (FR-L4) — LLM 착지점 2/3, 버전 전진.

단일 러너 전제(발행 러너와 동일 규율) — 동시 쓰기가 필요해지면
UNIQUE(scope, scope_ref, version) 충돌 재시도를 더한다.
"""

import psycopg

from sns.tools.contracts import PlaybookScope, PlaybookVersion, WritePlaybook


class PgWritePlaybook:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def __call__(
        self, scope: PlaybookScope, guidance: str, scope_ref: str | None = None
    ) -> PlaybookVersion:
        row = self._conn.execute(
            """
            INSERT INTO playbook (scope, scope_ref, version, guidance)
            SELECT %(scope)s, %(ref)s, COALESCE(MAX(version), 0) + 1, %(guidance)s
              FROM playbook
             WHERE scope = %(scope)s AND scope_ref IS NOT DISTINCT FROM %(ref)s
            RETURNING version
            """,
            {"scope": scope, "ref": scope_ref, "guidance": guidance},
        ).fetchone()
        assert row is not None
        return PlaybookVersion(scope=scope, scope_ref=scope_ref, version=int(row[0]))


# 계약 적합성을 mypy가 강제.
def _check_playbook(store: PgWritePlaybook) -> WritePlaybook:
    return store
