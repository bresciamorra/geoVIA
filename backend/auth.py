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
    """Send approval email to admin with free/premium links"""
    token_free = create_approval_token(email, "free")
    token_premium = create_approval_token(email, "premium")
    link_free = f"{APP_URL}/auth/approve?token={token_free}"
    link_premium = f"{APP_URL}/auth/approve?token={token_premium}"

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <div style="background:#1a252f;padding:20px;border-radius:8px 8px 0 0">
        <h2 style="color:white;margin:0">🌍 geoVIA — Nuova Registrazione</h2>
      </div>
      <div style="background:#f8f9fa;padding:24px;border-radius:0 0 8px 8px">
        <p style="font-size:16px">Nuova richiesta di accesso da:</p>
        <p style="font-size:18px;font-weight:bold;color:#2c3e50">{email}</p>
        <p style="color:#7f8c8d;margin-top:16px">Scegli il profilo da assegnare:</p>

        <div style="margin-top:20px;display:flex;gap:16px">
          <a href="{link_free}"
             style="display:inline-block;padding:14px 28px;background:#27ae60;color:white;
                    text-decoration:none;border-radius:8px;font-weight:bold;font-size:15px">
            ✅ Approva FREE
          </a>
          <a href="{link_premium}"
             style="display:inline-block;padding:14px 28px;background:#2c3e50;color:white;
                    text-decoration:none;border-radius:8px;font-weight:bold;font-size:15px;margin-left:16px">
            ⭐ Approva PREMIUM
          </a>
        </div>

        <div style="margin-top:24px;padding:16px;background:white;border-radius:8px;border:1px solid #dde1e7">
          <p style="margin:0;font-size:13px;color:#7f8c8d">
            <strong>FREE</strong>: analisi GIS base, chat AI, storico progetti<br>
            <strong>PREMIUM</strong>: tutto + PDF, What-if, Confronto scenari, ReAct, Brief
          </p>
        </div>
      </div>
    </div>
    """

    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as client:
            r = await client.post(
                "https://comms.twilio.com/v1/Emails",
                auth=(TWILIO_SID, TWILIO_TOKEN),
                json={
                    "from": {"address": TWILIO_FROM, "name": "geoVIA"},
                    "to": [{"address": ADMIN_EMAIL}],
                    "content": {
                        "subject": f"geoVIA — Approva accesso: {email}",
                        "html": html
                    }
                }
            )
            print(f"[Email] status={r.status_code} to={ADMIN_EMAIL}")
            return r.status_code == 201
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
