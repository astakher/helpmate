# Stand-in for Workstream B - not part of the Part C deliverable
"""Password + TOTP login for the single owner (HELPMATE_AUTH=totp).

- Password: an argon2id hash in .env (HELPMATE_OWNER_PASSWORD_HASH, written by
  scripts/set_password.py), so the password itself is never stored. The hash is checked even for
  a wrong username, so the response time doesn't reveal which part was wrong.
- Rate limiting: 5 failed sign-ins within 15 min lock sign-in for 15 min (429 + Retry-After).
  Each 2FA challenge lives 5 min and allows 5 codes.
- TOTP (RFC 6238, 30 s steps, via pyotp): accepts the current step +/- 1 (phone clock drift) and
  never the same step twice (no replay). A new secret only takes effect after confirm_mfa.
- The TOTP secret, last used step and sessions persist in data/auth.json (git-ignored), so 2FA
  and sign-ins survive an API restart. Sessions are stored as SHA-256 digests of their tokens,
  never the tokens. Changing the password (scripts/set_password.py) signs every device out.
- Lost phone: `uv run python ../scripts/set_password.py --reset-2fa` (needs this machine).

Workstream B's real version moves users, secrets and sessions into Postgres and adds recovery
codes; the AuthPort is the same.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import secrets
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from helpmate.domain.models import OWNER_ID, LoginResult, User
from helpmate.domain.ports import Clock

log = logging.getLogger("helpmate.auth")

MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=15)
CHALLENGE_TTL = timedelta(minutes=5)
MAX_CODE_ATTEMPTS = 5
STEP_SECONDS = 30
# a real argon2 hash of a random value, so a wrong username costs as much time as a wrong password
_DUMMY_HASH = PasswordHasher().hash(secrets.token_urlsafe(16))


def _digest(token: str) -> str:
    """What's stored for a session: a leaked state file doesn't hand out usable tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


