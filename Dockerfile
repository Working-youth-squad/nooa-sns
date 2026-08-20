# 개발·테스트용 Linux 런타임 — nooa는 fcntl 의존으로 Windows 네이티브 불가.
# FR-S1: 프로덕션 CodeAct 실행도 이 이미지 기반 컨테이너(비루트) 안에서만.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# 렌더 계층: ffmpeg(영상 합성) + Noto CJK(한글 카드/자막)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home agent
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY README.md ./
COPY src ./src
COPY tests ./tests
RUN uv sync --frozen && chown -R agent:agent /app

USER agent
CMD ["uv", "run", "pytest", "-q"]
