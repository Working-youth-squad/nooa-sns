"""반증선 (b) 전제 — FR-S1 fail-closed 격리 게이트 (nooa 무관, 전 플랫폼 실행)."""

from pathlib import Path

import pytest

from sns.sandbox import SandboxError, assert_sandboxed, in_container


def test_no_flag_refused() -> None:
    with pytest.raises(SandboxError, match="SNS_SANDBOX=1 미선언"):
        assert_sandboxed(env={}, platform="linux", is_container=True)


def test_windows_host_refused_even_with_flag() -> None:
    with pytest.raises(SandboxError, match="Windows"):
        assert_sandboxed(env={"SNS_SANDBOX": "1"}, platform="win32", is_container=True)


def test_flag_without_container_evidence_refused() -> None:
    with pytest.raises(SandboxError, match="컨테이너 증거"):
        assert_sandboxed(env={"SNS_SANDBOX": "1"}, platform="linux", is_container=False)


def test_sandboxed_passes() -> None:
    assert_sandboxed(env={"SNS_SANDBOX": "1"}, platform="linux", is_container=True)


def test_in_container_dockerenv(tmp_path: Path) -> None:
    (tmp_path / ".dockerenv").write_text("")
    assert in_container(root=tmp_path) is True


def test_in_container_cgroup_marker(tmp_path: Path) -> None:
    cgroup = tmp_path / "proc" / "1"
    cgroup.mkdir(parents=True)
    (cgroup / "cgroup").write_text("0::/system.slice/docker-abc.scope\n")
    assert in_container(root=tmp_path) is True


def test_not_in_container(tmp_path: Path) -> None:
    assert in_container(root=tmp_path) is False
