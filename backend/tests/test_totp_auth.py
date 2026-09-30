# Stand-in for Workstream B - not part of the Part C deliverable
"""HELPMATE_AUTH=totp: password + TOTP, lockouts, replay protection, persistence, cookies."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pyotp
import pytest
from argon2 import PasswordHasher

from helpmate.adapters.clock import FakeClock
from helpmate.adapters.totp_auth import TotpAuth

TZ = ZoneInfo("America/Toronto")
PASSWORD = "correct horse battery staple"
HASH = PasswordHasher().hash(PASSWORD)


def secret_of(uri: str) -> str:
    return uri.split("secret=")[1].split("&")[0]


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 10, 5, 12, 0, tzinfo=TZ))


@pytest.fixture
def auth(tmp_path, clock):
    return TotpAuth("aman", HASH, tmp_path / "auth.json", clock)


def code(secret: str, clock: FakeClock) -> str:
    return pyotp.TOTP(secret).at(clock.now())


async def enable_2fa(auth: TotpAuth, clock: FakeClock) -> str:
    secret = secret_of(await auth.enroll_mfa())
    assert await auth.confirm_mfa(code(secret, clock))
    clock.advance(seconds=30)  # the confirm code is used up; login needs the next one
    return secret


async def test_password_login_session_and_logout(auth, clock):
    assert (await auth.login("aman", "wrong password")).session_token is None
    result = await auth.login("  AMAN ", PASSWORD)  # username is case/space-insensitive
    assert not result.mfa_required and result.session_token
    user = await auth.user_for(result.session_token)
    assert user and user.display_name == "aman" and not user.mfa_enabled
    await auth.logout(result.session_token)
    assert await auth.user_for(result.session_token) is None
    assert await auth.user_for(None) is None and await auth.user_for("forged") is None


async def test_sessions_expire(auth, clock):
    token = (await auth.login("aman", PASSWORD)).session_token
    clock.advance(days=7, seconds=1)
    assert await auth.user_for(token) is None


async def test_five_failures_lock_sign_in_for_15_minutes(auth, clock):
    for _ in range(4):
        assert (await auth.login("aman", "nope")).retry_after_seconds is None
    locked = await auth.login("aman", "nope")
    assert locked.retry_after_seconds == 15 * 60
    assert (await auth.login("aman", PASSWORD)).retry_after_seconds  # even the right password
    clock.advance(minutes=15, seconds=1)
    assert (await auth.login("aman", PASSWORD)).session_token


async def test_enrolment_only_counts_after_a_matching_code(tmp_path, auth, clock):
    uri = await auth.enroll_mfa()
    assert uri.startswith("otpauth://totp/HelpMate:aman?") and "issuer=HelpMate" in uri
    assert not auth.mfa_enabled
    assert not await auth.confirm_mfa("000000")
    assert not auth.mfa_enabled
    assert await auth.confirm_mfa(code(secret_of(uri), clock))
    assert auth.mfa_enabled
    reloaded = TotpAuth("aman", HASH, tmp_path / "auth.json", clock)  # survives a restart
    assert reloaded.mfa_enabled


async def test_login_with_2fa_rejects_replay_and_wrong_codes(auth, clock):
    secret = await enable_2fa(auth, clock)
    first = await auth.login("aman", PASSWORD)
    assert first.mfa_required and first.challenge_id and first.session_token is None
    right = code(secret, clock)
    assert await auth.verify_mfa(first.challenge_id, "123456") is None
    token = await auth.verify_mfa(first.challenge_id, right)
    assert token and (await auth.user_for(token)).mfa_enabled

    again = await auth.login("aman", PASSWORD)
    assert await auth.verify_mfa(again.challenge_id, right) is None  # the same code twice: no
    clock.advance(seconds=30)
    assert await auth.verify_mfa(again.challenge_id, code(secret, clock))  # the next code: yes


async def test_a_challenge_allows_five_codes_and_expires(auth, clock):
    secret = await enable_2fa(auth, clock)
    challenge = (await auth.login("aman", PASSWORD)).challenge_id
    for _ in range(5):
        assert await auth.verify_mfa(challenge, "000000") is None
    assert await auth.verify_mfa(challenge, code(secret, clock)) is None  # used up: sign in again

    late = (await auth.login("aman", PASSWORD)).challenge_id
    clock.advance(minutes=5, seconds=1)
    assert await auth.verify_mfa(late, code(secret, clock)) is None


async def test_codes_from_a_slightly_wrong_phone_clock_still_work(auth, clock):
    secret = await enable_2fa(auth, clock)
    clock.advance(seconds=30)  # (the step before now was used to confirm, so it'd be a replay)
    challenge = (await auth.login("aman", PASSWORD)).challenge_id
    drifted = pyotp.TOTP(secret).at(clock.now() - timedelta(seconds=30))  # phone 30 s behind
    assert await auth.verify_mfa(challenge, drifted)
    too_far = pyotp.TOTP(secret).at(clock.now() + timedelta(seconds=90))  # 3 steps: rejected
    assert await auth.verify_mfa((await auth.login("aman", PASSWORD)).challenge_id, too_far) is None


def test_bad_configuration_is_explained(tmp_path, clock):
    with pytest.raises(ValueError, match="set_password.py"):
        TotpAuth("aman", "", tmp_path / "a.json", clock)
    with pytest.raises(ValueError, match="argon2"):
        TotpAuth("aman", "plain-text-password", tmp_path / "a.json", clock)


async def test_api_status_codes_and_cookie_flags(app, container, clock, tmp_path):
    container.auth = TotpAuth("aman", HASH, tmp_path / "auth.json", clock)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://helpmate.test") as c:
        assert (await c.get("/api/me")).status_code == 401  # no dev auto-login any more
        wrong = await c.post("/api/auth/login", json={"username": "aman", "password": "x"})
        assert wrong.status_code == 401 and "Wrong username or password" in wrong.json()["detail"]

        ok = await c.post("/api/auth/login", json={"username": "aman", "password": PASSWORD})
        cookie = ok.headers["set-cookie"].lower()
        assert ok.status_code == 200 and "httponly" in cookie and "samesite=strict" in cookie
        assert "secure" in cookie  # served over HTTPS (as behind tailscale serve)
        assert (await c.get("/api/me")).json()["display_name"] == "aman"

        for _ in range(5):
            await c.post("/api/auth/login", json={"username": "aman", "password": "x"})
        locked = await c.post("/api/auth/login", json={"username": "aman", "password": PASSWORD})
        assert locked.status_code == 429 and locked.headers["retry-after"] == "900"
        assert "15 minutes" in locked.json()["detail"]

    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as plain:
        clock.advance(minutes=16)
        local = await plain.post("/api/auth/login", json={"username": "aman", "password": PASSWORD})
        assert "secure" not in local.headers["set-cookie"].lower()  # plain http on this machine
