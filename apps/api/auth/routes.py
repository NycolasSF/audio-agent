from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.auth.jwt import create_access_token
from apps.api.auth.models import (
    LoginBody,
    RegisterBody,
    TokenResponse,
    UserOut,
    UsageRecord,
    UsageResponse,
)
from core import settings
from core.services.user_service import authenticate_user, create_user

router = APIRouter(tags=["auth"])


def _user_repo():
    from apps.api import state
    return state.user_repo


@router.post("/auth/register", response_model=UserOut, status_code=201)
async def register(body: RegisterBody):
    user_repo = _user_repo()
    try:
        user = create_user(user_repo, str(body.email), body.password, body.name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return UserOut(
        id=user["id"],
        email=user["email"],
        name=user.get("name", ""),
        quota_minutes=user["quota_minutes"],
        usage_minutes=0.0,
    )


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginBody):
    user_repo = _user_repo()
    user = authenticate_user(user_repo, str(body.email), body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.get("is_active"):
        raise HTTPException(status_code=403, detail="Conta desativada")
    token = create_access_token(user["id"], user["email"])
    return TokenResponse(
        access_token=token,
        expires_in=settings.JWT_EXPIRE_DAYS * 86400,
    )


# /me and /usage são definidos em main.py após deps estarem disponíveis.
# to avoid importing deps.py before it exists during incremental build.
# Placed here for organization via include_router in main.py.
