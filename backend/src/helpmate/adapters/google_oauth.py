# Stand-in for Workstream B - not part of the Part C deliverable
"""Google OAuth credentials and authorised requests, shared by gmail.py and gcal.py.

The refresh token comes from scripts/google_auth.py (data/google_token.json, git-ignored). Access
tokens are refreshed when they expire and the rotated file is saved again. Apps in Google's
"Testing" status get 7-day refresh tokens, so an expired sign-in becomes GoogleNotConnected with
the fix in the message instead of a stack trace.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
]
RECONNECT = "From backend/, run: uv run python ../scripts/google_auth.py"


class GoogleNotConnected(RuntimeError):
    """No usable Google sign-in. The message says how to fix it."""


class GoogleCredentials:
    def __init__(self, token_file: Path) -> None:
        self._file = token_file
        self._creds: Any = None
        self._lock = asyncio.Lock()

    async def token(self, force_refresh: bool = False) -> str:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        async with self._lock:
            if self._creds is None:  # read lazily: the API starts even before Google is connected
                if not self._file.exists():
                    raise GoogleNotConnected(f"Google isn't connected yet. {RECONNECT}")
                self._creds = Credentials.from_authorized_user_file(str(self._file), SCOPES)
            if force_refresh or not self._creds.valid:
                try:
                    await asyncio.to_thread(self._creds.refresh, Request())
                except RefreshError as exc:
                    raise GoogleNotConnected(
                        "Google's sign-in expired or was revoked (test apps are signed out after "
                        f"7 days). {RECONNECT}"
                    ) from exc
                self._file.write_text(self._creds.to_json(), encoding="utf-8")
            return str(self._creds.token)


class GoogleApi:
    """Authorised JSON requests, with one retry after a token refresh on 401."""

    def __init__(self, client: httpx.AsyncClient, credentials: GoogleCredentials) -> None:
        self._client = client
        self._credentials = credentials

    async def request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in range(2):
            token = await self._credentials.token(force_refresh=attempt == 1)
            response = await self._client.request(
                method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )
            if response.status_code != 401:
                break
        if response.status_code == 403:
            message = response.json().get("error", {}).get("message", "forbidden")
            raise GoogleNotConnected(
                f"Google refused: {message} Check the API is enabled in Cloud Console and that "
                f"all permissions were ticked. {RECONNECT}"
            )
        response.raise_for_status()
        return response.json() if response.content else {}
