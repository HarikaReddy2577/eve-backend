from datetime import datetime, date as date_type
from decimal import Decimal
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from models import BookingStatus, PaymentStatus

class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class SignupIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(ORM):
    id: int; full_name: str; email: EmailStr

class CentreCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    location: str = Field(min_length=2, max_length=150)

class TestCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)

class OfferingCreate(BaseModel):
    test_id: int
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)

class TestOut(ORM):
    id: int; name: str

class OfferingOut(ORM):
    test: TestOut; price: Decimal

class CentreOut(ORM):
    id: int; name: str; location: str
    offerings: list[OfferingOut] = []

class SlotGenerate(BaseModel):
    date: date_type
    start_hour: int = Field(8, ge=0, le=23)
    end_hour: int = Field(18, ge=1, le=24)
    capacity: int = Field(5, ge=1, le=50)

class SlotOut(BaseModel):
    id: int; start_at: datetime; capacity: int; remaining: int

class CompareOut(BaseModel):
    centre_id: int; centre_name: str; location: str; price: Decimal

class BookingCreate(BaseModel):
    test_id: int; centre_id: int; slot_id: int

class BookingOut(ORM):
    id: int; user_id: int; test_id: int; centre_id: int; slot_id: int
    appointment_at: datetime; amount: Decimal; status: BookingStatus
    expires_at: datetime | None; created_at: datetime

class EventOut(ORM):
    from_status: str | None; to_status: str; reason: str; created_at: datetime

class PaymentCreate(BaseModel):
    booking_id: int
    simulate: PaymentStatus | None = None   # force SUCCESS/FAILED for testing

class PaymentOut(ORM):
    id: int; booking_id: int; amount: Decimal; status: PaymentStatus
    failure_reason: str | None; created_at: datetime