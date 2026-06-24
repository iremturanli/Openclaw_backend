"""Authentication use-cases: register, login, token refresh.

Passwords are hashed (bcrypt) and never stored or returned in clear. Tokens are
signed JWTs. On register a paired loyalty ``guest`` row is created so the new
account immediately has a (zero-balance) loyalty identity.
"""

from __future__ import annotations

import uuid

from app.core import security
from app.db.models.user import UserORM
from app.repositories.user_repo import UserRepository


class EmailAlreadyRegisteredError(Exception):
    """Raised when registering an email that already exists."""


class InvalidCredentialsError(Exception):
    """Raised when login email/password do not match."""


class TokenPair:
    """Access + refresh token pair."""

    def __init__(self, access: str, refresh: str) -> None:
        self.access = access
        self.refresh = refresh


class AuthService:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        phone_number: str | None = None,
    ) -> tuple[UserORM, TokenPair]:
        existing = await self._users.get_by_email(email)
        if existing is not None:
            raise EmailAlreadyRegisteredError(email)
        user = await self._users.create(
            user_id=f"usr_{uuid.uuid4().hex[:24]}",
            email=email,
            hashed_password=security.hash_password(password),
            full_name=full_name,
            phone_number=phone_number,
        )
        return user, self._issue(user)

    async def login(self, *, email: str, password: str) -> tuple[UserORM, TokenPair]:
        user = await self._users.get_by_email(email)
        if user is None or not security.verify_password(
            password, user.hashed_password
        ):
            raise InvalidCredentialsError()
        return user, self._issue(user)

    def _issue(self, user: UserORM) -> TokenPair:
        return TokenPair(
            access=security.create_token(
                user_id=user.id, guest_id=user.guest_id, token_type="access"
            ),
            refresh=security.create_token(
                user_id=user.id, guest_id=user.guest_id, token_type="refresh"
            ),
        )

    async def update_profile(
        self,
        user: UserORM,
        *,
        full_name: str | None = None,
        phone_number: str | None = None,
    ) -> UserORM:
        return await self._users.update_profile(
            user,
            full_name=full_name,
            phone_number=phone_number,
        )
