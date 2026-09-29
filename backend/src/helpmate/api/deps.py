from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from helpmate.container import Container
from helpmate.domain.models import User

SESSION_COOKIE = "helpmate_session"


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


async def current_user(request: Request, container: ContainerDep) -> User:
    user = await container.auth.user_for(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
