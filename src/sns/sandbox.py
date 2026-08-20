"""FR-S1 — CodeAct 실행 격리 게이트 (fail-closed).

NOOA README:133 — 내장 AST 검사는 봉쇄 경계가 아니다. 봉쇄 경계는 OS 격리.
격리를 확인하지 못하면 실행을 거부한다(조용히 비샌드박스 실행 금지 —
arc_agi_3/sandbox.py의 fail-closed 관례를 따름).

운영 계약: 샌드박스 이미지(Dockerfile)가 `SNS_SANDBOX=1`을 명시 선언하고,
게이트는 그 선언 + 컨테이너 증거(/.dockerenv 또는 cgroup 마커)를 모두 요구한다.
"""

import os
import sys
from collections.abc import Mapping
from pathlib import Path

_CGROUP_MARKERS = ("docker", "containerd", "kubepods", "libpod", "podman")


class SandboxError(RuntimeError):
    """격리 미확인 — CodeAct 에이전트 기동 거부."""


def in_container(*, root: Path = Path("/")) -> bool:
    """컨테이너 실행 증거 검사(휴리스틱): /.dockerenv 또는 cgroup 마커."""
    if (root / ".dockerenv").exists():
        return True
    cgroup = root / "proc" / "1" / "cgroup"
    try:
        text = cgroup.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(marker in text for marker in _CGROUP_MARKERS)


def assert_sandboxed(
    *,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    is_container: bool | None = None,
) -> None:
    """격리 확인 — 실패 시 SandboxError (fail-closed). 인자는 테스트 주입용."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    is_container = in_container() if is_container is None else is_container

    if env.get("SNS_SANDBOX") != "1":
        raise SandboxError(
            "SNS_SANDBOX=1 미선언 — 샌드박스 이미지 밖에서 CodeAct 실행 금지 (FR-S1). "
            "docker build 후 컨테이너에서 실행하라."
        )
    if platform == "win32":
        raise SandboxError("Windows 호스트 직접 실행 금지 — Linux 컨테이너에서만 (FR-S1).")
    if not is_container:
        raise SandboxError(
            "SNS_SANDBOX=1 선언됐지만 컨테이너 증거(/.dockerenv·cgroup) 없음 — "
            "fail-closed로 거부 (FR-S1)."
        )
