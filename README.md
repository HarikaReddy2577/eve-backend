# EVE Diagnostics: a slot-aware booking engine

> Book a diagnostic test at a centre, hold the slot while you pay, and never get double-booked.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.x-D71F00)
![Tests](https://img.shields.io/badge/pytest-3%20passing-0A9EDC?logo=pytest&logoColor=white)

Most booking demos are CRUD plus a random payment. This one is built around the problems real booking systems have to solve: **two people grabbing the last slot, users double-clicking "Pay", payments that fail halfway, and holds that must expire.** Each of those has a concrete answer in the code and a test that proves it.

---

## The problems it solves

| Real-world problem | What this project does | Where |
|---|---|---|
| Two users book the last slot at the same moment | The slot row is locked (`SELECT ... FOR UPDATE`), so concurrent requests queue and the second one gets `409` | `main.py` `create_booking` |
| A user starts booking but never pays | A `PENDING` booking holds the slot for **15 minutes**, then stops counting toward capacity | `services.py` `active_count`, `expire_if_needed` |
| An invalid status jump (e.g. `FAILED` to `CONFIRMED`) | One transition table; anything else returns `409` | `services.py` `ALLOWED`, `transition` |
| "Who changed this booking, and why?" | Every status change writes a row to `booking_events` | `services.py` `transition` |
| A double-click or network retry charges twice | `Idempotency-Key` header: a replay returns the original payment, not a new charge | `main.py` `make_payment` |
| Payments fail for different reasons | Failures carry a reason code: `INSUFFICIENT_FUNDS`, `BANK_TIMEOUT`, `CARD_DECLINED` | `main.py` `FAILURES` |
| A client sends a fake price | Price is read from the database, never from the request | `main.py` `create_booking` |
| Finding the cheapest centre | `GET /tests/{id}/centres` returns centres cheapest first | `main.py` `compare_centres` |

---

## How a booking flows

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant DB as PostgreSQL

    U->>API: POST /bookings (test, centre, slot)
    API->>DB: SELECT slot FOR UPDATE (lock)
    API->>DB: count CONFIRMED + unexpired PENDING
    alt slot has room
        API->>DB: INSERT booking (PENDING, expires in 15 min)
        API->>DB: INSERT booking_event (created)
        API-->>U: 201 PENDING
        U->>API: POST /payments (Idempotency-Key)
        API->>DB: lock booking, check key, record payment
        API->>DB: transition to CONFIRMED or FAILED + event
        API-->>U: 201 payment result
    else slot is full
        API-->>U: 409 Slot is full
    end
```

### Booking state machine

```mermaid
stateDiagram-v2
    [*] --> PENDING: booking created
    PENDING --> CONFIRMED: payment SUCCESS
    PENDING --> FAILED: payment FAILED
    PENDING --> CANCELLED: user cancels / hold expires
    CONFIRMED --> CANCELLED: user cancels
    FAILED --> [*]
    CANCELLED --> [*]
```

A slot is considered **occupied** by `CONFIRMED` bookings and by `PENDING` bookings whose hold has not expired. Failed and cancelled bookings free the slot immediately.

---

## Quick start (Windows, Command Prompt)

**Requirements:** Python 3.10+ and PostgreSQL.

```
git clone https://github.com/HarikaReddy2577/eve-backend.git
cd eve-backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Create the two databases (the second one is used only by the tests):

```
createdb -U postgres eve
createdb -U postgres eve_test
```

Set the environment variables and start the server:

```
set DATABASE_URL=postgresql://postgres:YOURPASSWORD@localhost:5432/eve
set SECRET_KEY=a-long-random-secret-of-at-least-32-bytes
uvicorn main:app --reload
```

Open **http://127.0.0.1:8000/docs** for the interactive Swagger UI.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string. If your password contains `@`, write it as `%40` |
| `SECRET_KEY` | JWT signing key. Use 32+ random bytes in production |

`set` only lasts for the current Command Prompt window, so set both again in each new window.

---

## Tests

The three tests cover the hardest guarantees. They **drop and recreate all tables**, so always run them against the test database:

```
set DATABASE_URL=postgresql://postgres:YOURPASSWORD@localhost:5432/eve_test
pytest -q
```

| Test | What it proves |
|---|---|
| `test_slot_cannot_be_overbooked` | With capacity 1, the first booking returns `201` and the second user gets `409` |
| `test_payment_is_idempotent` | Same `Idempotency-Key` twice returns `201` then `200` with the same payment id |
| `test_failed_payment_frees_slot_and_blocks_retry` | A failed payment sets the booking to `FAILED`, stores a reason code, blocks a second payment (`409`), and frees the slot for a new booking |

Expected output: `3 passed`.

---

## API at a glance

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/signup` | no | Create an account |
| POST | `/auth/login` | no | Get a JWT (valid 2 hours) |
| GET | `/tests` | no | List diagnostic tests |
| POST | `/tests` | yes | Create a test |
| GET | `/centres` | no | List centres (optional `location` filter) |
| POST | `/centres` | yes | Create a centre |
| GET | `/centres/{id}` | no | Centre with its tests and prices |
| POST | `/centres/{id}/tests` | yes | Offer a test at a centre with a price |
| POST | `/centres/{id}/slots/generate` | yes | Generate hourly slots for a date |
| GET | `/centres/{id}/slots?day=` | no | Slots with live remaining capacity |
| GET | `/tests/{id}/centres` | no | **Price comparison, cheapest first** |
| POST | `/bookings` | yes | Book a slot (starts a 15-minute hold) |
| GET | `/bookings` | yes | My bookings |
| GET | `/bookings/{id}` | yes | One booking (expires stale holds) |
| GET | `/bookings/{id}/events` | yes | **Audit timeline** |
| POST | `/bookings/{id}/cancel` | yes | Cancel a booking |
| POST | `/payments/` | yes | **Simulated payment** (supports `Idempotency-Key`) |

### Try the idempotency guarantee

Swagger UI does not show custom headers, so use curl (replace the token and booking id):

```
curl -X POST http://127.0.0.1:8000/payments/ ^
  -H "Authorization: Bearer YOUR_TOKEN" ^
  -H "Idempotency-Key: pay-001" ^
  -H "Content-Type: application/json" ^
  -d "{\"booking_id\": 1, \"simulate\": \"SUCCESS\"}"
```

Run it twice. The first call returns `201`; the second returns `200` with the same payment id and nothing is charged again. The `simulate` field forces `SUCCESS` or `FAILED` for testing; leave it out for a random outcome (80% success).

---

## Walkthrough with screenshots

A full happy path plus the overbooking rejection, captured from the Swagger UI.

<details open>
<summary><b>1. Sign up and log in</b></summary>

<img src="screenshots/1-signup-request.png" alt="Signup request" width="800">
<img src="screenshots/2-signup-response.png" alt="Signup response" width="800">
<img src="screenshots/3-login-request.png" alt="Login request" width="800">
<img src="screenshots/4-login-response.png" alt="Login response with JWT" width="800">

</details>

<details>
<summary><b>2. Create a test and a centre</b></summary>

<img src="screenshots/5-create-test-request.png" alt="Create test request" width="800">
<img src="screenshots/6-create-test-response.png" alt="Create test response" width="800">
<img src="screenshots/7-create-centre-request.png" alt="Create centre request" width="800">
<img src="screenshots/8-create-centre-response.png" alt="Create centre response" width="800">

</details>

<details>
<summary><b>3. Set a price for the test at the centre</b></summary>

<img src="screenshots/9-add-offering-request.png" alt="Add offering request" width="800">
<img src="screenshots/10-add-offering-response.png" alt="Add offering response" width="800">

</details>

<details>
<summary><b>4. Generate slots (capacity 1)</b></summary>

<img src="screenshots/11-generate-slots-request.png" alt="Generate slots request" width="800">
<img src="screenshots/12-generate-slots-response.png" alt="Generate slots response" width="800">

</details>

<details>
<summary><b>5. Book a slot: starts as PENDING with a 15-minute hold</b></summary>

The response shows `status: PENDING`, an `expires_at` 15 minutes ahead, and `amount: 499.00` taken from the database.

<img src="screenshots/13-booking-request.png" alt="Booking request" width="800">
<img src="screenshots/14-booking-response.png" alt="Booking response" width="800">

</details>

<details open>
<summary><b>6. The last slot cannot be double-booked</b></summary>

A second user booking the same full slot is rejected:

<img src="screenshots/15-slot-full.png" alt="409 Slot is full" width="800">

</details>

---

## Design decisions

**Why lock the slot row, not just check the count?**
Checking "is there room?" and then inserting is a race: two requests can both see one free seat. `SELECT ... FOR UPDATE` on the slot makes concurrent bookings for the same slot run one at a time, so the capacity check is always accurate.

**Why expire holds lazily?**
A `PENDING` booking carries an `expires_at`. The capacity count ignores expired holds, and a booking is formally moved to `CANCELLED` the next time it is read or paid. This needs no background worker and is always correct for capacity. In production a scheduled job would also sweep expired holds.

**Why one `transition()` function?**
Status rules and audit logging live in `services.py`. A route cannot change a status without passing the transition table, and cannot change one without writing a `booking_events` row.

**Why idempotency keys on payments?**
Networks retry and users double-click. The key is stored with a unique constraint, so a repeat returns the original result. Reusing a key for a different booking is rejected with `422`.

**Why does `FAILED` end the booking?**
It keeps the state machine simple and the audit trail unambiguous: a retry is a new booking, which re-checks capacity and the price.

**Security basics**
Passwords are hashed with bcrypt, tokens are signed JWTs that expire in 2 hours, and every booking lookup is scoped to the owner, so another user's booking returns `404`.

---

## Project structure

```
eve-backend/
├── database.py      engine, session, declarative base
├── models.py        tables and enums (User, Centre, Slot, Booking, BookingEvent, Payment ...)
├── schemas.py       Pydantic request and response models
├── security.py      bcrypt hashing, JWT creation and verification
├── services.py      state machine, slot capacity, hold expiry
├── main.py          API routes
├── test_api.py      pytest suite
├── screenshots/     walkthrough images used in this README
└── requirements.txt
```

---

## Known limitations and what I'd build next

| Limitation | Next step |
|---|---|
| Tables are created with `create_all`, so schema changes need a manual reset | Alembic migrations |
| Expired holds are cleaned up only on access | Celery or a scheduled job to sweep them |
| Any logged-in user can create centres, tests and slots | An admin role |
| Cancelling a `CONFIRMED` booking does not refund | Refund flow with its own payment status |
| Payments are simulated | Integrate a real gateway behind the same idempotency layer |
| Slots are generated in UTC | Per-centre time zones |
| Tests cover the three core guarantees | Add a threaded concurrency test and hold-expiry test |
| Runs only with a local PostgreSQL | Dockerfile and docker-compose |
