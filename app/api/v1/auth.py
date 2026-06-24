"""Authentication endpoints: register, login, refresh, me.

Returns a [UserOut] plus a signed access/refresh token pair. The mobile app
stores the tokens securely and sends the access token as a Bearer header; the
loyalty ``guestId`` is taken from the authenticated user, not from the client.
"""

from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_auth_service, get_current_user, get_user_repository
from app.core import security
from app.db.models.user import UserORM
from app.models.auth import (
    AuthResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    UpdateProfileRequest,
    UserOut,
)
from app.repositories.user_repo import UserRepository
from app.services.auth_service import (
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    TokenPair,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _response(user: UserORM, tokens: TokenPair) -> AuthResponse:
    return AuthResponse(
        user=UserOut.model_validate(user),
        access_token=tokens.access,
        refresh_token=tokens.refresh,
    )


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and return tokens",
)
async def register(
    request: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    try:
        user, tokens = await service.register(
            email=request.email,
            password=request.password,
            full_name=request.full_name,
            phone_number=request.phone_number,
        )
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from exc
    return _response(user, tokens)


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Sign in and return tokens",
)
async def login(
    request: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    try:
        user, tokens = await service.login(
            email=request.email, password=request.password
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        ) from exc
    return _response(user, tokens)


@router.post(
    "/refresh",
    response_model=AuthResponse,
    summary="Exchange a refresh token for a fresh token pair",
)
async def refresh(
    request: RefreshRequest,
    users: UserRepository = Depends(get_user_repository),
) -> AuthResponse:
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token.",
    )
    try:
        payload = security.decode_token(request.refresh_token)
    except jwt.PyJWTError as exc:
        raise invalid from exc
    if payload.get("type") != "refresh":
        raise invalid
    user_id = payload.get("sub")
    if not isinstance(user_id, str):
        raise invalid
    user = await users.get_by_id(user_id)
    if user is None:
        raise invalid

    tokens = TokenPair(
        access=security.create_token(
            user_id=user.id, guest_id=user.guest_id, token_type="access"
        ),
        refresh=security.create_token(
            user_id=user.id, guest_id=user.guest_id, token_type="refresh"
        ),
    )
    return _response(user, tokens)


@router.get(
    "/me",
    response_model=UserOut,
    summary="Return the signed-in user",
)
async def me(user: UserORM = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.patch(
    "/me",
    response_model=UserOut,
    summary="Update the signed-in user's profile",
)
async def update_me(
    request: UpdateProfileRequest,
    user: UserORM = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> UserOut:
    updated = await service.update_profile(
        user,
        full_name=request.full_name,
        phone_number=request.phone_number,
    )
    return UserOut.model_validate(updated)
