"""
Auth module — JWT + bcrypt
Simple email/password auth for geoVIA demo.
"""
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Cookie, HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY = os.getenv("SECRET_KEY", "geovia-secret-key-change-in-production-2026")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30

DB_PATH = os.getenv("DB_PATH", "data/geovia.db")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def init_auth_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            active INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(email: str) -> str:
    expire = datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": email, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def register_user(email: str, password: str) -> dict:
    email = email.lower().strip()
    if len(password) < 6:
        return {"ok": False, "error": "Password minima 6 caratteri"}
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)",
                     (email, hash_password(password)))
        conn.commit()
        return {"ok": True}
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "Email già registrata"}
    finally:
        conn.close()


def login_user(email: str, password: str) -> dict:
    email = email.lower().strip()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT password_hash FROM users WHERE email=? AND active=1",
                       (email,)).fetchone()
    conn.close()
    if not row or not verify_password(password, row[0]):
        return {"ok": False, "error": "Email o password non corretti"}
    return {"ok": True, "token": create_token(email), "email": email}


def get_current_user(geovia_token: Optional[str] = Cookie(default=None)) -> str:
    if not geovia_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    email = verify_token(geovia_token)
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return email
