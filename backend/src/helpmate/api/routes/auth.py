"""Auth endpoints. The flow is Workstream B's; with HELPMATE_AUTH=dev every call succeeds."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from helpmate.api.deps import SESSION_COOKIE, ContainerDep, CurrentUser
from helpmate.api.schemas.bodies import LoginIn, LoginOut, MfaConfirmIn, MfaEnrollOut, MfaIn
from helpmate.container import Container
from helpmate.domain.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

DEV_AUTH_NO_MFA = (
    "Two-step verification needs the real login (HELPMATE_AUTH=totp, Workstream B). The dev login "
    "signs everyone in automatically, so a code would protect nothing."
)


def _require_real_auth(container: Container) -> None:
    # Stand-in for Workstream B - not part of the Part C deliverable. Refusing here (instead of
    # handing out the dev example secret) stops the Settings page looking as if 2FA were on.
    if container.auth.is_fake:
        raise HTTPException(status.HTTP_409_CONFLICT, DEV_AUTH_NO_MFA)


def _set_session(request: Request, response: Response, token: str) -> None:
    # HttpOnly + SameSite=Strict always; Secure when the request came over HTTPS. Behind
    # `tailscale serve`, uvicorn's proxy headers (from 127.0.0.1) make the scheme "https".
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )


@router.post(
    "/login",
    response_model=LoginOut,
    responses={401: {"description": "wrong username or password"}, 429: {"description": "locked"}},
)
async def login(
    body: LoginIn, request: Request, response: Response, container: ContainerDep
) -> LoginOut:
    result = await container.auth.login(body.username, body.password)
    if result.retry_after_seconds:
        minutes = max(1, round(result.retry_after_seconds / 60))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed sign-ins. Try again in {minutes} minute{'s' * (minutes != 1)}.",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
    if not result.session_token and not result.mfa_required:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password.")
    if result.session_token:
        _set_session(request, response, result.session_token)
    return LoginOut(mfa_required=result.mfa_required, challenge_id=result.challenge_id)


@router.post("/mfa", status_code=status.HTTP_204_NO_CONTENT)
async def verify_mfa(
    body: MfaIn, request: Request, response: Response, container: ContainerDep
) -> None:
    token = await container.auth.verify_mfa(body.challenge_id, body.code)
    if token is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "That code didn't work. Use the newest code; after 5 tries, sign in again.",
        )
    _set_session(request, response, token)


@router.post(
    "/mfa/enroll",
    response_model=MfaEnrollOut,
    responses={409: {"description": "the dev login can't enable two-step verification"}},
)
async def enroll_mfa(_: CurrentUser, container: ContainerDep) -> MfaEnrollOut:
    _require_real_auth(container)
    return MfaEnrollOut(otpauth_uri=await container.auth.enroll_mfa())


# Stand-in for Workstream B - not part of the Part C deliverable (docs/part-c.md §7)
@router.post(
    "/mfa/enroll/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"description": "the code doesn't match"},
        409: {"description": "the dev login can't enable two-step verification"},
    },
)
async def confirm_mfa(body: MfaConfirmIn, _: CurrentUser, container: ContainerDep) -> None:
    """Finish enrolment with the first code from the authenticator app. Until this succeeds,
    two-step verification is NOT on (a scanned QR code alone changes nothing)."""
    _require_real_auth(container)
    if not await container.auth.confirm_mfa(body.code):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That code doesn't match. Check your phone's clock is set automatically, then use the "
            "newest code.",
        )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, container: ContainerDep) -> None:
    await container.auth.logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


me_router = APIRouter(tags=["auth"])


@me_router.get("/me", response_model=User)
async def me(user: CurrentUser) -> User:
    return user
