\# EVE Diagnostics: Slot-Aware Booking Engine



Slot-aware diagnostic booking engine with concurrency-safe scheduling and idempotent payments.



\*\*Stack:\*\* FastAPI, SQLAlchemy 2, PostgreSQL, JWT (PyJWT + bcrypt), pytest.



\## Features



| Feature | How it works |

|---|---|

| Slot capacity, no overbooking | Row-level lock on the slot (`SELECT ... FOR UPDATE`) so two users can't take the last slot |

| 15-minute payment hold | `PENDING` bookings reserve a slot and expire if unpaid |

| Booking state machine | Only valid transitions are allowed, enforced in one place (`services.py`) |

| Audit trail | Every status change is stored in `booking\_events` |

| Idempotent payments | `Idempotency-Key` header, so a double-click never charges twice |

| Realistic payment failures | Failed payments carry a reason code, e.g. `INSUFFICIENT\_FUNDS` |

| Price comparison | `GET /tests/{id}/centres` returns centres cheapest first |

| Tests | 3 pytest tests covering the hard parts |



\## Setup (Windows, Command Prompt)



Requirements: Python 3.10+ and PostgreSQL.



```

git clone https://github.com/YOURUSERNAME/eve-backend.git

cd eve-backend

python -m venv venv

venv\\Scripts\\activate

pip install -r requirements.txt

```



Create two databases, `eve` and `eve\_test`:



```

createdb -U postgres eve

createdb -U postgres eve\_test

```



\### Environment variables



| Variable | Purpose |

|---|---|

| `DATABASE\_URL` | PostgreSQL connection string |

| `SECRET\_KEY` | JWT signing key. Use a long random value (32+ bytes) in production |



```

set DATABASE\_URL=postgresql://postgres:YOURPASSWORD@localhost:5432/eve

set SECRET\_KEY=a-long-random-secret-key-of-at-least-32-bytes

```



If your password contains `@`, write it as `%40` in the URL. `set` only lasts for the current window.



\### Run the server



```

uvicorn main:app --reload

```



Open http://127.0.0.1:8000/docs for the interactive Swagger UI.



\### Run the tests



The tests drop all tables, so always point them at the test database:



```

set DATABASE\_URL=postgresql://postgres:YOURPASSWORD@localhost:5432/eve\_test

pytest -q

```



Expected: `3 passed`.



\## Screenshots



\### Sign up



Request:



!\[Signup request](screenshots/1-signup-request.png)



Response (`201 Created`):



!\[Signup response](screenshots/2-signup-response.png)



\### Log in



Request:



!\[Login request](screenshots/3-login-request.png)



Response (`200 OK`, returns a JWT):



!\[Login response](screenshots/4-login-response.png)



Documented responses (`200` and `422`):



!\[Login response schema](screenshots/5-login-schema.png)



\## Endpoints



| Method | Path | Auth | Description |

|---|---|---|---|

| POST | `/auth/signup` | No | Create an account |

| POST | `/auth/login` | No | Get a JWT access token |

| GET | `/tests` | No | List diagnostic tests |

| POST | `/tests` | Yes | Create a test |

| GET | `/centres` | No | List centres (optional `location` filter) |

| POST | `/centres` | Yes | Create a centre |

| GET | `/centres/{id}` | No | Centre details with its tests and prices |

| POST | `/centres/{id}/tests` | Yes | Attach a test with a price to a centre |

| POST | `/centres/{id}/slots/generate` | Yes | Generate hourly slots for a date |

| GET | `/centres/{id}/slots?day=` | No | List slots with remaining capacity |

| GET | `/tests/{id}/centres` | No | Price comparison, cheapest first |

| POST | `/bookings` | Yes | Book a slot (creates a `PENDING` hold) |

| GET | `/bookings` | Yes | List my bookings |

| GET | `/bookings/{id}` | Yes | Booking details (expires stale holds) |

| GET | `/bookings/{id}/events` | Yes | Audit timeline for a booking |

| POST | `/bookings/{id}/cancel` | Yes | Cancel a booking |

| POST | `/payments/` | Yes | Simulated payment (supports `Idempotency-Key`) |



\## Booking state machine



```

PENDING   -> CONFIRMED | FAILED | CANCELLED

CONFIRMED -> CANCELLED

FAILED    -> (final)

CANCELLED -> (final)

```



\## Design decisions



\- \*\*Row-level locking on slots\*\* prevents overbooking. Concurrent requests for the same slot queue up on the lock.

\- \*\*15-minute hold, expired lazily on access.\*\* Unpaid `PENDING` bookings stop counting towards capacity once they expire. A background job would replace this in production.

\- \*\*State machine and audit trail live in one place\*\* (`services.py`), so no route can skip a rule or forget to log a change.

\- \*\*Idempotency keys\*\* make payment retries safe. Replaying a key returns the original payment with `200` instead of charging again.

\- \*\*Price comes from the database, never the client.\*\* The booking stores the price at booking time.

\- \*\*Ownership checks.\*\* Users can only see and pay for their own bookings; others return `404`.



\## Project structure



```

database.py   engine, session, Base

models.py     SQLAlchemy models and enums

schemas.py    Pydantic request/response schemas

security.py   password hashing and JWT auth

services.py   state machine, slot capacity, hold expiry

main.py       API routes

test\_api.py   pytest tests

```



\## What I'd do next



\- Alembic migrations instead of `create\_all`

\- A Celery job to expire holds in the background

\- An admin role for creating centres and tests

\- Refunds when cancelling a `CONFIRMED` booking

\- A Dockerfile and docker-compose for one-command setup

