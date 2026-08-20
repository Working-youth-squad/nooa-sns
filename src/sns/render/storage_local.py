"""로컬 디렉터리 MediaStore (FR-M3 벤더 seam) — 정적 호스팅 디렉터리 전제.

`root`에 콘텐츠 주소화 파일을 쓰고 `base_url`로 공개 URL을 만든다.
IG 발행은 공개 접근 URL이 필수 — base_url이 실제 공개 호스트(정적 서버·
페이지 호스팅)를 가리키면 실발행에 그대로 쓸 수 있다. 같은 checksum 재저장은
같은 경로(멱등). load()는 발행 어댑터의 media_bytes seam(YT 업로드)용 역조회.
"""

from pathlib import Path

from sns.render.storage import MediaStore
from sns.tools.contracts import MediaKind


class LocalDirMediaStore:
    def __init__(self, root: Path, *, base_url: str) -> None:
        self._root = root
        self._base_url = base_url.rstrip("/")

    def put(self, data: bytes, *, checksum: str, kind: MediaKind, ext: str) -> str:
        rel = f"{kind}/{checksum}.{ext}"
        path = self._root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():  # 콘텐츠 주소화 — 같은 checksum은 재기록 불필요(멱등)
            path.write_bytes(data)
        return f"{self._base_url}/{rel}"

    def load(self, url: str) -> bytes:
        prefix = f"{self._base_url}/"
        if not url.startswith(prefix):
            raise ValueError(f"이 스토어의 URL이 아님: {url}")
        rel = url[len(prefix) :]
        path = (self._root / rel).resolve()
        if not path.is_relative_to(self._root.resolve()):  # 경로 탈출 차단
            raise ValueError(f"루트 밖 경로 접근 거부: {url}")
        return path.read_bytes()


# 계약 적합성을 mypy가 강제.
def _check_store(store: LocalDirMediaStore) -> MediaStore:
    return store
