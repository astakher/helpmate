"""Auth endpoints. The flow is Workstream B's; with HELPMATE_AUTH=dev every call succeeds."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from helpmate.api.deps import SESSION_COOKIE, ContainerDep, CurrentUser
from helpmate.api.schemas.bodies import LoginIn, LoginOut, MfaEnrollOut, MfaIn
from helpmate.domain.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session(response: Response, token: str) -> None:
    # TODO(B): secure=True once served over HTTPS (Tailscale); SameSite=Strict + HttpOnly always
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", path="/")


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn, response: Response, container: ContainerDep) -> LoginOut:
    result = await container.auth.login(body.username, body.password)
    if result.session_token:
        _set_session(response, result.session_token)
    return LoginOut(mfa_required=result.mfa_required, challenge_id=result.challenge_id)


@router.post("/mfa", status_code=status.HTTP_204_NO_CONTENT)
async def verify_mfa(body: MfaIn, response: Response, container: ContainerDep) -> None:
    token = await container.auth.verify_mfa(body.challenge_id, body.code)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid code")
    _set_session(response, token)


@router.post("/mfa/enroll", response_model=MfaEnrollOut)
async def enroll_mfa(_: CurrentUser, container: ContainerDep) -> MfaEnrollOut:
    return MfaEnrollOut(otpauth_uri=await container.auth.enroll_mfa())


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, container: ContainerDep) -> None:
    await container.auth.logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


me_router = APIRouter(tags=["auth"])


@me_router.get("/me", response_model=User)
async def me(user: CurrentUser) -> User:
    return user
