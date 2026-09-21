"""Write side — normalised, transactional PostgreSQL access.

Everything here is used by `application/commands/` only. The ORM ↔ domain
translation stays inside these classes so the domain never sees SQLAlchemy.

None of these methods reads through the cache, by design: a command that acted
on a cached profile could persist a decision made from a stale row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from identity_app.modules.identity.domain.capabilities import Capability
from identity_app.modules.identity.domain.entities import (
    OtpCode,
    RefreshToken,
    User,
    UserLanguage,
    UserRole,
    UserRoleChange,
    UserStatus,
    UserStatusChange,
)
from identity_app.modules.identity.infra import models as orm


def _user_to_domain(row: orm.UserModel) -> User:
    return User(
        id=row.id,
        phone=row.phone,
        email=row.email,
        full_name=row.full_name,
        language=UserLanguage(row.language),
        photo_url=row.photo_url,
        password_hash=row.password_hash,
        role=UserRole(row.role),
        status=UserStatus(row.status),
        requested_role=UserRole(row.requested_role) if row.requested_role else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyUserWriteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def save(self, user: User) -> User:
        row: orm.UserModel | None = await self._session.get(orm.UserModel, user.id)
        now = datetime.now(UTC)
        if row is None:
            row = orm.UserModel(
                id=user.id,
                phone=user.phone,
                email=user.email,
                full_name=user.full_name,
                language=user.language.value,
                photo_url=user.photo_url,
                password_hash=user.password_hash,
                role=user.role.value,
                status=user.status.value,
                requested_role=user.requested_role.value if user.requested_role else None,
                created_at=user.created_at or now,
                updated_at=now,
            )
            self._session.add(row)
        else:
            row.full_name = user.full_name
            row.email = user.email
            row.language = user.language.value
            row.photo_url = user.photo_url
            row.password_hash = user.password_hash
            row.role = user.role.value
            row.status = user.status.value
            row.requested_role = user.requested_role.value if user.requested_role else None
            row.updated_at = now
        await self._session.flush()
        user.updated_at = now
        return user

    async def find_by_id(self, user_id: UUID) -> User | None:
        # `session.get()` would answer from the identity map. Combined with
        # `expire_on_commit=False` on the session factory, that can hand back a
        # row from before another request activated the account — the OTP flow
        # would then re-run its "first verification" branch and re-emit
        # `user.registered`. `populate_existing` forces a real SELECT.
        result = await self._session.execute(
            select(orm.UserModel)
            .where(orm.UserModel.id == user_id)
            .execution_options(populate_existing=True),
        )
        row = result.scalar_one_or_none()
        return None if row is None else _user_to_domain(row)

    async def find_by_phone(self, phone: str) -> User | None:
        result = await self._session.execute(
            select(orm.UserModel)
            .where(orm.UserModel.phone == phone)
            .execution_options(populate_existing=True),
        )
        row = result.scalar_one_or_none()
        return None if row is None else _user_to_domain(row)

    async def find_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(orm.UserModel)
            .where(orm.UserModel.email == email)
            .execution_options(populate_existing=True),
        )
        row = result.scalar_one_or_none()
        return None if row is None else _user_to_domain(row)

    async def record_status_change(self, change: UserStatusChange) -> None:
        self._session.add(
            orm.UserStatusHistoryModel(
                id=change.id,
                user_id=change.user_id,
                from_status=change.from_status.value if change.from_status else None,
                to_status=change.to_status.value,
                reason=change.reason,
                changed_by=change.changed_by,
                changed_at=change.changed_at,
            ),
        )
        await self._session.flush()

    async def record_role_change(self, change: UserRoleChange) -> None:
        self._session.add(
            orm.UserRoleHistoryModel(
                id=change.id,
                user_id=change.user_id,
                from_role=change.from_role.value if change.from_role else None,
                to_role=change.to_role.value if change.to_role else None,
                requested_role=change.requested_role.value if change.requested_role else None,
                reason=change.reason,
                changed_by=change.changed_by,
                changed_at=change.changed_at,
            ),
        )
        await self._session.flush()


def _capability_to_domain(row: orm.UserCapabilityModel) -> Capability:
    return Capability(
        user_id=row.user_id,
        service=row.service,
        capability_type=row.capability_type,
        access_status=row.access_status,
        operational_status=row.operational_status,
        status_source=row.status_source,
        actions=tuple(row.actions or ()),
        projection_version=row.projection_version,
        last_event_id=row.last_event_id,
        updated_at=row.updated_at,
        created_at=row.created_at,
    )


class SqlAlchemyCapabilityWriteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID, service: str, capability_type: str) -> Capability | None:
        result = await self._session.execute(
            select(orm.UserCapabilityModel)
            .where(
                orm.UserCapabilityModel.user_id == user_id,
                orm.UserCapabilityModel.service == service,
                orm.UserCapabilityModel.capability_type == capability_type,
            )
            .execution_options(populate_existing=True),
        )
        row = result.scalar_one_or_none()
        return None if row is None else _capability_to_domain(row)

    async def upsert(
        self,
        *,
        user_id: UUID,
        service: str,
        capability_type: str,
        access_status: str | None = None,
        operational_status: str | None = None,
        status_source: str | None = None,
        actions: list[str] | None = None,
        projection_version: int | None = None,
        last_event_id: str | None = None,
    ) -> Capability:
        result = await self._session.execute(
            select(orm.UserCapabilityModel).where(
                orm.UserCapabilityModel.user_id == user_id,
                orm.UserCapabilityModel.service == service,
                orm.UserCapabilityModel.capability_type == capability_type,
            ),
        )
        row = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if row is None:
            row = orm.UserCapabilityModel(
                user_id=user_id,
                service=service,
                capability_type=capability_type,
                access_status=access_status or "requested",
                operational_status=operational_status or "unknown",
                status_source=status_source or "diddifreeid",
                actions=actions or [],
                projection_version=projection_version or 1,
                last_event_id=last_event_id,
                created_at=now,
                updated_at=now,
            )
            self._session.add(row)
        else:
            if access_status is not None:
                row.access_status = access_status
            if operational_status is not None:
                row.operational_status = operational_status
            if status_source is not None:
                row.status_source = status_source
            if actions is not None:
                row.actions = actions
            if projection_version is not None:
                row.projection_version = projection_version
            if last_event_id is not None:
                row.last_event_id = last_event_id
            row.updated_at = now
        await self._session.flush()
        return _capability_to_domain(row)

    async def commit(self) -> None:
        await self._session.commit()


class SqlAlchemyOtpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def save(self, otp: OtpCode) -> OtpCode:
        self._session.add(
            orm.OtpCodeModel(
                id=otp.id,
                phone=otp.phone,
                email=otp.email,
                code_hash=otp.code_hash,
                expires_at=otp.expires_at,
                consumed_at=otp.consumed_at,
                attempts=otp.attempts,
                created_at=otp.created_at,
            ),
        )
        await self._session.flush()
        return otp

    async def find_latest_active(self, phone: str | None, email: str | None) -> OtpCode | None:
        identifier_filter = orm.OtpCodeModel.phone == phone if phone else orm.OtpCodeModel.email == email
        result = await self._session.execute(
            select(orm.OtpCodeModel)
            .where(
                identifier_filter,
                orm.OtpCodeModel.consumed_at.is_(None),
            )
            .order_by(orm.OtpCodeModel.created_at.desc())
            .limit(1)
            .execution_options(populate_existing=True),
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return OtpCode(
            id=row.id,
            phone=row.phone,
            email=row.email,
            code_hash=row.code_hash,
            expires_at=row.expires_at,
            created_at=row.created_at,
            consumed_at=row.consumed_at,
            attempts=row.attempts,
        )

    async def register_attempt(self, otp_id: UUID) -> int:
        """Increment in SQL rather than read-modify-write in Python: two wrong
        codes submitted concurrently must count as two attempts, otherwise the
        brute-force ceiling is trivially bypassed by parallel requests."""
        result = await self._session.execute(
            update(orm.OtpCodeModel)
            .where(orm.OtpCodeModel.id == otp_id)
            .values(attempts=orm.OtpCodeModel.attempts + 1)
            .returning(orm.OtpCodeModel.attempts),
        )
        attempts = result.scalar_one()
        await self._session.flush()
        return attempts

    async def mark_consumed(self, otp_id: UUID) -> None:
        row = await self._session.get(orm.OtpCodeModel, otp_id)
        if row is None or row.consumed_at is not None:
            return
        row.consumed_at = datetime.now(UTC)
        await self._session.flush()


class SqlAlchemyRefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def save(self, token: RefreshToken) -> RefreshToken:
        self._session.add(
            orm.RefreshTokenModel(
                id=token.id,
                user_id=token.user_id,
                token_hash=token.token_hash,
                device_info=token.device_info,
                revoked_at=token.revoked_at,
                expires_at=token.expires_at,
                created_at=token.created_at,
            ),
        )
        await self._session.flush()
        return token

    async def find_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(orm.RefreshTokenModel)
            .where(orm.RefreshTokenModel.token_hash == token_hash)
            .execution_options(populate_existing=True),
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return RefreshToken(
            id=row.id,
            user_id=row.user_id,
            token_hash=row.token_hash,
            device_info=row.device_info,
            revoked_at=row.revoked_at,
            expires_at=row.expires_at,
            created_at=row.created_at,
        )

    async def revoke(self, token_id: UUID) -> None:
        await self._session.execute(
            update(orm.RefreshTokenModel)
            .where(
                orm.RefreshTokenModel.id == token_id,
                orm.RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC)),
        )
        await self._session.flush()

    async def revoke_all_for_user(self, user_id: UUID) -> int:
        result = await self._session.execute(
            update(orm.RefreshTokenModel)
            .where(
                orm.RefreshTokenModel.user_id == user_id,
                orm.RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC)),
        )
        await self._session.flush()
        return result.rowcount or 0
