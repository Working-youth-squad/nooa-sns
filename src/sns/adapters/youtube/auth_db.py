"""YT OAuth 자격의 DB 암호화 영속 (NFR-4 승계) — token.json 파일 저장 대체.

원본 auth.load_credentials의 "DB 영속은 후속" 예약을 이행한다:
authorized_user JSON을 `channel.token_encrypted`(Fernet 암호문)에 저장하고,
refresh 성공 시 갱신분을 다시 암호화 저장한다. 평문은 메모리에서만 존재(FR-S3).

무인 환경(interactive=False)에서 자격 부재/만료 시 브라우저 플로우를 띄우지 않고
fail-fast 한다 — 상주 러너가 조용히 멈추는 대신 명확히 실패하게.
"""

import json
from pathlib import Path
from typing import Any

from sns.adapters.youtube.auth import SCOPES
from sns.crypto import TokenCipher


class YouTubeAuthError(RuntimeError):
    """무인 환경에서 자격 확보 실패 — 대화형 재발급 필요."""


def persist_credentials(conn: Any, cipher: TokenCipher, channel_id: str, credentials: Any) -> None:
    """authorized_user JSON을 암호화해 channel 행에 저장."""
    encrypted, version = cipher.encrypt(credentials.to_json())
    conn.execute(
        "UPDATE channel SET token_encrypted = %s, token_key_version = %s WHERE id = %s",
        (encrypted, version, channel_id),
    )


def credentials_from_token_json(token_json: str) -> Any:
    from google.oauth2.credentials import Credentials

    return Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
        json.loads(token_json), list(SCOPES)
    )


def ensure_credentials(
    conn: Any,
    cipher: TokenCipher,
    channel_id: str,
    *,
    client_secret: Path,
    interactive: bool = False,
) -> Any:
    """DB 자격 로드(+필요 시 refresh·재저장). 부재 시 interactive면 브라우저 플로우.

    반환은 google.oauth2 Credentials — build_youtube/build_youtube_analytics에 그대로.
    """
    row = conn.execute(
        "SELECT token_encrypted FROM channel WHERE id = %s", (channel_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"채널 없음: {channel_id}")

    credentials = None
    if row[0] is not None:
        credentials = credentials_from_token_json(cipher.decrypt(bytes(row[0])))
        # authorized_user 복원은 access token이 비거나 만료일 수 있다 — refresh_token이
        # 있으면 갱신 시도 후 갱신분을 재암호화 저장한다.
        if (credentials.expired or not credentials.valid) and credentials.refresh_token:
            from google.auth.transport.requests import Request

            credentials.refresh(Request())
            persist_credentials(conn, cipher, channel_id, credentials)

    if credentials is not None and credentials.valid:
        return credentials

    if not interactive:
        raise YouTubeAuthError(
            f"YT 자격 부재/무효(channel={channel_id}) — 대화형 재발급 필요: "
            "`python -m sns.bootstrap yt-auth --platform youtube --handle <h>`"
        )

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), list(SCOPES))
    credentials = flow.run_local_server(port=0)
    persist_credentials(conn, cipher, channel_id, credentials)
    return credentials
