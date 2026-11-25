"""
Auth module — JWT + bcrypt + Twilio Email
Registration requires admin approval via email.
Profiles: pending / free / premium
"""
import os
import sqlite3
import httpx
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Cookie, HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY = os.getenv("SECRET_KEY", "geovia-secret-key-change-in-production-2026")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30

DB_PATH = os.getenv("DB_PATH", "data/geovia.db")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM_EMAIL", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "abm@virgilio.it")
APP_URL = os.getenv("APP_URL", "https://geovia-production.up.railway.app")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def init_auth_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            profile TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def hash_password(password: str) -> str:
    return pwd_context.hash(password[:72])


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain[:72], hashed)


def create_token(email: str, profile: str = "free") -> str:
    expire = datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": email, "profile": profile, "exp": expire},
                      SECRET_KEY, algorithm=ALGORITHM)


def create_approval_token(email: str, profile: str) -> str:
    """Token for admin approval link — no expiry for simplicity"""
    return jwt.encode({"sub": email, "profile": profile, "action": "approve"},
                      SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_user_profile(email: str) -> Optional[str]:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT profile FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    return row[0] if row else None


async def send_approval_email(email: str):
    """Send approval email using Twilio approved template format"""
    token_free = create_approval_token(email, "free")
    token_premium = create_approval_token(email, "premium")
    link_free = f"{APP_URL}/auth/approve?token={token_free}"
    link_premium = f"{APP_URL}/auth/approve?token={token_premium}"

    # Twilio trial: exact HTML + exact subject required
    # Links go in Order Number field only
    html = (
        "<p><b>This is a test email from Twilio.</b></p>"
        "<h2>Thank you for your order!</h2>"
        "<p>We are excited to let you know that your order has been confirmed and is being processed.</p>"
        "<p>You will receive a shipping confirmation email once your items are on their way.</p>"
        f"<p>Order Number: {email} | FREE: {link_free} | PREMIUM: {link_premium}</p>"
        "<p>Thank you for shopping with us!</p>"
        "<p>Best regards,<br/>The Team</p>"
    )
    subject = "Your Order Has Been Confirmed!"

    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as client:
            r = await client.post(
                "https://comms.twilio.com/v1/Emails",
                auth=(TWILIO_SID, TWILIO_TOKEN),
                json={
                    "from": {"address": TWILIO_FROM, "name": "Trial with Twilio"},
                    "to": [{"address": ADMIN_EMAIL}],
                    "content": {
                        "subject": subject,
                        "html": html
                    }
                }
            )
            print(f"[Email] status={r.status_code} body={r.text[:100]}")
            return r.status_code in (200, 201, 202)
    except Exception as e:
        print(f"[Email] error: {e}")
        return False


def register_user_pending(email: str, password: str) -> dict:
    email = email.lower().strip()
    if len(password) < 6:
        return {"ok": False, "error": "Password minima 6 caratteri"}
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT INTO users (email, password_hash, profile) VALUES (?, ?, 'pending')",
                     (email, hash_password(password)))
        conn.commit()
        return {"ok": True}
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "Email già registrata"}
    finally:
        conn.close()


def approve_user(email: str, profile: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("UPDATE users SET profile=? WHERE email=?", (profile, email))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def login_user(email: str, password: str) -> dict:
    email = email.lower().strip()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT password_hash, profile FROM users WHERE email=?",
                       (email,)).fetchone()
    conn.close()
    if not row or not verify_password(password, row[0]):
        return {"ok": False, "error": "Email o password non corretti"}
    profile = row[1]
    if profile == "pending":
        return {"ok": False, "error": "Account in attesa di approvazione. Riceverai una email quando sarà attivato."}
    return {"ok": True, "token": create_token(email, profile), "email": email, "profile": profile}


def get_current_user(geovia_token: Optional[str] = Cookie(default=None)) -> dict:
    if not geovia_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    payload = verify_token(geovia_token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return payload
