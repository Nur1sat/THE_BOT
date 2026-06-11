from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from xau_signal_bot.bot.config import Settings
from xau_signal_bot.database.models import Base, SignalRecord, SourceResultRecord, User, UserSettings
from xau_signal_bot.services.models import SignalResult, UserSignalSettings


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = create_async_engine(settings.database_url, future=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        if self.settings.default_alerts_enabled:
            await self.enable_default_alert_preferences_for_existing_users()

    async def close(self) -> None:
        await self.engine.dispose()

    async def get_or_create_user(
        self,
        telegram_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
    ) -> tuple[User, UserSettings]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(User).options(selectinload(User.settings)).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                user = User(telegram_id=telegram_id, username=username, first_name=first_name)
                db_settings = UserSettings(
                    timeframe=self.settings.default_timeframe,
                    minimum_confidence=self.settings.default_minimum_confidence,
                    alerts_enabled=self.settings.default_alerts_enabled,
                    risk_percentage=self.settings.default_risk_percentage,
                    news_filter_enabled=self.settings.default_news_filter_enabled,
                )
                user.settings = db_settings
                session.add(user)
            else:
                user.username = username
                user.first_name = first_name
                if not user.settings:
                    db_settings = UserSettings(
                        timeframe=self.settings.default_timeframe,
                        minimum_confidence=self.settings.default_minimum_confidence,
                        alerts_enabled=self.settings.default_alerts_enabled,
                        risk_percentage=self.settings.default_risk_percentage,
                        news_filter_enabled=self.settings.default_news_filter_enabled,
                    )
                    user.settings = db_settings
                else:
                    db_settings = user.settings
            await session.commit()
            return user, db_settings

    async def get_user_settings(self, telegram_id: int) -> UserSignalSettings:
        user, db_settings = await self.get_or_create_user(telegram_id)
        del user
        return self.to_signal_settings(db_settings)

    async def update_user_settings(self, telegram_id: int, updates: dict[str, object]) -> UserSignalSettings:
        async with self.session_factory() as session:
            result = await session.execute(
                select(User).options(selectinload(User.settings)).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                user = User(telegram_id=telegram_id)
                db_settings = UserSettings()
                user.settings = db_settings
                session.add(user)
                await session.flush()
            elif not user.settings:
                db_settings = UserSettings(user_id=user.id)
                user.settings = db_settings
            else:
                db_settings = user.settings
            for key, value in updates.items():
                setattr(db_settings, key, value)
            await session.commit()
            return self.to_signal_settings(db_settings)

    async def save_signal(self, result: SignalResult, telegram_id: int | None = None) -> SignalRecord:
        async with self.session_factory() as session:
            user_id = None
            if telegram_id is not None:
                user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
                user = user_result.scalar_one_or_none()
                user_id = user.id if user else None
            signal = SignalRecord(
                user_id=user_id,
                decision=result.decision.value,
                confidence=result.confidence,
                confidence_label=result.confidence_label,
                payload=result.to_record(),
            )
            session.add(signal)
            await session.flush()
            for source in result.source_results:
                session.add(
                    SourceResultRecord(
                        signal_id=signal.id,
                        name=source.name,
                        ok=source.ok,
                        direction=source.direction.value,
                        summary=source.summary,
                        error=source.error,
                        payload=source.to_dict(),
                    )
                )
            await session.commit()
            await session.refresh(signal)
            return signal

    async def get_alert_users(self) -> list[tuple[User, UserSettings]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(User, UserSettings)
                .join(UserSettings, UserSettings.user_id == User.id)
                .where(UserSettings.alerts_enabled.is_(True))
            )
            return list(result.all())

    async def update_alert_state(self, settings_id: int, key: str) -> None:
        async with self.session_factory() as session:
            result = await session.execute(select(UserSettings).where(UserSettings.id == settings_id))
            settings = result.scalar_one_or_none()
            if settings:
                settings.last_alert_key = key
                settings.last_alert_at = datetime.now(timezone.utc)
                await session.commit()

    async def enable_default_alert_preferences_for_existing_users(self) -> None:
        async with self.session_factory() as session:
            result = await session.execute(select(UserSettings))
            for settings in result.scalars():
                settings.alerts_enabled = True
                if settings.timeframe not in {"1m", "3m", "5m"}:
                    settings.timeframe = self.settings.default_timeframe
                if settings.minimum_confidence == 75 and self.settings.default_minimum_confidence < 75:
                    settings.minimum_confidence = self.settings.default_minimum_confidence
                if settings.minimum_confidence < self.settings.default_minimum_confidence:
                    settings.minimum_confidence = self.settings.default_minimum_confidence
            await session.commit()

    @staticmethod
    def to_signal_settings(settings: UserSettings) -> UserSignalSettings:
        return UserSignalSettings(
            timeframe=settings.timeframe,
            minimum_confidence=settings.minimum_confidence,
            alerts_enabled=settings.alerts_enabled,
            risk_percentage=settings.risk_percentage,
            news_filter_enabled=settings.news_filter_enabled,
        )
