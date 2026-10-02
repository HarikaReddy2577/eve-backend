import enum
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, ForeignKey, Numeric, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

class BookingStatus(str, enum.Enum):
    PENDING = "PENDING"; CONFIRMED = "CONFIRMED"; FAILED = "FAILED"; CANCELLED = "CANCELLED"

class PaymentStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"; FAILED = "FAILED"

def now(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

class Centre(Base):
    __tablename__ = "centres"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    location: Mapped[str] = mapped_column(String(150), index=True)
    offerings: Mapped[list["CentreTest"]] = relationship(back_populates="centre")

class DiagnosticTest(Base):
    __tablename__ = "diagnostic_tests"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)

class CentreTest(Base):
    __tablename__ = "centre_tests"
    __table_args__ = (UniqueConstraint("centre_id", "test_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centres.id"))
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id"))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    centre: Mapped["Centre"] = relationship(back_populates="offerings")
    test: Mapped["DiagnosticTest"] = relationship()

class Slot(Base):
    __tablename__ = "slots"
    __table_args__ = (UniqueConstraint("centre_id", "start_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centres.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int] = mapped_column(default=5)

class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id"))
    centre_id: Mapped[int] = mapped_column(ForeignKey("centres.id"))
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), index=True)
    appointment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[BookingStatus] = mapped_column(default=BookingStatus.PENDING, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class BookingEvent(Base):
    __tablename__ = "booking_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[PaymentStatus]
    failure_reason: Mapped[str | None] = mapped_column(String(50))
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)