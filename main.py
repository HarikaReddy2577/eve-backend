import random
from datetime import datetime, date, time, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, Header, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
import models, schemas
from models import BookingStatus, PaymentStatus
from database import Base, engine, get_db
from security import hash_password, verify_password, create_token, current_user
from services import transition, active_count, expire_if_needed, utcnow, HOLD_MINUTES

Base.metadata.create_all(engine)
app = FastAPI(title="EVE Diagnostics API")

# ---------- Auth ----------
@app.post("/auth/signup", response_model=schemas.UserOut, status_code=201)
def signup(data: schemas.SignupIn, db: Session = Depends(get_db)):
    email = data.email.lower()
    if db.scalar(select(models.User).where(models.User.email == email)):
        raise HTTPException(409, "Email already registered")
    user = models.User(full_name=data.full_name, email=email,
                       password_hash=hash_password(data.password))
    db.add(user); db.commit(); db.refresh(user)
    return user

@app.post("/auth/login", response_model=schemas.TokenOut)
def login(data: schemas.LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(models.User).where(models.User.email == data.email.lower()))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": create_token(user.id)}

# ---------- Tests & Centres ----------
@app.post("/tests", response_model=schemas.TestOut, status_code=201)
def create_test(data: schemas.TestCreate, db: Session = Depends(get_db),
                _=Depends(current_user)):
    t = models.DiagnosticTest(name=data.name)
    db.add(t)
    try:
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Test already exists")
    db.refresh(t); return t

@app.get("/tests", response_model=list[schemas.TestOut])
def list_tests(db: Session = Depends(get_db)):
    return db.scalars(select(models.DiagnosticTest)).all()

@app.post("/centres", response_model=schemas.CentreOut, status_code=201)
def create_centre(data: schemas.CentreCreate, db: Session = Depends(get_db),
                  _=Depends(current_user)):
    c = models.Centre(name=data.name, location=data.location)
    db.add(c); db.commit(); db.refresh(c)
    return c

@app.post("/centres/{centre_id}/tests", response_model=schemas.CentreOut, status_code=201)
def add_test_to_centre(centre_id: int, data: schemas.OfferingCreate,
                       db: Session = Depends(get_db), _=Depends(current_user)):
    centre = db.get(models.Centre, centre_id)
    if not centre or not db.get(models.DiagnosticTest, data.test_id):
        raise HTTPException(404, "Centre or test not found")
    db.add(models.CentreTest(centre_id=centre_id, test_id=data.test_id, price=data.price))
    try:
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Test already offered at this centre")
    db.refresh(centre); return centre

def centre_query():
    return select(models.Centre).options(
        selectinload(models.Centre.offerings).selectinload(models.CentreTest.test))

@app.get("/centres", response_model=list[schemas.CentreOut])
def list_centres(location: str | None = None, db: Session = Depends(get_db)):
    q = centre_query()
    if location:
        q = q.where(models.Centre.location.ilike(f"%{location}%"))
    return db.scalars(q).all()

@app.get("/centres/{centre_id}", response_model=schemas.CentreOut)
def get_centre(centre_id: int, db: Session = Depends(get_db)):
    c = db.scalar(centre_query().where(models.Centre.id == centre_id))
    if not c:
        raise HTTPException(404, "Centre not found")
    return c

# ---------- Slots ----------
@app.post("/centres/{centre_id}/slots/generate", status_code=201)
def generate_slots(centre_id: int, data: schemas.SlotGenerate,
                   db: Session = Depends(get_db), _=Depends(current_user)):
    if not db.get(models.Centre, centre_id):
        raise HTTPException(404, "Centre not found")
    if data.start_hour >= data.end_hour:
        raise HTTPException(422, "start_hour must be before end_hour")
    created = 0
    for h in range(data.start_hour, data.end_hour):
        start = datetime.combine(data.date, time(h), tzinfo=timezone.utc)
        if not db.scalar(select(models.Slot.id).where(
                models.Slot.centre_id == centre_id, models.Slot.start_at == start)):
            db.add(models.Slot(centre_id=centre_id, start_at=start, capacity=data.capacity))
            created += 1
    db.commit()
    return {"created": created}

@app.get("/centres/{centre_id}/slots", response_model=list[schemas.SlotOut])
def list_slots(centre_id: int, day: date, db: Session = Depends(get_db)):
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    slots = db.scalars(select(models.Slot).where(
        models.Slot.centre_id == centre_id, models.Slot.start_at >= start,
        models.Slot.start_at < start + timedelta(days=1)).order_by(models.Slot.start_at)).all()
    return [schemas.SlotOut(id=s.id, start_at=s.start_at, capacity=s.capacity,
            remaining=max(0, s.capacity - active_count(db, s.id))) for s in slots]

