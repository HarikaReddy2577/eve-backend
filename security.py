import os
from datetime import datetime, timedelta, timezone
import bcrypt, jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db
import models

SECRET = os.getenv("SECRET_KEY", "change-me-in-prod")
ALGO = "HS256"
bearer = HTTPBearer()

def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_password(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode(), h.encode())

def create_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=2)
    return jwt.encode({"sub": str(user_id), "exp": exp}, SECRET, algorithm=ALGO)

def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer),
                 db: Session = Depends(get_db)) -> models.User:
    try:
        payload = jwt.decode(cred.credentials, SECRET, algorithms=[ALGO])
        user = db.get(models.User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid or expired token")
    if not user:
        raise HTTPException(401, "User not found")
    return user