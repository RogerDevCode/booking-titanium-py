# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "sqlalchemy>=2.0.25"
# ]
# ///
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from f.internal._config import DEFAULT_TIMEZONE
from f.internal._db_sqlalchemy import Base


class ProviderORM(Base):
    __tablename__ = "providers"

    provider_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    specialty: Mapped[str] = mapped_column(String(255), default="Medicina General", nullable=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gcal_calendar_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(100), default=DEFAULT_TIMEZONE, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    services: Mapped[list[ServiceORM]] = relationship(
        back_populates="provider",
        cascade="all, delete-orphan",
    )
    bookings: Mapped[list[BookingORM]] = relationship(
        back_populates="provider",
        cascade="all, delete-orphan",
    )


class ServiceORM(Base):
    __tablename__ = "services"

    service_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_id: Mapped[UUID] = mapped_column(ForeignKey("providers.provider_id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="MXN", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    provider: Mapped[ProviderORM] = relationship(back_populates="services")
    bookings: Mapped[list[BookingORM]] = relationship(
        back_populates="service",
        cascade="all, delete-orphan",
    )


class ClientORM(Base):
    __tablename__ = "clients"

    client_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gcal_calendar_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_fields: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    bookings: Mapped[list[BookingORM]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
    )


class BookingORM(Base):
    __tablename__ = "bookings"

    booking_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_id: Mapped[UUID] = mapped_column(ForeignKey("providers.provider_id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[UUID] = mapped_column(ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False)
    service_id: Mapped[UUID] = mapped_column(ForeignKey("services.service_id", ondelete="CASCADE"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rescheduled_from: Mapped[UUID | None] = mapped_column(ForeignKey("bookings.booking_id"), nullable=True)
    rescheduled_to: Mapped[UUID | None] = mapped_column(ForeignKey("bookings.booking_id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    gcal_provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gcal_client_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gcal_sync_status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    gcal_retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gcal_last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reminder_24h_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reminder_2h_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reminder_30min_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    provider: Mapped[ProviderORM] = relationship(back_populates="bookings")
    client: Mapped[ClientORM] = relationship(back_populates="bookings")
    service: Mapped[ServiceORM] = relationship(back_populates="bookings")
