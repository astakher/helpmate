# Stand-in for Workstream B - not part of the Part C deliverable
"""Two-step verification enrolment: the dev login refuses it instead of pretending (Sep 30)."""

from __future__ import annotations

from helpmate.domain.models import OWNER_ID, LoginResult, User


async def test_dev_auth_refuses_enrolment_instead_of_handing_out_an_example_secret(client):
    enroll = await client.post("/api/auth/mfa/enroll")
    confirm = await client.post("/api/auth/mfa/enroll/confirm", json={"code": "123456"})
    assert enroll.status_code == confirm.status_code == 409
    assert "HELPMATE_AUTH=totp" in enroll.json()["detail"]
    assert (await client.get("/api/me")).json()["mfa_enabled"] is False


class TotpStub:
    """Stands in for B's real TOTP auth: the secret is fixed, the right code is 246810."""

    name, is_fake = "totp-stub", False

    def __init__(self) -> None:
        self.user = User(id=OWNER_ID, display_name="Owner", mfa_enabled=False)

    async def user_for(self, token):
        return self.user

    async def login(self, username, password):
        return LoginResult(mfa_required=self.user.mfa_enabled, session_token="t")

    async def verify_mfa(self, challenge_id, code):
        return "t" if code == "246810" else None

    async def enroll_mfa(self):
        return "otpauth://totp/HelpMate:owner?secret=NEWSECRETFORTEST&issuer=HelpMate"

    async def confirm_mfa(self, code):
        if code != "246810":
            return False
        self.user = self.user.model_copy(update={"mfa_enabled": True})
        return True

    async def logout(self, token):
        return None


async def test_real_auth_enrols_only_after_a_matching_code(client, container):
    container.auth = TotpStub()
    enroll = await client.post("/api/auth/mfa/enroll")
    assert enroll.status_code == 200 and "NEWSECRETFORTEST" in enroll.json()["otpauth_uri"]
    assert (await client.get("/api/me")).json()["mfa_enabled"] is False  # scanning isn't enough

    wrong = await client.post("/api/auth/mfa/enroll/confirm", json={"code": "111111"})
    assert wrong.status_code == 400 and "newest code" in wrong.json()["detail"]
    bad_shape = await client.post("/api/auth/mfa/enroll/confirm", json={"code": "12ab"})
    assert bad_shape.status_code == 422

    ok = await client.post("/api/auth/mfa/enroll/confirm", json={"code": "246810"})
    assert ok.status_code == 204
    assert (await client.get("/api/me")).json()["mfa_enabled"] is True
