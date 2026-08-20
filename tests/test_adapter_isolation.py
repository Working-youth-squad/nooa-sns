"""반증선 (d) — nooa import는 어댑터(sns/agents/core.py) 한 곳만 (FR-C8, NFR-5)."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "sns"
ADAPTER = SRC / "agents" / "core.py"
IMPORT_RE = re.compile(r"^\s*(from nooa|import nooa)", re.MULTILINE)


def test_nooa_import_only_in_adapter() -> None:
    offenders = [
        p.relative_to(SRC)
        for p in SRC.rglob("*.py")
        if p != ADAPTER and IMPORT_RE.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"어댑터 밖 nooa import: {offenders}"


def test_adapter_exists_and_imports_nooa() -> None:
    assert IMPORT_RE.search(ADAPTER.read_text(encoding="utf-8"))