# ---------- Price comparison ----------
@app.get("/tests/{test_id}/centres", response_model=list[schemas.CompareOut])
def compare_centres(test_id: int, location: str | None = None, db: Session = Depends(get_db)):
    q = (select(models.CentreTest).options(selectinload(models.CentreTest.centre))
         .join(models.Centre, models.CentreTest.centre_id == models.Centre.id)
         .where(models.CentreTest.test_id == test_id).order_by(models.CentreTest.price))
    if location:
        q = q.where(models.Centre.location.ilike(f"%{location}%"))
    return [schemas.CompareOut(centre_id=o.centre.id, centre_name=o.centre.name,
            location=o.centre.location, price=o.price) for o in db.scalars(q)]

# ---------- Bookings ----------
def own_booking(db, booking_id, user, lock=False):
    q = select(models.Booking).where(models.Booking.id == booking_id,
                                     models.Booking.user_id == user.id)
    if lock:
        q = q.with_for_update()
    b = db.scalar(q)
    if not b:
        raise HTTPException(404, "Booking not found")
    return b

@app.post("/bookings", response_model=schemas.BookingOut, status_code=201)
def create_booking(data: schemas.BookingCreate, db: Session = Depends(get_db),
                   user: models.User = Depends(current_user)):
    # Lock the slot row: concurrent requests for the same slot queue up here
    slot = db.scalar(select(models.Slot).where(models.Slot.id == data.slot_id).with_for_update())
    if not slot or slot.centre_id != data.centre_id:
        raise HTTPException(404, "Slot not found for this centre")
    if slot.start_at <= utcnow():
        raise HTTPException(422, "Slot is in the past")
    offering = db.scalar(select(models.CentreTest).where(
        models.CentreTest.centre_id == data.centre_id, models.CentreTest.test_id == data.test_id))
    if not offering:
        raise HTTPException(404, "This centre does not offer this test")
    if active_count(db, slot.id) >= slot.capacity:
        raise HTTPException(409, "Slot is full")
    b = models.Booking(user_id=user.id, test_id=data.test_id, centre_id=data.centre_id,
                       slot_id=slot.id, appointment_at=slot.start_at, amount=offering.price,
                       expires_at=utcnow() + timedelta(minutes=HOLD_MINUTES))
    db.add(b); db.flush()
    db.add(models.BookingEvent(booking_id=b.id, from_status=None,
                               to_status="PENDING", reason="booking created"))
    db.commit(); db.refresh(b)
    return b

@app.get("/bookings", response_model=list[schemas.BookingOut])
def my_bookings(db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    return db.scalars(select(models.Booking).where(models.Booking.user_id == user.id)
                      .order_by(models.Booking.created_at.desc())).all()

@app.get("/bookings/{booking_id}", response_model=schemas.BookingOut)
def get_booking(booking_id: int, db: Session = Depends(get_db),
                user: models.User = Depends(current_user)):
    b = own_booking(db, booking_id, user, lock=True)
    expire_if_needed(db, b); db.refresh(b)
    return b

@app.get("/bookings/{booking_id}/events", response_model=list[schemas.EventOut])
def booking_timeline(booking_id: int, db: Session = Depends(get_db),
                     user: models.User = Depends(current_user)):
    own_booking(db, booking_id, user)
    return db.scalars(select(models.BookingEvent).where(
        models.BookingEvent.booking_id == booking_id).order_by(models.BookingEvent.id)).all()

@app.post("/bookings/{booking_id}/cancel", response_model=schemas.BookingOut)
def cancel_booking(booking_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(current_user)):
    b = own_booking(db, booking_id, user, lock=True)
    transition(db, b, BookingStatus.CANCELLED, "cancelled by user")
    db.commit(); db.refresh(b)
    return b

# ---------- Simulated payment ----------
FAILURES = ["INSUFFICIENT_FUNDS", "BANK_TIMEOUT", "CARD_DECLINED"]

@app.post("/payments/", response_model=schemas.PaymentOut, status_code=201)
def make_payment(data: schemas.PaymentCreate, response: Response,
                 idempotency_key: str | None = Header(default=None),
                 db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    b = own_booking(db, data.booking_id, user, lock=True)
    if idempotency_key:
        prev = db.scalar(select(models.Payment).where(
            models.Payment.idempotency_key == idempotency_key))
        if prev:
            if prev.booking_id != b.id:
                raise HTTPException(422, "Idempotency-Key already used for another booking")
            response.status_code = 200
            return prev                       # replay, no double charge
    expire_if_needed(db, b)
    if b.status != BookingStatus.PENDING:
        raise HTTPException(409, f"Cannot pay for a {b.status.value} booking")
    result = data.simulate or (PaymentStatus.SUCCESS if random.random() < 0.8
                               else PaymentStatus.FAILED)
    ok = result == PaymentStatus.SUCCESS
    p = models.Payment(booking_id=b.id, amount=b.amount, status=result,
                       idempotency_key=idempotency_key,
                       failure_reason=None if ok else random.choice(FAILURES))
    db.add(p); db.flush()
    transition(db, b, BookingStatus.CONFIRMED if ok else BookingStatus.FAILED,
               f"payment {result.value}")
    db.commit(); db.refresh(p)
    return p