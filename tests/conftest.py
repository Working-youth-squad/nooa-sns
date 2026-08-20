"""nooa는 fcntl 의존으로 Linux/macOS 전용 — Windows 네이티브에선 nooa 의존 테스트 제외.

Windows 로컬 실행 경로: `docker build -t nooa-sns-test . && docker run --rm nooa-sns-test`
CI(ubuntu)가 전체 스위트의 정본 검증 환경이다.
"""

import sys

if sys.platform == "win32":
    collect_ignore = ["helpers.py", "test_determinism.py", "test_tool_surface.py"]
