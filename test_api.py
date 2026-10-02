import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from database import Base, engine
from main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)

def auth(email="a@b.com"):
    client.post("/auth/signup", json={"full_name": "Test User", "email": email, "password": "password123"})
    tok = client.post("/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}

def setup_slot(h, capacity=1):
    t = client.post("/tests", json={"name": "CBC"}, headers=h).json()
    c = client.post("/centres", json={"name": "EVE Lab", "location": "Hyderabad"}, headers=h).json()
    client.post(f"/centres/{c['id']}/tests", json={"test_id": t["id"], "price": 499}, headers=h)
    day = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
    client.post(f"/centres/{c['id']}/slots/generate",
                json={"date": day, "start_hour": 9, "end_hour": 10, "capacity": capacity}, headers=h)
    s = client.get(f"/centres/{c['id']}/slots", params={"day": day}).json()[0]
    return t["id"], c["id"], s["id"]

def book(h, t, c, s):
    return client.post("/bookings", json={"test_id": t, "centre_id": c, "slot_id": s}, headers=h)

def test_slot_cannot_be_overbooked():
    h1, h2 = auth("a@b.com"), auth("c@d.com")
    t, c, s = setup_slot(h1, capacity=1)
    assert book(h1, t, c, s).status_code == 201
    assert book(h2, t, c, s).status_code == 409

def test_payment_is_idempotent():
    h = auth(); t, c, s = setup_slot(h)
    b = book(h, t, c, s).json()
    hdr = {**h, "Idempotency-Key": "k1"}
    body = {"booking_id": b["id"], "simulate": "SUCCESS"}
    p1 = client.post("/payments/", json=body, headers=hdr)
    p2 = client.post("/payments/", json=body, headers=hdr)
    assert p1.status_code == 201 and p2.status_code == 200
    assert p1.json()["id"] == p2.json()["id"]

def test_failed_payment_frees_slot_and_blocks_retry():
    h = auth(); t, c, s = setup_slot(h)
    b = book(h, t, c, s).json()
    r = client.post("/payments/", json={"booking_id": b["id"], "simulate": "FAILED"}, headers=h)
    assert r.json()["failure_reason"]
    assert client.get(f"/bookings/{b['id']}", headers=h).json()["status"] == "FAILED"
    assert client.post("/payments/", json={"booking_id": b["id"]}, headers=h).status_code == 409
    assert book(h, t, c, s).status_code == 201