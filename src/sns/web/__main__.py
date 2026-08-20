"""웹 인사이트 서버 실행 — DATABASE_URL 필수. `uv run python -m sns.web`."""

import os

import uvicorn

from sns.web.app import create_app, default_conn_factory


def main() -> None:
    app = create_app(default_conn_factory(os.environ["DATABASE_URL"]))
    uvicorn.run(
        app,
        host=os.environ.get("SNS_WEB_HOST", "127.0.0.1"),
        port=int(os.environ.get("SNS_WEB_PORT", "8080")),
    )


if __name__ == "__main__":
    main()
