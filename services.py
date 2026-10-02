from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import Session
import models
from models import BookingStatus as S

HOLD_MINUTES = 15
ALLOWED = {
    S.PENDING: {S.CONFIRMED, S.FAILED, S.CANCELLED},
    S.CONFIRMED: {S.CANCELLED},
    S.FAILED: set(),
    S.CANCELLED: set(),
}

def utcnow(): return datetime.now(timezone.utc)

def transition(db: Session, b: models.Booking, new: S, reason: str = ""):
    if new not in ALLOWED[b.status]:
        raise HTTPException(409, f"Cannot move booking from {b.status.value} to {new.value}")
    db.add(models.BookingEvent(booking_id=b.id, from_status=b.status.value,
                               to_status=new.value, reason=reason))
    b.status = new

def active_count(db: Session, slot_id: int) -> int:
    """Bookings currently occupying the slot: CONFIRMED + unexpired PENDING holds."""
    return db.scalar(select(func.count()).select_from(models.Booking).where(
        models.Booking.slot_id == slot_id,
        or_(models.Booking.status == S.CONFIRMED,
            and_(models.Booking.status == S.PENDING,
                 models.Booking.expires_at > utcnow())))) or 0

def expire_if_needed(db: Session, b: models.Booking):
    if b.status == S.PENDING and b.expires_at and b.expires_at <= utcnow():
        transition(db, b, S.CANCELLED, "payment hold expired")
        db.commit()