class TotpAuth:
    name = "totp"
    is_fake = False

    def __init__(
        self,
        username: str,
        password_hash: str,
        state_file: Path,
        clock: Clock,
        session_ttl: timedelta = timedelta(days=7),
    ) -> None:
        if not password_hash:
            raise ValueError(
                "HELPMATE_AUTH=totp needs a password. In your own terminal, from backend/: "
                "uv run python ../scripts/set_password.py"
            )
        self._hasher = PasswordHasher()
        try:
            self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError as exc:
            raise ValueError(
                "HELPMATE_OWNER_PASSWORD_HASH isn't an argon2 hash; run scripts/set_password.py"
            ) from exc
        self._username = username
        self._password_hash = password_hash
        self._state_file = state_file
        self._clock = clock
        self._session_ttl = session_ttl
        self._state: dict[str, Any] = self._load()
        self._pending_secret: str | None = None
        # sha256(token) -> expiry; saved in the state file so a restart keeps devices signed in
        self._sessions: dict[str, datetime] = {
            digest: datetime.fromisoformat(expires)
            for digest, expires in self._state.get("sessions", {}).items()
        }
        self._challenges: dict[str, tuple[datetime, int]] = {}  # id -> (expires, attempts)
        self._failures: deque[datetime] = deque()
        self._locked_until: datetime | None = None

    @property
    def mfa_enabled(self) -> bool:
        return bool(self._state.get("totp_secret"))

    async def user_for(self, session_token: str | None) -> User | None:
        if not session_token:
            return None
        digest = _digest(session_token)
        expires = self._sessions.get(digest)
        if expires is None or expires <= self._clock.now():
            if self._sessions.pop(digest, None) is not None:
                self._save_sessions()
            return None
        return User(id=OWNER_ID, display_name=self._username, mfa_enabled=self.mfa_enabled)

    async def login(self, username: str, password: str) -> LoginResult:
        now = self._clock.now()
        if self._locked_until is not None and now < self._locked_until:
            return LoginResult(mfa_required=False, retry_after_seconds=self._retry_after(now))
        right_user = secrets.compare_digest(username.strip().lower(), self._username.lower())
        right_password = self._check_password(password if right_user else "", right_user)
        if not (right_user and right_password):
            return self._failed(now)
        self._failures.clear()
        if self.mfa_enabled:
            challenge = secrets.token_urlsafe(16)
            self._challenges[challenge] = (now + CHALLENGE_TTL, 0)
            return LoginResult(mfa_required=True, challenge_id=challenge)
        return LoginResult(mfa_required=False, session_token=self._new_session(now))

    async def verify_mfa(self, challenge_id: str, code: str) -> str | None:
        now = self._clock.now()
        entry = self._challenges.get(challenge_id)
        if entry is None or entry[0] <= now:
            self._challenges.pop(challenge_id, None)
            return None
        expires, attempts = entry
        if attempts + 1 >= MAX_CODE_ATTEMPTS:
            self._challenges.pop(challenge_id, None)  # last try: afterwards sign in again
        else:
            self._challenges[challenge_id] = (expires, attempts + 1)
        step = self._matching_step(self._state["totp_secret"], code, now)
        if step is None or step <= self._state.get("last_step", -1):  # wrong or replayed
            return None
        self._state["last_step"] = step
        self._save()
        self._challenges.pop(challenge_id, None)
        return self._new_session(now)

    async def enroll_mfa(self) -> str:
        self._pending_secret = pyotp.random_base32()
        return pyotp.TOTP(self._pending_secret).provisioning_uri(
            name=self._username, issuer_name="HelpMate"
        )

    async def confirm_mfa(self, code: str) -> bool:
        if self._pending_secret is None:
            return False
        step = self._matching_step(self._pending_secret, code, self._clock.now())
        if step is None:
            return False
        self._state.update(totp_secret=self._pending_secret, last_step=step)
        self._pending_secret = None
        self._save()
        log.info("two-step verification turned on for %s", self._username)
        return True

    async def logout(self, session_token: str | None) -> None:
        if session_token and self._sessions.pop(_digest(session_token), None) is not None:
            self._save_sessions()

    # --- helpers ---------------------------------------------------------------------------

    def _check_password(self, password: str, right_user: bool) -> bool:
        try:
            return self._hasher.verify(self._password_hash if right_user else _DUMMY_HASH, password)
        except VerificationError:
            return False

    def _failed(self, now: datetime) -> LoginResult:
        self._failures.append(now)
        while self._failures and now - self._failures[0] > FAILURE_WINDOW:
            self._failures.popleft()
        if len(self._failures) >= MAX_FAILURES:
            self._locked_until = now + LOCKOUT
            self._failures.clear()
            log.warning("sign-in locked for %s after %d failures", LOCKOUT, MAX_FAILURES)
            return LoginResult(mfa_required=False, retry_after_seconds=self._retry_after(now))
        return LoginResult(mfa_required=False)

    def _retry_after(self, now: datetime) -> int:
        assert self._locked_until is not None
        return max(1, math.ceil((self._locked_until - now).total_seconds()))

    def _new_session(self, now: datetime) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions = {d: e for d, e in self._sessions.items() if e > now}  # drop expired
        self._sessions[_digest(token)] = now + self._session_ttl
        self._save_sessions()
        return token

    def _save_sessions(self) -> None:
        self._state["sessions"] = {d: e.isoformat() for d, e in self._sessions.items()}
        self._save()

    @staticmethod
    def _matching_step(secret: str, code: str, now: datetime) -> int | None:
        if not (len(code) == 6 and code.isdigit()):
            return None
        totp = pyotp.TOTP(secret)
        current = int(now.timestamp()) // STEP_SECONDS
        for step in (current - 1, current, current + 1):
            if secrets.compare_digest(totp.at(step * STEP_SECONDS), code):
                return step
        return None

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self._state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def _save(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state), encoding="utf-8")
        tmp.replace(self._state_file)
