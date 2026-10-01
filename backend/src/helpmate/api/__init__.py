from fastapi import APIRouter

from helpmate.api.routes import (
    audit,
    auth,
    chat,
    health,
    memory,
    organize,
    plan,
    proposals,
    push,
    settings,
    tools,
    voice,
)

api_router = APIRouter(prefix="/api")
for module in (
    health,
    chat,
    proposals,
    tools,
    organize,
    plan,
    memory,
    voice,
    push,
    settings,
    audit,
):
    api_router.include_router(module.router)
api_router.include_router(auth.router)
api_router.include_router(auth.me_router)
