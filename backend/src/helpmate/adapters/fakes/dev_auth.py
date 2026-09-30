from __future__ import annotations

from helpmate.domain.models import OWNER_ID, LoginResult, User

DEV_TOKEN = "dev-session"


class DevAuth:
    """HELPMATE_AUTH=dev: every request is the owner. Never use it with Tailscale Funnel."""

    name = "dev"
    is_fake = True

    def __init__(self) -> None:
        self._owner = User(id=OWNER_ID, display_name="Owner (dev)", mfa_enabled=False)

    async def user_for(self, session_token: str | None) -> User | None:
        return self._owner

    async def login(self, username: str, password: str) -> LoginResult:
        return LoginResult(mfa_required=False, session_token=DEV_TOKEN)

    async def verify_mfa(self, challenge_id: str, code: str) -> str | None:
        return DEV_TOKEN

    async def enroll_mfa(self) -> str:
        # a well-known example secret: dev auth protects nothing (the routes refuse enrolment)
        return "otpauth://totp/HelpMate:owner?secret=JBSWY3DPEHPK3PXP&issuer=HelpMate"

    async def confirm_mfa(self, code: str) -> bool:
        return False  # dev auth can't turn two-step verification on

    async def logout(self, session_token: str | None) -> None:
        return None
